"""PR #5の採用候補と停止予測の回帰。"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from test_gait import standing_pose
from engine import _begin_final_stop
from stop_runtime import GeneratedStop
from run_stop_replay import selected_specification


class SelectedStopTests(unittest.TestCase):
    def run_stop(self, displacement, destination):
        pose, parents, names = standing_pose()
        frames = np.repeat(pose[None], 4, axis=0)
        frames[:, 0, 0] += displacement
        frames = GeneratedStop(list(frames), [[1, 1]] * 4, 'left')
        replay = dict(metadata=dict(support='left', parents=parents, names=names))
        character = SimpleNamespace(asset_pool=object(), engine=object())
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, MOTIONBRICKS_STOP_REPLAY_DIR=folder), \
                patch('stop_replay.capture_replay', return_value=replay), \
                patch('stop_runtime.new_character', side_effect=lambda *a: object()), \
                patch('stop_runtime.generate_candidate', return_value=frames), \
                patch('stop_runtime.diagnose', return_value=dict(accepted=True, arrival_error_m=0, quality=dict(support_slide_m=0, root_second_difference_m=0, knee_angle_step_deg=0))):
            return _begin_final_stop(character, pose, [.01, 0], {}, None,
                                     destination=destination, ground={})

    def test_rejects_passed_backward_and_insufficient_progress_before_selection(self):
        for displacement in ([.01, .14, .01, .01], [-.03] * 4, [.005] * 4):
            with self.subTest(displacement=displacement):
                _, metrics = self.run_stop(displacement, [.1, 0])
                self.assertIsNone(metrics['search']['selected'])
                self.assertTrue(all(not row['metrics']['accepted']
                                    for row in metrics['search']['candidates']))

    def test_selected_displacement_reaches_next_stop_prediction(self):
        from locomotion_cycle import LocomotionCycle
        frames, metrics = self.run_stop([.005, .01, .015, .015], [.1, 0])
        self.assertIsNotNone(metrics['search']['selected'])
        self.assertAlmostEqual(metrics['travel_distance_m'], .015)
        cycle = LocomotionCycle(log=None)
        cycle.note_final_stop(frames, metrics)
        self.assertAlmostEqual(cycle.last_stop_distance_m, .015)

    def test_repeatability_uses_selected_including_refined_offset(self):
        rows = [dict(specification=dict(id=i), metrics=dict(checks={})) for i in range(34)]
        for selected in (14, 32):
            self.assertEqual(selected_specification(dict(selected=selected, candidates=rows)),
                             dict(id=selected))
        self.assertIsNone(selected_specification(dict(selected=None, candidates=rows)))
