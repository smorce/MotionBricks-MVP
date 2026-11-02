"""異なる移動要求へ停止距離を引き継がない。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from locomotion_cycle import LocomotionCycle


class StopHistoryTests(unittest.TestCase):
    def test_new_move_invalidates_unqualified_stop_distance(self):
        for distance in (.25, .5):
            with self.subTest(distance=distance):
                cycle = LocomotionCycle(log=None)
                cycle.last_stop_distance_m = distance
                cycle.begin_move([.3, 0], True, 2)
                self.assertEqual(cycle.last_stop_distance_m, 0)
