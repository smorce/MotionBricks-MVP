"""停止要求後の接地回復の回帰。"""
import unittest
from unittest.mock import patch

from test_gait import standing_pose, observe
from locomotion_cycle import LocomotionCycle, SETTLED


class StopContactTests(unittest.TestCase):
    def airborne(self):
        pose, _, names = standing_pose()
        from final_stop import calibrate_stop_ground
        ground = calibrate_stop_ground(pose, standing_pose()[1], names)
        pose[names.index('RightLeg'), 2] += .2
        cycle = LocomotionCycle(log=None)
        cycle.ground_calibration = ground
        cycle.begin_move([.07, 0], True, 1)
        return cycle, pose

    def test_wait_advances_walk_and_timeout_does_not_settle(self):
        cycle, pose = self.airborne()
        with patch('gait_plan.USE_PROCEDURAL_STEP', False):
            for _ in range(45):
                action = cycle.tick(observe(pose))
                self.assertTrue(action.walk)
                self.assertIsNone(action.pose)
                self.assertIsNone(cycle.settled_pose)
            for _ in range(3):
                action = cycle.tick(observe(pose))
                if action.begin_stop_recovery:
                    break
            self.assertFalse(action.walk)
            self.assertTrue(action.begin_stop_recovery)
            self.assertEqual(cycle.phase, 'contact_recovery')
            self.assertTrue(cycle.contact_fallback)

    def test_recovery_has_a_deadline_and_never_restarts_walk(self):
        cycle, pose = self.airborne()
        with patch('gait_plan.USE_PROCEDURAL_STEP', False):
            for _ in range(48):
                action = cycle.tick(observe(pose))
                if action.begin_stop_recovery:
                    break
            cycle.note_stop_recovery(True, .2)
            for _ in range(120):
                action = cycle.tick(observe(pose))
                self.assertFalse(action.walk)
                self.assertFalse(action.begin_stop_recovery)
            self.assertEqual(cycle.phase, 'stop_failed')
            self.assertIsNone(cycle.settled_pose)

    def test_recovery_landing_settles_and_new_move_clears_recovery(self):
        cycle, pose = self.airborne()
        for _ in range(48):
            action = cycle.tick(observe(pose))
            if action.begin_stop_recovery:
                break
        cycle.note_stop_recovery(True, .2)
        landed, _, _ = standing_pose()
        for _ in range(30):
            action = cycle.tick(observe(landed))
        self.assertEqual(action.phase, SETTLED)
        cycle.begin_move([3, 0], True, 2)
        self.assertTrue(cycle.tick(observe(landed)).walk)

    def test_failed_generation_does_not_report_arrival(self):
        cycle, pose = self.airborne()
        for _ in range(48):
            action = cycle.tick(observe(pose))
            if action.begin_stop_recovery:
                break
        cycle.note_stop_recovery(False, 0)
        action = cycle.tick(observe(pose))
        self.assertFalse(action.walk)
        self.assertFalse(action.play)
        self.assertFalse(action.begin_arrival)
        self.assertEqual(action.phase, 'stop_failed')

    def test_stop_remains_latched_after_overshoot_until_landing(self):
        cycle, pose = self.airborne()
        with patch('gait_plan.USE_PROCEDURAL_STEP', False):
            first = cycle.tick(observe(pose))
            pose[0, 0] = .3
            action = cycle.tick(observe(pose))
            self.assertEqual(action.phase, 'waiting_for_foot_contact')
            self.assertTrue((first.facing == action.facing).all())
            landed, _, _ = standing_pose()
            landed[0, 0] = .3
            for _ in range(3):
                action = cycle.tick(observe(landed))
            self.assertEqual(action.phase, SETTLED)

    def test_contact_observation_runs_once_per_tick(self):
        cycle, pose = self.airborne()
        with patch.object(cycle.plants, 'update', wraps=cycle.plants.update) as update:
            cycle.tick(observe(pose))
            self.assertEqual(update.call_count, 1)
