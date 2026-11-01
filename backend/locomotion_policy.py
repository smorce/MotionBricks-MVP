"""座標変換と、以前の歩き・走り・固定距離の到着判定。

実行時の停止は click_planner と公式 SOMACharacter の Idle 遷移が行う。
この判定は、その離散動作の単体テストのために残している。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

ARRIVAL_RADIUS = 0.36
WALK_DISTANCE = 1.8
REPLAN_ANGLE_DEG = 12.0
WALK_SPEED = 1.25
JOG_SPEED = 2.2
LEAD_SECONDS = 0.75
GOAL_LIMIT = 100.0


@dataclass
class MoveState:
    goal: tuple[float, float] | None = None
    is_moving: bool = False
    generated_direction: tuple[float, float] | None = None
    last_mode: str | None = None
    idle_issued: bool = False
    target_pose_id: str = "F001"
    player_started: bool = False


@dataclass(frozen=True)
class Plan:
    kind: str
    mode: str | None = None
    speed: float | None = None
    direction: tuple[float, float, float] | None = None
    lead: tuple[float, float, float] | None = None
    distance: float = 0.0
    pose_id: str | None = None


def three_to_runtime(x: float, z: float) -> tuple[float, float]:
    """Three.js の床 (x, z) を、Z-up ランタイムの地面 (x, y) にする。"""
    return (float(x), float(-z))


def runtime_to_three(x: float, y: float, z: float) -> tuple[float, float, float]:
    return (float(x), float(z), float(-y))


def _valid_goal(x: float, y: float) -> bool:
    return math.isfinite(x) and math.isfinite(y) and abs(x) <= GOAL_LIMIT and abs(y) <= GOAL_LIMIT


def on_move(state: MoveState, x: float, y: float) -> MoveState:
    if not _valid_goal(x, y):
        return state
    return replace(
        state,
        goal=(float(x), float(y)),
        is_moving=True,
        idle_issued=False,
        generated_direction=None,
        last_mode=None,
        target_pose_id="F001",
    )


def on_pose_choice(state: MoveState, pose_id: str) -> MoveState:
    state = replace(state, target_pose_id=str(pose_id))
    if state.idle_issued and state.goal is not None:
        return replace(state, idle_issued=False, is_moving=True)
    return state


def movement_mode(distance: float) -> str:
    return "walk" if distance < WALK_DISTANCE else "jog"


def plan_motion(state: MoveState, root_xy: tuple[float, float], time_to_transition: float, dt: float) -> tuple[MoveState, Plan]:
    if state.goal is None:
        return state, Plan("hold")
    root = np.asarray(root_xy, dtype=np.float64)
    goal = np.asarray(state.goal, dtype=np.float64)
    diff = goal - root
    distance = float(np.linalg.norm(diff))
    direction = diff / max(distance, 1e-6)
    if distance > ARRIVAL_RADIUS and state.is_moving:
        mode = movement_mode(distance)
        speed = WALK_SPEED if mode == "walk" else JOG_SPEED
        previous = None if state.generated_direction is None else np.asarray(state.generated_direction, dtype=np.float64)
        turned = False
        if previous is not None:
            turned = math.degrees(math.acos(float(np.clip(direction @ previous, -1.0, 1.0)))) > REPLAN_ANGLE_DEG
        need = previous is None or turned or state.last_mode != mode or time_to_transition <= dt
        if need:
            ahead = min(distance, speed * LEAD_SECONDS)
            lead_xy = root + direction * ahead
            new_state = replace(
                state,
                generated_direction=(float(direction[0]), float(direction[1])),
                last_mode=mode,
                player_started=True,
            )
            return new_state, Plan(
                "locomote",
                mode=mode,
                speed=speed,
                direction=(float(direction[0]), float(direction[1]), 0.0),
                lead=(float(lead_xy[0]), float(lead_xy[1]), 0.0),
                distance=distance,
            )
        return state, Plan("hold", mode=mode, distance=distance)
    if state.is_moving and not state.idle_issued:
        facing = state.generated_direction or (1.0, 0.0)
        new_state = replace(state, is_moving=False, idle_issued=True, player_started=True)
        return new_state, Plan(
            "arrive",
            direction=(facing[0], facing[1], 0.0),
            lead=(float(root[0]), float(root[1]), 0.0),
            distance=distance,
            pose_id=state.target_pose_id,
        )
    return state, Plan("hold", distance=distance)
