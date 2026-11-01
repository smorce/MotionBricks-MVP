import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from bvh_io import parse_bvh
from locomotion_policy import (
    ARRIVAL_RADIUS,
    MoveState,
    movement_mode,
    on_move,
    on_pose_choice,
    plan_motion,
    runtime_to_three,
    three_to_runtime,
)
from quats import quat_from_axis_angle, quat_to_mat, rotate_vec
from soma_skeleton import SOMA_JOINT_NAMES


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "F001.bvh"
SOMA_BVH = Path(r"C:\Users\kbpsh\src\motionbricks\assets\motions\soma\locomotion\idle\idle_loop_001__A268.bvh")


class QuatTests(unittest.TestCase):
    def test_x_rotation_lifts_y_to_z(self):
        q = quat_from_axis_angle(np.array([1.0, 0.0, 0.0]), math.pi / 2)
        lifted = rotate_vec(q, np.array([0.0, 1.0, 0.0]))
        self.assertAlmostEqual(lifted[2], 1.0, places=5)
        roundtrip = quat_to_mat(q)
        self.assertAlmostEqual(float(np.linalg.det(roundtrip)), 1.0, places=5)


class PolicyTests(unittest.TestCase):
    def test_coordinate_roundtrip(self):
        self.assertEqual(three_to_runtime(1.5, 2.0), (1.5, -2.0))
        self.assertEqual(runtime_to_three(1.5, -2.0, 0.9), (1.5, 0.9, 2.0))

    def test_near_click_walks_then_arrives(self):
        state = on_move(MoveState(), 1.0, 0.0)
        modes = self._travel(state)
        self.assertIn("walk", modes)
        self.assertNotIn("jog", modes)

    def test_far_click_jogs_then_walks(self):
        state = on_move(MoveState(), 4.0, 0.0)
        modes = self._travel(state)
        self.assertEqual(modes[0], "jog")
        self.assertIn("walk", modes)

    def test_reclick_replans_direction(self):
        state = on_move(MoveState(), 4.0, 0.0)
        state, plan = plan_motion(state, (0.0, 0.0), 10.0, 1 / 60)
        self.assertEqual(plan.kind, "locomote")
        state = on_move(state, 0.0, 4.0)
        self.assertIsNone(state.generated_direction)
        state, plan = plan_motion(state, (0.2, 0.0), 10.0, 1 / 60)
        self.assertEqual(plan.kind, "locomote")
        self.assertGreater(plan.direction[1], 0.5)

    def test_pose_choice_after_arrival_reopens_motion(self):
        state = on_move(MoveState(), 0.1, 0.0)
        state, plan = plan_motion(state, (0.1, 0.0), 10.0, 1 / 60)
        self.assertEqual(plan.kind, "arrive")
        state = on_pose_choice(state, "F043")
        self.assertTrue(state.is_moving)
        self.assertEqual(state.target_pose_id, "F043")

    def test_invalid_goal_is_ignored(self):
        state = on_move(MoveState(), math.nan, 0.0)
        self.assertIsNone(state.goal)

    def _travel(self, state: MoveState) -> list[str]:
        pos = np.zeros(2)
        modes = []
        dt = 1 / 60
        for _ in range(60 * 12):
            state, plan = plan_motion(state, (float(pos[0]), float(pos[1])), 10.0, dt)
            if plan.kind == "arrive":
                self.assertLessEqual(plan.distance, ARRIVAL_RADIUS + 1e-6)
                return modes
            if plan.kind == "locomote":
                modes.append(plan.mode)
                step = np.asarray(plan.direction[:2]) * plan.speed * dt
                pos += step
            elif state.is_moving and state.generated_direction is not None:
                pos += np.asarray(state.generated_direction) * (1.25 if state.last_mode == "walk" else 2.2) * dt
        self.fail("did not arrive")


class BvhTests(unittest.TestCase):
    def test_tiny_bvh(self):
        text = """HIERARCHY
ROOT Hips
{
  OFFSET 0 100 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation
  JOINT Spine
  {
    OFFSET 0 10 0
    CHANNELS 3 Zrotation Yrotation Xrotation
    End Site
    {
      OFFSET 0 10 0
    }
  }
}
MOTION
Frames: 1
Frame Time: 0.033333
0 100 0 0 90 0 0 0 0
"""
        clip = parse_bvh(text)
        self.assertEqual(clip.names, ["Hips", "Spine"])
        self.assertAlmostEqual(clip.local_translations[0, 1], 1.0, places=5)
        self.assertGreater(abs(clip.local_rotations[0, 1]), 0.1)

    def test_soma_joint_count(self):
        self.assertEqual(len(SOMA_JOINT_NAMES), 30)
        self.assertEqual(len(set(SOMA_JOINT_NAMES)), 30)

    @unittest.skipUnless(FIXTURE.exists(), "PoseLoom fixture is absent")
    def test_poseloom_fixture_parses(self):
        clip = parse_bvh(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(clip.names[0], "Hips")
        self.assertIn("LeftUpLeg", clip.names)
        self.assertEqual(clip.local_translations.shape[0], len(clip.names))


class ModeTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(movement_mode(1.0), "walk")
        self.assertEqual(movement_mode(3.0), "jog")


if __name__ == "__main__":
    unittest.main()
