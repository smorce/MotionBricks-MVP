"""停止診断と探索の回帰テスト。"""

import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from test_gait import standing_pose
from final_stop import calibrate_stop_ground, validate_stop_motion


class StopAutomationTests(unittest.TestCase):
    def test_gradual_foot_inversion_is_rejected(self):
        pose,parents,names=standing_pose()
        frames=np.repeat(pose[None],80,axis=0)
        for frame,angle in zip(frames,np.linspace(0,np.pi,80)):
            frame[names.index('LeftFoot'),3:]=[np.sin(angle/2),0,0,np.cos(angle/2)]
        result=validate_stop_motion(frames,pose,[0,0],parents,names,calibrate_stop_ground(pose,parents,names))
        self.assertFalse(result['checks']['ankles']['passed'])

    def test_safe_landing_recovery_does_not_report_arrival(self):
        from locomotion_cycle import LocomotionCycle, STOP_FAILED
        from test_final_stop import observe

        pose, _, _ = standing_pose()
        cycle = LocomotionCycle(log=None)
        cycle.begin_move([1, 0], True, 1)
        cycle.note_final_stop(
            [pose.copy() for _ in range(4)], dict(accepted=True, recovery_only=True)
        )
        for _ in range(4):
            cycle.tick(observe(pose))
        self.assertEqual(cycle.phase, STOP_FAILED)
        self.assertTrue(cycle.stop_failure_reason)

    def test_candidate_budget_and_both_supports(self):
        from stop_runtime import candidate_specs

        specs = candidate_specs("right")
        self.assertEqual(len(specs), 24)
        self.assertEqual({s["support"] for s in specs}, {"left", "right"})
        self.assertEqual(specs[0]["support"], "right")

    def test_search_rejects_shared_player(self):
        from stop_candidate_search import search_candidates

        player = object()
        with self.assertRaisesRegex(ValueError, "independent"):
            search_candidates(
                [{}, {}],
                lambda spec: player,
                lambda p, s: [],
                lambda f: {"accepted": False},
            )

    def test_cumulative_contact_slide_is_rejected(self):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 20, axis=0)
        frames[:, 0, 0] = np.linspace(0, 0.04, 20)
        result = validate_stop_motion(
            frames,
            pose,
            [0.04, 0],
            parents,
            names,
            calibrate_stop_ground(pose, parents, names),
        )
        self.assertFalse(result["checks"]["support"]["passed"])
        self.assertGreater(result["checks"]["support"]["max_slip_m"], 0.02)

    def test_turn_does_not_invert_body_relative_knee(self):
        from collect_stance import knees_continuous
        from quats import quat_mul

        pose, parents, names = standing_pose()
        pose[names.index("LeftLeg"), 3:] = [0, np.sin(0.2), 0, np.cos(0.2)]
        pose[names.index("LeftShin"), 3:] = [0, -np.sin(0.4), 0, np.cos(0.4)]
        turned = pose.copy()
        turned[0, 3:] = quat_mul(np.array([0, 0, 1, 0]), pose[0, 3:])
        self.assertTrue(knees_continuous(turned, pose, parents, names))

    def test_reports_simultaneous_failures(self):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 8, axis=0)
        frames[2, 0, 0] += 0.2
        frames[3, names.index("LeftToeBase"), 0] += 0.1
        result = validate_stop_motion(
            frames,
            pose,
            [1, 0],
            parents,
            names,
            calibrate_stop_ground(pose, parents, names),
        )
        self.assertFalse(result["checks"]["bones"]["passed"])
        self.assertFalse(result["checks"]["root"]["passed"])
        self.assertFalse(result["checks"]["destination"]["passed"])
        self.assertEqual(len(result["checks"]), 9)

    def test_search_never_selects_unsafe_candidate(self):
        from stop_candidate_search import search_candidates

        result = search_candidates(
            [{"id": "bad"}, {"id": "good"}],
            lambda spec: spec,
            lambda player, spec: np.zeros((4, 1, 7)),
            lambda frames: {"accepted": False, "arrival_error_m": 0},
        )
        self.assertIsNone(result["selected"])
        self.assertEqual(len(result["candidates"]), 2)

    def test_replay_roundtrip_is_detached(self):
        import tempfile
        from stop_replay import save_replay, load_replay

        pose, _, _ = standing_pose()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "replay.json"
            save_replay(
                path,
                pose=pose,
                history=np.repeat(pose[None], 32, axis=0),
                delta_times=np.zeros(32),
                metadata={"phase": "moving"},
            )
            a, b = load_replay(path), load_replay(path)
            a["history"][0][0][0] = 999
            self.assertNotEqual(a["history"], b["history"])
