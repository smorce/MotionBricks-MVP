"""Pure navigation stop controller. No CUDA, Warp, or MotionBricks import required.

Scene Preview owns motion transitions. This module only converts an absolute
click goal into the speed/direction inputs expected by its LocomotionCommand.
Its stop decision is anticipatory because the generated clip transition travels
forward instead of hard-snapping the root to the destination.
"""
from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ClickStopSettings:
    # Tunable heuristics, NOT NVIDIA defaults; verify in Roze's scene.
    min_stop_distance_m: float = 0.22
    max_stop_distance_m: float = 2.6
    stop_lead_seconds: float = 0.78
    stop_margin_m: float = 0.10
    slowing_zone_m: float = 2.2
    min_movement_strength: float = 0.12
    # Stop-distance estimates use the character's *actual* planar velocity.


@dataclass(frozen=True)
class ClickDecision:
    stop: bool
    input_strength: float
    stop_distance_m: float
    goal_distance_m: float


def stop_distance(speed_mps: float, settings: ClickStopSettings = ClickStopSettings()) -> float:
    speed = max(0.0, float(speed_mps))
    if not math.isfinite(speed):
        raise ValueError('speed_mps must be finite')
    distance = speed * settings.stop_lead_seconds + settings.stop_margin_m
    return max(settings.min_stop_distance_m, min(distance, settings.max_stop_distance_m))


def plan_click_move(
    goal_distance_m: float,
    actual_speed_mps: float,
    settings: ClickStopSettings = ClickStopSettings(),
) -> ClickDecision:
    distance = float(goal_distance_m)
    if not math.isfinite(distance) or distance < 0:
        raise ValueError('goal_distance_m must be finite and >= 0')
    threshold = stop_distance(actual_speed_mps, settings)
    if distance <= threshold:
        return ClickDecision(True, 0.0, threshold, distance)
    # Gradually reduce input before the official idle transition triggers.
    # NVIDIA MovementControl supplies the spring-based smoothing afterward.
    remaining = max(0.0, distance - threshold)
    strength = max(settings.min_movement_strength, min(1.0, remaining / settings.slowing_zone_m))
    return ClickDecision(False, strength, threshold, distance)
