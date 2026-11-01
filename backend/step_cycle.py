"""接地を保った一歩。

開始姿勢の局所変換だけを基準に、各フレームを作り直す。
支持足のワールド座標は固定し、遊脚が上がった分だけ腰を進める。
腰だけを目的地へ運ぶフレームは作らない。解けない脚は伸ばさず、腰の移動を短くする。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from quats import mat_to_quat, quat_mul, quat_normalize, quat_to_mat
from soma_skeleton import SOMA_JOINT_NAMES, soma_parents, world_from_locals

CHAINS = {
    "left": ("LeftLeg", "LeftShin", "LeftFoot"),
    "right": ("RightLeg", "RightShin", "RightFoot"),
}
TOES = {"left": "LeftToeBase", "right": "RightToeBase"}


def joint_index(names: list[str]) -> dict[str, int]:
    return {name: index for index, name in enumerate(names)}


def fk(pose: np.ndarray, parents: list[int]):
    return world_from_locals(parents, pose[:, :3], pose[:, 3:7])


def _normalize(vec: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vec))
    if length < 1e-8:
        return np.zeros(3, dtype=np.float64)
    return np.asarray(vec, dtype=np.float64) / length


def quat_between(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    a = _normalize(start)
    b = _normalize(end)
    if float(np.linalg.norm(a)) < 1e-8 or float(np.linalg.norm(b)) < 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0])
    cross = np.cross(a, b)
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if dot > 0.999999:
        return np.array([0.0, 0.0, 0.0, 1.0])
    if dot < -0.999999:
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if float(np.linalg.norm(axis)) < 1e-6:
            axis = np.cross(a, np.array([0.0, 1.0, 0.0]))
        return _axis_angle(axis, math.pi)
    return quat_normalize(np.array([cross[0], cross[1], cross[2], 1.0 + dot]))


def _axis_angle(axis: np.ndarray, radians: float) -> np.ndarray:
    axis = _normalize(axis)
    scale = math.sin(radians * 0.5)
    return np.array([axis[0] * scale, axis[1] * scale, axis[2] * scale, math.cos(radians * 0.5)])


def quat_slerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    start = quat_normalize(a)
    end = quat_normalize(b)
    dot = float(np.dot(start, end))
    if dot < 0.0:
        end = -end
        dot = -dot
    if dot > 0.9995:
        return quat_normalize(start + (end - start) * t)
    dot = min(1.0, dot)
    theta = math.acos(dot)
    scale = math.sin(theta)
    return quat_normalize(
        start * math.sin((1.0 - t) * theta) / scale + end * math.sin(t * theta) / scale
    )


def facing_of(root_quat: np.ndarray) -> np.ndarray:
    forward = quat_to_mat(root_quat) @ np.array([1.0, 0.0, 0.0])
    forward[2] = 0.0
    flat = _normalize(forward)
    if float(np.linalg.norm(flat)) < 1e-8:
        return np.array([1.0, 0.0, 0.0])
    return flat


def yaw_toward(root_quat: np.ndarray, direction_xy: np.ndarray) -> np.ndarray:
    current = facing_of(root_quat)
    target = _normalize(np.array([direction_xy[0], direction_xy[1], 0.0]))
    if float(np.linalg.norm(target)) < 1e-8:
        return quat_normalize(root_quat)
    cross = current[0] * target[1] - current[1] * target[0]
    dot = float(np.clip(current[0] * target[0] + current[1] * target[1], -1.0, 1.0))
    spin = _axis_angle(np.array([0.0, 0.0, 1.0]), math.atan2(cross, dot))
    return quat_normalize(quat_mul(spin, root_quat))


def ik_points(root: np.ndarray, target: np.ndarray, thigh: float, shin: float, pole: np.ndarray):
    """膝を pole 側に曲げる。届かない目標は脚の長さの内側へ戻す。"""
    offset = np.asarray(target, dtype=np.float64) - np.asarray(root, dtype=np.float64)
    dist = float(np.linalg.norm(offset))
    longest = max(1e-4, (thigh + shin) * 0.98)
    shortest = abs(thigh - shin) + 1e-3
    clamped = False
    if dist < 1e-6:
        offset = _normalize(pole - root)
        if float(np.linalg.norm(offset)) < 1e-8:
            offset = np.array([1.0, 0.0, 0.0])
        dist = shortest
        clamped = True
    if dist > longest or dist < shortest:
        dist = min(longest, max(shortest, dist))
        clamped = True
    direction = offset / float(np.linalg.norm(offset))
    used = np.asarray(root, dtype=np.float64) + direction * dist
    cos_hip = (thigh * thigh + dist * dist - shin * shin) / (2.0 * thigh * dist)
    cos_hip = float(np.clip(cos_hip, -1.0, 1.0))
    along = thigh * cos_hip
    height = math.sqrt(max(0.0, thigh * thigh - along * along))
    pole_dir = np.asarray(pole, dtype=np.float64) - np.asarray(root, dtype=np.float64)
    pole_dir = pole_dir - direction * float(np.dot(pole_dir, direction))
    if float(np.linalg.norm(pole_dir)) < 1e-6:
        pole_dir = np.cross(direction, np.array([0.0, 0.0, 1.0]))
    pole_dir = _normalize(pole_dir)
    knee = np.asarray(root, dtype=np.float64) + direction * along + pole_dir * height
    return knee, used, clamped


def _swing_joint(pose, parents, joint: int, old_dir: np.ndarray, new_dir: np.ndarray):
    if float(np.linalg.norm(old_dir)) < 1e-8 or float(np.linalg.norm(new_dir)) < 1e-8:
        return pose
    _pos, rot = fk(pose, parents)
    new_world = quat_to_mat(quat_between(old_dir, new_dir)) @ rot[joint]
    parent = parents[joint]
    parent_rot = np.eye(3) if parent < 0 else rot[parent]
    pose = pose.copy()
    pose[joint, 3:7] = mat_to_quat(parent_rot.T @ new_world)
    return pose


def solve_leg(pose, parents, names, side: str, foot_target: np.ndarray, pole: np.ndarray):
    index = joint_index(names)
    thigh, shin, foot = (index[name] for name in CHAINS[side])
    pos, rot = fk(pose, parents)
    saved_foot = rot[foot].copy()
    thigh_len = float(np.linalg.norm(pose[shin, :3]))
    shin_len = float(np.linalg.norm(pose[foot, :3]))
    knee, used, _clamped = ik_points(pos[thigh], foot_target, thigh_len, shin_len, pole)
    pose = _swing_joint(pose, parents, thigh, pos[shin] - pos[thigh], knee - pos[thigh])
    pos, _rot = fk(pose, parents)
    pose = _swing_joint(pose, parents, shin, pos[foot] - pos[shin], used - pos[shin])
    pos, rot = fk(pose, parents)
    pose = pose.copy()
    pose[foot, 3:7] = mat_to_quat(rot[shin].T @ saved_foot)
    return pose


def leg_metrics(pose, parents, names, side: str) -> tuple[float, float, float]:
    """thigh length, shin length, hip-to-ankle drop."""
    index = joint_index(names)
    thigh, shin, foot = (index[name] for name in CHAINS[side])
    pos, _rot = fk(pose, parents)
    return (
        float(np.linalg.norm(pose[shin, :3])),
        float(np.linalg.norm(pose[foot, :3])),
        abs(float(pos[thigh][2] - pos[foot][2])),
    )


def choose_swing(left_xyz, right_xyz, facing, left_z, right_z) -> str:
    if left_z > right_z + 0.03:
        return "left"
    if right_z > left_z + 0.03:
        return "right"
    forward = _normalize(np.array([facing[0], facing[1], 0.0]))
    left_ahead = float(np.dot(left_xyz[:2], forward[:2]))
    right_ahead = float(np.dot(right_xyz[:2], forward[:2]))
    if left_ahead < right_ahead - 0.01:
        return "left"
    return "right"


def _smooth(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3.0 - 2.0 * u)


@dataclass
class StepState:
    kind: str
    swing: str
    elapsed: float
    duration: float
    done: bool
    base_pose: np.ndarray
    travel: np.ndarray
    support_target: np.ndarray
    swing_start: np.ndarray
    swing_land: np.ndarray
    lift: float
    target_quat: np.ndarray
    facing: np.ndarray
    lateral: np.ndarray
    match_speed: bool

    @property
    def u(self) -> float:
        if self.duration <= 1e-6:
            return 1.0
        return min(1.0, self.elapsed / self.duration)

    @property
    def landing(self) -> bool:
        return self.u >= 0.82


def _chain_positions(pose, parents, names):
    index = joint_index(names)
    pos, _rot = fk(pose, parents)
    feet = {}
    hips = {}
    for side, chain in CHAINS.items():
        feet[side] = pos[index[chain[2]]].copy()
        hips[side] = pos[index[chain[0]]].copy()
    return feet, hips


def begin_step(pose, parents, names, *, kind: str, direction_xy, distance_m: float, swing: str, speed_mps: float) -> StepState:
    base = np.array(pose, dtype=np.float64, copy=True)
    direction = _normalize(np.array([direction_xy[0], direction_xy[1], 0.0], dtype=np.float64))
    if float(np.linalg.norm(direction)) < 1e-8:
        direction = facing_of(base[0, 3:7])
    lateral = _normalize(np.cross(np.array([0.0, 0.0, 1.0]), direction))
    feet, _hips = _chain_positions(base, parents, names)
    support = "right" if swing == "left" else "left"
    support_target = feet[support].copy()
    swing_start = feet[swing].copy()
    if kind == "collect":
        travel = np.zeros(3, dtype=np.float64)
        land = _collect_landing(support_target, swing_start, direction, lateral)
        duration = 0.42
        lift = 0.055
        match_speed = False
    else:
        travel = direction * float(distance_m)
        land = swing_start + travel
        land[2] = swing_start[2]
        speed = max(0.0, float(speed_mps))
        if speed <= 0.15:
            duration = min(0.72, max(0.36, 0.40 + float(distance_m) * 0.35))
            match_speed = False
        else:
            duration = min(0.85, max(0.32, 2.0 * float(distance_m) / speed))
            match_speed = True
        lift = 0.06 + 0.05 * min(1.0, float(distance_m) / 0.6)
    return StepState(
        kind=kind,
        swing=swing,
        elapsed=0.0,
        duration=duration,
        done=False,
        base_pose=base,
        travel=travel,
        support_target=support_target,
        swing_start=swing_start,
        swing_land=land,
        lift=lift,
        target_quat=yaw_toward(base[0, 3:7], direction[:2]),
        facing=direction,
        lateral=lateral,
        match_speed=match_speed,
    )


def _collect_landing(support: np.ndarray, swing: np.ndarray, facing: np.ndarray, lateral: np.ndarray) -> np.ndarray:
    forward = float(np.dot(support[:3], facing))
    side = float(np.dot(swing[:3], lateral))
    height = float(np.dot(support[:3], np.array([0.0, 0.0, 1.0])))
    # 横幅は遊脚側の座標を維持し、前後だけ支持足の 10cm 手前へ置く。
    land = facing * (forward - 0.10) + lateral * side
    land[2] = swing[2] if swing[2] > 0.0 else height
    land[2] = swing[2]
    return land


def _progress(state: StepState) -> float:
    u = state.u
    if state.match_speed:
        return 1.0 - (1.0 - u) ** 2
    return _smooth(u)


def advance_step(parents, names, state: StepState, dt: float):
    """開始姿勢から dt 進めた姿勢と、更新した状態を返す。"""
    state.elapsed += max(0.0, float(dt))
    if state.elapsed >= state.duration:
        state.done = True
    u = state.u
    progress = _progress(state)
    pose = state.base_pose.copy()
    shift = 0.0
    if state.kind == "travel" and u < 0.18:
        shift = 0.035 * (u / 0.18)
    toward = state.lateral if state.swing == "right" else -state.lateral
    pose[0, :3] = state.base_pose[0, :3] + state.travel * progress + toward * shift
    turn = min(1.0, u / 0.40)
    pose[0, 3:7] = quat_slerp(state.base_pose[0, 3:7], state.target_quat, turn)
    pose = _clamp_support(pose, parents, names, state)
    if state.kind == "travel" and u < 0.18:
        swing_target = state.swing_start.copy()
    else:
        if state.kind == "travel":
            local = (u - 0.18) / 0.82
        else:
            local = u
        local = _smooth(local)
        swing_target = (1.0 - local) * state.swing_start + local * state.swing_land
        swing_target = swing_target.copy()
        swing_target[2] = state.swing_start[2] + math.sin(math.pi * local) * state.lift
    support = "right" if state.swing == "left" else "left"
    pose = solve_leg(pose, parents, names, support, state.support_target, _pole(state, support, pose))
    pose = solve_leg(pose, parents, names, state.swing, swing_target, _pole(state, state.swing, pose))
    return pose, state


def _pole(state: StepState, side: str, pose: np.ndarray) -> np.ndarray:
    outward = state.lateral if side == "left" else -state.lateral
    return pose[0, :3] + state.facing * 0.45 + outward * 0.2 + np.array([0.0, 0.0, 0.15])


def _clamp_support(pose, parents, names, state: StepState):
    """支持足が届かない腰の移動は、足首を伸ばす前に短くする。"""
    index = joint_index(names)
    support = "right" if state.swing == "left" else "left"
    thigh, shin, _foot = (index[name] for name in CHAINS[support])
    pos, _rot = fk(pose, parents)
    reach = (float(np.linalg.norm(pose[shin, :3])) + float(np.linalg.norm(pose[_foot, :3]))) * 0.96
    hip = pos[thigh]
    offset = hip - state.support_target
    dist = float(np.linalg.norm(offset))
    if dist <= reach or dist < 1e-6:
        return pose
    allowed = state.support_target + offset / dist * reach
    pose = pose.copy()
    pose[0, :3] = pose[0, :3] + (allowed - hip)
    return pose


def foot_points(pose, parents, names) -> dict[str, dict[str, np.ndarray]]:
    index = joint_index(names)
    pos, _rot = fk(pose, parents)
    points = {}
    for side, chain in CHAINS.items():
        points[side] = {
            "ankle": pos[index[chain[2]]].copy(),
            "toe": pos[index[TOES[side]]].copy(),
        }
    return points


def default_parents():
    return soma_parents()


def default_names():
    return list(SOMA_JOINT_NAMES)
