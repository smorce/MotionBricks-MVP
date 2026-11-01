"""公式 Scene Preview の SOMA キャラクターで、クリック先まで歩いて止まる。

線形移動は Walk ブレンド（入力の長さ 1）だけで使う。短い距離と最後の一歩は
公式の目標姿勢生成を事前検証して再生し、着地後は公式 Idle へ入れない。
IdleState.enter は待機クリップの開始姿勢へ生成するため、足幅が変わる。

推論はこのプロセスの NVlabs/motionbricks 環境で行う。ルート座標は目標へ吸着しない。
MOTIONBRICKS_ROOT が未設定なら、docs/examples/_rig.py がある親を探す。
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
from queue import Empty, Queue

import numpy as np

from locomotion_cycle import IDLE, LocomotionCycle, POSE_DONE, SETTLED
from quats import RX90, quat_mul, quat_to_mat
from soma_pose import overlay_pose
from collect_stance import build_collect_target, build_collect_lift, build_weight_target, valid_weight_shift, validate_motion
from step_cycle import choose_swing, foot_points
from final_stop import build_stop_target, validate_stop_motion, stop_support, validate_stop_progress
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
    from motionbricks.runtime.target_pose import IKPin, TargetPoseInferenceParams, place_target_poses
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
        "IKPin": IKPin,
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


def _begin_collect(character, planted, swing, rt, wp, facing, cancelled=None):
    """独立キャラクターで全フレームを検証し、ライブ再生器には触れない。"""
    names = list(character.skeleton.joint_names)
    parents = [character.skeleton.joint_parent(i) for i in range(len(names))]
    target_pose = build_collect_target(planted, names, swing, parents)
    if target_pose is None:
        other = 'right' if swing == 'left' else 'left'
        target_pose = build_collect_target(planted, names, other, parents)
        swing = other
    if target_pose is None:
        return None, dict(accepted=False, reason="No safe F001 collect target")
    scratch = rt["SOMACharacter"](
        character.engine, asset_pool=character.asset_pool,
        modes=rt["DEFAULT_LOCOMOTION_MODES"],
        idle_paths=(rt["DEFAULT_IDLE_CLIPS"][0],),
        crouch_idle_paths=rt["DEFAULT_CROUCH_IDLE_CLIPS"],
    )
    _sync_pose(scratch, planted, wp, seed=True)
    source = wp.array(np.repeat(target_pose[None].astype(np.float32), rt["MODEL_POSES_PER_TOKEN"], axis=0),
                      dtype=wp.transform, device=character.engine.device)
    target = wp.empty_like(source)
    # 目標は既にワールド配置済みなので恒等配置を使い、二重変換を防ぐ。
    rt["place_target_poses"](wp.vec3(0, 0, 0), wp.vec3(1, 0, 0), source, target, stream=character.engine.stream)
    placed = target.numpy().reshape((-1, len(names), 7))[0]
    support = 'right' if swing == 'left' else 'left'
    a = foot_points(planted, parents, names)[support]
    b = foot_points(placed, parents, names)[support]
    if any(not np.allclose(a[part], b[part], atol=1e-5) for part in ('ankle', 'toe')):
        return None, dict(accepted=False, reason="Target placement changed support foot")
    mask = rt["IKPin"].RIGHT_FOOT if swing == 'left' else rt["IKPin"].LEFT_FOOT
    if cancelled is not None and cancelled.is_set():
        return None, dict(accepted=False, reason="Collect cancelled")
    params = rt["TargetPoseInferenceParams"](transition_early_by_frames=0, num_poses_to_use=1, ik_pin_mask=mask)

    def generate_segment(goal):
        scratch.generate_to_target_poses(goal, params)
        segment = []
        for _ in range(int(4 / DT)):
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("Collect cancelled")
            scratch._sample_playback(DT)
            segment.append(scratch.current_pose.numpy().reshape((-1, 7)).copy())
            scratch.player.record_pose(DT, scratch.current_pose)
            if scratch.time_to_transition() <= 0:
                return segment
        raise RuntimeError("Collect playback timed out")

    weight = build_weight_target(planted, parents, names, swing)
    # 公式補正器で開始時の両足を保つ目標を作る。独自の脚IKは使わない。
    both = rt["IKPin"].LEFT_FOOT | rt["IKPin"].RIGHT_FOOT
    pin_pose = wp.array(planted.astype(np.float32), dtype=wp.transform, device=character.engine.device)
    weight_pose = wp.array(weight.astype(np.float32), dtype=wp.transform, device=character.engine.device)
    corrector = scratch._target_pose_ik_corrector
    corrector.capture_pins(pin_pose, both, stream=character.engine.stream)
    corrector.apply(weight_pose, 1.0, stream=character.engine.stream)
    weight = weight_pose.numpy().reshape((-1, 7))
    weight_target = wp.array(np.repeat(weight[None].astype(np.float32), rt["MODEL_POSES_PER_TOKEN"], axis=0), dtype=wp.transform, device=character.engine.device)
    params = rt["TargetPoseInferenceParams"](transition_early_by_frames=0, num_poses_to_use=1,
        ik_pin_mask=rt["IKPin"].LEFT_FOOT | rt["IKPin"].RIGHT_FOOT)
    weight_frames = generate_segment(weight_target)
    if not valid_weight_shift(weight_frames, planted, parents, names, swing):
        return None, dict(accepted=False, reason="Weight shift did not preserve both contacts")
    params = rt["TargetPoseInferenceParams"](transition_early_by_frames=0, num_poses_to_use=1, ik_pin_mask=mask)
    a = foot_points(planted, parents, names)[swing]['ankle']
    b = foot_points(target_pose, parents, names)[swing]['ankle']
    intermediate = build_collect_lift(weight_frames[-1], parents, names, swing, float(np.linalg.norm(b[:2] - a[:2])))
    if intermediate is None:
        return None, dict(accepted=False, reason="No safe lift target")
    lift_target = wp.array(np.repeat(intermediate[None].astype(np.float32), rt["MODEL_POSES_PER_TOKEN"], axis=0), dtype=wp.transform, device=character.engine.device)
    frames = [planted.copy(), *weight_frames, *generate_segment(lift_target), *generate_segment(target)]
    metrics = validate_motion(frames, planted, parents, names, swing)
    metrics["stages"] = 3
    metrics["swing"] = swing
    return (frames if metrics['accepted'] else None), metrics


def _begin_final_stop(character, pose, goal, rt, wp, destination=None):
    """歩行履歴から公式生成し、表示する前に停止区間全体を検証する。"""
    names = list(character.skeleton.joint_names)
    parents = [character.skeleton.joint_parent(i) for i in range(len(names))]
    target_pose = build_stop_target(pose, goal, parents, names)
    if target_pose is None:
        return None, dict(accepted=False, stage='target', reason='No safe final stop target')
    support = stop_support(pose, goal, parents, names)
    target = wp.array(np.repeat(target_pose[None].astype(np.float32), rt['MODEL_POSES_PER_TOKEN'], axis=0),
                      dtype=wp.transform, device=character.engine.device)
    frames = []
    try:
        # 履歴を初期化せず、直前までの速度と歩行位相を生成器へ渡す。
        character.generate_to_target_poses(target, rt['TargetPoseInferenceParams'](
            transition_early_by_frames=0, num_poses_to_use=1,
            ik_pin_mask=rt['IKPin'].LEFT_FOOT if support == 'left' else rt['IKPin'].RIGHT_FOOT))
        for _ in range(int(4 / DT)):
            character._sample_playback(DT)
            frames.append(character.current_pose.numpy().reshape((-1, 7)).copy())
            character.player.record_pose(DT, character.current_pose)
            if character.time_to_transition() <= 0:
                break
        else:
            return None, dict(accepted=False, stage='generation', reason='Final stop generation timed out')
        metrics = validate_stop_motion(frames, pose, goal, parents, names)
        metrics.update(stage='validation', support=support)
        if metrics['accepted']:
            reason = validate_stop_progress(frames, pose, goal if destination is None else destination, support, parents, names)
            if reason:
                metrics.update(accepted=False, reason=reason)
        metrics['travel_distance_m'] = float(np.linalg.norm(frames[-1][0, :2] - pose[0, :2])) if frames else 0.0
        return (frames if metrics['accepted'] else None), metrics
    finally:
        _sync_pose(character, pose, wp, seed=True)
        character.clear_ik_pins()



def _collect_job(planted, swing, facing, cancelled):
    """推論専用エンジンを使い、ライブ歩行とGPU状態を共有しない。"""
    rt = _load_runtime()
    wp = rt["wp"]
    wp.init()
    wp.set_device("cuda:0")
    assets = rt["load_rig_assets"](rt["ModelRig"].SOMA)
    pool = rt["SmartPrimitiveAssetPool"](assets.clip_registry, assets.reference_pose, assets.model_to_runtime)
    engine = rt["MotionBricksSOMAEngine"](rt["SOMA_N1_FP32_ONNX_PATH"], model_to_runtime=assets.model_to_runtime)
    with engine, wp.ScopedStream(engine.stream):
        character = rt["SOMACharacter"](engine, asset_pool=pool, modes=rt["DEFAULT_LOCOMOTION_MODES"],
            idle_paths=(rt["DEFAULT_IDLE_CLIPS"][0],), crouch_idle_paths=rt["DEFAULT_CROUCH_IDLE_CLIPS"])
        return _begin_collect(character, planted, swing, rt, wp, facing, cancelled)


def _drain(commands: Queue, nav: NavState, cycle=None):
    goal = None
    while True:
        try:
            cmd = commands.get_nowait()
        except Empty:
            return nav, goal
        if cmd.get("type") == "upper_idle_ready" and cycle is not None:
            cycle.note_upper_idle_ready(cmd.get("move_id"), cmd.get("settle_seq"))
        if cmd.get("type") == "collect_review" and cycle is not None:
            metrics = cmd.get("metrics")
            cycle.note_collect_review(cmd.get("accepted") is True, metrics if isinstance(metrics, dict) else {}, cmd.get("move_id"), cmd.get("settle_seq"))
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
        collect_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="collect-gpu")
        collect_job = None
        collect_cancel = Event()
        while True:
            drained = _drain(commands, nav, cycle)
            if drained is None:
                collect_cancel.set()
                collect_executor.shutdown(wait=False, cancel_futures=True)
                return
            nav, moved = drained
            if moved is not None:
                collect_cancel.set()
                if collect_job is not None:
                    collect_job[0].cancel()
                    collect_job = None
                goal = moved
                cycle.begin_move(moved, nav.hold_stance, nav.move_id)
            if not nav.hold_stance and nav.target_pose_id != cycle.target_pose_id:
                cycle.note_pose_choice(nav.target_pose_id)
            if collect_job is not None and cycle.phase != "collect_preparing":
                collect_cancel.set()
                collect_job[0].cancel()
                collect_job = None
            if collect_job is not None and collect_job[0].done():
                future, move_id, settle_seq = collect_job
                collect_job = None
                try:
                    collect_frames, metrics = future.result()
                except Exception as exc:
                    collect_frames, metrics = None, dict(accepted=False, reason=f"Collect generation failed: {exc}")
                if cycle.stage_collect(collect_frames, metrics, move_id, settle_seq):
                    publish({"type": "collect_candidate", "move_id": move_id, "settle_seq": settle_seq,
                             "frames": [frame.tolist() for frame in collect_frames], "metrics": metrics})
                elif metrics.get("reason"):
                    print(f"Collect rejected: {metrics['reason']}", flush=True)
            pose = character.current_pose.numpy().reshape((-1, 7)).copy()
            playback = character._playback_source.name
            contacts_available = playback != "CLIP" and cycle.phase in (IDLE, "moving", "decelerating", "waiting_for_foot_contact", "contact_recovery")
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
            if action.begin_final_stop:
                try:
                    stop_frames, stop_metrics = _begin_final_stop(character, action.pose, cycle.final_stop_goal, rt, wp, destination=cycle.goal)
                except Exception as exc:
                    _sync_pose(character, pose, wp, seed=True)
                    stop_frames, stop_metrics = None, dict(accepted=False, stage='generation', reason=f'Final stop generation failed: {exc}')
                cycle.note_final_stop(stop_frames, stop_metrics)
                character.movement.reset_desired_velocity()
            elif action.begin_stop_recovery:
                try:
                    applied = _enter_arrival(character, action.pose, "F001", rt, wp, facing)
                    cycle.note_stop_recovery(applied, character.time_to_transition() if applied else 0.0)
                except Exception as exc:
                    _sync_pose(character, action.pose, wp, seed=True)
                    cycle.note_stop_recovery(False, 0.0)
                    publish({"type": "error", "message": f"Stop recovery failed: {exc}"})
                character.movement.reset_desired_velocity()
            elif action.begin_collect:
                planted = action.pose
                feet = foot_points(planted, parents, names)
                swing = choose_swing(feet['left']['ankle'], feet['right']['ankle'], facing,
                                     feet['left']['ankle'][2], feet['right']['ankle'][2])
                collect_cancel = Event()
                collect_job = (collect_executor.submit(_collect_job, planted.copy(), swing, facing.copy(), collect_cancel), cycle.move_id, cycle.settle_seq)
            elif action.begin_arrival:
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
            last_root = pose[0, :2].copy()
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
                        "threshold_m": round(max(.08, cycle.stop_prediction_m), 3),
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
