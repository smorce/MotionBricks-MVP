import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from collect_stance import needs_collect, build_collect_target, validate_motion
from test_gait import standing_pose

class CollectTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertFalse(needs_collect(.26, .34))
        self.assertTrue(needs_collect(.261, .2))
        self.assertTrue(needs_collect(.1, .341))
        self.assertFalse(needs_collect(float('nan'), .5))

    def test_missing_reference_preserves_input(self):
        from unittest.mock import patch
        pose, parents, names = standing_pose()
        original = pose.copy()
        with patch('collect_stance.overlay_pose', return_value=None):
            self.assertIsNone(build_collect_target(pose, names, 'left', parents))
        np.testing.assert_array_equal(pose, original)

    def test_sliding_motion_is_rejected(self):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 20, axis=0)
        frames[:, 0, 0] += np.linspace(0, .1, 20)
        result = validate_motion(frames, pose, parents, names, 'left')
        self.assertFalse(result['accepted'])
        self.assertGreater(result['support_slip_m'], .02)

    def test_no_lift_is_rejected(self):
        pose, parents, names = standing_pose()
        result = validate_motion(np.repeat(pose[None], 20, axis=0), pose, parents, names, 'left')
        self.assertFalse(result['accepted'])

class CollectTargetTests(unittest.TestCase):
    def test_target_only_replaces_swing_rotations(self):
        from unittest.mock import patch
        reference, parents, names = standing_pose()
        base=reference.copy()
        index=names.index('LeftLeg')
        base[index,3:]=[0,np.sin(.2),0,np.cos(.2)]
        original=base.copy()
        with patch('collect_stance.overlay_pose',return_value=reference):
            target=build_collect_target(base,names,'left',parents)
        self.assertIsNotNone(target)
        np.testing.assert_array_equal(base,original)
        np.testing.assert_array_equal(target[:,:3],base[:,:3])
        swing=[names.index('Left'+part) for part in ('Leg','Shin','Foot','ToeBase')]
        other=[i for i in range(len(names)) if i not in swing]
        np.testing.assert_array_equal(target[other],base[other])
        from step_cycle import foot_points
        a,b=foot_points(base,parents,names),foot_points(target,parents,names)
        np.testing.assert_allclose(a['right']['ankle'],b['right']['ankle'])
        np.testing.assert_allclose(a['right']['toe'],b['right']['toe'])

    def test_intermediate_lifts_foot_without_moving_support(self):
        from collect_stance import build_collect_lift
        from step_cycle import foot_points
        base,parents,names=standing_pose()
        target=build_collect_lift(base,parents,names,'left')
        self.assertIsNotNone(target)
        a,b=foot_points(base,parents,names),foot_points(target,parents,names)
        for part in ('ankle','toe'):
            self.assertGreaterEqual(b['left'][part][2]-a['left'][part][2],.04)
            np.testing.assert_allclose(a['right'][part],b['right'][part])

if __name__ == '__main__':
    unittest.main()
