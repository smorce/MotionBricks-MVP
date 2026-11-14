import unittest
from frame_pipeline import FramePipeline

class PipelineTests(unittest.TestCase):
    def test_default_prefill_is_low_latency(self):
        pipe = FramePipeline()
        self.assertEqual(pipe.prefill, 6)

    def test_begin_returns_cleared_frame_count(self):
        pipe = FramePipeline(capacity=8, prefill=4)
        pipe.begin(1)
        pipe.offer({'type': 'frame', 'phase': 'moving'}, 'a', 1)
        pipe.offer({'type': 'frame', 'phase': 'moving'}, 'b', 1)
        self.assertEqual(pipe.begin(2), 2)
        self.assertEqual(pipe.begin(3), 0)

    def test_initial_epoch_can_release_idle_frames(self):
        pipe = FramePipeline(capacity=4, prefill=1)
        pipe.begin(-1)
        self.assertTrue(pipe.offer({'type': 'frame', 'phase': 'idle'}, 'initial', -1))
        self.assertEqual(pipe.take()[1], 'initial')

    def test_buffers_committed_frames_and_rejects_old_request(self):
        pipe = FramePipeline(capacity=4, prefill=2)
        pipe.begin(1)
        self.assertTrue(pipe.offer({'type':'frame','gait':{'move_id':1},'phase':'moving'}, 'a', 1))
        self.assertIsNone(pipe.take())
        pipe.offer({'type':'frame','gait':{'move_id':1},'phase':'moving'}, 'b', 1)
        self.assertEqual(pipe.take()[1], 'a')
        pipe.begin(2)
        self.assertFalse(pipe.offer({'type':'frame'}, 'old', 1))
        self.assertIsNone(pipe.take())

    def test_short_move_is_released_only_when_terminal_is_committed(self):
        pipe=FramePipeline(capacity=4,prefill=3)
        pipe.begin(1)
        pipe.offer({'type':'frame','phase':'moving'}, 'start',1)
        pipe.offer({'type':'frame','phase':'settled'}, 'end',1)
        self.assertEqual(pipe.take()[1],'start')
        self.assertEqual(pipe.take()[1],'end')
        self.assertIsNone(pipe.take())

    def test_events_follow_their_frame_and_invalidation_discards_them(self):
        pipe=FramePipeline(capacity=4,prefill=1)
        pipe.begin(1)
        pipe.event({'type':'arrived'},1)
        pipe.offer({'type':'frame','phase':'settled'}, 'end',1)
        self.assertEqual(pipe.take()[2],[{'type':'arrived'}])
        pipe.event({'type':'arrived'},1)
        pipe.begin(2)
        pipe.offer({'type':'frame','phase':'moving'}, 'new',2)
        self.assertEqual(pipe.take()[2],[])


class GenerationIdentityTests(unittest.TestCase):
    def test_new_move_discards_queued_frames_but_keeps_direct_messages(self):
        from engine import _discard_queued_frames
        from queue import Queue

        output = Queue()
        output.put((1, {'type': 'frame', 'sequence': 1}, None, [], None))
        output.put(('direct', {'type': 'rig'}))
        output.put((1, {'type': 'frame', 'sequence': 2}, None, [], None))

        self.assertEqual(_discard_queued_frames(output), 2)
        self.assertEqual(output.get_nowait()[0], 'direct')
        self.assertTrue(output.empty())

    def test_intake_waits_for_terminal_frame_to_be_taken_before_next_frame(self):
        from engine import _intake_output
        from queue import Queue
        from types import SimpleNamespace

        output = Queue()
        epoch = SimpleNamespace(value=1)
        pipe = FramePipeline(capacity=4, prefill=1)
        pipe.begin(1)
        pipe.offer({'type': 'frame', 'phase': 'settled'}, 'terminal', 1)
        output.put((1, {'type': 'frame', 'phase': 'moving'}, 'next', [], None))

        self.assertEqual(_intake_output(output, pipe, epoch, lambda _message: None), 0)
        self.assertEqual(pipe.take()[1], 'terminal')
        self.assertEqual(_intake_output(output, pipe, epoch, lambda _message: None), 1)
        self.assertEqual(pipe.take()[1], 'next')

    def test_intake_drains_a_batch_larger_than_the_old_four_frame_limit(self):
        from engine import _intake_output
        from queue import Queue
        from types import SimpleNamespace

        output = Queue()
        epoch = SimpleNamespace(value=1)
        pipe = FramePipeline(capacity=16, prefill=1)
        pipe.begin(1)
        for sequence in range(8):
            output.put((1, {'type': 'frame', 'sequence': sequence}, sequence, [], None))

        count = _intake_output(output, pipe, epoch, lambda _message: None)

        self.assertEqual(count, 8)
        self.assertEqual(len(pipe.frames), 8)

    def test_delayed_result_from_old_request_is_not_queued(self):
        from frame_pipeline import ProcessOutput
        from queue import Queue
        from threading import Event
        from types import SimpleNamespace
        output = Queue()
        epoch = SimpleNamespace(value=1)
        producer = ProcessOutput(output, epoch, Event())
        producer.event({'type': 'arrived'}, 1)
        epoch.value = 2
        self.assertFalse(producer.offer({'type': 'frame', 'sequence': 1}, 'old endpoint', 1))
        self.assertTrue(output.empty())
        self.assertTrue(producer.offer({'type': 'frame', 'sequence': 2}, 'new endpoint', 2))
        packet = output.get_nowait()
        self.assertEqual(packet[2], 'new endpoint')
        self.assertEqual(packet[3], [])

    def test_cancelled_search_never_starts_inference(self):
        from stop_candidate_search import search_candidates
        from unittest.mock import Mock
        generate = Mock()
        result = search_candidates([{}], Mock(), generate, Mock(), cancelled=lambda: True)
        generate.assert_not_called()
        self.assertIsNone(result['frames'])
        self.assertIsNone(result['selected'])

    def test_visual_stop_generate_checks_cancellation(self):
        from stop_distance_probe import pure_generate
        from unittest.mock import Mock
        import numpy as np
        pose = np.zeros((30, 7), dtype=np.float32)
        pose[:, 6] = 1.0
        replay = dict(pose=pose.tolist(), metadata=dict(goal=[0.2, 0.0], parents=[-1]+[0]*29,
                      names=['Hips']+[f'J{i}' for i in range(29)], ground=dict(floor_z=0.0, offsets={'left':{'ankle':0,'toe':0},'right':{'ankle':0,'toe':0}}),
                      contacts=[1,1,1,1], support='left'))
        character = Mock()
        character.current_pose.numpy.return_value = pose
        character.current_foot_contacts.numpy.return_value = np.array([1,1,1,1])
        character.time_to_transition.return_value = 1.0
        rt = dict(wp=Mock(), IKPin=Mock(NONE=0, LEFT_FOOT=1, RIGHT_FOOT=2), TargetPoseInferenceParams=Mock())
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            pure_generate(character, replay, dict(mode='A', pinned=False), rt, np.zeros((4, 30, 7)), cancelled=lambda: True)

    def test_generation_packet_reports_writer_owned_by_inference_process(self):
        from frame_pipeline import ProcessOutput
        from queue import Queue
        from threading import Event
        from types import SimpleNamespace
        from unittest.mock import patch
        output = Queue()
        producer = ProcessOutput(output, SimpleNamespace(value=1), Event())
        writer = SimpleNamespace(last_save_ms=12., dropped=2, failed=1)
        with patch('replay_writer.WRITER', writer):
            producer.offer({'type':'frame', 'sequence':60}, 'endpoint', 1)
        metrics = output.get_nowait()[4]
        self.assertEqual(metrics['replay_dropped'], 2)
        self.assertEqual(metrics['replay_failed'], 1)
        self.assertEqual(metrics['replay_save_ms'], 12.)

    def test_initial_generation_packet_uses_sentinel_identity(self):
        from frame_pipeline import ProcessOutput
        from queue import Queue
        from threading import Event
        from types import SimpleNamespace

        output = Queue()
        producer = ProcessOutput(output, SimpleNamespace(value=-1), Event())
        producer.offer({'type': 'frame', 'sequence': 0}, 'initial', None)

        self.assertEqual(output.get_nowait()[0], -1)

    def test_intake_skips_many_stale_packets_and_tracks_consumed(self):
        from engine import _intake_output
        from queue import Queue
        from types import SimpleNamespace

        output = Queue()
        epoch = SimpleNamespace(value=2)
        consumed = SimpleNamespace(value=0)
        pipe = FramePipeline(capacity=16, prefill=2)
        pipe.begin(2)
        for seq in range(80):
            output.put((1, {'type': 'frame', 'sequence': seq, 'phase': 'settled'}, None, [], None))
        output.put((2, {'type': 'frame', 'sequence': 80, 'phase': 'moving'}, 'c0', [], None))
        output.put((2, {'type': 'frame', 'sequence': 81, 'phase': 'moving'}, 'c1', [], None))

        count = _intake_output(output, pipe, epoch, lambda _m: None, consumed=consumed)
        self.assertEqual(count, 2)
        self.assertEqual(consumed.value, 80)
        self.assertEqual(len(pipe.frames), 2)

    def test_pacer_caps_terminal_in_flight_to_two_and_wakes_on_consume(self):
        from frame_pipeline import GenerationPacer
        from threading import Event
        from types import SimpleNamespace

        consumed = SimpleNamespace(value=0)
        wake = Event()
        pacer = GenerationPacer(consumed, wake)
        pacer.produced = 2
        self.assertTrue(pacer.should_wait('settled'))
        self.assertFalse(pacer.should_wait('moving'))
        consumed.value = 1
        self.assertFalse(pacer.should_wait('settled'))

        pacer.produced = 37
        self.assertTrue(pacer.should_wait('moving'))
        consumed.value = 2
        self.assertFalse(pacer.should_wait('moving'))


class DisplayCheckpointTests(unittest.TestCase):
    def test_reclick_restores_displayed_source_instead_of_newest_sent_frame(self):
        from frame_pipeline import CheckpointHistory
        history = CheckpointHistory(capacity=2)
        history.add(10, 1, 'displayed pose and history')
        history.add(11, 1, 'newer undisplayed pose')
        self.assertEqual(history.resolve(10,1),'displayed pose and history')
        self.assertIsNone(history.resolve(10,2))
        history.add(12,2,'new request')
        self.assertIsNone(history.resolve(10,1))


class StreamPayloadTests(unittest.TestCase):
    def test_large_learning_context_is_retained_only_in_diagnostics(self):
        from engine import _stream_selection
        selection = dict(status='matched', candidate={'id':'A'}, state_features={'recent_poses':[1]*1000},
                         review={'learning_context':{'recent_poses':[2]*1000}})
        compact = _stream_selection(selection)
        self.assertEqual(compact, dict(status='matched',candidate={'id':'A'}))
        self.assertIn('state_features',selection)
        self.assertIn('review',selection)
