import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import gait_plan
from click_planner import plan_click_move, stop_distance


class _ProceduralFlag:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self._prev = None

    def __enter__(self):
        self._prev = gait_plan.USE_PROCEDURAL_STEP
        gait_plan.USE_PROCEDURAL_STEP = self.enabled
        return self

    def __exit__(self, *_exc):
        gait_plan.USE_PROCEDURAL_STEP = self._prev


class ClickControllerTests(unittest.TestCase):
    def test_near_goal_does_not_creep(self):
        decision = plan_click_move(0.05, 0.0)
        self.assertTrue(decision.stop)
        self.assertEqual(decision.input_strength, 0.0)
        self.assertEqual(decision.mode, "micro")

    def test_short_distance_is_not_a_slow_walk(self):
        with _ProceduralFlag(True):
            decision = plan_click_move(0.4, 0.2)
            self.assertTrue(decision.stop)
            self.assertEqual(decision.input_strength, 0.0)
            self.assertNotEqual(decision.input_strength, 0.12)

    def test_procedural_off_keeps_full_walk_for_short_distance(self):
        with _ProceduralFlag(False):
            decision = plan_click_move(0.4, 0.2)
            self.assertFalse(decision.stop)
            self.assertEqual(decision.input_strength, 1.0)
            self.assertEqual(decision.mode, "walk")

    def test_long_walk_uses_the_full_blend_until_the_last_step(self):
        with _ProceduralFlag(True):
            far = plan_click_move(8.0, 2.3)
            self.assertFalse(far.stop)
            self.assertEqual(far.input_strength, 1.0)
            self.assertEqual(far.mode, "walk")
            near = plan_click_move(0.4, 2.3)
            self.assertTrue(near.stop)
            self.assertEqual(near.input_strength, 0.0)

    def test_stop_window_does_not_grow_with_speed(self):
        self.assertEqual(stop_distance(0.3), stop_distance(2.4))
        self.assertEqual(stop_distance(99), stop_distance(0.0))

    def test_rejects_invalid_inputs(self):
        for value in (-1, float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    plan_click_move(value, 0.0)
                with self.assertRaises(ValueError):
                    stop_distance(value)


if __name__ == "__main__":
    unittest.main()
