"""推論プロセスが確定した区間だけを配信する有界バッファ。"""
from collections import deque
from threading import Condition

TERMINAL = {'idle', 'settled', 'stop_failed', 'collect_preparing', 'pose_done'}

class FramePipeline:
    def __init__(self, capacity=120, prefill=90):
        self.capacity, self.prefill = capacity, prefill
        self.condition = Condition()
        self.frames = deque()
        self.events = []
        self.epoch = None
        self.playing = False
        self.closed = False
        self.underflows = 0

    def begin(self, epoch):
        with self.condition:
            self.epoch = epoch
            self.frames.clear()
            self.events.clear()
            self.playing = False
            self.condition.notify_all()

    def event(self, message, epoch):
        with self.condition:
            if epoch == self.epoch:
                self.events.append(message)

    def offer(self, message, checkpoint, epoch):
        with self.condition:
            while not self.closed and epoch == self.epoch and (len(self.frames) >= self.capacity or (self.frames and self.frames[-1][0].get('phase') in TERMINAL)):
                self.condition.wait(.05)
            if self.closed or epoch != self.epoch:
                return False
            self.frames.append((message, checkpoint, self.events))
            self.events = []
            self.condition.notify_all()
            return True

    def take(self):
        with self.condition:
            if not self.playing:
                self.playing = len(self.frames) >= self.prefill or any(f[0].get('phase') in TERMINAL for f in self.frames)
            if not self.playing:
                return None
            if not self.frames:
                self.underflows += 1
                self.playing = False
                return None
            result = self.frames.popleft()
            if result[0].get('phase') in TERMINAL:
                self.playing = False
            self.condition.notify_all()
            return result

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class ProcessOutput:
    """単一推論プロセスから確定区間を渡す。要求更新後の結果は送らない。"""
    def __init__(self, output, epoch, closed):
        self.output, self.epoch, self.closed = output, epoch, closed
        self.events = []

    def is_current(self, epoch):
        return not self.closed.is_set() and (epoch if epoch is not None else -1) == self.epoch.value

    def event(self, message, epoch):
        if self.is_current(epoch):
            self.events.append(message)

    def offer(self, message, checkpoint, epoch):
        from queue import Full
        from timings import TIMINGS
        identity = epoch if epoch is not None else -1
        events, self.events = self.events, []
        metrics = None
        if message['sequence'] % 60 == 0:
            from replay_writer import WRITER
            metrics = dict(stages=TIMINGS.summary(), replay_save_ms=WRITER.last_save_ms,
                           replay_dropped=WRITER.dropped, replay_failed=WRITER.failed)
        packet = (epoch, message, checkpoint, events, metrics)
        while not self.closed.is_set() and identity == self.epoch.value:
            try:
                self.output.put(packet, timeout=.05)
                return True
            except Full:
                pass
        return False


class CheckpointHistory:
    """配信済み連番に、表示元の姿勢と推論履歴を対応づける。"""
    def __init__(self, capacity=240):
        self.capacity = capacity
        self.snapshots = {}

    def add(self, sequence, move_id, checkpoint):
        self.snapshots[(sequence, move_id)] = checkpoint
        if len(self.snapshots) > self.capacity:
            self.snapshots.pop(next(iter(self.snapshots)))

    def resolve(self, sequence, move_id):
        return self.snapshots.get((sequence, move_id))
