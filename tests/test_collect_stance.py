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

if __name__ == '__main__':
    unittest.main()
