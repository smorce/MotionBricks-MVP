"""クリック先までの停止判定。CUDA や MotionBricks には依存しない。

停止開始距離は現在の水平速度から先に見積もる。公式の Idle 遷移は
その場で止まらず、遷移クリップのあいだ前へ進むためである。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ClickStopSettings:
    # ロゼのシーンで合わせる実験値。NVIDIA の既定値ではない。
    # 通り過ぎるときは stop_lead_seconds を 0.90 へ、手前で止まりすぎるときは 0.65 へ。
    min_stop_distance_m: float = 0.22
    max_stop_distance_m: float = 2.6
    stop_lead_seconds: float = 0.78
    stop_margin_m: float = 0.10
    slowing_zone_m: float = 2.2
    min_movement_strength: float = 0.12


@dataclass(frozen=True)
class ClickDecision:
    stop: bool
    input_strength: float
    stop_distance_m: float
    goal_distance_m: float


def stop_distance(speed_mps: float, settings: ClickStopSettings = ClickStopSettings()) -> float:
    speed = max(0.0, float(speed_mps))
    if not math.isfinite(speed):
        raise ValueError("speed_mps must be finite")
    distance = speed * settings.stop_lead_seconds + settings.stop_margin_m
    return max(settings.min_stop_distance_m, min(distance, settings.max_stop_distance_m))


def plan_click_move(
    goal_distance_m: float,
    actual_speed_mps: float,
    settings: ClickStopSettings = ClickStopSettings(),
) -> ClickDecision:
    distance = float(goal_distance_m)
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("goal_distance_m must be finite and >= 0")
    threshold = stop_distance(actual_speed_mps, settings)
    if distance <= threshold:
        return ClickDecision(True, 0.0, threshold, distance)
    remaining = max(0.0, distance - threshold)
    strength = max(settings.min_movement_strength, min(1.0, remaining / settings.slowing_zone_m))
    return ClickDecision(False, strength, threshold, distance)
