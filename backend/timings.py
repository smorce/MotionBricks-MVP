"""各段階の所要時間を有界履歴で集計する。"""
from collections import defaultdict, deque
from contextlib import contextmanager
from threading import Lock
import time

class Timings:
    def __init__(self):
        self.values = defaultdict(lambda: deque(maxlen=4096))
        self.lock = Lock()

    def record(self, stage, ms):
        with self.lock:
            self.values[stage].append(float(ms))

    @contextmanager
    def measure(self, stage):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, (time.perf_counter()-start)*1000)

    def summary(self):
        with self.lock:
            values = {k: sorted(v) for k, v in self.values.items()}
        return {k: dict(count=len(v), p95_ms=v[min(len(v)-1,int(len(v)*.95))], max_ms=v[-1])
                for k,v in values.items() if v}

TIMINGS = Timings()
