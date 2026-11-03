"""診断のJSON化と保存を推論経路から外す。"""
import json
import logging
from queue import Queue, Full
from threading import Thread
from pathlib import Path
import time
import numpy as np

class ReplayWriter:
    def __init__(self, capacity=8):
        self.queue = Queue(capacity)
        self.dropped = 0
        self.failed = 0
        self.last_save_ms = 0.
        self.thread = Thread(target=self._run, name='replay-writer', daemon=True)
        self.thread.start()

    def submit(self, path, payload):
        try:
            self.queue.put_nowait((Path(path), payload))
            return True
        except Full:
            self.dropped += 1
            logging.getLogger('roze').warning('Replay save queue is full')
            return False

    def _run(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                path, payload = item
                start = time.perf_counter()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                    default=lambda value: value.tolist() if isinstance(value, np.ndarray) else value.item()), encoding='utf-8')
                self.last_save_ms = (time.perf_counter()-start)*1000
                from timings import TIMINGS
                TIMINGS.record("replay_save", self.last_save_ms)
            except Exception:
                self.failed += 1
                logging.getLogger('roze').exception('Replay save failed')
            finally:
                self.queue.task_done()

    def flush(self):
        self.queue.join()

WRITER = ReplayWriter()
