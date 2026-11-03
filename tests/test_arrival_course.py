import unittest
import numpy as np
from test_gait import standing_pose
from locomotion_cycle import LocomotionCycle

class ArrivalCourseTests(unittest.TestCase):
    def test_stop_target_projects_without_changing_destination(self):
        cycle = LocomotionCycle()
        cycle.begin_move([1, .04], True, 1)
        pose, _, _ = standing_pose()
        cycle.course_direction = np.array([1., 0., 0.])
        cycle._lock_stop_course(pose)
        np.testing.assert_allclose(cycle.goal[:2], [1, .04])
        np.testing.assert_allclose(cycle.final_stop_goal[:2], [1, 0])

    def test_direction_is_locked_after_stop(self):
        cycle = LocomotionCycle()
        cycle.begin_move([1, .04], True, 1)
        pose, _, _ = standing_pose()
        cycle.stop_facing = np.array([1., 0., 0.])
        np.testing.assert_allclose(cycle._facing(pose, None), [1, 0, 0])

    def test_reclick_resets_course(self):
        cycle = LocomotionCycle()
        cycle.begin_move([1, 0], True, 1)
        cycle.course_direction = np.array([1., 0., 0.])
        cycle.stop_facing = cycle.course_direction.copy()
        cycle.begin_move([0, 1], True, 2)
        self.assertIsNone(cycle.course_direction)
        self.assertIsNone(cycle.stop_facing)

    def test_turn_is_bounded_per_tick(self):
        cycle = LocomotionCycle()
        cycle.begin_move([0, 1], True, 1)
        pose, _, _ = standing_pose()
        cycle.command_direction = np.array([1., 0., 0.])
        cycle._update_course(pose, {})
        direction = cycle._facing(pose, None)
        self.assertGreater(direction[1], 0.)
        self.assertLessEqual(abs(np.arctan2(direction[1], direction[0])), 2 * cycle._dt + 1e-9)

    def test_validated_landing_within_five_cm_needs_no_retry(self):
        from test_gait import observe
        from locomotion_cycle import FINAL_STEP, SETTLED, STOP_RETRY
        for error, expected in [(0.04, SETTLED), (0.051, STOP_RETRY)]:
            with self.subTest(error=error):
                cycle = LocomotionCycle(log=None)
                cycle.begin_move([1, 0], True, 1)
                pose, _, _ = standing_pose()
                pose[0, 0] = 1 - error
                cycle.phase = FINAL_STEP
                cycle.note_final_stop([pose.copy()], {'accepted': True})
                cycle.tick(observe(pose))
                self.assertEqual(cycle.phase, expected)

    def test_six_cm_move_requires_validated_generation(self):
        from test_gait import observe
        from unittest.mock import patch
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([.06, 0], True, 1)
        pose, _, _ = standing_pose()
        with patch('gait_plan.USE_PROCEDURAL_STEP', False):
            action = cycle.tick(observe(pose))
        self.assertTrue(action.begin_final_stop)
        self.assertFalse(action.walk)

    def test_rejected_preview_keeps_continuous_walk_before_playback_commit(self):
        from test_gait import observe
        from unittest.mock import patch
        cycle = LocomotionCycle(log=None)
        cycle.preview_stops = True
        cycle.begin_move([.4, 0], True, 1)
        pose, _, _ = standing_pose()
        with patch('gait_plan.USE_PROCEDURAL_STEP', False):
            action = cycle.tick(observe(pose))
            self.assertTrue(action.begin_final_stop)
            self.assertTrue(cycle.reject_stop_preview(pose))
            self.assertTrue(cycle.tick(observe(pose)).walk)
        np.testing.assert_allclose(cycle.goal[:2], [.4, 0])

    def test_preview_cannot_restart_a_committed_stop(self):
        from locomotion_cycle import FINAL_STEP
        cycle = LocomotionCycle(log=None)
        cycle.preview_stops = True
        cycle.begin_move([.4, 0], True, 1)
        pose, _, _ = standing_pose()
        cycle.phase = FINAL_STEP
        cycle.final_stop_frames = [pose.copy()]
        self.assertFalse(cycle.reject_stop_preview(pose))

    def test_near_destination_corrects_cross_track_before_stop(self):
        angles = []
        pose, _, _ = standing_pose()
        for remaining in (1., .2):
            cycle = LocomotionCycle(log=None)
            cycle.begin_move([remaining, .1], True, 1)
            cycle.route_direction = np.array([1., 0.])
            cycle.command_direction = np.array([1., 0., 0.])
            cycle._dt = 1.
            cycle._update_course(pose, {})
            angles.append(np.arctan2(cycle.command_direction[1], cycle.command_direction[0]))
        self.assertGreater(angles[1], angles[0] + .1)


    def test_walk_regenerates_for_small_course_changes(self):
        from dataclasses import dataclass
        from types import SimpleNamespace
        from engine import _prime_walk
        @dataclass(frozen=True)
        class Settings:
            direction_regeneration_dot: float = .92
            velocity_direction_halflife: float = .2
        movement = SimpleNamespace(desired_velocity_direction=np.zeros(3), desired_velocity=np.zeros(3), settings=Settings())
        locomotion = SimpleNamespace(active_mode=SimpleNamespace(default_speed=1.), settings=Settings(), _force_regeneration=False)
        character = SimpleNamespace(movement=movement, state_machine=SimpleNamespace(active_locomotion_state=locomotion))
        _prime_walk(character, np.array([1.,0.,0.]))
        self.assertGreater(locomotion.settings.direction_regeneration_dot, np.cos(np.deg2rad(2)))
        self.assertTrue(locomotion._force_regeneration)
        self.assertLessEqual(movement.settings.velocity_direction_halflife, .05)

    def test_restoring_pose_updates_runtime_ground_and_clears_stale_velocity(self):
        from types import SimpleNamespace
        from engine import _sync_pose
        from unittest.mock import Mock
        pose, _, _ = standing_pose()
        pose[0,:2] = [2., 3.]
        character = SimpleNamespace(current_pose=SimpleNamespace(numpy=lambda:pose.copy(), assign=Mock()),
            character_ground_position=np.zeros(3), actual_velocity=np.ones(3),
            player=SimpleNamespace(seed_history_from_pose=Mock()))
        _sync_pose(character,pose,None,seed=True)
        np.testing.assert_allclose(character.character_ground_position,[2.,3.,0.])
        np.testing.assert_allclose(character.actual_velocity,0.)


    def test_uncommitted_stop_can_advance_one_frame_near_destination(self):
        cycle = LocomotionCycle(log=None)
        cycle.preview_stops = True
        cycle.begin_move([.06,0.],True,1)
        cycle.route_direction = np.array([1.,0.])
        pose, _, _ = standing_pose()
        self.assertTrue(cycle.reject_stop_preview(pose))
        self.assertAlmostEqual(cycle.preview_next_s,cycle.clock+cycle._dt)
