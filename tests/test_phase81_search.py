"""ライブ停止で全探索と同じ候補集合を使う。"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from engine import _begin_final_stop
from stop_runtime import GeneratedStop, candidate_specs


class LiveSearchTests(unittest.TestCase):
    def test_replay_diagnosis_rejects_progress_rejected_by_live_navigation(self):
        from stop_runtime import diagnose
        pose=np.zeros((1,7))
        replay=dict(pose=pose.tolist(),metadata=dict(goal=[.1,0],parents=[],names=[],ground={},control=dict(destination=[.2,0])))
        frames=GeneratedStop([pose],[],'left')
        with patch('stop_runtime.validate_stop_motion',return_value=dict(accepted=True)), \
             patch('final_stop.validate_stop_progress',return_value='Stop trajectory passed destination or moved backward') as progress:
            metrics=diagnose(replay,frames)
        self.assertFalse(metrics['accepted'])
        self.assertEqual(progress.call_args.args[2],[.2,0])

    def test_recovery_rebuilds_target_for_current_position(self):
        pose=np.zeros((1,7))
        replay=dict(pose=pose.tolist(),metadata=dict(support='left',parents=[],names=[],f001=[[9]*7],control={}))
        seen=[]
        def generate(player,saved,spec,rt):
            seen.append(saved['metadata'].copy())
            raise ValueError('Unsafe candidate')
        character=SimpleNamespace(engine=object(),asset_pool=object())
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ',MOTIONBRICKS_STOP_REPLAY_DIR=directory), \
             patch('stop_replay.capture_replay',return_value=replay), \
             patch('stop_runtime.new_character',side_effect=lambda *a:object()), \
             patch('stop_runtime.generate_candidate',side_effect=generate):
            frames,metrics=_begin_final_stop(character,pose,[1,0],{},None,ground={})
        self.assertIsNone(frames)
        self.assertFalse(metrics['accepted'])
        self.assertEqual(seen[-1]['goal'],[0,0])
        self.assertIsNone(seen[-1]['f001'])
        self.assertEqual(replay['metadata']['f001'],[[9]*7])

    def test_live_search_reaches_previously_omitted_safe_candidate(self):
        pose=np.zeros((1,7))
        replay=dict(pose=pose.tolist(), metadata=dict(support='left',parents=[],names=[]))
        winner=candidate_specs()[0]['id']
        frames=GeneratedStop([pose.copy()], [], 'left')
        def generate(player, saved, spec, rt):
            if spec['id']!=winner:
                raise ValueError('Unsafe candidate')
            return frames
        character=SimpleNamespace(engine=object(),asset_pool=object())
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ', MOTIONBRICKS_STOP_REPLAY_DIR=directory), \
             patch('stop_replay.capture_replay',return_value=replay), \
             patch('stop_runtime.new_character',side_effect=lambda *a:object()), \
             patch('stop_runtime.generate_candidate',side_effect=generate), \
             patch('stop_runtime.diagnose',return_value=dict(accepted=True,arrival_error_m=0,quality=dict(support_slide_m=0,root_second_difference_m=0,knee_angle_step_deg=0))), \
             patch('engine.validate_stop_progress',return_value=''):
            actual, metrics=_begin_final_stop(character,pose,[0,0],{},None,ground={})
        self.assertIs(actual,frames)
        self.assertFalse(metrics.get('recovery_only',False))
        self.assertEqual(metrics['generation_conditions']['id'],winner)
