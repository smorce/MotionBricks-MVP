"""歩行・停止の計測行。GPU には依存しない。"""
from __future__ import annotations

import csv
import io
import json
import threading


class GaitLog:
    def __init__(self, limit: int = 4000) -> None:
        self.limit = limit
        self._rows: list[dict] = []
        self._lock = threading.Lock()

    def add(self, row: dict) -> None:
        with self._lock:
            self._rows.append(row)
            if len(self._rows) > self.limit:
                self._rows = self._rows[-self.limit :]

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    def to_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=False, indent=2)

    def to_csv(self) -> str:
        rows = self.snapshot()
        buffer = io.StringIO()
        fields = [
            "t", "phase", "mode", "playback", "official_state",
            "actual_speed_mps", "commanded_speed_mps",
            "left_planted", "right_planted", "contact_source",
            "left_x", "left_y", "left_z", "right_x", "right_y", "right_z",
            "left_slip_m", "right_slip_m", "stance_width_m",
            "stop_requested_s", "last_plant_s", "settled_s", "event",
            "root_x", "root_y", "goal_error_m", "stop_prediction_m", "stop_root_positions",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()


GAIT_LOG = GaitLog()
