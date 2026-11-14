"""状態別の距離探索と目視評価の契約。"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from stop_distance_probe import recommendations, specifications, state_features


class ProbeTests(unittest.TestCase):
    def test_initial_matrix(self):
        specs = specifications()
        self.assertEqual(len(specs), 36)
        self.assertEqual(len({s['id'] for s in specs}), 36)

    def test_human_review_takes_priority_without_changing_diagnostics(self):
        candidates = [dict(id='A', metrics=dict(accepted=False)),
                      dict(id='B', metrics=dict(accepted=True)),
                      dict(id='C', metrics=dict(accepted=True))]
        result = recommendations(candidates, {'A':'good', 'B':'bad'})
        self.assertEqual(result['safe_ids'], ['B', 'C'])
        self.assertEqual(result['recommended_ids'], ['A'])
        self.assertEqual(result['diagnostic_failed_recommended_ids'], ['A'])
        self.assertFalse(candidates[0]['metrics']['accepted'])
        self.assertEqual(result['unreviewed_ids'], ['C'])

    def test_velocity_uses_interval_before_newest_pose(self):
        import numpy as np
        history = np.zeros((4, 1, 7))
        history[:, 0, 0] = [0, .01, .02, .03]
        replay = dict(history=history.tolist(), pose=history[-1].tolist(),
                      delta_times=[.02, .02, .02, 0],
                      metadata=dict(support='left', ground={}, contacts=[1, 1, 0, 0]))
        result = state_features(replay)
        self.assertAlmostEqual(result['speed_mps'], .5)
        self.assertEqual(result['direction'], [1., 0.])

    def test_safe_natural_candidates_rank_by_slip_after_error(self):
        candidates = [dict(id=i, metrics=dict(accepted=True, arrival_error_m=.01,
                      quality=dict(support_slide_m=slip))) for i, slip in [('A', .02), ('B', .01)]]
        self.assertEqual(recommendations(candidates, {'A':'good', 'B':'good'})['recommended_ids'], ['B', 'A'])

    def test_pure_generate_aligns_f001_pelvis_to_goal_direction_on_soma_rig(self):
        import json
        import numpy as np
        from types import SimpleNamespace
        from quats import RX90, quat_from_axis_angle, quat_mul, quat_to_mat
        from final_stop import calibrate_stop_ground
        from step_cycle import fk
        from stop_distance_probe import pure_generate

        ref = json.loads((Path(__file__).resolve().parents[1] / 'backend' / 'soma_reference.json').read_text(encoding='utf-8'))
        orig = np.asarray(ref['local_transforms'], dtype=np.float64)
        orig[0, :3] = quat_to_mat(RX90) @ orig[0, :3]
        orig[0, 3:] = quat_mul(RX90, orig[0, 3:])
        # 進行方向 (45度方向) へ歩いている元姿勢
        orig[0, 3:] = quat_mul(quat_from_axis_angle(np.array([0., 0., 1.]), 3 * np.pi / 4), orig[0, 3:])
        names = list(ref['joint_names'])
        parents = list(ref['parents'])
        ground = calibrate_stop_ground(orig, parents, names)
        goal = [1.0, 1.0]
        replay = dict(pose=orig.tolist(), metadata=dict(goal=goal, parents=parents, names=names, ground=ground, support='left', contacts=[1, 1, 0, 0]))

        class _Arr:
            def __init__(self, data):
                self._data = np.asarray(data)
            def numpy(self):
                return self._data

        class _Char:
            def __init__(self):
                self.engine = SimpleNamespace(device='cpu', stream=None)
                self.current_pose = _Arr(orig.copy())
                self.current_foot_contacts = _Arr([1, 1, 1, 1])
                self._t = 1
            def generate_to_target_poses(self, targets, params):
                self.captured_targets = targets._data
            def _sample_playback(self, dt):
                self._t -= 1
            def time_to_transition(self):
                return self._t

        char = _Char()
        rt = {
            'wp': SimpleNamespace(array=lambda d, **kw: _Arr(d), transform=object),
            'IKPin': SimpleNamespace(NONE=0, LEFT_FOOT=1, RIGHT_FOOT=2),
            'TargetPoseInferenceParams': lambda **kw: kw,
        }
        spec = {'id': 'A-0.800', 'mode': 'A', 'pinned': False, 'generation_settings': {'num_poses_to_use': 1, 'allowed_token_counts': [8, 14]}}
        generated = pure_generate(char, replay, spec, rt, np.repeat(orig[None], 4, axis=0))
        target = np.asarray(generated.target_poses[0], dtype=np.float64)
        pos, _ = fk(target, parents)
        left = pos[names.index('LeftLeg')][:2] - pos[names.index('RightLeg')][:2]
        fwd = np.array([left[1], -left[0]], dtype=np.float64)
        fwd /= np.linalg.norm(fwd)
        expected = np.array([1.0, 1.0]) / np.sqrt(2.0)
        self.assertGreater(float(np.dot(fwd, expected)), 0.995, f'Expected target pelvis facing {expected}, got {fwd}')

