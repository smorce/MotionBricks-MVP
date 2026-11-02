"""停止探索用の独立再生器と公式推論アダプター。"""

import numpy as np
from engine import _sync_pose, DT
from final_stop import (
    build_stop_target,
    check_bone_lengths,
    foot_points,
    support_target_metrics,
    validate_stop_motion,
)
from stop_replay import restore_history


class GeneratedStop(list):
    """姿勢と公式モデルの接地信頼度を同じフレーム順で保持する。"""

    def __init__(self, frames, contacts, support):
        super().__init__(frames)
        self.contacts = contacts
        self.support = support


def new_character(rt, engine, pool, replay):
    from stop_replay import model_manifest
    if replay['metadata'].get('model',model_manifest())!=model_manifest():
        raise ValueError('Replay model version differs from installed model')
    character = rt["SOMACharacter"](
        engine,
        asset_pool=pool,
        modes=rt["DEFAULT_LOCOMOTION_MODES"],
        idle_paths=(rt["DEFAULT_IDLE_CLIPS"][0],),
        crouch_idle_paths=rt["DEFAULT_CROUCH_IDLE_CLIPS"],
    )
    _sync_pose(character, np.asarray(replay["pose"]), rt["wp"])
    restore_history(character, replay)
    return character


def candidate_specs(preferred="left", limit=24):
    other = "right" if preferred == "left" else "left"
    return [
        dict(
            id=f"{mode}-{side}-{shift}-{tokens}",
            mode=mode,
            support=side,
            root_shift=0.0,
            root_lower=shift,
            tokens=tokens,
        )
        for mode in ("f001", "staged")
        for shift in (0.0, 0.06, 0.12)
        for side in (preferred, other)
        for tokens in (8, 14)
    ][:limit]


def refinement_specs(preferred='left'):
    other='right' if preferred=='left' else 'left'
    return [dict(id=f'refine-{side}-{lower}-{tokens}',mode='f001',support=side,
                 root_shift=0.,root_lower=lower,tokens=tokens)
            for lower in (.08,.09,.10) for side in (preferred,other) for tokens in (8,14)]


def generate_candidate(character, replay, spec, rt):
    wp = rt["wp"]
    data = replay["metadata"]
    pose = np.asarray(replay["pose"])
    names, parents, ground = data["names"], data["parents"], data["ground"]
    goal = np.asarray(data["goal"])
    saved_target=data.get('f001')
    target=np.asarray(saved_target,dtype=float).copy() if saved_target is not None else build_stop_target(pose, goal, parents, names, ground)
    if target is None:
        raise ValueError("No safe standing target")
    target[0,:2]=goal[:2]
    if spec["mode"] == "stride":
        target[1:, 3:] = pose[1:, 3:]
    direction = goal[:2] - pose[0, :2]
    target[0, :2] += (
        direction / max(np.linalg.norm(direction), 1e-9) * spec["root_shift"]
    )
    landing = target.copy()
    target[0, 2] -= spec.get("root_lower", 0.0)
    mask = (
        rt["IKPin"].LEFT_FOOT if spec["support"] == "left" else rt["IKPin"].RIGHT_FOOT
    )
    original = wp.array(
        pose.astype(np.float32), dtype=wp.transform, device=character.engine.device
    )
    corrected = wp.array(
        target.astype(np.float32), dtype=wp.transform, device=character.engine.device
    )
    corrector = character._target_pose_ik_corrector
    try:
        swing_mask = (
            rt["IKPin"].RIGHT_FOOT
            if spec["support"] == "left"
            else rt["IKPin"].LEFT_FOOT
        )
        landing_array = wp.array(
            landing.astype(np.float32),
            dtype=wp.transform,
            device=character.engine.device,
        )
        corrector.capture_pins(
            landing_array, swing_mask, stream=character.engine.stream
        )
        corrector.apply(corrected, 1.0, stream=character.engine.stream)
        corrector.capture_pins(original, mask, stream=character.engine.stream)
        corrector.apply(corrected, 1.0, stream=character.engine.stream)
        target = corrected.numpy().reshape((-1, 7)).copy()
    finally:
        character.clear_ik_pins()
    metrics = support_target_metrics(pose, target, spec["support"], parents, names)
    if (
        metrics["support_target_error_3d_m"] > 0.02
        or not check_bone_lengths([target], pose, names)["bone_lengths_valid"]
    ):
        raise ValueError("Unreachable pinned target: " + str(metrics))
    targets = wp.array(
        np.repeat(target[None].astype(np.float32), 4, axis=0),
        dtype=wp.transform,
        device=character.engine.device,
    )
    airborne = False
    landed = False
    landing_pin = None
    swing = "right" if spec["support"] == "left" else "left"
    both = mask | swing_mask
    corrector.capture_pins(original, both, stream=character.engine.stream)

    def sample():
        nonlocal airborne, landed, landing_pin
        character._sample_playback(DT)
        raw = character.current_pose.numpy().reshape((-1, 7)).copy()
        from final_stop import contact_points

        feet = contact_points(foot_points(raw, parents, names), ground)[swing]
        height = min(point[2] - ground["floor_z"] for point in feet.values())
        if not airborne and height > 0.025:
            airborne = True
            corrector.capture_pins(original, mask, stream=character.engine.stream)
        if airborne and not landed and height <= 0.02:
            confidence = np.asarray(character.current_foot_contacts.numpy()).reshape(-1)
            channel = 0 if swing == "left" else 2
            if max(confidence[channel : channel + 2]) >= 0.5:
                landed = True
                corrector.capture_pins(original, mask, stream=character.engine.stream)
                corrector.apply(
                    character.current_pose, 1.0, stream=character.engine.stream
                )
                landing_pin = wp.clone(character.current_pose)
        corrector.capture_pins(
            landing_pin if landed else original,
            both if landed or not airborne else mask,
            stream=character.engine.stream,
        )
        corrector.apply(character.current_pose, 1.0, stream=character.engine.stream)

    try:
        prefix = []
        contacts = []
        if spec["mode"] == "staged":
            for fraction in (0.0, 1.0):
                lifted = pose.copy()
                lifted[0, :2] += (goal[:2] - pose[0, :2]) * fraction
                lifted[0, 2] += 0.10
                middle = pose.copy()
                middle[0, :2] += (goal[:2] - pose[0, :2]) * fraction
                middle[0, 2] -= spec.get("root_lower", 0.0)
                middle_array = wp.array(
                    middle.astype(np.float32),
                    dtype=wp.transform,
                    device=character.engine.device,
                )
                lift_array = wp.array(
                    lifted.astype(np.float32),
                    dtype=wp.transform,
                    device=character.engine.device,
                )
                corrector.capture_pins(
                    lift_array, swing_mask, stream=character.engine.stream
                )
                corrector.apply(middle_array, 1.0, stream=character.engine.stream)
                corrector.capture_pins(original, mask, stream=character.engine.stream)
                corrector.apply(middle_array, 1.0, stream=character.engine.stream)
                middle_targets = wp.array(
                    np.repeat(middle_array.numpy()[None], 4, axis=0),
                    dtype=wp.transform,
                    device=character.engine.device,
                )
                character.generate_to_target_poses(
                    middle_targets,
                    rt["TargetPoseInferenceParams"](
                        transition_early_by_frames=0,
                        num_poses_to_use=4,
                        ik_pin_mask=mask,
                        allowed_token_counts=(8,),
                    ),
                )
                corrector.capture_pins(original, mask, stream=character.engine.stream)
                for _ in range(240):
                    sample()
                    prefix.append(
                        character.current_pose.numpy().reshape((-1, 7)).copy()
                    )
                    contacts.append(character.current_foot_contacts.numpy().tolist())
                    character.player.record_pose(DT, character.current_pose)
                    if character.time_to_transition() <= 0:
                        break
                else:
                    raise RuntimeError("Intermediate generation timed out")
        character.generate_to_target_poses(
            targets,
            rt["TargetPoseInferenceParams"](
                transition_early_by_frames=0,
                num_poses_to_use=4,
                ik_pin_mask=mask,
                allowed_token_counts=(spec["tokens"],),
            ),
        )
        corrector.capture_pins(original, mask, stream=character.engine.stream)
        frames = prefix
        for _ in range(240):
            sample()
            frames.append(character.current_pose.numpy().reshape((-1, 7)).copy())
            contacts.append(character.current_foot_contacts.numpy().tolist())
            if character.time_to_transition() <= 0:
                break
        else:
            raise RuntimeError("Stop generation timed out")
        # 公式バッファ末尾の保持区間も採取し、Idleへ渡す足の安定を測る。
        for _ in range(12):
            sample()
            frames.append(character.current_pose.numpy().reshape((-1, 7)).copy())
            contacts.append(character.current_foot_contacts.numpy().tolist())
        return GeneratedStop(frames, contacts, spec["support"])
    finally:
        character.clear_ik_pins()


def diagnose(replay, frames):
    data = replay["metadata"]
    return validate_stop_motion(
        frames,
        np.asarray(replay["pose"]),
        data["goal"],
        data["parents"],
        data["names"],
        data["ground"],
    )
