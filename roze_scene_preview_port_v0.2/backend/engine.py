"""Roze click-to-move using NVIDIA's *actual* Scene Preview character runtime.

Install under the official repository as motionbricks/roze_mvp/backend/engine.py.
The state machine, idle clip transition, locomotion blending, velocity springs,
pose recorder and contact IK are all taken from the official upstream `app/`
modules; this file only adds a click-target controller and WebSocket publishing.

Important: official pose-to-idle transition is not an exact click-point solver.
The browser never teleports the root to conceal remaining target error.
"""
from __future__ import annotations
from dataclasses import replace
import math
import sys
import time
from pathlib import Path
from queue import Empty, Queue

import numpy as np

# `roze_mvp` must be directly inside the cloned official NVlabs/motionbricks repo.
REPO = Path(__file__).resolve().parents[2]
if not (REPO / 'app' / 'runtime' / 'common' / 'states.py').is_file():
    raise RuntimeError(
        'roze_mvp must be inside the official NVlabs/motionbricks repository. '
        'Required app/runtime/common/states.py was not found at: ' + str(REPO)
    )
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import warp as wp
from motionbricks.model.contract import ModelRig, MODEL_POSES_PER_TOKEN
from motionbricks.runtime.target_pose import TargetPoseInferenceParams, place_target_poses
from app.runtime.common.io.smart_primitive_document import SmartPrimitiveAssetPool
from app.runtime.common.motion import LocomotionCommand, PlaybackSource
from app.runtime.common.rig import load_rig_assets
from app.runtime.soma.character import SOMACharacter
from app.runtime.soma.presets import (
    DEFAULT_IDLE_CLIPS, DEFAULT_CROUCH_IDLE_CLIPS, DEFAULT_LOCOMOTION_MODES,
    LINEAR_LOCOMOTION,
)

from click_planner import ClickStopSettings, plan_click_move
from soma_pose import read_soma_pose

FPS = 30
DT = 1.0 / FPS
STOP_SETTINGS = ClickStopSettings()


def _norm_xy(vec: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    size = float(np.linalg.norm(vec[:2]))
    if size > 1e-6:
        return np.array([vec[0] / size, vec[1] / size, 0.0], dtype=np.float32)
    return fallback.copy()


def _pose_to_four_frames(raw, skeleton, device) -> wp.array:
    """Read pre-retargeted SOMA Z-up JSON into the official target buffer."""
    if len(raw) != skeleton.num_joints:
        raise ValueError('SOMA target joint count mismatched')
    joints = [wp.transform(wp.vec3(*joint[:3]), wp.quat(*joint[3:])) for joint in raw]
    return wp.array([list(joints) for _ in range(MODEL_POSES_PER_TOKEN)],
                    dtype=wp.transform, device=device)


def _request_custom_pose(character: SOMACharacter, pose_id: str) -> bool:
    """Generate *after* official idle transition, never snap to final pose."""
    raw = read_soma_pose(pose_id, character.skeleton)
    if raw is None:
        return False
    src = _pose_to_four_frames(raw, character.skeleton, character.engine.device)
    target = wp.empty_like(src)
    pos = character.character_ground_position.copy()
    pos[2] = 0.0
    # Use current facing, not a newly forced world rotation.
    facing = _norm_xy(character.movement.current_facing,
                      np.array([1.0, 0.0, 0.0], dtype=np.float32))
    place_target_poses(wp.vec3(*pos), wp.vec3(*facing), src, target,
                       stream=character.engine.stream)
    character.generate_to_target_poses(
        target,
        TargetPoseInferenceParams(transition_early_by_frames=0, num_poses_to_use=1),
    )
    return True


def worker(commands: Queue, publish):
    """All GPU objects live on one persistent worker thread."""
    wp.init()
    wp.set_device('cuda:0')
    assets = load_rig_assets(ModelRig.SOMA)
    pool = SmartPrimitiveAssetPool(assets.clip_registry, assets.reference_pose,
                                   assets.model_to_runtime)

    # Lower minimum speed for click navigation: this is the only adjustment to
    # official locomotion mode. It permits gradual slow-down near a target.
    # Other official modes remain available for crouching/directional control.
    click_mode = replace(LINEAR_LOCOMOTION, minimum_speed=0.0)
    modes = (click_mode, *[m for m in DEFAULT_LOCOMOTION_MODES if m.name != click_mode.name])

    from motionbricks.model.soma.contract import SOMA_N1_FP32_ONNX_PATH
    from motionbricks.model.soma.engine import MotionBricksSOMAEngine
    engine = MotionBricksSOMAEngine(SOMA_N1_FP32_ONNX_PATH,
                                    model_to_runtime=assets.model_to_runtime)
    with engine, wp.ScopedStream(engine.stream):
        character = SOMACharacter(
            engine, asset_pool=pool, modes=modes,
            idle_paths=(DEFAULT_IDLE_CLIPS[0],),  # deterministic stop test
            crouch_idle_paths=DEFAULT_CROUCH_IDLE_CLIPS,
        )
        skeleton = character.skeleton
        publish({
            'type': 'rig',
            'joint_names': skeleton.joint_names,
            'parents': [skeleton.joint_parent(i) for i in range(skeleton.num_joints)],
            'rest': skeleton.reference_local_transforms.numpy().reshape(-1, 7).tolist(),
        })

        goal = None
        move_id = None
        target_pose_id = 'F001'
        phase = 'idle'  # idle -> moving -> stopping -> idle/pose_transition -> pose_done
        pose_applied = False
        arrived_sent = False
        next_tick = time.monotonic()
        tick = 0

        while True:
            try:
                while True:
                    cmd = commands.get_nowait()
                    kind = cmd.get('type')
                    if kind == 'quit':
                        return
                    if kind == 'move':
                        x, y = float(cmd['x']), float(cmd['y'])
                        if not (math.isfinite(x) and math.isfinite(y)) or abs(x) > 100 or abs(y) > 100:
                            continue
                        goal = np.array([x, y, 0.0], dtype=np.float32)
                        move_id = cmd.get('move_id')
                        target_pose_id = 'F001'
                        phase = 'moving'
                        pose_applied = False
                        arrived_sent = False
                    elif kind == 'pose_choice' and cmd.get('move_id') == move_id:
                        target_pose_id = str(cmd['pose_id'])
                        # If Jev arrives late, immediately start a new generated
                        # transition only *after* the official stop completes.
                        if phase in ('idle', 'pose_done'):
                            phase = 'pose_pending'
                            arrived_sent = False
            except Empty:
                pass

            actual_speed = float(np.linalg.norm(character.actual_velocity[:2]))
            pos = character.character_ground_position.copy()
            direction = character.movement.current_facing.copy()
            distance = None
            controller_strength = 0.0

            if goal is not None:
                diff = goal - pos
                diff[2] = 0.0
                distance = float(np.linalg.norm(diff[:2]))
                direction = _norm_xy(diff, direction)
                if phase == 'moving':
                    decision = plan_click_move(distance, actual_speed, STOP_SETTINGS)
                    if decision.stop:
                        # The official Locomotion -> Idle state switch will
                        # generate the idle clip entrance using 4 recent poses.
                        phase = 'stopping'
                        publish({'type': 'stop_triggered', 'distance_m': distance,
                                 'speed_mps': actual_speed,
                                 'threshold_m': decision.stop_distance_m})
                    else:
                        controller_strength = decision.input_strength

            command = LocomotionCommand(
                facing_direction=direction,
                movement=direction * controller_strength if phase == 'moving' else None,
                use_max_speed=False,
            )
            character.step(DT, command)

            # State machine stops by generating a clip entrance, then plays its loop.
            # Public API lacks a playback state property; inspecting _playback_source
            # is scoped here and documented for upstream version compatibility.
            in_idle_loop = (
                character.state_machine.state is character.state_machine.standing_idle_state
                and character._playback_source is PlaybackSource.CLIP
            )

            if phase == 'stopping' and in_idle_loop:
                phase = 'pose_pending'
            if phase == 'pose_pending' and in_idle_loop:
                try:
                    pose_applied = _request_custom_pose(character, target_pose_id)
                except Exception as exc:
                    publish({'type': 'error', 'message': f'Pose transition failed: {exc}'})
                    pose_applied = False
                phase = 'pose_transition' if pose_applied else 'idle'
            if phase == 'pose_transition' and character.time_to_transition() <= DT:
                phase = 'pose_done'

            if goal is not None and phase in ('idle', 'pose_done') and not arrived_sent:
                final_pos = character.character_ground_position.copy()
                arrival_error = float(np.linalg.norm((goal - final_pos)[:2]))
                publish({'type': 'arrived', 'pose_id': target_pose_id,
                         'pose_applied': pose_applied,
                         'arrival_error_m': round(arrival_error, 3)})
                arrived_sent = True

            # No layer writes the root position or directly overrides joints.
            # Official BaseCharacter.step() also records the actually shown pose.
            publish({'type': 'frame',
                     'poses': character.current_pose.numpy().reshape(-1, 7).tolist()})
            if tick % 15 == 0:
                publish({'type': 'motion_state', 'phase': phase,
                         'official_state': character.state_machine.state.name,
                         'distance_m': None if distance is None else round(distance, 3),
                         'actual_speed_mps': round(actual_speed, 3),
                         'controller_strength': round(controller_strength, 3)})
            tick += 1
            next_tick += DT
            remaining = next_tick - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            else:
                next_tick = time.monotonic()
