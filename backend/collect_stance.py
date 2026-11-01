"""収束目標と、表示前のモーション品質検証。独自 IK は使用しない。"""
import numpy as np
from soma_pose import overlay_pose
from quats import quat_mul, quat_to_mat
from step_cycle import foot_points, facing_of, fk
from soma_skeleton import SOMA_JOINT_NAMES, soma_parents

COLLECT_SAGITTAL_M = 0.26
COLLECT_WIDTH_M = 0.34
COLLECT_WAIT_S = 0.85
SUPPORT_SLIP_M = 0.02


def needs_collect(sagittal_m, width_m):
    return bool(np.isfinite([sagittal_m, width_m]).all() and
                (sagittal_m > COLLECT_SAGITTAL_M or width_m > COLLECT_WIDTH_M))


def stance(pose, parents, names):
    points = foot_points(pose, parents, names)
    delta = points['left']['ankle'] - points['right']['ankle']
    facing = facing_of(pose[0, 3:])
    return abs(float(delta @ facing)), abs(float(delta @ np.cross([0, 0, 1], facing)))


def valid_pose(pose):
    return (pose.ndim == 2 and pose.shape[1] == 7 and np.isfinite(pose).all()
            and np.allclose(np.linalg.norm(pose[:, 3:], axis=1), 1, atol=.01))


def knees_valid(pose, parents, names):
    positions, _ = fk(pose, parents)
    for side in ('Left', 'Right'):
        hip, knee, ankle = [positions[names.index(side + part)] for part in ('Leg', 'Shin', 'Foot')]
        upper, lower = knee - hip, ankle - knee
        length = np.linalg.norm(upper) * np.linalg.norm(lower)
        if length < 1e-8 or np.dot(upper, lower) / length < -.5:
            return False
    return True


def knees_continuous(pose, original, parents, names):
    current, _ = fk(pose, parents)
    initial, _ = fk(original, parents)
    for side in ('Left', 'Right'):
        def bend(points):
            hip, knee, ankle = [points[names.index(side + part)] for part in ('Leg', 'Shin', 'Foot')]
            axis = ankle - hip
            if np.dot(axis, axis) < 1e-8:
                return np.zeros(3)
            offset = knee - hip
            return offset - axis * np.dot(offset, axis) / np.dot(axis, axis)
        # 旋回でワールド上の方向が反転しても、身体内の曲がりは維持される。
        a = quat_to_mat(original[0, 3:]).T @ bend(initial)
        b = quat_to_mat(pose[0, 3:]).T @ bend(current)
        if np.linalg.norm(a) > .01 and np.linalg.norm(b) > .01 and np.dot(a, b) < 0:
            return False
    return True


def build_collect_target(settled, joint_names, swing, parents=None):
    base = np.asarray(settled, dtype=float)
    if swing not in ('left', 'right') or not valid_pose(base):
        return None
    if parents is None:
        if list(joint_names) != list(SOMA_JOINT_NAMES):
            return None
        parents = soma_parents()
    reference = overlay_pose('F001', joint_names, base)
    if reference is None:
        return None
    target = base.copy()
    for suffix in ('Leg', 'Shin', 'Foot', 'ToeBase'):
        name = swing.title() + suffix
        if name not in joint_names:
            return None
        i = joint_names.index(name)
        target[i, 3:] = reference[i][3:]
    if not valid_pose(target) or not knees_valid(target, parents, joint_names) or not knees_continuous(target, base, parents, joint_names):
        return None
    before = stance(base, parents, joint_names)
    after = stance(target, parents, joint_names)
    if max(after[0] / COLLECT_SAGITTAL_M, after[1] / COLLECT_WIDTH_M) >= max(before[0] / COLLECT_SAGITTAL_M, before[1] / COLLECT_WIDTH_M):
        return None
    a, b = foot_points(base, parents, joint_names), foot_points(target, parents, joint_names)
    support = 'right' if swing == 'left' else 'left'
    for part in ('ankle', 'toe'):
        if not np.allclose(a[support][part], b[support][part], atol=1e-6):
            return None
        if abs(b[swing][part][2] - a[support][part][2]) > .04:
            return None
    return target


def build_collect_lift(settled, parents, names, swing, distance_m=.2):
    """支持足を動かさず、遊脚の回転だけで中間目標を探す。"""
    points = foot_points(settled, parents, names)
    joint = names.index(swing.title() + "Leg")
    _, world_rot = fk(settled, parents)
    axis_world = np.cross([0, 0, 1], facing_of(settled[0, 3:]))
    parent = parents[joint]
    axis = world_rot[parent].T @ axis_world if parent >= 0 else axis_world
    height = float(np.clip(distance_m * .25, .05, .08))
    for degrees in (sign * angle for angle in range(1, 61) for sign in (1, -1)):
        angle = np.deg2rad(degrees) / 2
        rotation = np.r_[axis * np.sin(angle), np.cos(angle)]
        candidate = settled.copy()
        candidate[joint, 3:] = quat_mul(rotation, settled[joint, 3:])
        lifted = foot_points(candidate, parents, names)
        clearance = [lifted[swing][part][2] - points[swing][part][2] for part in ('ankle', 'toe')]
        if knees_valid(candidate, parents, names) and knees_continuous(candidate, settled, parents, names) and min(clearance) >= height and max(clearance) <= .09:
            return candidate
    return None


def build_weight_target(planted, parents, names, swing):
    """関節は変更せず、公式生成器へ支持足方向のルート目標を渡す。"""
    support = 'right' if swing == 'left' else 'left'
    point = foot_points(planted, parents, names)[support]['ankle'][:2]
    delta = point - planted[0, :2]
    target = planted.copy()
    length = np.linalg.norm(delta)
    if length > 1e-6:
        target[0, :2] += delta / length * min(.03, length * .25)
    return target


def valid_weight_shift(frames, original, parents, names, swing):
    start = foot_points(original, parents, names)
    support = 'right' if swing == 'left' else 'left'
    if not frames or not all(valid_pose(p) and knees_valid(p, parents, names) and knees_continuous(p, original, parents, names) for p in frames):
        return False
    for pose in frames:
        points = foot_points(pose, parents, names)
        if any(np.linalg.norm(points[s][part] - start[s][part]) > .02 for s in ('left', 'right') for part in ('ankle', 'toe')):
            return False
    point = start[support]['ankle'][:2]
    return np.linalg.norm(frames[-1][0, :2] - point) < np.linalg.norm(original[0, :2] - point) - .005


def validate_motion(frames, original, parents, names, swing, slip_limit=SUPPORT_SLIP_M):
    frames = np.asarray(frames)
    result = dict(accepted=False, reason='Invalid generated poses', support_slip_m=0.0, lift_m=0.0)
    if len(frames) < 3 or frames.shape[1:] != original.shape or not all(valid_pose(p) for p in frames):
        return result
    support = 'right' if swing == 'left' else 'left'
    start = foot_points(original, parents, names)
    points = [foot_points(p, parents, names) for p in frames]
    slip = max(float(np.linalg.norm(p[support][part][:2] - start[support][part][:2])) for p in points for part in ('ankle', 'toe'))
    lift = max(min(float(p[swing][part][2] - start[swing][part][2]) for part in ('ankle', 'toe')) for p in points)
    result.update(support_slip_m=slip, lift_m=lift, before=stance(original, parents, names), after=stance(frames[-1], parents, names))
    offsets = np.linalg.norm(frames[:, 0, :2] - original[0, :2], axis=1)
    result.update(root_displacement_m=float(offsets[-1]), root_excursion_m=float(max(offsets)),
                  root_path_m=float(np.linalg.norm(np.diff(frames[:, 0, :2], axis=0), axis=1).sum()))
    if max(offsets) > .08:
        result['reason'] = 'Root excursion exceeds limit'
    elif slip > slip_limit:
        result['reason'] = 'Support foot slip exceeds limit'
    elif lift < .025:
        result['reason'] = 'Swing foot did not lift'
    elif any(abs(points[-1][swing][part][2] - start[support][part][2]) > .04 for part in ('ankle', 'toe')):
        result['reason'] = 'Swing foot did not land'
    elif any(np.linalg.norm(p[0, :3] - q[0, :3]) > .04 for p, q in zip(frames, frames[1:])):
        result['reason'] = 'Root discontinuity'
    elif max(result['after'][0] / .26, result['after'][1] / .34) >= max(result['before'][0] / .26, result['before'][1] / .34):
        result['reason'] = 'Stance did not improve'
    elif any(not np.allclose(p[1:, :3], original[1:, :3], atol=1e-4) for p in frames):
        result['reason'] = 'Bone lengths changed'
    elif any(np.max(2 * np.arccos(np.clip(np.abs(np.sum(p[:, 3:] * q[:, 3:], axis=1)), 0, 1))) > .35 for p, q in zip(frames, frames[1:])):
        result['reason'] = 'Joint rotation discontinuity'
    elif not all(knees_valid(p, parents, names) and knees_continuous(p, original, parents, names) for p in frames):
        result['reason'] = 'Invalid knee bend'
    elif any(p[side][part][2] < start[side][part][2] - .02 for p in points for side in ('left', 'right') for part in ('ankle', 'toe')):
        result['reason'] = 'Foot penetrated ground'
    else:
        result.update(accepted=True, reason='')
    return result
