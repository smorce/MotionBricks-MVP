"""床クリックの移動、最後の一歩、停止姿勢。

描画する姿勢の所有者はフェーズごとに一つにする。

- walk: MotionBricks の線形移動。入力の長さは 1 で、Walk ブレンドに置く。
- short_step / few_steps / 最後の一歩: gait_plan.USE_PROCEDURAL_STEP が True のときだけ。
  支持足を固定した手続き踏み出し。切り分け中の既定は False（公式 Walk のみ）。
- settled: 着地した同一フレームの姿勢を、次の移動要求まで保持する。
  公式 Idle へは入らない。IdleState.enter が待機クリップの開始姿勢へ生成し、
  足幅が変わるためである。
- 到着動作: settled のあと、ポーズ ID が届いてから一度だけ生成する。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from collect_stance import COLLECT_WAIT_S, needs_collect, stance
from foot_plant import PlantState, stance_width_m
from gait_log import GAIT_LOG
import gait_plan
from gait_plan import (
    DECEL_ZONE_M,
    MICRO_M,
    OFFICIAL_WALK_SPEED_MPS,
    classify_distance,
    horizontal_reach_m,
)
from step_cycle import (
    advance_step,
    begin_step,
    choose_swing,
    default_names,
    default_parents,
    facing_of,
    foot_points,
    leg_metrics,
)

IDLE = "idle"
MOVING = "moving"
DECELERATING = "decelerating"
FINAL_STEP = "final_step"
WAITING = "waiting_for_foot_contact"
CONTACT_RECOVERY = "contact_recovery"
SETTLED = "settled"
POSE_PENDING = "pose_pending"
POSE_TRANSITION = "pose_transition"
POSE_DONE = "pose_done"

CONTACT_WAIT_S = 0.75
POSE_WAIT_S = 8.0
COLLECT_PREPARING = "collect_preparing"
COLLECTING = "collecting"


@dataclass
class Action:
    phase: str
    walk: bool = False
    play: bool = False
    begin_collect: bool = False
    begin_arrival: bool = False
    pose: np.ndarray | None = None
    seed: bool = False
    prime_walk: bool = False
    facing: np.ndarray | None = None
    gait: dict | None = None


class LocomotionCycle:
    def __init__(self, log=GAIT_LOG) -> None:
        self.log = log
        self.phase = IDLE
        self.goal: np.ndarray | None = None
        self.hold_stance = True
        self.move_id: int | None = None
        self.mode: str | None = None
        self.travel_mode: str | None = None
        self.choice = None
        self.step = None
        self.base_pose: np.ndarray | None = None
        self.settled_pose: np.ndarray | None = None
        self.settle_seq = 0
        self.pose_ready = False
        self.target_pose_id = "F001"
        self.arrival_started = False
        self.arrival_done = False
        self.pose_applied = False
        self._seed_pending = False
        self.pose_time = 0.0
        self.clock = 0.0
        self.stop_requested_s: float | None = None
        self.stop_facing = None
        self._plants_updated_s = None
        self.last_plant_s: float | None = None
        self.settled_s: float | None = None
        self.contact_fallback = False
        self.collect_checked = False
        self.collect_attempted = False
        self.upper_idle_ready = False
        self.collect_failure_reason = ""
        self.collect_original_pose = None
        self.collect_metrics = {}
        self.collect_frames = []
        self.collect_index = 0
        self.collect_review = None
        self.collect_started_s = None
        self.budget = 0.0
        self.walk_primed = False
        self.plants = PlantState()
        self._prev_points: dict | None = None
        self._ground_z = 0.0
        self._event = ""
        self._dt = 1.0 / 60.0
        self.parents = default_parents()
        self.names = default_names()

    def begin_move(self, goal_xy, hold_stance: bool, move_id) -> None:
        self.goal = np.array([float(goal_xy[0]), float(goal_xy[1]), 0.0], dtype=np.float64)
        self.hold_stance = bool(hold_stance)
        self.move_id = move_id
        self.mode = None
        self.travel_mode = None
        self.choice = None
        self.step = None
        self.settled_pose = None
        self.pose_ready = False
        self.target_pose_id = "F001"
        self.arrival_started = False
        self.arrival_done = False
        self.pose_applied = False
        self._seed_pending = False
        self.pose_time = 0.0
        self.stop_requested_s = None
        self.stop_facing = None
        self.last_plant_s = None
        self.settled_s = None
        self.contact_fallback = False
        self.collect_checked = False
        self.collect_attempted = False
        self.upper_idle_ready = False
        self.collect_failure_reason = ""
        self.collect_original_pose = None
        self.collect_metrics = {}
        self.collect_frames = []
        self.collect_index = 0
        self.collect_review = None
        self.collect_started_s = None
        self.budget = 0.0
        self.walk_primed = False
        self.plants = PlantState()
        self._prev_points = None
        self.phase = MOVING
        self._event = "move"

    def note_upper_idle_ready(self, move_id, settle_seq):
        if self.phase != SETTLED or move_id != self.move_id or settle_seq != self.settle_seq or self.collect_checked:
            return False
        self.upper_idle_ready = True
        return True

    def stage_collect(self, frames, metrics, move_id, settle_seq):
        if self.phase != COLLECT_PREPARING or move_id != self.move_id or settle_seq != self.settle_seq:
            return False
        if frames is None or not metrics.get("accepted"):
            self.note_collect(None, metrics, move_id, settle_seq)
            return False
        self.collect_review = (frames, metrics, self.clock)
        return True

    def note_collect_review(self, accepted, metrics, move_id, settle_seq):
        if self.phase != COLLECT_PREPARING or self.collect_review is None or move_id != self.move_id or settle_seq != self.settle_seq:
            return False
        frames, soma_metrics, _ = self.collect_review
        self.collect_review = None
        combined = {**soma_metrics, "vrm": metrics, "accepted": accepted is True}
        if accepted is not True:
            combined["reason"] = metrics.get("reason", "VRM validation failed")
        self.note_collect(frames if accepted is True else None, combined, move_id, settle_seq)
        return True

    def expire_collect_review(self):
        if self.collect_review is not None and self.clock - self.collect_review[2] >= 5:
            self.note_collect_review(False, {"reason": "VRM validation timed out"}, self.move_id, self.settle_seq)

    def note_collect(self, frames, metrics, move_id, settle_seq):
        if self.phase != COLLECT_PREPARING or move_id != self.move_id or settle_seq != self.settle_seq:
            return
        self.collect_metrics = metrics
        if frames is None or not metrics.get("accepted"):
            self.phase = SETTLED
            self.collect_failure_reason = metrics.get("reason", "Generation failed")
            return
        self.collect_frames = frames
        self.collect_index = 0
        self.phase = COLLECTING

    def note_pose_choice(self, pose_id: str) -> None:
        if self.hold_stance or self.arrival_started:
            return
        if not pose_id:
            return
        self.target_pose_id = pose_id
        self.pose_ready = True
        self._event = "pose_choice"

    def note_arrival(self, applied: bool, time_to_transition: float) -> None:
        self.arrival_started = True
        self.arrival_done = not applied
        self.pose_applied = bool(applied)
        self.pose_time = max(0.0, float(time_to_transition))
        self.phase = POSE_DONE if (not applied or self.pose_time <= self._dt) else POSE_TRANSITION
        self.settled_pose = None

    def tick(self, obs: dict) -> Action:
        dt = float(obs.get("dt") or self._dt)
        self._dt = dt
        self.clock += dt
        self.expire_collect_review()
        if self.phase == COLLECT_PREPARING and self.collect_started_s is not None and self.clock - self.collect_started_s >= 15:
            self.collect_review = None
            self.note_collect(None, {"accepted": False, "reason": "Collect preparation timed out"}, self.move_id, self.settle_seq)
        self._event = ""
        pose = np.asarray(obs["pose"], dtype=np.float64)
        parents = obs.get("parents") or self.parents
        names = obs.get("names") or self.names
        self.parents = parents
        self.names = names
        if self.phase == POSE_TRANSITION:
            self.pose_time = max(0.0, self.pose_time - dt)
            if self.pose_time <= dt:
                self.phase = POSE_DONE
                self.arrival_done = True
            return self._action(pose, walk=False, play=True, obs=obs)
        if self.phase == POSE_DONE:
            return self._action(pose, play=True, obs=obs)
        if self.phase == POSE_PENDING:
            return self._action(pose, begin_arrival=True, obs=obs)

        if self.goal is None:
            self.phase = IDLE
            return self._action(pose, play=True, obs=obs)

        position = pose[0, :2]
        distance = float(np.linalg.norm(self.goal[:2] - position))
        facing = self._facing(pose, obs.get("facing"))
        if self.mode is None:
            self._classify(pose, parents, names, distance)
        self._update_plants(obs, pose, parents, names, dt)

        if self.phase == COLLECTING:
            frame = self.collect_frames[self.collect_index]
            self.collect_index += 1
            if self.collect_index == len(self.collect_frames):
                self._settle(frame, "collect_complete")
            return self._action(frame, pose_out=frame, seed=True, obs=obs)

        if self.phase == COLLECT_PREPARING:
            return self._action(self.settled_pose, pose_out=self.settled_pose, obs=obs)

        if self.mode == "micro" and self.phase != SETTLED:
            if self.stop_requested_s is None:
                self.stop_requested_s = self.clock
                self.stop_facing = facing.copy()
            return self._wait_to_settle(pose, parents, names, obs)

        if self.phase == SETTLED:
            return self._hold_or_arrive(pose, obs)

        if gait_plan.USE_PROCEDURAL_STEP and self.step is not None:
            return self._advance_procedural(parents, names, obs)
        if not gait_plan.USE_PROCEDURAL_STEP:
            self.step = None

        stop_at = self.choice.final_window_m if gait_plan.USE_PROCEDURAL_STEP else MICRO_M
        if self.stop_requested_s is None and self.mode == "walk" and distance > stop_at:
            self.phase = DECELERATING if distance <= DECEL_ZONE_M else MOVING
            prime = not self.walk_primed
            self.walk_primed = True
            return self._action(pose, walk=True, prime_walk=prime, facing=facing, obs=obs)

        # 通常歩行の最後、または短距離の踏み出し。ここから公式 Idle には入らない。
        if self.stop_requested_s is None:
            self.stop_requested_s = self.clock
            self.stop_facing = facing.copy()
            self._event = "stop_requested"

        if not gait_plan.USE_PROCEDURAL_STEP:
            return self._wait_to_settle(pose, parents, names, obs)

        if self.mode == "walk":
            self.budget = distance
            self.mode = "final"
        if self.budget <= 0.08 and self.step is None:
            return self._wait_to_settle(pose, parents, names, obs)

        swing = self._swing_choice(pose, parents, names)
        kind_distance = min(self.budget, self.choice.final_window_m)
        speed = float(obs.get("actual_speed") or 0.0) if self.mode == "final" else 0.0
        self.step = begin_step(
            pose, parents, names,
            kind="travel",
            direction_xy=self.goal[:2] - position,
            distance_m=kind_distance,
            swing=swing,
            speed_mps=speed,
        )
        self.budget = max(0.0, self.budget - kind_distance)
        self.phase = FINAL_STEP
        return self._advance_procedural(parents, names, obs)

    def _classify(self, pose, parents, names, distance: float) -> None:
        reaches = []
        for side in ("left", "right"):
            thigh, shin, drop = leg_metrics(pose, parents, names, side)
            reaches.append(horizontal_reach_m(thigh, shin, drop))
        reach = min(reaches) if reaches else 0.4
        self.choice = classify_distance(distance, reach)
        self.mode = self.choice.mode
        self.travel_mode = self.choice.mode
        self.budget = 0.0 if self.mode in ("walk", "micro") else distance
        self._capture_ground(pose, parents, names)

    def _wait_to_settle(self, pose, parents, names, obs) -> Action:
        """公式歩行を進めながら接地を待ち、時間切れは回復状態にする。"""
        both, _fallback = self._feet_ready(obs, pose, parents, names, self._dt)
        waited = self.clock - (self.stop_requested_s or self.clock)
        if both:
            self._settle(pose, "plant")
            return self._hold_or_arrive(pose, obs)
        timed_out = waited > CONTACT_WAIT_S
        if timed_out and self.phase != CONTACT_RECOVERY:
            self._event = "contact_timeout"
        self.phase = CONTACT_RECOVERY if timed_out else WAITING
        self.contact_fallback = timed_out or not bool(obs.get("contacts_available", False))
        prime = not self.walk_primed
        self.walk_primed = True
        return self._action(pose, walk=True, prime_walk=prime, facing=self.stop_facing, obs=obs)

    def _advance_procedural(self, parents, names, obs) -> Action:
        pose, self.step = advance_step(parents, names, self.step, self._dt)
        if self.step.landing and self.last_plant_s is None and self.step.u > 0.95:
            self.last_plant_s = self.clock
            self._event = "plant"
        if not self.step.done:
            self.phase = WAITING if self.step.landing else FINAL_STEP
            return self._action(pose, pose_out=pose, obs=obs)
        self.step = None
        if self.budget > 0.08:
            self.phase = MOVING
            return self._action(pose, pose_out=pose, obs=obs)
        self._settle(pose, "plant")
        return self._hold_or_arrive(pose, obs)

    def _hold_or_arrive(self, pose, obs) -> Action:
        shown = self.settled_pose if self.settled_pose is not None else pose
        seed = self._seed_pending
        self._seed_pending = False
        if self.hold_stance and not self.collect_checked and self.settled_s is not None:
            waited = self.clock - self.settled_s
            if waited >= 2.5:
                self.collect_checked = True
                self.collect_failure_reason = "Upper idle readiness timed out"
            elif waited >= COLLECT_WAIT_S and self.upper_idle_ready:
                self._update_plants(obs, shown, self.parents, self.names, self._dt)
                sagittal, width = stance(shown, self.parents, self.names)
                self.collect_checked = self.plants.left and self.plants.right
                if self.plants.left and self.plants.right and needs_collect(sagittal, width):
                    self.collect_attempted = True
                    self.collect_original_pose = shown.copy()
                    self.phase = COLLECT_PREPARING
                    self.collect_started_s = self.clock
                    action = self._action(shown, pose_out=shown, seed=seed, obs=obs)
                    action.begin_collect = True
                    return action
        if self.hold_stance or self.arrival_done:
            return self._action(shown, pose_out=shown, seed=seed, obs=obs)
        if self.pose_ready and not self.arrival_started:
            self.phase = POSE_PENDING
            self._event = "arrival"
            return self._action(shown, begin_arrival=True, pose_out=shown, obs=obs)
        if (
            not self.pose_ready
            and self.settled_s is not None
            and self.clock - self.settled_s > POSE_WAIT_S
        ):
            self.arrival_done = True
            self.contact_fallback = True
            self._event = "pose_timeout"
        return self._action(shown, pose_out=shown, seed=seed, obs=obs)

    def _settle(self, pose, reason: str) -> None:
        if self.phase == SETTLED and self.settled_pose is not None:
            return
        self.settled_pose = np.array(pose, dtype=np.float64, copy=True)
        self.settle_seq += 1
        self.settled_s = self.clock
        self.last_plant_s = self.last_plant_s or self.clock
        self.phase = SETTLED
        self.step = None
        self._seed_pending = True
        self._event = reason

    def _feet_ready(self, obs, pose, parents, names, dt) -> tuple[bool, bool]:
        self._update_plants(obs, pose, parents, names, dt)
        available = bool(obs.get("contacts_available", False))
        if not available:
            return self.plants.left and self.plants.right, True
        return self.plants.left and self.plants.right, False

    def _swing_choice(self, pose, parents, names) -> str:
        feet, _hips = _feet(pose, parents, names)
        return choose_swing(
            feet["left"], feet["right"], facing_of(pose[0, 3:7]),
            float(feet["left"][2]), float(feet["right"][2]),
        )

    def _sagittal(self, pose, parents, names) -> float:
        feet, _hips = _feet(pose, parents, names)
        facing = facing_of(pose[0, 3:7])
        return abs(float(np.dot(feet["left"] - feet["right"], facing)))

    def _facing(self, pose, given) -> np.ndarray:
        if self.goal is not None:
            delta = self.goal[:2] - pose[0, :2]
            length = float(np.linalg.norm(delta))
            if length > 1e-4:
                direction = np.array([delta[0] / length, delta[1] / length, 0.0])
                return direction
        if given is not None:
            vec = np.asarray(given, dtype=np.float64)
            length = float(np.linalg.norm(vec[:2]))
            if length > 1e-6:
                return np.array([vec[0] / length, vec[1] / length, 0.0])
        face = facing_of(pose[0, 3:7])
        return face

    def _capture_ground(self, pose, parents, names) -> None:
        points = foot_points(pose, parents, names)
        zs = [float(points[side][part][2]) for side in ("left", "right") for part in ("ankle", "toe")]
        self._ground_z = min(zs)

    def _update_plants(self, obs, pose, parents, names, dt) -> None:
        if self._plants_updated_s == self.clock:
            return
        self._plants_updated_s = self.clock
        points = foot_points(pose, parents, names)
        heights = np.array([
            points["left"]["ankle"][2], points["left"]["toe"][2],
            points["right"]["ankle"][2], points["right"]["toe"][2],
        ])
        speeds = np.zeros(4)
        if self._prev_points is not None and dt > 0:
            order = (
                ("left", "ankle"), ("left", "toe"), ("right", "ankle"), ("right", "toe"),
            )
            for index, (side, part) in enumerate(order):
                speeds[index] = float(np.linalg.norm(
                    points[side][part][:2] - self._prev_points[side][part][:2]
                )) / dt
        self._prev_points = points
        contacts = obs.get("contacts")
        self.plants.update(
            contacts=None if contacts is None else np.asarray(contacts, dtype=np.float64),
            heights=heights,
            speeds=speeds,
            points={"left": points["left"]["ankle"], "right": points["right"]["ankle"]},
            contacts_available=bool(obs.get("contacts_available", False)),
            ground_z=self._ground_z,
        )

    def _action(self, shown, obs, *, walk=False, play=False, begin_arrival=False, pose_out=None, seed=False, prime_walk=False, facing=None) -> Action:
        pose = shown if pose_out is None else pose_out
        self._update_plants(obs, pose, self.parents, self.names, self._dt)
        points = foot_points(pose, self.parents, self.names)
        facing_vec = facing if facing is not None else self._facing(pose, obs.get("facing"))
        width = stance_width_m(points["left"]["ankle"], points["right"]["ankle"], facing_vec)
        commanded = OFFICIAL_WALK_SPEED_MPS if walk else 0.0
        row = {
            "t": round(self.clock, 4),
            "phase": self.phase,
            "mode": self.travel_mode or self.mode or "",
            "playback": obs.get("playback") or "",
            "official_state": obs.get("official_state") or "",
            "actual_speed_mps": round(float(obs.get("actual_speed") or 0.0), 4),
            "commanded_speed_mps": commanded,
            "left_planted": self.plants.left,
            "right_planted": self.plants.right,
            "contact_source": self.plants.source,
            "collect_checked": self.collect_checked,
            "collect_attempted": self.collect_attempted,
            "collect_failure_reason": self.collect_failure_reason,
            "collect_metrics": self.collect_metrics,
            "left_x": round(float(points["left"]["ankle"][0]), 5),
            "left_y": round(float(points["left"]["ankle"][1]), 5),
            "left_z": round(float(points["left"]["ankle"][2]), 5),
            "right_x": round(float(points["right"]["ankle"][0]), 5),
            "right_y": round(float(points["right"]["ankle"][1]), 5),
            "right_z": round(float(points["right"]["ankle"][2]), 5),
            "left_slip_m": round(self.plants.segment_m["left"], 5),
            "right_slip_m": round(self.plants.segment_m["right"], 5),
            "stance_width_m": round(width, 5),
            "stop_requested_s": self.stop_requested_s,
            "last_plant_s": self.last_plant_s,
            "settled_s": self.settled_s,
            "event": self._event,
            "settle_seq": self.settle_seq,
            "move_id": self.move_id,
            "contacts_available": bool(obs.get("contacts_available", False)),
            "contact_fallback": self.contact_fallback,
            "event": self._event,
        }
        if self.log is not None:
            self.log.add(row)
        gait = {
            "mode": self.travel_mode or self.mode or "",
            "phase": self.phase,
            "contacts_available": row["contacts_available"],
            "contact_source": self.plants.source,
            "collect_checked": self.collect_checked,
            "collect_attempted": self.collect_attempted,
            "collect_failure_reason": self.collect_failure_reason,
            "collect_metrics": self.collect_metrics,
            "feet": {
                "left": _foot_payload(points["left"], self.plants.left, self.plants.segment_m["left"]),
                "right": _foot_payload(points["right"], self.plants.right, self.plants.segment_m["right"]),
            },
            "stance_width_m": row["stance_width_m"],
            "commanded_speed_mps": commanded,
            "actual_speed_mps": row["actual_speed_mps"],
            "settle_seq": self.settle_seq,
            "move_id": self.move_id,
            "stop_requested_s": self.stop_requested_s,
            "last_plant_s": self.last_plant_s,
            "settled_s": self.settled_s,
            "contact_fallback": self.contact_fallback,
            "left_slip_m": row["left_slip_m"],
            "right_slip_m": row["right_slip_m"],
        }
        return Action(
            phase=self.phase,
            walk=walk,
            play=play,
            begin_arrival=begin_arrival,
            pose=None if pose_out is None else np.array(pose_out, dtype=np.float64, copy=True),
            seed=seed,
            prime_walk=prime_walk,
            facing=facing_vec,
            gait=gait,
        )


def _feet(pose, parents, names):
    points = foot_points(pose, parents, names)
    return (
        {"left": points["left"]["ankle"], "right": points["right"]["ankle"]},
        None,
    )


def _foot_payload(parts, planted: bool, slip: float) -> dict:
    ankle = parts["ankle"]
    return {
        "x": round(float(ankle[0]), 5),
        "y": round(float(ankle[1]), 5),
        "z": round(float(ankle[2]), 5),
        "toe_z": round(float(parts["toe"][2]), 5),
        "planted": bool(planted),
        "slip_m": round(float(slip), 5),
    }
