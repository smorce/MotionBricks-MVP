import unittest
from frame_pipeline import FramePipeline

class PipelineTests(unittest.TestCase):
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
