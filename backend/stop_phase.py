"""停止から到着ポーズまでの段階。描画も GPU も持たない。

段階は idle → moving → stopping → pose_pending → pose_transition → pose_done。
stopping のあいだは公式の Idle 遷移に任せ、待機ループへ入ってからポーズを生成する。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

IDLE = "idle"
MOVING = "moving"
STOPPING = "stopping"
POSE_PENDING = "pose_pending"
POSE_TRANSITION = "pose_transition"
POSE_DONE = "pose_done"

GOAL_LIMIT = 100.0
_SETTLED = (IDLE, POSE_DONE)


@dataclass(frozen=True)
class NavState:
    phase: str = IDLE
    move_id: int | None = None
    target_pose_id: str = "F001"
    arrived_sent: bool = False
    pose_applied: bool = False


@dataclass(frozen=True)
class CommandResult:
    state: NavState
    quit: bool = False
    move_to: tuple[float, float] | None = None


def apply_nav_command(state: NavState, cmd: dict) -> CommandResult:
    kind = cmd.get("type")
    if kind == "quit":
        return CommandResult(state, quit=True)
    if kind == "move":
        try:
            x = float(cmd["x"])
            y = float(cmd["y"])
        except (KeyError, TypeError, ValueError):
            return CommandResult(state)
        if not (math.isfinite(x) and math.isfinite(y)) or abs(x) > GOAL_LIMIT or abs(y) > GOAL_LIMIT:
            return CommandResult(state)
        return CommandResult(
            replace(
                state,
                phase=MOVING,
                move_id=cmd.get("move_id"),
                target_pose_id="F001",
                arrived_sent=False,
                pose_applied=False,
            ),
            move_to=(x, y),
        )
    if kind == "pose_choice" and cmd.get("move_id") == state.move_id:
        pose_id = cmd.get("pose_id")
        if not isinstance(pose_id, str) or not pose_id:
            return CommandResult(state)
        phase = state.phase
        arrived = state.arrived_sent
        if phase in _SETTLED:
            phase = POSE_PENDING
            arrived = False
        return CommandResult(replace(state, target_pose_id=pose_id, phase=phase, arrived_sent=arrived))
    return CommandResult(state)


def arm_stop(phase: str, should_stop: bool) -> tuple[str, bool]:
    if phase == MOVING and should_stop:
        return STOPPING, True
    return phase, False


def after_playback(
    phase: str,
    *,
    in_idle_loop: bool,
    in_clip_transition: bool,
    time_to_transition: float,
    dt: float,
) -> tuple[str, bool]:
    """再生結果から次の段階と、ポーズ生成を始めるかを返す。"""
    if phase == STOPPING and in_idle_loop:
        phase = POSE_PENDING
    if phase == POSE_PENDING and not in_clip_transition:
        return phase, True
    if phase == POSE_TRANSITION and time_to_transition <= dt:
        return POSE_DONE, False
    return phase, False


def after_pose_request(applied: bool, time_to_transition: float, dt: float) -> str:
    if not applied:
        return IDLE
    if time_to_transition <= dt:
        return POSE_DONE
    return POSE_TRANSITION


def arrival_due(phase: str, arrived_sent: bool, has_goal: bool) -> bool:
    return has_goal and not arrived_sent and phase in _SETTLED
