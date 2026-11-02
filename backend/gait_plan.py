"""移動距離から、歩行ブレンドを使うか、踏み出しで進むかを決める。

SOMA の線形移動は Walk 目標が default_speed（2.3m/s）にある。
入力の長さを 0.12 まで下げると desired speed が約 0.28m/s になり、
生成姿勢は Idle 目標の近くに残ったままルートだけが進む。それが短距離の足滑りである。

境界は仕様の初期値（0.15 / 0.6 / 1.2m）を、届く歩幅に合わせて狭める。
一度選んだ方式は、その移動要求が終わるまで維持する。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# app/runtime/soma/presets.py の LINEAR_LOCOMOTION.default_speed と同じ。
OFFICIAL_WALK_SPEED_MPS = 2.3
MICRO_M = 0.08
SPEC_SHORT_M = 0.62
SPEC_FEW_M = 1.25
DECEL_ZONE_M = 2.2
# 切り分け中は False。独自踏み出し（step_cycle IK）を使わず公式 Walk のみにする。
USE_PROCEDURAL_STEP = False


@dataclass(frozen=True)
class GaitChoice:
    mode: str
    short_edge_m: float
    few_edge_m: float
    final_window_m: float


def horizontal_reach_m(thigh_m: float, shin_m: float, drop_m: float) -> float:
    """膝を曲げたまま前へ出せる水平距離。伸ばし切りは使わない。"""
    reach = max(0.0, (thigh_m + shin_m) * 0.96)
    drop = min(abs(drop_m), reach)
    slack = math.sqrt(max(0.0, reach * reach - drop * drop))
    return max(0.18, slack * 0.85)


def classify_distance(distance_m: float, reach_m: float) -> GaitChoice:
    distance = float(distance_m)
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("goal_distance_m must be finite and >= 0")
    reach = max(0.18, float(reach_m))
    short_edge = min(SPEC_SHORT_M, max(0.20, reach))
    few_edge = min(SPEC_FEW_M, short_edge * 2.0)
    window = min(0.70, max(0.25, reach))
    if distance < MICRO_M:
        mode = "micro"
    elif not USE_PROCEDURAL_STEP:
        mode = "walk"
    elif distance <= short_edge:
        mode = "short_step"
    elif distance <= few_edge:
        mode = "few_steps"
    else:
        mode = "walk"
    return GaitChoice(mode, short_edge, few_edge, window)


def walk_command_scale(mode: str) -> float:
    """線形移動へ渡す入力の長さ。中間値は返さない。"""
    if mode == "walk":
        return 1.0
    return 0.0
