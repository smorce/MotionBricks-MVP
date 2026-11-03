"""到着失敗の記録を残したまま、公式Idleへの移行をゆっくり再生する。"""
import numpy as np
from engine import DT, _command, _sync_pose
from final_stop import check_bone_lengths
from stop_replay import capture_replay
from stop_runtime import new_character, GeneratedStop
from stop_contact_lock import StopContactLock


def blend_from_hold(original, pose, elapsed):
    weight = np.clip(elapsed, 0., 1.)
    weight = weight * weight * (3. - 2. * weight)
    result = original + (pose - original) * weight
    # 待機クリップの骨格寸法へ変形せず、現在の骨格に回転を適用する。
    result[1:, :3] = original[1:, :3]
    start, end = original[:, 3:], pose[:, 3:]
    end = np.where(np.sum(start * end, axis=1, keepdims=True) < 0, -end, end)
    rotation = start + (end - start) * weight
    result[:, 3:] = rotation / np.linalg.norm(rotation, axis=1, keepdims=True)
    return result


def generate_failure_relaxation(character, ground, rt, facing):
    original = character.current_pose.numpy().reshape((-1, 7)).copy()
    replay = capture_replay(character, original[0, :2], ground)
    scratch = new_character(rt, character.engine, character.asset_pool, replay)
    scratch.actual_velocity.fill(0.)
    scratch.movement.last_input_facing[:] = facing
    scratch.state_machine.state.enter(scratch, scratch.state_machine)
    data = replay['metadata']
    lock = StopContactLock(original, data['contacts'], data['parents'], data['names'], ground)
    frames, contacts = [original], [data['contacts']]
    idle_elapsed = 0.
    for tick in range(600):
        scratch.step(DT * .5, _command(rt, facing, None))
        pose = scratch.current_pose.numpy().reshape((-1, 7)).copy()
        _sync_pose(scratch, blend_from_hold(original, pose, (tick + 1) * DT), rt['wp'])
        lock.apply(scratch, rt)
        frames.append(scratch.current_pose.numpy().reshape((-1, 7)).copy())
        contacts.append(scratch.current_foot_contacts.numpy().reshape(-1).tolist())
        if scratch._playback_source.name == 'CLIP':
            idle_elapsed += DT * .5
            if idle_elapsed >= .5:
                break
    else:
        raise RuntimeError('Failure relaxation timed out')
    if not np.isfinite(frames).all():
        raise ValueError('Failure relaxation contains nonfinite poses')
    metrics = check_bone_lengths(np.asarray(frames), original, data['names'])
    metrics.update(accepted=metrics['bone_lengths_valid'], playback_rate=.5,
                   duration_seconds=(len(frames)-1)*DT,
                   root_drift_m=float(np.linalg.norm(frames[-1][0, :2]-original[0, :2])),
                   human_rating='unknown')
    return GeneratedStop(frames, contacts, None) if metrics['accepted'] else None, metrics
