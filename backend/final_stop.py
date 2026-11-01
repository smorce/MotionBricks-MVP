"""公式生成用の停止目標と、吸着させない着地検証。"""
import numpy as np
from soma_pose import overlay_pose
from step_cycle import foot_points, facing_of
from quats import quat_mul
from collect_stance import valid_pose, knees_valid, knees_continuous


def stop_support(pose, goal, parents, names):
    """低い足を支持足とし、同じ高さなら進行方向の後足を選ぶ。"""
    points = foot_points(pose, parents, names)
    heights = {s: min(points[s][p][2] for p in ('ankle', 'toe')) for s in points}
    if abs(heights['left'] - heights['right']) > .015:
        return min(heights, key=heights.get)
    direction = np.asarray(goal)[:2] - pose[0, :2]
    return min(('left', 'right'), key=lambda s: float(points[s]['ankle'][:2] @ direction))


def validate_stop_progress(frames, original, destination, support, parents, names):
    """回復区間の前進量、通過、支持足の累積滑りを検証する。"""
    delta = np.asarray(destination)[:2] - original[0, :2]
    distance = float(np.linalg.norm(delta))
    roots = np.asarray(frames)[:, 0, :2]
    if distance > .08:
        projections = (roots - original[0, :2]) @ (delta / distance)
        if (np.any(projections < -.02) or np.any(projections > distance + .02)
                or np.any(np.linalg.norm(roots - np.asarray(destination)[:2], axis=1) > distance + .02)):
            return 'Stop trajectory passed destination or moved backward'
        if distance - np.linalg.norm(roots[-1] - np.asarray(destination)[:2]) < .01:
            return 'Stop recovery made insufficient progress'
    start = foot_points(original, parents, names)[support]
    ground = min(start[p][2] for p in ('ankle', 'toe'))
    for frame in frames:
        foot = foot_points(frame, parents, names)[support]
        if min(foot[p][2] for p in ('ankle', 'toe')) > ground + .02:
            break
        if any(np.linalg.norm(foot[p][:2] - start[p][:2]) > .02 for p in ('ankle', 'toe')):
            return 'Stop support foot drifted'
    return ''


def build_stop_target(original, goal, parents, names):
    raw = overlay_pose('F001', names, original)
    if raw is None:
        return None
    target = np.asarray(raw, dtype=float)
    source_facing = facing_of(target[0, 3:])
    facing = facing_of(original[0, 3:])
    angle = np.arctan2(facing[1], facing[0]) - np.arctan2(source_facing[1], source_facing[0])
    target[0, 3:] = quat_mul(np.array([0, 0, np.sin(angle/2), np.cos(angle/2)]), target[0, 3:])
    target[0, :2] = goal[:2]
    start = foot_points(original, parents, names)
    end = foot_points(target, parents, names)
    ground = min(start[s][p][2] for s in ('left', 'right') for p in ('ankle', 'toe'))
    target[0, 2] += ground - min(end[s][p][2] for s in ('left', 'right') for p in ('ankle', 'toe'))
    return target if valid_pose(target) and knees_valid(target, parents, names) else None


def check_bone_lengths(frames, original, names, atol_m=.002, rtol=.01):
    """ローカル並進のノルムを比較し、各骨の最大誤差を記録する。許容値は暫定。"""
    frames = np.asarray(frames, dtype=np.float64)
    original = np.asarray(original, dtype=np.float64)
    lengths = np.linalg.norm(original[1:, :3], axis=1)
    generated = np.linalg.norm(frames[:, 1:, :3], axis=2)
    errors = np.abs(generated - lengths)
    tolerances = atol_m + rtol * lengths
    local_deltas = np.linalg.norm(frames[:, 1:, :3] - original[None, 1:, :3], axis=2)
    failed = np.argwhere(errors > tolerances)
    diagnostics = []
    for bone, name in enumerate(names[1:]):
        frame = int(np.argmax(errors[:, bone]))
        diagnostics.append(dict(joint=name, frame=frame,
                                local_position_delta_m=float(np.max(local_deltas[:, bone])),
                                bone_length_delta_m=float(errors[frame, bone]),
                                tolerance_m=float(tolerances[bone])))
    result = dict(bone_lengths_valid=not len(failed),
                  max_bone_length_error_m=float(np.max(errors)),
                  bone_length_atol_m=atol_m, bone_length_rtol=rtol,
                  bone_length_diagnostics=diagnostics)
    if len(failed):
        frame, bone = map(int, failed[0])
        result.update(failed_joint=names[bone + 1], failed_frame=frame,
                      local_position_delta_m=float(local_deltas[frame, bone]),
                      bone_length_delta_m=float(errors[frame, bone]))
    return result


def validate_stop_motion(frames, original, goal, parents, names):
    frames = np.asarray(frames)
    result = dict(accepted=False, reason='Invalid stop motion')
    if len(frames) < 4 or frames.shape[1:] != original.shape or not all(valid_pose(p) for p in frames):
        return result
    result.update(check_bone_lengths(frames, original, names))
    points = [foot_points(p, parents, names) for p in frames]
    start = foot_points(original, parents, names)
    ground = min(start[s][p][2] for s in ('left', 'right') for p in ('ankle', 'toe'))
    error = float(np.linalg.norm(frames[-1, 0, :2] - goal[:2]))
    result['arrival_error_m'] = error
    if error > .08:
        result['reason'] = 'Stop missed destination'
    elif any(np.linalg.norm(b[0, :3]-a[0, :3]) > .06 for a, b in zip([original, *frames[:-1]], frames)):
        result['reason'] = 'Stop root discontinuity'
    elif any(not knees_valid(p, parents, names) or not knees_continuous(p, original, parents, names) for p in frames):
        result['reason'] = 'Invalid stop knee bend'
    elif not result['bone_lengths_valid']:
        result['reason'] = 'Stop bone lengths changed'
    elif any(p[s][part][2] < ground-.02 for p in points for s in ('left', 'right') for part in ('ankle', 'toe')):
        result['reason'] = 'Stop foot penetrated ground'
    elif any(np.linalg.norm(b[s][part][:2]-a[s][part][:2]) > .02
             for a,b in zip([start,*points[:-1]],points) for s in ('left','right') for part in ('ankle','toe')
             if a[s][part][2] <= ground+.02 and b[s][part][2] <= ground+.02):
        result['reason'] = 'Stop planted foot slid'
    elif any(min(points[-1][s][part][2] for part in ('ankle','toe')) > ground+.04 for s in ('left','right')):
        result['reason'] = 'Stop feet did not land'
    elif any(np.max(2*np.arccos(np.clip(np.abs(np.sum(a[:,3:]*b[:,3:],axis=1)),0,1))) > .35 for a,b in zip([original,*frames[:-1]],frames)):
        result['reason'] = 'Stop joint rotation discontinuity'
    elif any(np.linalg.norm(b[s][part]-a[s][part]) > .002 for a,b in zip(points[-4:-1],points[-3:]) for s in ('left','right') for part in ('ankle','toe')):
        result['reason'] = 'Stop final feet are unstable'
    else:
        result.update(accepted=True, reason='')
    return result
