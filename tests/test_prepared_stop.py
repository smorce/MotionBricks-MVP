"""未一致でも停止生成を試す新実験の契約。"""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from prepared_stop_selector import select_prepared_stop
from visual_stop_selector import load_candidates
from locomotion_cycle import LocomotionCycle, STOP_FAILED


class PreparedStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_candidates()

    def unseen(self):
        state = copy.deepcopy(self.rows[0]['context'])
        state['speed_mps'] = 0
        state['contacts'] = [1, 1, 1, 1]
        return state

    def test_unmatched_state_prepares_early(self):
        result = select_prepared_stop(self.unseen(), 1.1, self.rows)
        self.assertEqual(result['action'], 'walk')
        self.assertEqual(result['status'], 'preparing')

    def test_unmatched_state_generates_a_once_before_fifteen_cm(self):
        result = select_prepared_stop(self.unseen(), .59, self.rows)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['status'], 'experimental')
        self.assertEqual(result['candidate']['mode'], 'A')
        self.assertFalse(result['candidate']['pinned'])
        self.assertEqual(result['human_rating'], 'unknown')
        self.assertEqual(result['target_pose_distance_m'], .59)

    def test_short_click_also_generates_without_retargeting_destination(self):
        result = select_prepared_stop(self.unseen(), .3, self.rows)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['target_pose_distance_m'], .3)

    def test_reviewed_condition_can_start_twelve_cm_before_x(self):
        result = select_prepared_stop(self.rows[0]['context'], 1.1, self.rows)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['x_m'], 1)

    def test_failed_single_attempt_never_enters_retry_search(self):
        cycle = LocomotionCycle(log=None)
        cycle.note_final_stop(None, dict(accepted=False, single_attempt=True))
        self.assertEqual(cycle.phase, STOP_FAILED)
