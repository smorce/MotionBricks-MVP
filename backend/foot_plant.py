"""足の接地と、接地中の水平滑り。

接地値は推定なので、高さ・水平速度と組み合わせる。公式クリップ再生中は
4 点すべてが 0 になることがある。その 0 は「浮いている」ではなく、
接地情報が使えない、として扱う。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

CONTACT_ORDER = ("left_heel", "left_toe", "right_heel", "right_toe")


def _clamp01(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _falloff(value: float, low: float, high: float) -> float:
    """low 以下で 1、high 以上で 0。"""
    if not math.isfinite(value):
        return 0.0
    if high <= low:
        return 1.0 if value <= low else 0.0
    if value <= low:
        return 1.0
    if value >= high:
        return 0.0
    return 1.0 - (value - low) / (high - low)


def contact_channel_score(
    contact: float | None,
    height_m: float,
    speed_mps: float,
    *,
    contacts_available: bool,
    ground_z: float,
) -> float:
    """1 点（かかとまたはつま先）の接地らしさ。0〜1。"""
    height_term = _falloff(height_m - ground_z, 0.02, 0.07)
    speed_term = _falloff(speed_mps, 0.03, 0.14)
    if not contacts_available or contact is None:
        return 0.62 * height_term + 0.38 * speed_term
    return 0.34 * _clamp01(contact) + 0.40 * height_term + 0.26 * speed_term


def foot_plant_score(
    contacts: tuple[float, float] | None,
    heights: tuple[float, float],
    speeds: tuple[float, float],
    *,
    contacts_available: bool,
    ground_z: float,
) -> float:
    """片足。速く動いている足は、接触値だけでは接地にしない。"""
    if max(speeds) > 0.16 or min(heights) - ground_z >= 0.07:
        return 0.0
    heel = None if contacts is None else contacts[0]
    toe = None if contacts is None else contacts[1]
    heel_score = contact_channel_score(
        heel, heights[0], speeds[0], contacts_available=contacts_available, ground_z=ground_z,
    )
    toe_score = contact_channel_score(
        toe, heights[1], speeds[1], contacts_available=contacts_available, ground_z=ground_z,
    )
    return max(heel_score, toe_score)


@dataclass
class PlantState:
    """ヒステリシス付きの左右接地と、接地区間の滑り。"""

    left: bool = False
    right: bool = False
    anchor: dict[str, np.ndarray] = field(default_factory=dict)
    segment_m: dict[str, float] = field(default_factory=lambda: {"left": 0.0, "right": 0.0})
    worst_m: dict[str, float] = field(default_factory=lambda: {"left": 0.0, "right": 0.0})
    source: str = "unavailable"

    def update(
        self,
        *,
        contacts: np.ndarray | None,
        heights: np.ndarray,
        speeds: np.ndarray,
        points: dict[str, np.ndarray],
        contacts_available: bool,
        ground_z: float,
    ) -> None:
        values = None if contacts is None else np.asarray(contacts, dtype=np.float64).reshape(-1)
        if values is not None and values.shape[0] != 4:
            raise ValueError("contacts must contain 4 values: left heel, left toe, right heel, right toe")
        height = np.asarray(heights, dtype=np.float64).reshape(-1)
        speed = np.asarray(speeds, dtype=np.float64).reshape(-1)
        if height.shape[0] != 4 or speed.shape[0] != 4:
            raise ValueError("heights and speeds must contain 4 values")
        self.source = "model+geometry" if contacts_available else "geometry"
        scores = {}
        for side, contact_slice in (("left", slice(0, 2)), ("right", slice(2, 4))):
            pair = None if values is None or not contacts_available else (
                float(values[contact_slice][0]), float(values[contact_slice][1]),
            )
            scores[side] = foot_plant_score(
                pair,
                (float(height[contact_slice][0]), float(height[contact_slice][1])),
                (float(speed[contact_slice][0]), float(speed[contact_slice][1])),
                contacts_available=contacts_available,
                ground_z=ground_z,
            )
        self.left = _with_hysteresis(self.left, scores["left"])
        self.right = _with_hysteresis(self.right, scores["right"])
        for side, planted in (("left", self.left), ("right", self.right)):
            point = np.asarray(points[side], dtype=np.float64)
            if planted:
                if side not in self.anchor:
                    self.anchor[side] = point.copy()
                    self.segment_m[side] = 0.0
                else:
                    slip = float(np.linalg.norm(point[:2] - self.anchor[side][:2]))
                    self.segment_m[side] = slip
                    self.worst_m[side] = max(self.worst_m[side], slip)
            else:
                self.anchor.pop(side, None)
                self.segment_m[side] = 0.0


def _with_hysteresis(was_planted: bool, score: float) -> bool:
    if was_planted:
        return score >= 0.42
    return score >= 0.64


def stance_width_m(left_xyz: np.ndarray, right_xyz: np.ndarray, facing_xy: np.ndarray) -> float:
    """進行方向に直交する左右の足幅。前後の開きは含まない。"""
    facing = np.asarray(facing_xy, dtype=np.float64)
    flat = float(np.linalg.norm(facing[:2]))
    if flat < 1e-8:
        facing = np.array([1.0, 0.0])
    else:
        facing = facing[:2] / flat
    lateral = np.array([-facing[1], facing[0]])
    delta = np.asarray(left_xyz[:2], dtype=np.float64) - np.asarray(right_xyz[:2], dtype=np.float64)
    return abs(float(np.dot(delta, lateral)))
