"""XYZW クォータニオンと回転行列。BVH の合成順は MotionBricks のローダに合わせる。"""
from __future__ import annotations

import math

import numpy as np

Array = np.ndarray


def quat_normalize(q: Array) -> Array:
    q = np.asarray(q, dtype=np.float64)
    n = float(np.linalg.norm(q))
    if n < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    return q / n


def quat_conj(q: Array) -> Array:
    x, y, z, w = quat_normalize(q)
    return np.array([-x, -y, -z, w])


def quat_mul(a: Array, b: Array) -> Array:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array(
        [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ],
        dtype=np.float64,
    )


def quat_from_axis_angle(axis: Array, radians: float) -> Array:
    axis = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(axis))
    if n < 1e-12 or abs(radians) < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    axis = axis / n
    s = math.sin(radians * 0.5)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, math.cos(radians * 0.5)])


def euler_channels_to_quat(axis_ids: list[int], degrees: list[float]) -> Array:
    """ファイルに並んだ回転チャンネル順に左から掛ける。axis は 0=X, 1=Y, 2=Z。"""
    q = np.array([0.0, 0.0, 0.0, 1.0])
    for axis_id, degree in zip(axis_ids, degrees):
        axis = np.zeros(3)
        axis[axis_id] = 1.0
        q = quat_mul(q, quat_from_axis_angle(axis, math.radians(degree)))
    return quat_normalize(q)


def quat_to_mat(q: Array) -> Array:
    x, y, z, w = quat_normalize(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def mat_to_quat(m: Array) -> Array:
    m = np.asarray(m, dtype=np.float64)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return quat_normalize(np.array([x, y, z, w]))


def rotate_vec(q: Array, v: Array) -> Array:
    return quat_to_mat(q) @ np.asarray(v, dtype=np.float64)


# Y-up のソースを Newton の Z-up へ。+90 度の X 回転（MotionBricks の MUJOCO 変換）。
RX90 = quat_from_axis_angle(np.array([1.0, 0.0, 0.0]), math.pi / 2.0)
RZ = np.array([0.0, 0.0, 1.0])
