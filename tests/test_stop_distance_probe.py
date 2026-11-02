"""状態別の距離探索と目視評価の契約。"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from stop_distance_probe import recommendations, specifications, state_features


class ProbeTests(unittest.TestCase):
    def test_initial_matrix(self):
        specs = specifications()
        self.assertEqual(len(specs), 36)
        self.assertEqual(len({s['id'] for s in specs}), 36)

    def test_human_cannot_override_safety(self):
        candidates = [dict(id='A', metrics=dict(accepted=False)),
                      dict(id='B', metrics=dict(accepted=True)),
                      dict(id='C', metrics=dict(accepted=True))]
        result = recommendations(candidates, {'A':'good', 'B':'bad'})
        self.assertEqual(result['safe_ids'], ['B', 'C'])
        self.assertEqual(result['recommended_ids'], [])
        self.assertEqual(result['unreviewed_ids'], ['C'])

    def test_velocity_uses_interval_before_newest_pose(self):
        import numpy as np
        history = np.zeros((4, 1, 7))
        history[:, 0, 0] = [0, .01, .02, .03]
        replay = dict(history=history.tolist(), pose=history[-1].tolist(),
                      delta_times=[.02, .02, .02, 0],
                      metadata=dict(support='left', ground={}, contacts=[1, 1, 0, 0]))
        result = state_features(replay)
        self.assertAlmostEqual(result['speed_mps'], .5)
        self.assertEqual(result['direction'], [1., 0.])

    def test_safe_natural_candidates_rank_by_slip_after_error(self):
        candidates = [dict(id=i, metrics=dict(accepted=True, arrival_error_m=.01,
                      quality=dict(support_slide_m=slip))) for i, slip in [('A', .02), ('B', .01)]]
        self.assertEqual(recommendations(candidates, {'A':'good', 'B':'good'})['recommended_ids'], ['B', 'A'])
