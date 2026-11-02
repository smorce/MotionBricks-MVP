"""目視評価の状態境界と距離選択を検証する。"""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from visual_stop_selector import load_candidates, select_stop


class VisualStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_candidates()

    def test_only_eleven_reviewed_pairs(self):
        self.assertEqual(len(self.rows), 11)
        self.assertTrue(all(r['review']['mark'] == 'good' for r in self.rows))

    def test_exact_state_and_short_distance(self):
        row = self.rows[0]
        result = select_stop(row['context'], .15, self.rows)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['x_m'], .15)
        self.assertEqual(result['human_rating'], 'unknown')

    def test_unseen_speed_is_unknown(self):
        state = copy.deepcopy(self.rows[0]['context'])
        state['speed_mps'] = 9
        self.assertEqual(select_stop(state, .3, self.rows)['status'], 'unknown')

    def test_too_short_does_not_compress(self):
        self.assertEqual(select_stop(self.rows[0]['context'], .02, self.rows)['status'], 'unknown')

    def test_missing_history_is_unknown(self):
        state = dict(self.rows[0]['context'], recent_poses=[])
        self.assertEqual(select_stop(state, .3, self.rows)['status'], 'unknown')

    def test_world_translation_preserves_state_similarity(self):
        state = copy.deepcopy(self.rows[0]['context'])
        state['root'][0] += 5
        for pose in state['recent_poses']:
            pose[0][0] += 5
        self.assertEqual(select_stop(state, .15, self.rows)['status'], 'matched')

    def test_same_gait_in_another_world_heading_matches(self):
        from quats import quat_mul
        import numpy as np
        state = copy.deepcopy(self.rows[0]['context'])
        rotation = np.array([0., 0., np.sin(np.pi/4), np.cos(np.pi/4)])
        state['direction'] = [-state['direction'][1], state['direction'][0]]
        for pose in state['recent_poses']:
            x, y = pose[0][:2]
            pose[0][:2] = [-y, x]
            pose[0][3:] = quat_mul(rotation, np.asarray(pose[0][3:])).tolist()
        self.assertEqual(select_stop(state, .15, self.rows)['status'], 'matched')
