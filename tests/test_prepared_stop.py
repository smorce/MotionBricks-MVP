"""未一致でも停止生成を試す新実験の契約。"""
import copy
import sys
import unittest
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from prepared_stop_selector import select_prepared_stop
from visual_stop_selector import load_candidates
from locomotion_cycle import LocomotionCycle, STOP_FAILED


class PreparedStopTests(unittest.TestCase):
    def test_near_rejected_preview_emits_a_walk_frame_before_next_preview(self):
        from test_gait import standing_pose, observe
        from unittest.mock import patch
        cycle = LocomotionCycle(log=None)
        cycle.preview_stops = True; cycle.stop_mode = 'prepared'
        cycle.begin_move([.14, 0], True, 1)
        cycle.route_direction = np.array([1., 0.])
        cycle.visual_selection = dict(status='experimental', action='stop')
        pose, _, _ = standing_pose()
        self.assertTrue(cycle.reject_stop_preview(pose))
        with patch('gait_plan.USE_PROCEDURAL_STEP', False):
            action = cycle.tick(observe(pose))
        self.assertTrue(action.walk)
        self.assertFalse(action.begin_final_stop)

    def test_slow_root_sway_does_not_become_a_travel_direction(self):
        from test_gait import standing_pose
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.stop_mode = 'prepared'
        cycle.begin_move([0, 2], True, 1)
        for i in range(30):
            pose[0, 0] = i*.002
            cycle._update_course(pose, {})
        self.assertIsNone(cycle.course_direction)

    def test_fast_walk_previews_f001_before_braking_distance_is_lost(self):
        state = self.unseen()
        state['speed_mps'] = 2.
        result = select_prepared_stop(state, 1.15, self.rows)
        self.assertEqual(result['action'], 'stop')

    def test_walking_compensates_measured_heading_before_stop_window(self):
        from test_gait import standing_pose
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([0, 1], True, 1)
        cycle.stop_mode = 'prepared'
        cycle.course_direction = np.array([.1, np.sqrt(.99), 0.])
        cycle.command_direction = np.array([0., 1., 0.])
        cycle._update_course(pose, {})
        self.assertLess(cycle.command_direction[0], 0.)

    def test_rejected_prepared_preview_advances_walk_without_recovery_step(self):
        from test_gait import standing_pose
        cycle = LocomotionCycle(log=None)
        cycle.preview_stops = True
        cycle.stop_mode = 'prepared'
        cycle.begin_move([.8, 0], True, 1)
        cycle.route_direction = np.array([1., 0.])
        pose, _, _ = standing_pose()
        self.assertTrue(cycle.reject_stop_preview(pose))
        self.assertEqual(cycle.phase, 'moving')
        self.assertFalse(cycle.final_stop_frames)
        self.assertEqual(cycle.stop_retry_count, 0)

    def test_prepared_stop_waits_for_cross_track_alignment(self):
        from test_gait import standing_pose, observe
        from unittest.mock import patch
        for lateral, stopping in ((.08, False), (.04, True)):
            with self.subTest(lateral=lateral):
                cycle = LocomotionCycle(log=None)
                cycle.stop_mode = 'prepared'
                cycle.begin_move([.5, lateral], True, 1)
                cycle.course_direction = np.array([1., 0., 0.])
                cycle.visual_selection = dict(status='experimental', action='stop')
                pose, _, _ = standing_pose()
                with patch('gait_plan.USE_PROCEDURAL_STEP', False):
                    action = cycle.tick(observe(pose))
                self.assertEqual(action.begin_final_stop, stopping)
                self.assertEqual(action.walk, not stopping)
                np.testing.assert_allclose(cycle.goal[:2], [.5, lateral])
                if stopping:
                    np.testing.assert_allclose(cycle.final_stop_goal[:2], [.5, 0.])

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

    def test_current_history_is_shared_between_reviewed_and_fallback_matching(self):
        from unittest.mock import patch
        from visual_stop_selector import travel_relative_history
        state = self.unseen()
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row['reference_history'] = travel_relative_history(row['context'])
        with patch('visual_stop_selector.travel_relative_history', wraps=travel_relative_history) as matching, \
             patch('prepared_stop_selector.travel_relative_history', wraps=travel_relative_history) as current:
            select_prepared_stop(state,.59,rows)
        self.assertEqual(current.call_count,1)
        self.assertFalse(any(call.args[0] is state for call in matching.call_args_list))
