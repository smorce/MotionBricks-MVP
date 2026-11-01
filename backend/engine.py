"""公式 Scene Preview の SOMA キャラクターで、クリック先まで歩いて止まる。

推論はこのプロセスの NVlabs/motionbricks 環境で行う。停止そのものは
LocomotionState から IdleState への公式遷移に任せ、待機ループに入ってから
PoseLoom の姿勢へ生成でつなぐ。ルート座標は目標へ吸着しない。
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

from click_planner import ClickStopSettings, plan_click_move
from quats import RX90, quat_mul, quat_to_mat
from soma_pose import overlay_pose
from stop_phase import (
    MOVING,
    NavState,
    after_playback,
    after_pose_request,
    apply_nav_command,
    arm_stop,
    arrival_due,
)

UPDATE_HZ = 60.0
DT = 1.0 / UPDATE_HZ
STOP_SETTINGS = ClickStopSettings()
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
        LINEAR_LOCOMOTION,
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
        "LINEAR_LOCOMOTION": LINEAR_LOCOMOTION,
    }


def _norm_xy(vec: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    size = float(np.linalg.norm(vec[:2]))
    if size > 1e-6:
        return np.array([vec[0] / size, vec[1] / size, 0.0], dtype=np.float32)
    return fallback.astype(np.float32, copy=True)


def _request_custom_pose(character, pose_id: str, rt) -> bool:
    """公式の待機が終わったあとに、骨長を保ったまま目標姿勢へ生成する。"""
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
    # 目標の手前で入力を弱めるため、公式の最低速度だけを外す。
    click_mode = replace(rt["LINEAR_LOCOMOTION"], minimum_speed=0.0)
    modes = (click_mode, *[mode for mode in rt["DEFAULT_LOCOMOTION_MODES"] if mode.name != click_mode.name])
    engine = rt["MotionBricksSOMAEngine"](
        rt["SOMA_N1_FP32_ONNX_PATH"],
        model_to_runtime=assets.model_to_runtime,
    )
    playback = rt["PlaybackSource"]
    with engine, wp.ScopedStream(engine.stream):
        character = rt["SOMACharacter"](
            engine,
            asset_pool=pool,
            modes=modes,
            idle_paths=(rt["DEFAULT_IDLE_CLIPS"][0],),
            crouch_idle_paths=rt["DEFAULT_CROUCH_IDLE_CLIPS"],
        )
        skeleton = character.skeleton
        rest = skeleton.reference_local_transforms.numpy().reshape((-1, 7)).copy()
        # USD の基準姿勢は Y-up。配信フレームは Z-up なので、ルートだけ同じ基底に揃える。
        rest[0, :3] = quat_to_mat(RX90) @ rest[0, :3]
        rest[0, 3:] = quat_mul(RX90, rest[0, 3:])
        publish(
            {
                "type": "rig",
                "joint_names": skeleton.joint_names,
                "parents": [skeleton.joint_parent(i) for i in range(skeleton.num_joints)],
                "rest": rest.tolist(),
                "stream_hz": UPDATE_HZ,
            }
        )
        nav = NavState()
        goal = None
        last_generate_ms = 0.0
        frames = 0
        tick = 0
        report_at = time.monotonic()
        next_tick = time.monotonic()
        while True:
            drained = _drain(commands, nav)
            if drained is None:
                return
            nav, moved = drained
            if moved is not None:
                goal = moved
            position = character.character_ground_position.copy()
            facing = character.movement.current_facing.copy()
            actual_speed = float(np.linalg.norm(character.actual_velocity[:2]))
            distance = None
            strength = 0.0
            if goal is not None:
                diff = goal - position
                diff[2] = 0.0
                distance = float(np.linalg.norm(diff[:2]))
                facing = _norm_xy(diff, facing)
                if nav.phase == MOVING:
                    decision = plan_click_move(distance, actual_speed, STOP_SETTINGS)
                    phase, started = arm_stop(nav.phase, decision.stop)
                    nav = replace(nav, phase=phase)
                    if started:
                        publish(
                            {
                                "type": "stop_triggered",
                                "distance_m": distance,
                                "speed_mps": actual_speed,
                                "threshold_m": decision.stop_distance_m,
                            }
                        )
                    else:
                        strength = decision.input_strength
            movement = facing * strength if nav.phase == MOVING else None
            started_at = time.perf_counter()
            character.step(
                DT,
                rt["LocomotionCommand"](
                    facing_direction=facing,
                    movement=movement,
                    use_max_speed=False,
                ),
            )
            step_ms = (time.perf_counter() - started_at) * 1000.0
            if step_ms >= _SLOW_STEP_MS:
                last_generate_ms = step_ms
            # 公開 API に再生源が無い。公式 Idle の「遷移中」と「ループ中」をここで区別する。
            in_clip_transition = character._playback_source is playback.CLIP_TRANSITION
            in_idle_loop = (
                character.state_machine.state is character.state_machine.standing_idle_state
                and character._playback_source is playback.CLIP
            )
            phase, attempt = after_playback(
                nav.phase,
                in_idle_loop=in_idle_loop,
                in_clip_transition=in_clip_transition,
                time_to_transition=character.time_to_transition(),
                dt=DT,
            )
            nav = replace(nav, phase=phase)
            if attempt:
                pose_started = time.perf_counter()
                try:
                    applied = _request_custom_pose(character, nav.target_pose_id, rt)
                except Exception as exc:
                    publish({"type": "error", "message": f"Pose transition failed: {exc}"})
                    applied = False
                if applied:
                    last_generate_ms = (time.perf_counter() - pose_started) * 1000.0
                nav = replace(
                    nav,
                    pose_applied=applied,
                    phase=after_pose_request(
                        applied,
                        character.time_to_transition() if applied else DT,
                        DT,
                    ),
                )
            if arrival_due(nav.phase, nav.arrived_sent, goal is not None):
                final_position = character.character_ground_position.copy()
                arrival_error = float(np.linalg.norm((goal - final_position)[:2]))
                publish(
                    {
                        "type": "arrived",
                        "pose_id": nav.target_pose_id,
                        "pose_applied": nav.pose_applied,
                        "arrival_error_m": round(arrival_error, 3),
                        "generate_ms": round(last_generate_ms, 2),
                    }
                )
                nav = replace(nav, arrived_sent=True)
            publish(
                {
                    "type": "frame",
                    "phase": nav.phase,
                    "official_state": character.state_machine.state.name,
                    "actual_speed_mps": round(actual_speed, 3),
                    "poses": character.current_pose.numpy().reshape((-1, 7)).tolist(),
                    "generate_ms": round(last_generate_ms, 2),
                }
            )
            frames += 1
            tick += 1
            if tick % 15 == 0:
                publish(
                    {
                        "type": "motion_state",
                        "phase": nav.phase,
                        "official_state": character.state_machine.state.name,
                        "distance_m": None if distance is None else round(distance, 3),
                        "actual_speed_mps": round(actual_speed, 3),
                        "controller_strength": round(strength, 3),
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
