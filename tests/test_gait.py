"""踏み出し、接地、停止の回帰。GPU は使わない。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import gait_plan
from foot_plant import PlantState, stance_width_m
from gait_log import GaitLog
from gait_plan import classify_distance, walk_command_scale
from locomotion_cycle import SETTLED, WAITING, LocomotionCycle
from soma_skeleton import SOMA_JOINT_NAMES, soma_parents
from step_cycle import advance_step, begin_step, foot_points, fk


class _ProceduralFlag:
    """テスト中だけ手続き踏み出しの有無を切り替える。"""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self._prev = None

    def __enter__(self):
        self._prev = gait_plan.USE_PROCEDURAL_STEP
        gait_plan.USE_PROCEDURAL_STEP = self.enabled
        return self

    def __exit__(self, *_exc):
        gait_plan.USE_PROCEDURAL_STEP = self._prev


def standing_pose():
    """膝が前に出た立ち姿勢。脚は伸ばし切らない。"""
    pose = np.zeros((len(SOMA_JOINT_NAMES), 7), dtype=np.float64)
    pose[:, 6] = 1.0
    pose[0, :3] = [0.0, 0.0, 0.92]
    index = {name: i for i, name in enumerate(SOMA_JOINT_NAMES)}
    pose[index["LeftLeg"], :3] = [0.0, 0.12, -0.05]
    pose[index["LeftShin"], :3] = [0.22, 0.0, -0.28]
    pose[index["LeftFoot"], :3] = [-0.16, 0.0, -0.32]
    pose[index["LeftToeBase"], :3] = [0.08, 0.0, -0.02]
    pose[index["RightLeg"], :3] = [0.0, -0.12, -0.05]
    pose[index["RightShin"], :3] = [0.22, 0.0, -0.28]
    pose[index["RightFoot"], :3] = [-0.16, 0.0, -0.32]
    pose[index["RightToeBase"], :3] = [0.08, 0.0, -0.02]
    return pose, soma_parents(), list(SOMA_JOINT_NAMES)


def observe(pose, speed=0.0, contacts=None, available=False):
    return {
        "pose": pose,
        "dt": 1 / 60,
        "actual_speed": speed,
        "contacts": contacts,
        "contacts_available": available,
        "playback": "GENERATED",
        "official_state": "Locomotion",
        "facing": np.array([1.0, 0.0, 0.0]),
    }


class FootPlantTests(unittest.TestCase):
    def test_clip_zero_contacts_are_unavailable_not_airborne(self):
        plants = PlantState()
        plants.update(
            contacts=np.zeros(4),
            heights=np.array([0.02, 0.02, 0.02, 0.02]),
            speeds=np.zeros(4),
            points={"left": np.zeros(3), "right": np.array([0.0, -0.2, 0.0])},
            contacts_available=False,
            ground_z=0.0,
        )
        self.assertEqual(plants.source, "geometry")
        self.assertTrue(plants.left and plants.right)

    def test_high_fast_foot_is_not_planted_even_with_a_high_contact_value(self):
        plants = PlantState()
        plants.update(
            contacts=np.array([0.95, 0.95, 0.1, 0.1]),
            heights=np.array([0.18, 0.16, 0.02, 0.02]),
            speeds=np.array([0.4, 0.4, 0.0, 0.0]),
            points={"left": np.array([0.2, 0.1, 0.18]), "right": np.array([0.0, -0.1, 0.02])},
            contacts_available=True,
            ground_z=0.0,
        )
        self.assertFalse(plants.left)
        self.assertTrue(plants.right)

    def test_slip_accumulates_only_while_planted(self):
        plants = PlantState()
        plants.update(
            contacts=None,
            heights=np.zeros(4),
            speeds=np.zeros(4),
            points={"left": np.zeros(3), "right": np.array([0.0, -0.2, 0.0])},
            contacts_available=False,
            ground_z=0.0,
        )
        plants.update(
            contacts=None,
            heights=np.zeros(4),
            speeds=np.zeros(4),
            points={"left": np.array([0.03, 0.0, 0.0]), "right": np.array([0.0, -0.2, 0.0])},
            contacts_available=False,
            ground_z=0.0,
        )
        self.assertGreater(plants.segment_m["left"], 0.02)
        self.assertLess(plants.segment_m["right"], 1e-8)
        plants.update(
            contacts=None,
            heights=np.array([0.2, 0.2, 0.0, 0.0]),
            speeds=np.array([0.5, 0.5, 0.0, 0.0]),
            points={"left": np.array([0.4, 0.0, 0.2]), "right": np.array([0.0, -0.2, 0.0])},
            contacts_available=False,
            ground_z=0.0,
        )
        self.assertFalse(plants.left)
        self.assertEqual(plants.segment_m["left"], 0.0)
        self.assertGreater(plants.worst_m["left"], 0.02)


class GaitPlanTests(unittest.TestCase):
    def test_distance_bands_and_full_walk_input(self):
        reach = 0.55
        with _ProceduralFlag(True):
            self.assertEqual(classify_distance(0.05, reach).mode, "micro")
            self.assertEqual(classify_distance(0.30, reach).mode, "short_step")
            # 届く一歩が 0.55m なので、0.60m は一歩では覆えない。
            self.assertEqual(classify_distance(0.60, reach).mode, "few_steps")
            self.assertEqual(classify_distance(0.50, reach).mode, "short_step")
            self.assertEqual(classify_distance(1.0, reach).mode, "few_steps")
            self.assertEqual(classify_distance(2.0, reach).mode, "walk")
        self.assertEqual(walk_command_scale("walk"), 1.0)
        self.assertEqual(walk_command_scale("short_step"), 0.0)
        self.assertNotIn(round(walk_command_scale("short_step"), 2), (0.12,))

    def test_short_edge_follows_reach_without_a_hard_pop(self):
        with _ProceduralFlag(True):
            near = classify_distance(0.50, 0.48)
            far = classify_distance(0.50, 0.70)
            self.assertEqual(near.mode, "few_steps")
            self.assertEqual(far.mode, "short_step")
            self.assertLess(abs(near.short_edge_m - far.short_edge_m), 0.2)

    def test_procedural_off_classifies_non_micro_as_walk(self):
        reach = 0.55
        with _ProceduralFlag(False):
            self.assertEqual(classify_distance(0.05, reach).mode, "micro")
            self.assertEqual(classify_distance(0.30, reach).mode, "walk")
            self.assertEqual(classify_distance(0.60, reach).mode, "walk")
            self.assertEqual(classify_distance(2.0, reach).mode, "walk")


class StepTests(unittest.TestCase):
    def test_support_foot_stays_and_swing_foot_lifts(self):
        pose, parents, names = standing_pose()
        start = foot_points(pose, parents, names)
        state = begin_step(
            pose, parents, names, kind="travel", direction_xy=np.array([1.0, 0.0]),
            distance_m=0.30, swing="right", speed_mps=0.0,
        )
        support = start["left"]["ankle"].copy()
        peak = float(start["right"]["ankle"][2])
        root0 = pose[0, 0]
        early_root = root0
        for frame in range(40):
            pose, state = advance_step(parents, names, state, 1 / 60)
            now = foot_points(pose, parents, names)
            peak = max(peak, float(now["right"]["ankle"][2]))
            slip = float(np.linalg.norm(now["left"]["ankle"][:2] - support[:2]))
            self.assertLess(slip, 0.02, f"frame {frame}")
            if state.u < 0.18:
                early_root = pose[0, 0]
                self.assertLess(abs(pose[0, 0] - root0), 0.03)
                self.assertLess(abs(now["right"]["ankle"][2] - start["right"]["ankle"][2]), 0.01)
        self.assertGreater(peak, start["right"]["ankle"][2] + 0.03)
        self.assertGreater(early_root, root0 - 0.001)
        self.assertTrue(state.done)
        self.assertGreater(pose[0, 0], root0 + 0.15)

    def test_unreachable_root_travel_is_shortened(self):
        pose, parents, names = standing_pose()
        state = begin_step(
            pose, parents, names, kind="travel", direction_xy=np.array([1.0, 0.0]),
            distance_m=3.0, swing="right", speed_mps=0.0,
        )
        support = foot_points(pose, parents, names)["left"]["ankle"][:2].copy()
        for _ in range(80):
            pose, state = advance_step(parents, names, state, 1 / 60)
            if state.done:
                break
        moved = float(pose[0, 0])
        self.assertLess(moved, 1.2)
        landed = foot_points(pose, parents, names)["left"]["ankle"]
        self.assertLess(float(np.linalg.norm(landed[:2] - support)), 0.02)

    def test_coordinate_roundtrip_matches_the_browser_root(self):
        # placeRoot: (x - restx + ox, z - restz + floor, -y + resty + oz)
        rest = np.array([0.1, -0.2, 0.9])
        spawn = np.array([1.0, 3.0])
        floor = 0.05
        point = np.array([0.4, 0.2, 0.02])
        three = np.array([
            point[0] - rest[0] + spawn[0],
            point[2] - rest[2] + floor,
            -point[1] + rest[1] + spawn[1],
        ])
        back = np.array([
            three[0] + rest[0] - spawn[0],
            -(three[2] - rest[1] - spawn[1]),
            three[1] + rest[2] - floor,
        ])
        np.testing.assert_allclose(back, point, atol=1e-9)


class CycleTests(unittest.TestCase):
    def _run(self, distance, hold=True, speed_walk=False, procedural=True):
        pose, _parents, _names = standing_pose()
        log = GaitLog()
        cycle = LocomotionCycle(log)
        cycle.begin_move((distance, 0.0), hold, move_id=1)
        poses = []
        actions = []
        with _ProceduralFlag(procedural):
            for _ in range(240):
                action = cycle.tick(observe(pose, speed=2.3 if action_walk(actions) else 0.0))
                actions.append(action)
                if speed_walk and action.walk:
                    pose = pose.copy()
                    pose[0, 0] += 2.3 / 60
                elif action.walk and not procedural:
                    pose = pose.copy()
                    pose[0, 0] += min(2.3 / 60, max(0.0, distance - pose[0, 0]))
                elif action.pose is not None:
                    pose = action.pose
                poses.append(pose.copy())
                if cycle.phase == SETTLED and not action.begin_arrival:
                    break
        return cycle, actions, poses, log

    def test_short_step_arrives_without_sliding_the_stance_foot(self):
        cycle, actions, poses, log = self._run(0.30, procedural=True)
        self.assertEqual(cycle.phase, SETTLED)
        self.assertLess(abs(poses[-1][0, 0] - 0.30), 0.08)
        self.assertTrue(any(item.pose is not None and not item.walk for item in actions))
        self.assertFalse(any(item.walk for item in actions))
        width0 = _width(poses[0])
        width1 = _width(poses[-1])
        self.assertLess(abs(width1 - width0), 0.02)
        planted = [row for row in log.snapshot() if row["event"] in ("plant", "micro") or row["phase"] == "final_step"]
        self.assertTrue(planted)
        # 支持足の接地区間だけを見る。遊脚は滑り計測から外れる。
        steps = [row for row in log.snapshot() if row["phase"] == "final_step"]
        self.assertTrue(any(row["left_planted"] != row["right_planted"] for row in steps))
        support_slip = max(max(row["left_slip_m"], row["right_slip_m"]) for row in log.snapshot())
        self.assertLess(support_slip, 0.02)

    def test_walk_uses_full_input_then_a_final_step(self):
        pose, _p, _n = standing_pose()
        cycle = LocomotionCycle(GaitLog())
        cycle.begin_move((4.0, 0.0), True, 2)
        saw_walk = False
        saw_step = False
        with _ProceduralFlag(True):
            for _ in range(180):
                action = cycle.tick(observe(pose, speed=2.3))
                if action.walk:
                    saw_walk = True
                    self.assertIsNone(action.pose)
                    pose = pose.copy()
                    pose[0, 0] += 2.3 / 60
                else:
                    self.assertIsNotNone(action.pose)
                    saw_step = True
                    pose = action.pose
                if cycle.phase == SETTLED:
                    break
        self.assertTrue(saw_walk and saw_step)
        self.assertLess(abs(pose[0, 0] - 4.0), 0.10)
        self.assertEqual(cycle.phase, SETTLED)

    def test_procedural_off_uses_official_walk_without_step_cycle(self):
        cycle, actions, poses, log = self._run(4.0, procedural=False)
        self.assertEqual(cycle.phase, SETTLED)
        self.assertTrue(any(item.walk for item in actions))
        self.assertIsNone(cycle.step)
        self.assertFalse(any(row["phase"] == "final_step" for row in log.snapshot()))
        self.assertLess(abs(poses[-1][0, 0] - 4.0), 0.12)
        self.assertTrue(
            any(row["event"] in ("plant", "contact_timeout") for row in log.snapshot())
        )

    def test_procedural_off_short_goal_never_builds_a_step(self):
        cycle, actions, poses, _log = self._run(0.30, procedural=False)
        self.assertEqual(cycle.phase, SETTLED)
        self.assertIsNone(cycle.step)
        self.assertTrue(any(item.walk for item in actions))
        self.assertFalse(any(
            item.pose is not None and item.phase == "final_step" for item in actions
        ))
        self.assertLess(abs(poses[-1][0, 0] - 0.30), 0.12)

    def test_settled_pose_survives_a_speed_spike_and_a_late_frame(self):
        cycle, _actions, poses, _log = self._run(0.30, procedural=True)
        frozen = poses[-1].copy()
        spiked = frozen.copy()
        spiked[0, 0] += 0.4
        spiked[22, 3:7] = [0, 0, 0.4, 0.9]
        for _ in range(30):
            action = cycle.tick(observe(spiked, speed=1.8))
            self.assertEqual(action.phase, SETTLED)
            self.assertFalse(action.walk)
            np.testing.assert_allclose(action.pose[0, :3], frozen[0, :3], atol=1e-6)
            np.testing.assert_allclose(action.pose[22, 3:7], frozen[22, 3:7], atol=1e-6)

    def test_new_move_replaces_the_previous_step(self):
        pose, _p, _n = standing_pose()
        cycle = LocomotionCycle(GaitLog())
        with _ProceduralFlag(True):
            cycle.begin_move((0.4, 0.0), True, 1)
            cycle.tick(observe(pose))
            cycle.begin_move((0.25, 0.4), True, 2)
            self.assertEqual(cycle.move_id, 2)
            self.assertEqual(cycle.step, None)
            action = cycle.tick(observe(pose))
            self.assertEqual(action.gait["move_id"], 2)

    def test_arrival_pose_waits_and_runs_once(self):
        pose, _p, _n = standing_pose()
        cycle = LocomotionCycle(GaitLog())
        with _ProceduralFlag(True):
            cycle.begin_move((0.30, 0.0), False, 7)
            action = None
            for _ in range(180):
                action = cycle.tick(observe(pose if action is None or action.pose is None else action.pose))
                if action.pose is not None:
                    pose = action.pose
                if cycle.phase == SETTLED:
                    break
            self.assertEqual(cycle.phase, SETTLED)
            waiting = cycle.tick(observe(pose, speed=0.0))
            self.assertFalse(waiting.begin_arrival)
            cycle.note_pose_choice("F043")
            started = cycle.tick(observe(pose))
            self.assertTrue(started.begin_arrival)
            cycle.note_arrival(True, 0.4)
            again = cycle.tick(observe(pose))
            self.assertFalse(again.begin_arrival)
            self.assertEqual(again.phase, "pose_transition")

    def test_hold_stance_never_starts_arrival(self):
        cycle, _a, poses, _l = self._run(0.30, hold=True, procedural=True)
        cycle.note_pose_choice("F043")
        action = cycle.tick(observe(poses[-1]))
        self.assertFalse(action.begin_arrival)
        self.assertEqual(action.phase, SETTLED)

    def test_missing_contacts_still_settle(self):
        cycle, actions, _poses, log = self._run(0.30, procedural=True)
        self.assertEqual(cycle.phase, SETTLED)
        self.assertTrue(any(row["contact_source"] == "geometry" for row in log.snapshot()))
        self.assertTrue(actions[-1].gait["contact_fallback"] or actions[-1].gait["contact_source"] == "geometry")


def action_walk(actions) -> bool:
    return bool(actions) and actions[-1].walk


def _width(pose):
    _pos, _rot = fk(pose, soma_parents())
    names = list(SOMA_JOINT_NAMES)
    points = foot_points(pose, soma_parents(), names)
    return stance_width_m(points["left"]["ankle"], points["right"]["ankle"], np.array([1.0, 0.0, 0.0]))


if __name__ == "__main__":
    unittest.main()
class CollectSyncTests(unittest.TestCase):
    def test_stale_ready_is_ignored(self):
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([0, 0], True, 8)
        pose, _, _ = standing_pose()
        cycle.tick(observe(pose))
        self.assertFalse(cycle.note_upper_idle_ready(7, cycle.settle_seq))
        self.assertTrue(cycle.note_upper_idle_ready(8, cycle.settle_seq))

    def test_ready_timeout_does_not_retry(self):
        cycle = LocomotionCycle(log=None)
        pose, _, _ = standing_pose()
        cycle.begin_move([0, 0], True, 8)
        for _ in range(165):
            cycle.tick(observe(pose))
        self.assertTrue(cycle.collect_checked)
        self.assertFalse(cycle.collect_attempted)
        self.assertEqual(cycle.phase, SETTLED)
    def test_wide_stance_attempts_once_and_failure_preserves_pose(self):
        from unittest.mock import patch
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([0, 0], True, 8)
        cycle.tick(observe(pose))
        original = cycle.settled_pose.copy()
        seq = cycle.settle_seq
        cycle.note_upper_idle_ready(8, seq)
        with patch('locomotion_cycle.stance', return_value=(.4, .2)):
            actions = [cycle.tick(observe(pose)) for _ in range(54)]
        self.assertEqual(sum(a.begin_collect for a in actions), 1)
        cycle.note_collect(None, {'accepted':False,'reason':'Rejected'}, 8, seq)
        for _ in range(180):
            self.assertFalse(cycle.tick(observe(pose)).begin_collect)
        self.assertEqual(cycle.settle_seq, seq)
        np.testing.assert_array_equal(cycle.settled_pose, original)

    def test_success_commits_final_pose_and_new_move_cancels_old_result(self):
        from unittest.mock import patch
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([0, 0], True, 8)
        cycle.tick(observe(pose))
        seq = cycle.settle_seq
        cycle.note_upper_idle_ready(8, seq)
        with patch('locomotion_cycle.stance', return_value=(.4, .2)):
            for _ in range(54):
                cycle.tick(observe(pose))
        final = pose.copy()
        final[0, 0] += .01
        cycle.note_collect([pose.copy(), final], {'accepted':True}, 8, seq)
        cycle.tick(observe(pose))
        cycle.tick(observe(pose))
        self.assertEqual(cycle.settle_seq, seq+1)
        np.testing.assert_array_equal(cycle.settled_pose, final)
        cycle.begin_move([1, 0], True, 9)
        cycle.note_collect([final], {'accepted':True}, 8, seq)
        self.assertEqual(cycle.phase, 'moving')
        self.assertIsNone(cycle.settled_pose)
