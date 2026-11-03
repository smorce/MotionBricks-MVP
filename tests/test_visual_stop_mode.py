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
