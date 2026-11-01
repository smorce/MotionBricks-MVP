"""公式 Scene Preview の SOMA キャラクターで、クリック先まで歩いて止まる。

線形移動は Walk ブレンド（入力の長さ 1）だけで使う。短い距離と最後の一歩は
LocomotionCycle の踏み出しが姿勢を所有し、着地後は公式 Idle へ入れない。
IdleState.enter は待機クリップの開始姿勢へ生成するため、足幅が変わる。

推論はこのプロセスの NVlabs/motionbricks 環境で行う。ルート座標は目標へ吸着しない。
MOTIONBRICKS_ROOT が未設定なら、docs/examples/_rig.py がある親を探す。
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue

import numpy as np

from locomotion_cycle import IDLE, LocomotionCycle, POSE_DONE, SETTLED
from quats import RX90, quat_mul, quat_to_mat
from soma_pose import overlay_pose
from stop_phase import NavState, apply_nav_command

UPDATE_HZ = 60.0
DT = 1.0 / UPDATE_HZ
_SLOW_STEP_MS = 15.0


def find_motionbricks_root() -> Path:
    env = os.environ.get("MOTIONBRICKS_ROOT", "").strip()
    if env:
        root = Path(env)
        if not (root / "docs" / "examples" / "_rig.py").is_file():
            raise RuntimeError(f"MOTIONBRICKS_ROOT does not contain docs/examples/_rig.py: {root}")
        return root
    for parent in Path(__file__).resolve().parents:
        if (parent / "docs" / "examples" / "_rig.py").is_file():
            return parent
    raise RuntimeError("Set MOTIONBRICKS_ROOT to a clone of NVlabs/motionbricks")


def _load_runtime():
    root = find_motionbricks_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import warp as wp
    from motionbricks.model.contract import MODEL_POSES_PER_TOKEN, ModelRig
    from motionbricks.model.soma.contract import SOMA_N1_FP32_ONNX_PATH
    from motionbricks.model.soma.engine import MotionBricksSOMAEngine
    from motionbricks.runtime.target_pose import TargetPoseInferenceParams, place_target_poses
    from app.runtime.common.io.smart_primitive_document import SmartPrimitiveAssetPool
    from app.runtime.common.motion import LocomotionCommand, PlaybackSource
    from app.runtime.common.rig import load_rig_assets
    from app.runtime.soma.character import SOMACharacter
    from app.runtime.soma.presets import (
        DEFAULT_CROUCH_IDLE_CLIPS,
        DEFAULT_IDLE_CLIPS,
        DEFAULT_LOCOMOTION_MODES,
    )

    return {
        "wp": wp,
        "MODEL_POSES_PER_TOKEN": MODEL_POSES_PER_TOKEN,
        "ModelRig": ModelRig,
        "SOMA_N1_FP32_ONNX_PATH": SOMA_N1_FP32_ONNX_PATH,
        "MotionBricksSOMAEngine": MotionBricksSOMAEngine,
        "TargetPoseInferenceParams": TargetPoseInferenceParams,
        "place_target_poses": place_target_poses,
        "SmartPrimitiveAssetPool": SmartPrimitiveAssetPool,
        "LocomotionCommand": LocomotionCommand,
        "PlaybackSource": PlaybackSource,
        "load_rig_assets": load_rig_assets,
        "SOMACharacter": SOMACharacter,
        "DEFAULT_CROUCH_IDLE_CLIPS": DEFAULT_CROUCH_IDLE_CLIPS,
        "DEFAULT_IDLE_CLIPS": DEFAULT_IDLE_CLIPS,
        "DEFAULT_LOCOMOTION_MODES": DEFAULT_LOCOMOTION_MODES,
    }


def _norm_xy(vec: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    size = float(np.linalg.norm(vec[:2]))
    if size > 1e-6:
        return np.array([vec[0] / size, vec[1] / size, 0.0], dtype=np.float32)
    return fallback.astype(np.float32, copy=True)


def _sync_pose(character, pose, wp, seed: bool = False) -> None:
    """表示する姿勢を、MotionBricks の現在姿勢へ戻す。推論は走らせない。"""
    flat = np.ascontiguousarray(np.asarray(pose, dtype=np.float32).reshape((-1, 7)))
    current = character.current_pose.numpy()
    current.reshape(-1, 7)[:] = flat
    character.current_pose.assign(current)
    if seed:
        character.player.seed_history_from_pose(character.current_pose)


def _prime_walk(character, facing: np.ndarray) -> None:
    """加速スプリングの低速域は Idle ブレンドなので、歩行開始時だけ Walk 速度に置く。"""
    mode = character.state_machine.active_locomotion_state.active_mode
    speed = float(mode.default_speed)
    direction = np.asarray(facing, dtype=np.float32).copy()
    direction[2] = 0.0
    norm = float(np.linalg.norm(direction[:2]))
    if norm < 1e-6:
        return
    direction[:2] /= norm
    movement = character.movement
    movement.desired_speed = speed
    movement.desired_speed_rate = 0.0
    movement.desired_velocity_direction[:] = direction
    movement.desired_velocity[:] = direction * speed
    movement.desired_velocity_angle = float(np.arctan2(direction[1], direction[0]))
    movement.desired_velocity_direction_rate = 0.0


def _request_custom_pose(character, pose_id: str, rt) -> bool:
    """骨長を保ったまま、着地姿勢から目標姿勢へ生成する。"""
    wp = rt["wp"]
    base = character.current_pose.numpy().reshape((-1, 7))
    raw = overlay_pose(pose_id, character.skeleton.joint_names, base)
    if raw is None:
        return False
    joints = [wp.transform(wp.vec3(*joint[:3]), wp.quat(*joint[3:])) for joint in raw]
    source = wp.array(
        [list(joints) for _ in range(rt["MODEL_POSES_PER_TOKEN"])],
        dtype=wp.transform,
        device=character.engine.device,
    )
    target = wp.empty_like(source)
    position = character.character_ground_position.copy()
    position[2] = 0.0
    facing = _norm_xy(
        character.movement.current_facing,
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    rt["place_target_poses"](
        wp.vec3(*position),
        wp.vec3(*facing),
        source,
        target,
        stream=character.engine.stream,
    )
    character.generate_to_target_poses(
        target,
        rt["TargetPoseInferenceParams"](transition_early_by_frames=0, num_poses_to_use=1),
    )
    return True


def _enter_arrival(character, planted, pose_id: str, rt, wp, facing: np.ndarray) -> bool:
    """到着ポーズの再生は Idle 状態でしか残らない。

    その enter は待機クリップへの遷移を生成する。公開する前に着地姿勢へ戻し、
    到着ポーズの生成で置き換える。待機クリップの足幅は画面に出ない。
    """
    _sync_pose(character, planted, wp, seed=True)
    character.step(
        DT,
        rt["LocomotionCommand"](facing_direction=facing, movement=None, use_max_speed=False),
    )
    _sync_pose(character, planted, wp, seed=True)
    return _request_custom_pose(character, pose_id, rt)


def _drain(commands: Queue, nav: NavState):
    goal = None
    while True:
        try:
            cmd = commands.get_nowait()
        except Empty:
            return nav, goal
        result = apply_nav_command(nav, cmd)
        if result.quit:
            return None
        nav = result.state
        if result.move_to is not None:
            goal = np.array([result.move_to[0], result.move_to[1], 0.0], dtype=np.float32)
    return nav, goal


def _command(rt, facing: np.ndarray, movement: np.ndarray | None):
    return rt["LocomotionCommand"](
        facing_direction=np.asarray(facing, dtype=np.float32),
        movement=None if movement is None else np.asarray(movement, dtype=np.float32),
        use_max_speed=False,
    )


def worker(commands: Queue, publish):
    """GPU と Warp は、この長寿命スレッドの中だけに置く。"""
    rt = _load_runtime()
    wp = rt["wp"]
    wp.init()
    wp.set_device("cuda:0")
    assets = rt["load_rig_assets"](rt["ModelRig"].SOMA)
    pool = rt["SmartPrimitiveAssetPool"](
        assets.clip_registry,
        assets.reference_pose,
        assets.model_to_runtime,
    )
    # 公式の最低速度は残す。0 にすると短距離が Idle ブレンドの滑りになる。
    engine = rt["MotionBricksSOMAEngine"](
        rt["SOMA_N1_FP32_ONNX_PATH"],
        model_to_runtime=assets.model_to_runtime,
    )
    with engine, wp.ScopedStream(engine.stream):
        character = rt["SOMACharacter"](
            engine,
            asset_pool=pool,
            modes=rt["DEFAULT_LOCOMOTION_MODES"],
            idle_paths=(rt["DEFAULT_IDLE_CLIPS"][0],),
            crouch_idle_paths=rt["DEFAULT_CROUCH_IDLE_CLIPS"],
        )
        skeleton = character.skeleton
        rest = skeleton.reference_local_transforms.numpy().reshape((-1, 7)).copy()
        # USD の基準姿勢は Y-up。配信フレームは Z-up なので、ルートだけ同じ基底に揃える。
        rest[0, :3] = quat_to_mat(RX90) @ rest[0, :3]
        rest[0, 3:] = quat_mul(RX90, rest[0, 3:])
        parents = [skeleton.joint_parent(i) for i in range(skeleton.num_joints)]
        names = list(skeleton.joint_names)
        publish(
            {
                "type": "rig",
                "joint_names": names,
                "parents": parents,
                "rest": rest.tolist(),
                "stream_hz": UPDATE_HZ,
            }
        )
        nav = NavState()
        cycle = LocomotionCycle()
        goal = None
        last_generate_ms = 0.0
        frames = 0
        tick = 0
        report_at = time.monotonic()
        next_tick = time.monotonic()
        last_root = None
        while True:
            drained = _drain(commands, nav)
            if drained is None:
                return
            nav, moved = drained
            if moved is not None:
                goal = moved
                cycle.begin_move(moved, nav.hold_stance, nav.move_id)
            if not nav.hold_stance and nav.target_pose_id != cycle.target_pose_id:
                cycle.note_pose_choice(nav.target_pose_id)
            pose = character.current_pose.numpy().reshape((-1, 7)).copy()
            playback = character._playback_source.name
            contacts_available = playback != "CLIP" and cycle.phase in (IDLE, "moving", "decelerating")
            root_speed = 0.0
            if last_root is not None:
                root_speed = float(np.linalg.norm(pose[0, :2] - last_root) / DT)
            started_at = time.perf_counter()
            action = cycle.tick(
                {
                    "pose": pose,
                    "parents": parents,
                    "names": names,
                    "dt": DT,
                    "actual_speed": root_speed,
                    "contacts": np.asarray(character.current_foot_contacts.numpy(), dtype=np.float64).reshape(-1),
                    "contacts_available": contacts_available,
                    "playback": playback,
                    "official_state": character.state_machine.state.name,
                    "facing": character.movement.current_facing.copy(),
                }
            )
            facing = _norm_xy(
                action.facing if action.facing is not None else character.movement.current_facing,
                np.array([1.0, 0.0, 0.0], dtype=np.float32),
            )
            if action.begin_arrival:
                planted = action.pose if action.pose is not None else pose
                try:
                    applied = _enter_arrival(character, planted, cycle.target_pose_id, rt, wp, facing)
                except Exception as exc:
                    publish({"type": "error", "message": f"Pose transition failed: {exc}"})
                    applied = False
                    _sync_pose(character, planted, wp, seed=True)
                cycle.note_arrival(applied, character.time_to_transition() if applied else 0.0)
            elif action.walk:
                if action.prime_walk:
                    _prime_walk(character, facing)
                character.step(DT, _command(rt, facing, facing))
            elif action.play:
                character.step(DT, _command(rt, facing, None))
            elif action.pose is not None:
                _sync_pose(character, action.pose, wp, seed=action.seed)
                if action.seed:
                    character.movement.reset_desired_velocity()
            step_ms = (time.perf_counter() - started_at) * 1000.0
            if step_ms >= _SLOW_STEP_MS:
                last_generate_ms = step_ms
            shown = character.current_pose.numpy().reshape((-1, 7)).copy()
            last_root = shown[0, :2].copy()
            distance = None if goal is None else float(np.linalg.norm(goal[:2] - shown[0, :2]))
            if _arrival_due(nav, cycle, goal is not None):
                publish(
                    {
                        "type": "arrived",
                        "pose_id": cycle.target_pose_id,
                        "pose_applied": cycle.pose_applied,
                        "arrival_error_m": None if distance is None else round(distance, 3),
                        "generate_ms": round(last_generate_ms, 2),
                    }
                )
                nav = replace(nav, arrived_sent=True)
            gait = action.gait or {}
            gait["phase"] = cycle.phase
            if gait.get("event") == "stop_requested":
                publish(
                    {
                        "type": "stop_triggered",
                        "distance_m": distance,
                        "speed_mps": round(root_speed, 3),
                        "threshold_m": None if cycle.choice is None else round(cycle.choice.final_window_m, 3),
                        "mode": cycle.mode,
                    }
                )
            publish(
                {
                    "type": "frame",
                    "phase": cycle.phase,
                    "official_state": character.state_machine.state.name,
                    "actual_speed_mps": round(root_speed, 3),
                    "poses": shown.tolist(),
                    "generate_ms": round(last_generate_ms, 2),
                    "gait": gait,
                }
            )
            frames += 1
            tick += 1
            if tick % 15 == 0:
                publish(
                    {
                        "type": "motion_state",
                        "phase": cycle.phase,
                        "official_state": character.state_machine.state.name,
                        "distance_m": None if distance is None else round(distance, 3),
                        "actual_speed_mps": round(root_speed, 3),
                        "controller_strength": 1.0 if action.walk else 0.0,
                        "mode": cycle.mode,
                        "gait": gait,
                    }
                )
            now = time.monotonic()
            if now - report_at >= 1.0:
                publish(
                    {
                        "type": "metrics",
                        "stream_hz": round(frames / (now - report_at), 1),
                        "generate_ms": round(last_generate_ms, 2),
                    }
                )
                frames = 0
                report_at = now
            next_tick += DT
            remaining = next_tick - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            else:
                next_tick = time.monotonic()


def _arrival_due(nav: NavState, cycle: LocomotionCycle, has_goal: bool) -> bool:
    if not has_goal or nav.arrived_sent:
        return False
    if cycle.hold_stance and cycle.phase == SETTLED:
        return True
    if not cycle.hold_stance and cycle.phase == POSE_DONE:
        return True
    return not cycle.hold_stance and cycle.arrival_done and cycle.phase == SETTLED
