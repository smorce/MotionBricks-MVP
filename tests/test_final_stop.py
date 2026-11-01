import unittest
from unittest.mock import patch
import numpy as np
from types import SimpleNamespace
from unittest.mock import Mock
from test_gait import standing_pose, observe
from locomotion_cycle import LocomotionCycle, FINAL_STEP, SETTLED
from final_stop import build_stop_target, validate_stop_motion, validate_stop_progress, check_bone_lengths, calibrate_stop_ground


class FinalStopTests(unittest.TestCase):
    def test_airborne_start_uses_fixed_ground(self):
        rest, parents, names = standing_pose()
        ground = calibrate_stop_ground(rest, parents, names, floor_z=.1)
        airborne = rest.copy()
        airborne[0, 2] += .04
        frames = np.repeat(rest[None], 4, axis=0)
        metrics = validate_stop_motion(frames, airborne, [0, 0], parents, names, ground)
        self.assertTrue(metrics['accepted'], metrics)
        with patch('final_stop.overlay_pose', return_value=rest.copy()):
            target = build_stop_target(airborne, [0, 0], parents, names, ground)
        self.assertAlmostEqual(target[0, 2], rest[0, 2])

    def test_penetration_details(self):
        rest, parents, names = standing_pose()
        ground = calibrate_stop_ground(rest, parents, names, floor_z=.1)
        frames = np.repeat(rest[None], 4, axis=0)
        frames[1:, 0, 2] -= .028
        metrics = validate_stop_motion(frames, rest, [0, 0], parents, names, ground)
        self.assertEqual(metrics['reason'], 'Stop foot penetrated ground')
        self.assertEqual(metrics['penetration_frame'], 1)
        self.assertEqual(metrics['penetration_side'], 'left')
        self.assertEqual(metrics['penetration_part'], 'ankle')
        self.assertAlmostEqual(metrics['ground_world_z'], .1)
        self.assertAlmostEqual(metrics['penetration_depth_m'], .028)
        self.assertAlmostEqual(metrics['root_height_m'], rest[0, 2] - .028)
        self.assertAlmostEqual(metrics['foot_world_z'], .242)

    def test_bone_tolerance_combines_absolute_and_relative_error(self):
        pose, _, names = standing_pose()
        joint = names.index('LeftShin')
        length = np.linalg.norm(pose[joint, :3])
        tolerance = .002 + .01 * length
        frames = np.repeat(pose[None], 4, axis=0)
        frames[:, joint, :3] *= 1 + (tolerance - 1e-6) / length
        self.assertTrue(check_bone_lengths(frames, pose, names)['bone_lengths_valid'])
        frames[:, joint, :3] = pose[joint, :3] * (1 + (tolerance + 1e-6) / length)
        self.assertFalse(check_bone_lengths(frames, pose, names)['bone_lengths_valid'])

    def test_local_direction_change_preserving_length_is_accepted(self):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 4, axis=0)
        joint = names.index('LeftToeBase')
        frames[:, joint, :3] = [.079, np.sqrt(.08**2 - .079**2), -.02]
        metrics = validate_stop_motion(frames, pose, [0, 0], parents, names, calibrate_stop_ground(pose, parents, names))
        self.assertTrue(metrics['accepted'], metrics)
        self.assertAlmostEqual(metrics['max_bone_length_error_m'], 0)
        self.assertGreater(metrics['bone_length_diagnostics'][joint - 1]['local_position_delta_m'], .01)

    def test_length_change_reports_joint_frame_and_serializable_diagnostics(self):
        import json
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 4, axis=0)
        joint = names.index('LeftToeBase')
        frames[2, joint, 0] += .03
        metrics = validate_stop_motion(frames, pose, [0, 0], parents, names, calibrate_stop_ground(pose, parents, names))
        self.assertEqual(metrics['reason'], 'Stop bone lengths changed')
        self.assertEqual(metrics['failed_joint'], 'LeftToeBase')
        self.assertEqual(metrics['failed_frame'], 2)
        self.assertAlmostEqual(metrics['local_position_delta_m'], .03)
        self.assertGreater(metrics['bone_length_delta_m'], .02)
        self.assertEqual(metrics['bone_length_delta_m'], metrics['max_bone_length_error_m'])
        json.dumps(metrics, allow_nan=False)

    def test_recovery_replays_segments_and_only_settles_at_destination(self):
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([.5, 0], True, 1)
        cycle.note_final_stop(None, {'accepted': False, 'reason': 'Stop missed destination'})
        for x in (.25, .5):
            self.assertTrue(cycle.tick(observe(pose)).begin_final_stop)
            end = pose.copy()
            end[0, 0] = x
            cycle.note_final_stop([end.copy() for _ in range(4)], {'accepted': True})
            for _ in range(4):
                self.assertFalse(cycle.tick(observe(pose)).walk)
            pose = end
        self.assertEqual(cycle.phase, SETTLED)
        self.assertEqual(cycle.stop_failure_reason, '')

    def test_recovery_stops_at_attempt_limit(self):
        from locomotion_cycle import STOP_FAILED
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([4, 0], True, 1)
        cycle.note_final_stop(None, {'accepted': False, 'reason': 'Generation failed'})
        for _ in range(8):
            self.assertTrue(cycle.tick(observe(pose)).begin_final_stop)
            pose = pose.copy()
            pose[0, 0] += .25
            cycle.note_final_stop([pose.copy() for _ in range(4)], {'accepted': True})
            for _ in range(4):
                cycle.tick(observe(pose))
        action = cycle.tick(observe(pose))
        self.assertEqual(cycle.phase, STOP_FAILED)
        self.assertFalse(action.begin_final_stop)
        self.assertFalse(action.walk)
        self.assertTrue(cycle.stop_failure_reason)

    def test_recovery_rejects_destination_passage_even_when_endpoint_returns(self):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 4, axis=0)
        frames[:, 0, 0] = [.1, .6, .3, .25]
        self.assertIn('passed destination', validate_stop_progress(frames, pose, [.5, 0], 'left', parents, names))

    def test_recovery_rejects_no_progress_and_cumulative_support_slip(self):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 4, axis=0)
        self.assertIn('insufficient progress', validate_stop_progress(frames, pose, [.5, 0], 'left', parents, names))
        frames[:, 0, 0] = [.01, .02, .03, .04]
        self.assertIn('support foot drifted', validate_stop_progress(frames, pose, [.5, 0], 'left', parents, names))

    def test_prediction_is_bounded_by_final_step_reach(self):
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([2, 0], True, 1)
        cycle.tick(observe(pose))
        with patch.object(cycle, '_update_plants'):
            cycle._flight = {'left': .75, 'right': .75}
            action = cycle.tick(observe(pose, speed=2.3))
        self.assertLessEqual(cycle.stop_prediction_m, cycle.choice.final_window_m)
        self.assertTrue(action.walk)

    def test_failure_requests_bounded_recovery_then_fails_without_walk(self):
        from locomotion_cycle import STOP_FAILED
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([2, 0], True, 1)
        cycle.note_final_stop(None, {'accepted': False, 'reason': 'Generation failed'})
        action = cycle.tick(observe(pose))
        self.assertTrue(action.begin_final_stop)
        self.assertFalse(action.walk)
        self.assertLessEqual(np.linalg.norm(cycle.final_stop_goal[:2] - pose[0, :2]), .25)
        cycle.note_final_stop(None, {'accepted': False, 'reason': 'Recovery failed'})
        self.assertEqual(cycle.phase, STOP_FAILED)
        self.assertFalse(cycle.tick(observe(pose)).walk)

    def test_target_places_root_at_goal_without_changing_bone_lengths(self):
        pose, parents, names = standing_pose()
        with patch('final_stop.overlay_pose', return_value=pose.copy()):
            target = build_stop_target(pose, [0.2, 0], parents, names, calibrate_stop_ground(pose, parents, names))
        np.testing.assert_allclose(target[0, :2], [.2, 0])
        np.testing.assert_array_equal(target[1:, :3], pose[1:, :3])

    def test_prediction_requests_generation_once_and_replays_before_settling(self):
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([2, 0], True, 1)
        cycle.tick(observe(pose, speed=2))
        near = pose.copy()
        near[0, 0] = 1.95
        action = cycle.tick(observe(near, speed=2))
        self.assertTrue(action.begin_final_stop)
        self.assertFalse(action.walk)
        frames = [near.copy() for _ in range(4)]
        cycle.note_final_stop(frames, {'accepted': True})
        for _ in range(4):
            action = cycle.tick(observe(near))
            self.assertFalse(action.walk)
        self.assertEqual(cycle.phase, SETTLED)

    def test_failure_never_restarts_walk(self):
        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([2, 0], True, 1)
        cycle.note_final_stop(None, {'accepted': False, 'reason': 'Generation failed'})
        self.assertFalse(cycle.tick(observe(pose)).walk)

    def test_no_endpoint_snap_or_unstable_feet(self):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 8, axis=0)
        result = validate_stop_motion(frames, pose, [.4, 0], parents, names, calibrate_stop_ground(pose, parents, names))
        self.assertFalse(result['accepted'])

    def test_official_generation_keeps_history_until_generation_and_restores_pose(self):
        from engine import _begin_final_stop
        pose, parents, names = standing_pose()
        events = []
        character = SimpleNamespace(
            skeleton=SimpleNamespace(joint_names=names, joint_parent=lambda i: parents[i]),
            engine=SimpleNamespace(device='cpu'),
            current_pose=SimpleNamespace(numpy=lambda: pose.copy()),
            player=SimpleNamespace(record_pose=Mock()),
            generate_to_target_poses=Mock(side_effect=lambda *args: events.append('generate')),
            _sample_playback=Mock(), time_to_transition=lambda: 0,
            clear_ik_pins=Mock())
        rt = {'MODEL_POSES_PER_TOKEN': 4, 'IKPin': SimpleNamespace(LEFT_FOOT=4, RIGHT_FOOT=8),
              'TargetPoseInferenceParams': lambda **kwargs: kwargs}
        wp = SimpleNamespace(array=lambda data, **kwargs: data, transform=object)
        with patch('engine.build_stop_target', return_value=pose), patch('engine._sync_pose', side_effect=lambda *args,**kwargs: events.append('restore')), patch('engine.validate_stop_motion', return_value={'accepted': True}):
            frames, metrics = _begin_final_stop(character, pose, [0,0], rt, wp, ground=calibrate_stop_ground(pose, parents, names))
        self.assertEqual(events, ['generate', 'restore'])
        self.assertTrue(metrics['accepted'])
        self.assertEqual(len(frames), 1)
        character.clear_ik_pins.assert_called_once()
        self.assertIn(character.generate_to_target_poses.call_args.args[1]['ik_pin_mask'], (4, 8))
        self.assertEqual(metrics['ik_pin_mask'], character.generate_to_target_poses.call_args.args[1]['ik_pin_mask'])

    def test_official_generation_exception_restores_pose(self):
        from engine import _begin_final_stop
        pose, parents, names = standing_pose()
        character = SimpleNamespace(skeleton=SimpleNamespace(joint_names=names,joint_parent=lambda i:parents[i]),
            engine=SimpleNamespace(device='cpu'), generate_to_target_poses=Mock(side_effect=RuntimeError('Inference failed')), clear_ik_pins=Mock())
        rt={'MODEL_POSES_PER_TOKEN':4,'TargetPoseInferenceParams':lambda **kwargs:kwargs,'IKPin':SimpleNamespace(LEFT_FOOT=4,RIGHT_FOOT=8)}
        wp=SimpleNamespace(array=lambda data,**kwargs:data,transform=object)
        with patch('engine.build_stop_target',return_value=pose), patch('engine._sync_pose') as restore:
            with self.assertRaisesRegex(RuntimeError,'Inference failed'):
                _begin_final_stop(character,pose,[0,0],rt,wp, ground=calibrate_stop_ground(pose, parents, names))
            restore.assert_called_once()
        character.clear_ik_pins.assert_called_once()
