"""自然さの推測を採用拒否に使わず、最低限の異常を拒否する。"""
import copy
import unittest
import numpy as np
from prepared_stop_acceptance import evaluate_prepared_stop


class PreparedStopAcceptanceTests(unittest.TestCase):
    def valid(self):
        validation = dict(accepted=True,reason='',bone_lengths_valid=True,
            rotation_peak=dict(angle_rad=.1),checks={name:dict(passed=True)
                for name in ('bones','root','feet','knees','ankles','support','swing','idle','destination')})
        validation['checks']['swing']['landed'] = True
        return validation

    def test_small_arrival_needs_no_minimum_forward_progress(self):
        decision = evaluate_prepared_stop(self.valid(), .04, 'Stop recovery made insufficient progress')
        self.assertTrue(decision['accepted'])
        self.assertIn('progress', decision['warnings'])

    def test_posture_heuristics_remain_diagnostics(self):
        validation = self.valid(); validation['accepted'] = False
        for name in ('knees','ankles','support','swing','idle'):
            validation['checks'][name]['passed'] = False
        decision = evaluate_prepared_stop(validation, .03, '')
        self.assertTrue(decision['accepted'])
        self.assertEqual(set(decision['warnings']), {'knees','ankles','support','swing','idle'})

    def test_structural_floor_and_jump_failures_still_reject(self):
        for name in ('bones','root','feet'):
            validation = self.valid(); validation['checks'][name]['passed'] = False
            decision = evaluate_prepared_stop(validation, .03, '')
            self.assertFalse(decision['accepted'])
            self.assertIn(name, decision['hard_failures'])

    def test_joint_jump_and_original_destination_are_required(self):
        validation = self.valid(); validation['rotation_peak']['angle_rad'] = .36
        self.assertFalse(evaluate_prepared_stop(validation, .03, '')['accepted'])
        self.assertFalse(evaluate_prepared_stop(self.valid(), .051, '')['accepted'])
        self.assertFalse(evaluate_prepared_stop(self.valid(), float('nan'), '')['accepted'])

    def test_invalid_pose_or_missing_diagnostics_never_pass(self):
        self.assertFalse(evaluate_prepared_stop(dict(accepted=False,reason='Invalid stop motion'), .01, '')['accepted'])

    def test_airborne_terminal_pose_is_not_treated_as_a_completed_stop(self):
        validation = self.valid(); validation['checks']['swing']['landed'] = False
        decision = evaluate_prepared_stop(validation, .02, '')
        self.assertFalse(decision['accepted'])
        self.assertIn('terminal_contact', decision['hard_failures'])

    def test_policy_does_not_rewrite_original_diagnostics(self):
        validation = self.valid(); before = copy.deepcopy(validation)
        evaluate_prepared_stop(validation, .04, 'Stop recovery made insufficient progress')
        self.assertEqual(validation, before)

    def test_actual_pose_corruption_is_rejected_before_advisory_selection(self):
        from test_gait import standing_pose
        from final_stop import calibrate_stop_ground, validate_stop_motion
        pose, parents, names = standing_pose()
        ground = calibrate_stop_ground(pose, parents, names)
        for corruption in ('nan','bone','root_jump','rotation','floor'):
            frames = np.repeat(pose[None], 8, axis=0)
            if corruption == 'nan': frames[2, 0, 0] = np.nan
            elif corruption == 'bone': frames[:, names.index('LeftShin'), :3] *= 1.5
            elif corruption == 'root_jump': frames[2, 0, 0] += .1
            elif corruption == 'rotation': frames[2, 2, 3:] = [0, 0, 1, 0]
            elif corruption == 'floor': frames[:, 0, 2] -= .05
            validation = validate_stop_motion(frames, pose, np.array([0., 0.]), parents, names, ground)
            with self.subTest(corruption=corruption):
                self.assertFalse(evaluate_prepared_stop(validation, 0., '')['accepted'])
