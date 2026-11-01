import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from bvh_io import parse_bvh
from retarget_mhr import retarget_bvh_text
from soma_pose import overlay_pose
from soma_skeleton import SOMA_JOINT_NAMES, load_soma_reference, reference_from_soma_bvh, world_from_locals

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "F001.bvh"
SOMA_BVH = Path(r"C:\Users\kbpsh\src\motionbricks\assets\motions\soma\locomotion\idle\idle_loop_001__A268.bvh")


class RetargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = load_soma_reference()

    def test_reference_has_thirty_joints(self):
        self.assertEqual(self.reference["joint_names"], SOMA_JOINT_NAMES)
        self.assertEqual(len(self.reference["local_transforms"]), 30)
        self.assertEqual(self.reference["parents"][0], -1)

    @unittest.skipUnless(SOMA_BVH.exists(), "MotionBricks SOMA clip is absent")
    def test_reference_matches_official_idle_frame(self):
        built = reference_from_soma_bvh(SOMA_BVH)
        current = np.asarray(self.reference["local_transforms"])
        fresh = np.asarray(built["local_transforms"])
        self.assertTrue(np.allclose(current, fresh, atol=1e-5))

    @unittest.skipUnless(FIXTURE.exists(), "PoseLoom fixture is absent")
    def test_standing_pose_is_upright_and_grounded(self):
        transforms = np.asarray(retarget_bvh_text(FIXTURE.read_text(encoding="utf-8")))
        self.assertEqual(transforms.shape, (30, 7))
        self.assertTrue(np.isfinite(transforms).all())
        norms = np.linalg.norm(transforms[:, 3:], axis=1)
        self.assertTrue(np.allclose(norms, 1.0, atol=1e-4))
        self.assertAlmostEqual(transforms[0, 0], 0.0, places=4)
        self.assertAlmostEqual(transforms[0, 1], 0.0, places=4)
        parents = self.reference["parents"]
        pos, _ = world_from_locals(parents, transforms[:, :3], transforms[:, 3:])
        names = {name: i for i, name in enumerate(SOMA_JOINT_NAMES)}
        self.assertGreater(pos[names["Head"], 2], pos[names["Hips"], 2])
        self.assertGreater(pos[names["Hips"], 2], 0.4)
        foot_z = min(pos[names[name], 2] for name in ("LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"))
        self.assertAlmostEqual(foot_z, 0.0, places=3)

    @unittest.skipUnless(FIXTURE.exists(), "PoseLoom fixture is absent")
    def test_overlay_keeps_extra_finger_joints(self):
        base = [[0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 1.0] for _ in range(31)]
        names = SOMA_JOINT_NAMES + ["LeftHandIndexEnd"]
        overlaid = overlay_pose("F001", names, base)
        self.assertEqual(len(overlaid), 31)
        self.assertEqual(overlaid[-1][:3], [0.1, 0.2, 0.3])
        self.assertNotEqual(overlaid[0][2], 0.3)

    @unittest.skipUnless(FIXTURE.exists(), "PoseLoom fixture is absent")
    def test_parser_rejects_a_second_root(self):
        text = FIXTURE.read_text(encoding="utf-8")
        doubled = text.replace("MOTION", "ROOT Hips\n{\nOFFSET 0 0 0\nCHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\n}\nMOTION", 1)
        with self.assertRaises(ValueError):
            parse_bvh(doubled)


if __name__ == "__main__":
    unittest.main()
