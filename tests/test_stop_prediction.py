import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from stop_prediction import landing_horizon


class StopPredictionTests(unittest.TestCase):
    def test_descending_foot_uses_height_and_velocity(self):
        self.assertAlmostEqual(landing_horizon(.06, -.3, .5), .2)

    def test_rising_foot_uses_observed_step_period(self):
        self.assertAlmostEqual(landing_horizon(.06, .3, .4), .4)

    def test_grounded_foot_has_no_remaining_flight(self):
        self.assertEqual(landing_horizon(0, -.1, .5), 0)
