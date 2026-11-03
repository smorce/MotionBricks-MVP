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
from pathlib import Path
from queue import Empty, Queue

import numpy as np
from timings import TIMINGS

from locomotion_cycle import IDLE, LocomotionCycle, POSE_DONE, SETTLED
from quats import RX90, quat_mul, quat_to_mat
from soma_pose import overlay_pose
from collect_stance import build_collect_target, build_collect_lift, build_weight_target, valid_weight_shift, validate_motion
from step_cycle import choose_swing, foot_points
from final_stop import build_stop_target, validate_stop_motion, stop_support, validate_stop_progress, calibrate_stop_ground
from final_stop import support_target_metrics, support_motion_metrics, check_bone_lengths, contact_points
import logging
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
    character.character_ground_position[:2] = flat[0, :2]
    character.character_ground_position[2] = 0.
    if seed:
        character.actual_velocity.fill(0.)
        character.player.seed_history_from_pose(character.current_pose)


def _prime_walk(character, facing: np.ndarray) -> None:
    """加速スプリングの低速域は Idle ブレンドなので、歩行開始時だけ Walk 速度に置く。"""
    locomotion = character.state_machine.active_locomotion_state
    locomotion.settings = replace(locomotion.settings, direction_regeneration_dot=float(np.cos(np.deg2rad(1))))
    locomotion._force_regeneration = True
    mode = locomotion.active_mode
    speed = float(mode.default_speed)
    direction = np.asarray(facing, dtype=np.float32).copy()
    direction[2] = 0.0
    norm = float(np.linalg.norm(direction[:2]))
    if norm < 1e-6:
        return
    direction[:2] /= norm
    movement = character.movement
    movement.settings = replace(movement.settings, velocity_direction_halflife=.05)
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


def live_candidate_specs(preferred):
    from stop_runtime import candidate_specs
    # 実モデルで平坦な目標より到達しやすかった、支持脚を曲げる候補から検証する。
    return sorted(candidate_specs(preferred), key=lambda spec: (
        spec['mode'] != 'staged', spec['tokens'] != 8, -spec['root_lower'],
        spec['support'] != preferred))


def _begin_final_stop(character, pose, goal, rt, wp, destination=None, *, ground, control=None, cancelled=None):
    """ライブの再生履歴を変更せず、独立再生器で少数の候補を検証する。"""
    if not hasattr(character, 'asset_pool'):
        return _begin_final_stop_legacy(character, pose, goal, rt, wp, destination, ground=ground)
    from stop_replay import capture_replay
    from stop_runtime import new_character, candidate_specs, refinement_specs, generate_candidate, diagnose
    from stop_candidate_search import search_candidates
    replay = capture_replay(character, goal, ground, control=control)
    preferred = replay['metadata']['support']
    specs = live_candidate_specs(preferred) if cancelled is not None else candidate_specs(preferred)
    deadline = time.perf_counter() + 2.0 if cancelled is not None else None
    def diagnose_progress(frames):
        with TIMINGS.measure("diagnostics"):
            metrics = diagnose(replay, frames)
        if metrics['accepted']:
            data = replay['metadata']
            reason = validate_stop_progress(
                frames, pose, goal if destination is None else destination,
                frames.support, data['parents'], data['names'])
            original_goal = goal if destination is None else destination
            error = float(np.linalg.norm(frames[-1][0, :2] - np.asarray(original_goal)[:2]))
            metrics['arrival_error_m'] = error
            if error > .05 + 1e-9:
                reason = 'Stop missed original destination'
            if reason:
                metrics.update(accepted=False, reason=reason)
        return metrics

    result = search_candidates(specs,
        lambda spec: new_character(rt, character.engine, character.asset_pool, replay),
        lambda scratch, spec: generate_candidate(scratch, replay, spec, rt),
        diagnose_progress, limit=24, stop_on_first=True, cancelled=cancelled, deadline=deadline)
    frames = result.pop('frames')
    if frames is None:
        refined_specs = refinement_specs(preferred)
        refined = search_candidates(refined_specs,
            lambda spec:new_character(rt,character.engine,character.asset_pool,replay),
            lambda scratch,spec:generate_candidate(scratch,replay,spec,rt),
            diagnose_progress,limit=24,stop_on_first=True, cancelled=cancelled, deadline=deadline)
        frames=refined.pop('frames')
        if refined['selected'] is not None:
            result['selected']=len(result['candidates'])+refined['selected']
        result['candidates'].extend(refined['candidates'])
    recovery_only = False
    if frames is None:
        import copy
        recovery = copy.deepcopy(replay)
        recovery['metadata']['goal'] = np.asarray(pose)[0, :2].tolist()
        recovery['metadata']['f001'] = None
        recovery['metadata'].setdefault('control', {})['destination'] = recovery['metadata']['goal']
        fallback = search_candidates(specs,
            lambda spec: new_character(rt, character.engine, character.asset_pool, recovery),
            lambda scratch, spec: generate_candidate(scratch, recovery, spec, rt),
            lambda values: diagnose(recovery, values), limit=24, stop_on_first=True, cancelled=cancelled, deadline=deadline)
        frames = fallback.pop('frames')
        result['recovery'] = fallback
        recovery_only = frames is not None
    if recovery_only:
        chosen = result['recovery']
        selected = chosen['candidates'][chosen['selected']]
        error = float(np.linalg.norm(frames[-1][0, :2] - np.asarray(goal if destination is None else destination)[:2]))
        metrics = dict(selected['metrics'], recovery_only=error > .05 + 1e-9, arrival_error_m=error, search=result,
                       generation_conditions=selected['specification'])
    elif result['selected'] is None:
        metrics = dict(accepted=False, reason='No safe stop candidate', search=result)
    else:
        selected = result['candidates'][result['selected']]
        metrics = dict(selected['metrics'], search=result, generation_conditions=selected['specification'])
    metrics['travel_distance_m'] = (
        float(np.linalg.norm(frames[-1][0, :2] - pose[0, :2]))
        if frames is not None else 0.0)
    directory = Path(os.environ.get('MOTIONBRICKS_STOP_REPLAY_DIR',
                                      str(Path(__file__).resolve().parents[1] / 'metrics/stop-replays')))
    replay['metadata']['search'] = result
    if frames is not None:
        replay['metadata']['frames'] = np.asarray(frames).copy()
        replay['metadata']['generated_contacts'] = frames.contacts
        replay['metadata']['generated_support'] = frames.support
        replay['metadata']['validation_goal'] = np.asarray(pose)[0,:2].tolist() if recovery_only else np.asarray(goal).tolist()
        replay['metadata']['recovery_only'] = metrics.get('recovery_only', False)
    from replay_writer import WRITER
    WRITER.submit(directory / f'stop-{time.time_ns()}.json', replay)
    return frames, metrics


def _begin_final_stop_legacy(character, pose, goal, rt, wp, destination=None, *, ground):
    """歩行履歴から公式生成し、表示する前に停止区間全体を検証する。"""
    names = list(character.skeleton.joint_names)
    parents = [character.skeleton.joint_parent(i) for i in range(len(names))]
    replay_directory = os.environ.get('MOTIONBRICKS_STOP_REPLAY_DIR')
    if replay_directory:
        from stop_replay import save_replay
        recorder = character.player.motion_history
        save_replay(Path(replay_directory) / f'stop-{time.time_ns()}.json',
                    pose=pose, history=recorder.poses.numpy(), delta_times=recorder.delta_times,
                    metadata=dict(goal=np.asarray(goal).tolist(), parents=parents, names=names,
                                  ground=ground, support=stop_support(pose, goal, parents, names),
                                  replay_scope='History capture only; GPU RNG and VRM mapping not captured'))
    target_pose = build_stop_target(pose, goal, parents, names, ground)
    if target_pose is None:
        return None, dict(accepted=False, stage='target', reason='No safe final stop target')
    support = stop_support(pose, goal, parents, names)
    mask = rt['IKPin'].LEFT_FOOT if support == 'left' else rt['IKPin'].RIGHT_FOOT
    diagnostics = support_target_metrics(pose, target_pose, support, parents, names)
    diagnostics['f001_support_target'] = diagnostics.copy()
    diagnostics['ik_pin_mask'] = int(mask)
    logging.getLogger(__name__).info('Stop target support diagnostics: %s', diagnostics)
    # 公式補正器で支持足を開始位置に固定する。独自の脚制御は使わない。
    pin_pose = wp.array(pose.astype(np.float32), dtype=wp.transform, device=character.engine.device)
    corrected = wp.array(target_pose.astype(np.float32), dtype=wp.transform, device=character.engine.device)
    corrector = character._target_pose_ik_corrector
    corrector.capture_pins(pin_pose, mask, stream=character.engine.stream)
    try:
        corrector.apply(corrected, 1.0, stream=character.engine.stream)
        target_pose = corrected.numpy().reshape((-1, 7)).copy()
    finally:
        character.clear_ik_pins()
    diagnostics.update(support_target_metrics(pose, target_pose, support, parents, names))
    diagnostics.update(check_bone_lengths([target_pose], pose, names))
    feet = contact_points(foot_points(target_pose, parents, names), ground)
    if (diagnostics['support_target_error_m'] > .02
            or diagnostics['support_target_toe_error_m'] > .02
            or diagnostics['support_target_error_3d_m'] > .02
            or diagnostics['support_target_direction_error_rad'] > .1
            or not diagnostics['bone_lengths_valid']
            or any(min(feet[s][p][2] for p in ('ankle', 'toe')) > ground['floor_z'] + .04
                   for s in ('left', 'right'))
            or any(feet[s][p][2] < ground['floor_z'] - .02
                   for s in ('left', 'right') for p in ('ankle', 'toe'))):
        return None, dict(diagnostics, accepted=False, stage='target', reason='No safe pinned stop target')
    target = wp.array(np.repeat(target_pose[None].astype(np.float32), rt['MODEL_POSES_PER_TOKEN'], axis=0),
                      dtype=wp.transform, device=character.engine.device)
    frames = []
    try:
        # 履歴を初期化せず、直前までの速度と歩行位相を生成器へ渡す。
        character.generate_to_target_poses(target, rt['TargetPoseInferenceParams'](
            transition_early_by_frames=0, num_poses_to_use=1,
            ik_pin_mask=mask))
        for _ in range(int(4 / DT)):
            character._sample_playback(DT)
            frames.append(character.current_pose.numpy().reshape((-1, 7)).copy())
            character.player.record_pose(DT, character.current_pose)
            if character.time_to_transition() <= 0:
                break
        else:
            return None, dict(diagnostics, accepted=False, stage='generation', reason='Final stop generation timed out')
        metrics = validate_stop_motion(frames, pose, goal, parents, names, ground)
        metrics = {**diagnostics, **metrics}
        metrics.update(support_motion_metrics(frames, pose, support, parents, names, ground))
        metrics.update(stage='validation', support=support, ik_pin_mask=int(mask))
        if metrics['accepted']:
            reason = validate_stop_progress(frames, pose, goal if destination is None else destination, support, parents, names)
            if reason:
                metrics.update(accepted=False, reason=reason)
        metrics['travel_distance_m'] = float(np.linalg.norm(frames[-1][0, :2] - pose[0, :2])) if frames else 0.0
        return (frames if metrics['accepted'] else None), metrics
    finally:
        _sync_pose(character, pose, wp, seed=True)
        character.clear_ik_pins()




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
            if cycle is not None:
                cycle.resume_checkpoint = cmd.get("_checkpoint")
                cycle.retarget_settings = cmd.get('retarget_settings', {})
                if cmd.get('stop_mode') in ('visual', 'prepared'):
                    cycle.stop_mode = cmd['stop_mode']
                else:
                    cycle.stop_mode = getattr(cycle, 'default_stop_mode', 'prepared')
    return nav, goal


def _stream_selection(selection):
    if selection is None:
        return None
    return {name: value for name, value in selection.items() if name not in ('state_features', 'review')}


def _command(rt, facing: np.ndarray, movement: np.ndarray | None):
    return rt["LocomotionCommand"](
        facing_direction=np.asarray(facing, dtype=np.float32),
        movement=None if movement is None else np.asarray(movement, dtype=np.float32),
        use_max_speed=False,
    )


def _produce_frames(pending, output, epoch, closed):
    from frame_pipeline import ProcessOutput
    proxy = ProcessOutput(output, epoch, closed)
    try:
        _generation_worker(pending, lambda message: output.put(('direct', message)), proxy)
    except BaseException as exc:
        output.put(('direct', {'type': 'error', 'message': str(exc)}))
    finally:
        from replay_writer import WRITER
        WRITER.flush()


def worker(commands: Queue, publish):
    from frame_pipeline import FramePipeline, TERMINAL, CheckpointHistory
    import multiprocessing
    from frame_clock import FrameClock
    clock = FrameClock()
    timer = None
    if sys.platform == "win32":
        import ctypes
        timer = ctypes.WinDLL("winmm")
        timer.timeBeginPeriod(1)
    from stop_phase import apply_nav_command
    pipeline = FramePipeline(capacity=240, prefill=180)
    context = multiprocessing.get_context('spawn')
    pending = context.Queue()
    output = context.Queue(maxsize=120)
    epoch = context.Value('q', -1)
    closed = context.Event()
    state = NavState()
    last_checkpoint = None
    checkpoints = CheckpointHistory()
    sequence = 0
    last_delivery = None
    process = context.Process(target=_produce_frames, args=(pending, output, epoch, closed), name='motion-inference', daemon=True)
    process.start()
    next_tick = time.perf_counter()
    try:
        while True:
            while not commands.empty():
                command = commands.get_nowait()
                resume_checkpoint = last_checkpoint
                if command.get('type') == 'move' and command.get('source_sequence') is not None:
                    resume_checkpoint = checkpoints.resolve(command['source_sequence'], command.get('source_move_id'))
                    if resume_checkpoint is None:
                        publish({'type':'error','message':'Move source frame is no longer available',
                                 'source_sequence':command['source_sequence'], 'source_move_id':command.get('source_move_id'),
                                 'latest_sequence':sequence-1})
                        continue
                result = apply_nav_command(state, command)
                if result.quit:
                    pending.put(command)
                    return
                state = result.state
                if result.move_to is not None:
                    epoch.value = state.move_id
                    pipeline.begin(state.move_id)
                    command = dict(command, _checkpoint=resume_checkpoint)
                pending.put(command)
            intake_started = time.perf_counter()
            for _ in range(4):
                if len(pipeline.frames) >= pipeline.capacity or (pipeline.frames and pipeline.frames[-1][0].get('phase') in TERMINAL):
                    break
                try:
                    generated = output.get_nowait()
                except Empty:
                    break
                if generated[0] == 'direct':
                    publish(generated[1])
                    continue
                identity, message, checkpoint, events, timing = generated
                if identity != pipeline.epoch:
                    continue
                if timing is not None:
                    publish(dict(type='generation_metrics', **timing))
                for event in events:
                    pipeline.event(event, identity)
                pipeline.offer(message, checkpoint, identity)
            TIMINGS.record("frame_intake", (time.perf_counter()-intake_started)*1000)
            if not process.is_alive() and output.empty():
                raise RuntimeError('Inference process stopped')
            packet = pipeline.take()
            if packet is not None:
                frame, last_checkpoint, events = packet
                from gait_log import GAIT_LOG
                row = frame.pop('_log_row', None)
                if row is not None:
                    GAIT_LOG.add(row)
                checkpoints.add(sequence, frame.get('gait', {}).get('move_id'), last_checkpoint)
                frame['sequence'] = sequence
                frame['simulation_time'] = sequence * DT
                frame['pipeline_underflows'] = pipeline.underflows
                sequence += 1
                now = time.perf_counter()
                if last_delivery is not None:
                    TIMINGS.record("delivery_interval", (now-last_delivery)*1000)
                last_delivery = now
                publish(frame)
                for event in events:
                    publish(event)
            next_tick += DT
            delay = next_tick - time.perf_counter()
            if delay > 0:
                clock.wait(next_tick)
            else:
                next_tick = time.perf_counter()
    finally:
        clock.close()
        pipeline.close()
        pending.put({'type': 'quit'})
        closed.set()
        process.join(timeout=3)
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
        if timer is not None:
            timer.timeEndPeriod(1)


def _generation_worker(commands: Queue, publish, pipeline):
    """GPU と Warp は、この単一推論プロセスだけが所有する。"""
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
        stop_ground = calibrate_stop_ground(rest, parents, names)
        publish(
            {
                "type": "rig",
                "joint_names": names,
                "parents": parents,
                "rest": rest.tolist(),
                "stop_ground": stop_ground,
                "stream_hz": UPDATE_HZ,
            }
        )
        nav = NavState()
        cycle = LocomotionCycle()
        cycle.preview_stops = True
        from visual_stop_runtime import VisualStopRuntime
        visual_stop = VisualStopRuntime()
        visual_stop.prepared = os.environ.get('MOTIONBRICKS_VISUAL_STOP') != '1'
        visual_stop_cache = visual_stop
        cycle.stop_mode = 'prepared' if visual_stop.prepared else 'visual'
        cycle.default_stop_mode = cycle.stop_mode
        cycle.ground_calibration = stop_ground
        comparison_idle = None
        if os.environ.get('MOTIONBRICKS_COMPARISON_REPLAY'):
            from stop_replay import capture_replay
            comparison_idle = capture_replay(character, character.current_pose.numpy().reshape((-1, 7))[0, :2] + [.3, 0], stop_ground)
        goal = None
        last_generate_ms = 0.0
        frames = 0
        tick = 0
        report_at = time.monotonic()
        last_root = None
        def emit(message):
            if message['type'] == 'frame':
                recorder = character.player.motion_history
                checkpoint = dict(pose=character.current_pose.numpy().reshape((-1, 7)).copy(),
                                  history=recorder.poses.numpy().copy(),
                                  delta_times=list(recorder.delta_times),
                                  contacts=character.current_foot_contacts.numpy().copy(),
                                  movement={name: value.copy() if isinstance(value, np.ndarray) else value
                                            for name, value in vars(character.movement).items()
                                            if isinstance(value, (np.ndarray, float, int))})
                from gait_log import GAIT_LOG
                row = GAIT_LOG.last()
                if row is not None:
                    message['_log_row'] = dict(row, final_stop_metrics=message['gait']['final_stop_metrics'])
                with TIMINGS.measure("producer_backpressure"):
                    pipeline.offer(message, checkpoint, cycle.move_id)
            else:
                pipeline.event(message, cycle.move_id)

        while True:
            drained = _drain(commands, nav, cycle)
            if drained is None:
                return
            nav, moved = drained
            if moved is not None:
                checkpoint = getattr(cycle, 'resume_checkpoint', None)
                if checkpoint is not None:
                    from stop_replay import restore_history
                    _sync_pose(character, checkpoint['pose'], wp, seed=True)
                    restore_history(character, dict(history=checkpoint['history'], delta_times=checkpoint['delta_times'],
                                                   metadata=dict(contacts=checkpoint['contacts'])))
                    for name, value in checkpoint.get('movement', {}).items():
                        setattr(character.movement, name, value.copy() if isinstance(value, np.ndarray) else value)
                    last_root = None
                if cycle.stop_mode in ('visual', 'prepared') and visual_stop_cache is None:
                    visual_stop_cache = VisualStopRuntime()
                visual_stop = visual_stop_cache if cycle.stop_mode in ('visual', 'prepared') else None
                if visual_stop:
                    visual_stop.selection = None
                    visual_stop.prepared = cycle.stop_mode == 'prepared'
                comparison_start = os.environ.get('MOTIONBRICKS_COMPARISON_REPLAY')
                if comparison_start and nav.move_id != 2:
                    from stop_replay import load_replay, restore_history
                    initial = comparison_idle if nav.move_id == 8 else load_replay(str(Path(comparison_start).parent / 'after-turn/source-replay.json') if nav.move_id == 7 else comparison_start)
                    _sync_pose(character, np.asarray(initial['pose']), wp)
                    restore_history(character, initial)
                    last_root = None
                goal = moved
                cycle.begin_move(moved, nav.hold_stance, nav.move_id)
            if not nav.hold_stance and nav.target_pose_id != cycle.target_pose_id:
                cycle.note_pose_choice(nav.target_pose_id)
            pose = character.current_pose.numpy().reshape((-1, 7)).copy()
            playback = character._playback_source.name
            contacts_available = playback != "CLIP" and cycle.phase in (IDLE, "moving", "decelerating", "waiting_for_foot_contact", "contact_recovery")
            root_speed = 0.0
            if last_root is not None:
                root_speed = float(np.linalg.norm(pose[0, :2] - last_root) / DT)
            started_at = time.perf_counter()
            with TIMINGS.measure("candidate_match"):
                cycle.visual_selection = visual_stop.observe(character, cycle.goal, stop_ground) if visual_stop and cycle.goal is not None and cycle.stop_requested_s is None else None
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
                generation_start = time.perf_counter()
                try:
                    if visual_stop:
                        stop_frames, stop_metrics = visual_stop.generate(character, cycle.final_stop_goal, stop_ground, rt, destination=cycle.goal)
                    else:
                        stop_control = dict(move_id=cycle.move_id, settle_seq=cycle.settle_seq,
                                            source_frame=tick, retry_count=cycle.stop_retry_count,
                                            last_stop_distance_m=cycle.last_stop_distance_m,
                                            facing=facing.tolist())
                        stop_frames, stop_metrics = _begin_final_stop(character, action.pose, cycle.final_stop_goal, rt, wp, destination=cycle.goal, ground=stop_ground, cancelled=lambda: not pipeline.is_current(cycle.move_id), control=dict(**stop_control, phase=cycle.phase, speed_mps=root_speed, stop_prediction_m=cycle.stop_prediction_m, destination=None if cycle.goal is None else cycle.goal.tolist(), contacts=dict(left=cycle.plants.left, right=cycle.plants.right), retarget_settings=getattr(cycle,'retarget_settings',{})))
                except Exception as exc:
                    _sync_pose(character, pose, wp, seed=True)
                    stop_frames, stop_metrics = None, dict(accepted=False, single_attempt=cycle.stop_mode == 'prepared', stage='generation', reason=f'Final stop generation failed: {exc}')
                TIMINGS.record("stop_generation", (time.perf_counter()-generation_start)*1000)
                if (not stop_metrics.get('accepted') or stop_metrics.get('recovery_only')) and cycle.reject_stop_preview(pose):
                    facing = cycle._facing(pose, character.movement.current_facing)
                    if not cycle.walk_primed:
                        _prime_walk(character, facing)
                        cycle.walk_primed = True
                    with TIMINGS.measure("walk_update"):
                        character.step(DT, _command(rt, facing, facing))
                    if action.gait:
                        action.gait['event'] = ''
                else:
                    cycle.note_final_stop(stop_frames, stop_metrics)
                    character.movement.reset_desired_velocity()
            elif action.begin_stop_recovery:
                try:
                    applied = _enter_arrival(character, action.pose, "F001", rt, wp, facing)
                    cycle.note_stop_recovery(applied, character.time_to_transition() if applied else 0.0)
                except Exception as exc:
                    _sync_pose(character, action.pose, wp, seed=True)
                    cycle.note_stop_recovery(False, 0.0)
                    emit({"type": "error", "message": f"Stop recovery failed: {exc}"})
                character.movement.reset_desired_velocity()
            elif action.begin_collect:
                planted = action.pose
                feet = foot_points(planted, parents, names)
                swing = choose_swing(feet['left']['ankle'], feet['right']['ankle'], facing,
                                     feet['left']['ankle'][2], feet['right']['ankle'][2])
                collect_frames, metrics = _begin_collect(character, planted.copy(), swing, rt, wp, facing.copy())
                if cycle.stage_collect(collect_frames, metrics, cycle.move_id, cycle.settle_seq):
                    emit({"type": "collect_candidate", "move_id": cycle.move_id, "settle_seq": cycle.settle_seq,
                          "frames": [frame.tolist() for frame in collect_frames], "metrics": metrics})
            elif action.begin_arrival:
                planted = action.pose if action.pose is not None else pose
                try:
                    applied = _enter_arrival(character, planted, cycle.target_pose_id, rt, wp, facing)
                except Exception as exc:
                    emit({"type": "error", "message": f"Pose transition failed: {exc}"})
                    applied = False
                    _sync_pose(character, planted, wp, seed=True)
                cycle.note_arrival(applied, character.time_to_transition() if applied else 0.0)
            elif action.walk:
                if action.prime_walk:
                    _prime_walk(character, facing)
                with TIMINGS.measure("walk_update"):
                    character.step(DT, _command(rt, facing, facing))
            elif action.play:
                character.step(DT, _command(rt, facing, None))
            elif action.pose is not None:
                _sync_pose(character, action.pose, wp, seed=action.seed)
                if cycle.phase in ('final_step','stop_retry') and not action.seed:
                    character.player.record_pose(DT,character.current_pose)
                if action.seed:
                    character.movement.reset_desired_velocity()
            step_ms = (time.perf_counter() - started_at) * 1000.0
            if step_ms >= _SLOW_STEP_MS:
                last_generate_ms = step_ms
            shown = character.current_pose.numpy().reshape((-1, 7)).copy()
            last_root = pose[0, :2].copy()
            distance = None if goal is None else float(np.linalg.norm(goal[:2] - shown[0, :2]))
            if _arrival_due(nav, cycle, goal is not None):
                emit(
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
            gait['stop_failure_reason'] = cycle.stop_failure_reason
            gait['goal_error_m'] = distance
            gait['final_stop_metrics'] = {name: value for name, value in cycle.final_stop_metrics.items()
                                          if name in ('accepted', 'stage', 'reason', 'arrival_error_m', 'travel_distance_m', 'recovery_only')}
            if gait.get("event") == "stop_requested":
                emit(
                    {
                        "type": "stop_triggered",
                        "distance_m": distance,
                        "speed_mps": round(root_speed, 3),
                        "threshold_m": round(max(.08, cycle.stop_prediction_m), 3),
                        "mode": cycle.mode,
                    }
                )
            emit(
                {
                    "type": "frame",
                    "sequence": tick,
                    "simulation_time": tick * DT,
                    "step_ms": round(step_ms, 3),
                    "visual_selection": _stream_selection(visual_stop.selection) if visual_stop else None,
                    "stop_mode": cycle.stop_mode,
                    "destination_xy": None if cycle.goal is None else cycle.goal[:2].tolist(),
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
                emit(
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
                emit(
                    {
                        "type": "metrics",
                        "stream_hz": round(frames / (now - report_at), 1),
                        "generate_ms": round(last_generate_ms, 2),
                    }
                )
                frames = 0
                report_at = now



def _arrival_due(nav: NavState, cycle: LocomotionCycle, has_goal: bool) -> bool:
    if not has_goal or nav.arrived_sent:
        return False
    if cycle.hold_stance and cycle.phase == SETTLED:
        return True
    if not cycle.hold_stance and cycle.phase == POSE_DONE:
        return True
    return not cycle.hold_stance and cycle.arrival_done and cycle.phase == SETTLED
