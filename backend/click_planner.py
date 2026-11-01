"""クリック先で、線形歩行を続けるか、踏み出しに渡すか。

入力の長さを 0.12 のように中間値へ縮めると、SOMA の Walk ブレンド（2.3m/s）から
外れ、Idle に近い姿勢のままルートだけが進む。ここは 0 か 1 しか返さない。
停止窓は速度×秒数ではなく、届く一歩の長さである。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from gait_plan import classify_distance, walk_command_scale

# 立ち姿勢からの仮の水平リーチ。実ポーズでは LocomotionCycle が測り直す。
NOMINAL_REACH_M = 0.55


@dataclass(frozen=True)
class ClickStopSettings:
    nominal_reach_m: float = NOMINAL_REACH_M


@dataclass(frozen=True)
class ClickDecision:
    stop: bool
    input_strength: float
    stop_distance_m: float
    goal_distance_m: float
    mode: str


def stop_distance(speed_mps: float, settings: ClickStopSettings = ClickStopSettings()) -> float:
    """最後の一歩に入る距離。速度では伸ばさない。"""
    speed = float(speed_mps)
    if not math.isfinite(speed) or speed < 0:
        raise ValueError("speed_mps must be finite and >= 0")
    return classify_distance(settings.nominal_reach_m, settings.nominal_reach_m).final_window_m


def plan_click_move(
    goal_distance_m: float,
    actual_speed_mps: float,
    settings: ClickStopSettings = ClickStopSettings(),
) -> ClickDecision:
    distance = float(goal_distance_m)
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("goal_distance_m must be finite and >= 0")
    speed = float(actual_speed_mps)
    if not math.isfinite(speed) or speed < 0:
        raise ValueError("speed_mps must be finite and >= 0")
    choice = classify_distance(distance, settings.nominal_reach_m)
    # 通常歩行でも、残りが一歩以内なら線形移動を止めて踏み出しに渡す。
    handoff = choice.mode != "walk" or distance <= choice.final_window_m
    strength = 0.0 if handoff else walk_command_scale("walk")
    return ClickDecision(handoff, strength, choice.final_window_m, distance, choice.mode)
