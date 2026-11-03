"""停止失敗後の待機移行は到着成功と区別する。"""
import unittest
import numpy as np
from locomotion_cycle import LocomotionCycle, STOP_FAILED
from test_gait import standing_pose, observe


class FailureRelaxationTests(unittest.TestCase):
    def test_blend_starts_at_hold_and_preserves_current_skeleton(self):
        from failure_relaxation import blend_from_hold
        pose, _, _ = standing_pose()
        target = pose.copy(); target[1:, :3] *= 1.1
        target[0, 0] += .03
        target[2, 3:] = [0., 0., 1., 0.]
        np.testing.assert_allclose(blend_from_hold(pose, target, 0), pose)
        end = blend_from_hold(pose, target, 1)
        np.testing.assert_allclose(end[1:, :3], pose[1:, :3])
        np.testing.assert_allclose(end[:, 3:], target[:, 3:])

    def failed(self):
        cycle = LocomotionCycle(log=None)
        cycle.stop_mode = 'prepared'
        cycle.begin_move([.04, 0], True, 1)
        cycle.note_final_stop(None, dict(accepted=False, single_attempt=True, reason='Rejected F001'))
        return cycle

    def test_prepared_failure_requests_relaxation_once(self):
        cycle = self.failed()
        pose, _, _ = standing_pose()
        action = cycle.tick(observe(pose))
        self.assertTrue(action.begin_failure_relaxation)
        self.assertEqual(cycle.phase, 'stop_relaxing')
        self.assertFalse(cycle.tick(observe(pose)).begin_failure_relaxation)
        self.assertEqual(cycle.stop_failure_reason, 'Rejected F001')

    def test_relaxation_ends_without_claiming_arrival(self):
        cycle = self.failed()
        pose, _, _ = standing_pose()
        cycle.tick(observe(pose))
        end = pose.copy(); end[0, 2] -= .01
        cycle.note_failure_relaxation([pose.copy(), end], {'accepted': True})
        cycle.tick(observe(pose))
        action = cycle.tick(observe(pose))
        self.assertEqual(cycle.phase, 'stop_relaxed')
        self.assertFalse(cycle.final_stop_metrics['accepted'])
        self.assertFalse(cycle.arrival_done)
        self.assertEqual(cycle.stop_failure_reason, 'Rejected F001')
        self.assertAlmostEqual(action.pose[0, 2], end[0, 2])
        cycle.begin_move([1, 0], True, 2)
        self.assertFalse(cycle.failure_relaxation_attempted)

    def test_failed_relaxation_holds_without_repeating_generation(self):
        cycle = self.failed()
        pose, _, _ = standing_pose()
        cycle.tick(observe(pose))
        cycle.note_failure_relaxation(None, {'accepted': False, 'reason': 'Idle transition failed'})
        action = cycle.tick(observe(pose))
        self.assertEqual(cycle.phase, STOP_FAILED)
        self.assertFalse(action.begin_failure_relaxation)
        self.assertEqual(cycle.stop_failure_reason, 'Rejected F001')

    def test_strict_visual_failure_keeps_its_existing_hold(self):
        cycle = self.failed(); cycle.stop_mode = 'visual'
        pose, _, _ = standing_pose()
        action = cycle.tick(observe(pose))
        self.assertEqual(cycle.phase, STOP_FAILED)
        self.assertFalse(action.begin_failure_relaxation)
