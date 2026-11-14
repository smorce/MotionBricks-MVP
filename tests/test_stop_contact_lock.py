import unittest
import numpy as np
from test_gait import standing_pose
from final_stop import calibrate_stop_ground
from stop_contact_lock import StopContactLock


class StopContactLockTests(unittest.TestCase):
    def test_floor_target_moves_only_ik_anchor_without_moving_source_root(self):
        from stop_contact_lock import floor_targets
        pose, parents, names = standing_pose()
        ground = calibrate_stop_ground(pose, parents, names)
        pose[0, 2] -= .03
        original = pose.copy()
        targets = floor_targets(pose, parents, names, ground)
        self.assertEqual(set(targets), {'left', 'right'})
        np.testing.assert_array_equal(pose, original)
        self.assertAlmostEqual(targets['left'][0, 2] - pose[0, 2], .02)
        np.testing.assert_array_equal(targets['left'][1:], pose[1:])

    def test_release_weight_fades_before_returning_to_generated_pose(self):
        pose, parents, names = standing_pose()
        lock = StopContactLock(pose, [1, 1, 1, 1], parents, names,
                               calibrate_stop_ground(pose, parents, names))
        weights = []
        for _ in range(4):
            lock.update(pose, [0, 0, 1, 1])
            weights.append(lock.releasing.get('left', (None, 0.))[1])
        self.assertEqual(weights, [.75, .5, .25, 0.])

    def test_contact_anchor_is_held_then_released_and_recaptured(self):
        pose, parents, names = standing_pose()
        lock = StopContactLock(pose, [1, 1, 1, 1], parents, names,
                               calibrate_stop_ground(pose, parents, names))
        moved = pose.copy(); moved[0, 0] += .01
        np.testing.assert_array_equal(lock.update(moved, [1, 1, 1, 1])['left'], pose)
        self.assertNotIn('left', lock.update(moved, [0, 0, 1, 1]))
        np.testing.assert_array_equal(lock.update(moved, [1, 1, 1, 1])['left'], moved)

    def test_confidence_does_not_pin_an_airborne_foot(self):
        pose, parents, names = standing_pose()
        ground = calibrate_stop_ground(pose, parents, names)
        pose[0, 2] += .1
        lock = StopContactLock(pose, [1, 1, 1, 1], parents, names, ground)
        self.assertFalse(lock.anchors)

    def test_apply_reuses_gpu_anchor_arrays_without_reallocating_each_frame(self):
        from types import SimpleNamespace
        pose, parents, names = standing_pose()
        ground = calibrate_stop_ground(pose, parents, names)
        lock = StopContactLock(pose, [1, 1, 1, 1], parents, names, ground)

        wp_calls = []

        class FakeWpArray:
            def __init__(self, data, **kwargs):
                wp_calls.append(kwargs)
                self.data = data

        class FakeCorrector:
            def capture_pins(self, arr, mask, stream=None): pass
            def apply(self, target, weight, stream=None): pass
            def clear_pins(self): pass

        character = SimpleNamespace(
            current_pose=SimpleNamespace(numpy=lambda: pose.copy()),
            current_foot_contacts=SimpleNamespace(numpy=lambda: np.array([1.0, 1.0, 1.0, 1.0])),
            engine=SimpleNamespace(device='cuda:0', stream=None),
            _target_pose_ik_corrector=FakeCorrector(),
        )
        rt = {
            'wp': SimpleNamespace(array=lambda data, **kw: FakeWpArray(data, **kw), transform='tx'),
            'IKPin': SimpleNamespace(LEFT_FOOT=1, RIGHT_FOOT=2),
        }
        lock.apply(character, rt)
        first_allocs = len(wp_calls)
        lock.apply(character, rt)
        lock.apply(character, rt)
        self.assertEqual(first_allocs, 2)
        self.assertEqual(len(wp_calls), 2)
