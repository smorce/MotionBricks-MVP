import sys
import unittest
from pathlib import Path
from queue import Queue

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from engine import _drain
from stop_phase import (
    IDLE,
    MOVING,
    POSE_DONE,
    POSE_PENDING,
    POSE_TRANSITION,
    STOPPING,
    NavState,
    after_playback,
    after_pose_request,
    apply_nav_command,
    arm_stop,
    arrival_due,
)


class StopPhaseTests(unittest.TestCase):
    def test_move_starts_and_rejects_a_bad_goal(self):
        started = apply_nav_command(NavState(), {"type": "move", "x": 1.5, "y": -2.0, "move_id": 3})
        self.assertEqual(started.state.phase, MOVING)
        self.assertEqual(started.move_to, (1.5, -2.0))
        self.assertEqual(started.state.move_id, 3)
        ignored = apply_nav_command(started.state, {"type": "move", "x": float("nan"), "y": 0})
        self.assertEqual(ignored.state.phase, MOVING)
        self.assertIsNone(ignored.move_to)

    def test_fast_stop_arms_once(self):
        phase, started = arm_stop(MOVING, True)
        self.assertEqual(phase, STOPPING)
        self.assertTrue(started)
        phase, started = arm_stop(phase, True)
        self.assertEqual(phase, STOPPING)
        self.assertFalse(started)

    def test_idle_loop_requests_pose_after_the_official_stop(self):
        phase, attempt = after_playback(
            STOPPING, in_idle_loop=False, in_clip_transition=True, time_to_transition=0.4, dt=1 / 60
        )
        self.assertEqual(phase, STOPPING)
        self.assertFalse(attempt)
        phase, attempt = after_playback(
            STOPPING, in_idle_loop=True, in_clip_transition=False, time_to_transition=0.0, dt=1 / 60
        )
        self.assertEqual(phase, POSE_PENDING)
        self.assertTrue(attempt)

    def test_pose_request_waits_out_the_generated_transition(self):
        self.assertEqual(after_pose_request(True, 0.4, 1 / 60), POSE_TRANSITION)
        self.assertEqual(after_pose_request(False, 0.4, 1 / 60), IDLE)
        phase, attempt = after_playback(
            POSE_TRANSITION, in_idle_loop=False, in_clip_transition=False, time_to_transition=0.01, dt=1 / 60
        )
        self.assertEqual(phase, POSE_DONE)
        self.assertFalse(attempt)

    def test_settled_pose_choice_replays_without_another_walk(self):
        done = NavState(phase=POSE_DONE, move_id=4, target_pose_id="F001", arrived_sent=True, pose_applied=True)
        late = apply_nav_command(done, {"type": "pose_choice", "pose_id": "F043", "move_id": 4})
        self.assertEqual(late.state.phase, POSE_PENDING)
        self.assertEqual(late.state.target_pose_id, "F043")
        self.assertFalse(late.state.arrived_sent)
        self.assertIsNone(late.move_to)
        phase, attempt = after_playback(
            late.state.phase, in_idle_loop=False, in_clip_transition=False, time_to_transition=0.0, dt=1 / 60
        )
        self.assertTrue(attempt)
        self.assertEqual(phase, POSE_PENDING)

    def test_stale_pose_choice_is_ignored(self):
        moving = NavState(phase=MOVING, move_id=2)
        stale = apply_nav_command(moving, {"type": "pose_choice", "pose_id": "F043", "move_id": 1})
        self.assertEqual(stale.state.target_pose_id, "F001")
        fresh = apply_nav_command(moving, {"type": "pose_choice", "pose_id": "F043", "move_id": 2})
        self.assertEqual(fresh.state.phase, MOVING)
        self.assertEqual(fresh.state.target_pose_id, "F043")

    def test_drain_keeps_the_latest_move_and_quits(self):
        commands = Queue()
        commands.put({"type": "move", "x": 1, "y": 0, "move_id": 1})
        commands.put({"type": "pose_choice", "pose_id": "F043", "move_id": 1})
        commands.put({"type": "move", "x": 2, "y": 3, "move_id": 2})
        nav, goal = _drain(commands, NavState())
        self.assertEqual(nav.move_id, 2)
        self.assertEqual(nav.phase, MOVING)
        self.assertEqual(nav.target_pose_id, "F001")
        self.assertAlmostEqual(float(goal[0]), 2.0)
        self.assertAlmostEqual(float(goal[1]), 3.0)
        commands.put({"type": "quit"})
        self.assertIsNone(_drain(commands, nav))

    def test_arrival_is_reported_once_after_idle_or_pose(self):
        self.assertFalse(arrival_due(STOPPING, False, True))
        self.assertTrue(arrival_due(IDLE, False, True))
        self.assertTrue(arrival_due(POSE_DONE, False, True))
        self.assertFalse(arrival_due(POSE_DONE, True, True))
        self.assertFalse(arrival_due(IDLE, False, False))


if __name__ == "__main__":
    unittest.main()
