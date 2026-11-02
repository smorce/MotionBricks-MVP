import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from locomotion_cycle import LocomotionCycle, COLLECT_PREPARING, SETTLED
from test_gait import standing_pose

class CollectReviewTests(unittest.TestCase):
    def prepared(self):
        cycle=LocomotionCycle(log=None)
        pose, _, _=standing_pose()
        cycle.begin_move([0,0],True,1)
        cycle.settled_pose=pose.copy()
        cycle.phase=COLLECT_PREPARING
        return cycle,pose

    def test_vrm_approval_required_and_stale_reply_ignored(self):
        cycle,pose=self.prepared()
        cycle.stage_collect([pose]*3, {'accepted':True},1,0)
        self.assertEqual(cycle.phase,COLLECT_PREPARING)
        self.assertFalse(cycle.note_collect_review(True,{},2,0))
        self.assertTrue(cycle.note_collect_review(False,{'reason':'VRM slip'},1,0))
        self.assertEqual(cycle.phase,SETTLED)
        self.assertEqual(cycle.collect_failure_reason,'VRM slip')

    def test_no_reply_preserves_original(self):
        cycle,pose=self.prepared()
        cycle.stage_collect([pose]*3, {'accepted':True},1,0)
        cycle.clock+=6
        cycle.expire_collect_review()
        self.assertEqual(cycle.phase,SETTLED)
        self.assertEqual(cycle.settle_seq,0)

    def test_approved_review_starts_playback(self):
        cycle,pose=self.prepared()
        cycle.stage_collect([pose]*3, {'accepted':True},1,0)
        self.assertTrue(cycle.note_collect_review(True,{'support_slip_m':.001},1,0))
        self.assertEqual(cycle.phase,'collecting')

    def test_new_move_invalidates_pending_vrm_approval(self):
        cycle,pose=self.prepared()
        cycle.stage_collect([pose]*3, {'accepted':True},1,0)
        cycle.begin_move([1,0],True,2)
        self.assertFalse(cycle.note_collect_review(True,{},1,0))
        self.assertEqual(cycle.phase,'moving')
