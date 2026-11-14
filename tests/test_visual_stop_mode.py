"""移動ごとの停止方式切り替えを検証する。"""
import sys
import unittest
from pathlib import Path
from queue import Queue
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from engine import _drain
from locomotion_cycle import LocomotionCycle
from stop_phase import NavState


class VisualModeTests(unittest.TestCase):
    def test_replay_static_metadata_is_cached(self):
        import stop_replay
        from unittest.mock import patch

        stop_replay._static_replay_metadata.cache_clear()
        with patch('stop_replay.subprocess.check_output', return_value='commit') as check_output, \
             patch('stop_replay.find_motionbricks_root', return_value=Path('.')), \
             patch('stop_replay.Path.read_bytes', return_value=b'mapping'), \
             patch('stop_replay.Path.read_text', return_value='source'):
            first = stop_replay._static_replay_metadata()
            second = stop_replay._static_replay_metadata()

        self.assertIs(first, second)
        check_output.assert_called_once()

    def test_visual_stop_runtime_reuses_scratch_character(self):
        from unittest.mock import patch
        from visual_stop_runtime import VisualStopRuntime

        runtime = VisualStopRuntime.__new__(VisualStopRuntime)
        runtime._scratch = None
        character = object()
        with patch('visual_stop_runtime.new_character', return_value=character) as new_character, \
             patch.object(runtime, '_reset_scratch') as reset:
            first = runtime._get_scratch('rt', 'engine', 'pool', {'pose': []})
            second = runtime._get_scratch('rt', 'engine', 'pool', {'pose': []})

        self.assertIs(first, character)
        self.assertIs(second, character)
        new_character.assert_called_once()
        reset.assert_called_once()

    def test_move_selects_visual_mode_without_changing_destination(self):
        cycle = LocomotionCycle(log=None)
        commands = Queue()
        commands.put(dict(type='move', x=.5, y=.2, move_id=1, stop_mode='visual'))
        _, goal = _drain(commands, NavState(), cycle)
        self.assertEqual(cycle.stop_mode, 'visual')
        self.assertAlmostEqual(float(goal[0]), .5)
        self.assertAlmostEqual(float(goal[1]), .2)

    def test_old_legacy_request_uses_prepared_controller(self):
        cycle = LocomotionCycle(log=None)
        cycle.stop_mode = 'visual'
        commands = Queue()
        commands.put(dict(type='move', x=1, y=0, move_id=2, stop_mode='legacy'))
        _drain(commands, NavState(), cycle)
        self.assertEqual(cycle.stop_mode, 'prepared')

    def test_client_without_mode_keeps_default_controller(self):
        cycle = LocomotionCycle(log=None)
        cycle.stop_mode = 'visual'
        commands = Queue()
        commands.put(dict(type='move', x=1, y=0, move_id=3))
        _drain(commands, NavState(), cycle)
        self.assertEqual(cycle.stop_mode, 'prepared')
