import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from click_planner import ClickStopSettings, plan_click_move, stop_distance


class ClickControllerTests(unittest.TestCase):
    def test_near_goal_stops(self):
        d = plan_click_move(0.1, 0.0)
        self.assertTrue(d.stop)
        self.assertEqual(d.input_strength, 0.0)

    def test_fast_motion_stops_earlier(self):
        self.assertGreater(stop_distance(2.4), stop_distance(0.3))
        self.assertTrue(plan_click_move(1.3, 2.4).stop)
        self.assertFalse(plan_click_move(1.3, 0.3).stop)

    def test_strength_increases_farther_from_goal(self):
        near = plan_click_move(1.8, 0.2)
        far = plan_click_move(8.0, 0.2)
        self.assertFalse(near.stop)
        self.assertLess(near.input_strength, far.input_strength)
        self.assertAlmostEqual(far.input_strength, 1.0)

    def test_stops_never_warp_or_overshoot_via_coordinate_edit(self):
        d = plan_click_move(0.8, 2.0)
        self.assertTrue(d.stop)
        self.assertFalse(hasattr(d, 'corrected_position'))

    def test_extreme_speed_is_capped(self):
        self.assertEqual(stop_distance(99), ClickStopSettings().max_stop_distance_m)

    def test_reject_invalid_goals(self):
        for val in (-1, float('inf'), float('nan')):
            with self.subTest(value=val), self.assertRaises(ValueError):
                plan_click_move(val, 0.0)


if __name__ == '__main__':
    unittest.main()
