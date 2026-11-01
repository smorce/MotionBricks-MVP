"""カフェ内のクリック場面。ポーズ候補はここでは絞らない。"""
from __future__ import annotations

import json
import math
from pathlib import Path

CASES_PATH = Path(__file__).with_name("cafe_usecases.json")
OPEN_FLOOR_ID = "open-floor"


def load_usecases() -> list[dict]:
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("cafe usecases must be a non-empty list")
    cases = [_normalize(row) for row in raw]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("cafe usecase ids must be unique")
    if not any(case["id"] == OPEN_FLOOR_ID and not case["marker"] for case in cases):
        raise ValueError("open-floor usecase must exist without a marker")
    if not any(case["marker"] for case in cases):
        raise ValueError("cafe usecases need at least one marker")
    return cases


def resolve_usecase(raw) -> dict:
    key = "" if raw is None else str(raw)
    cases = load_usecases()
    for case in cases:
        if case["id"] == key:
            return case
    for case in cases:
        if case["id"] == OPEN_FLOOR_ID:
            return case
    raise RuntimeError("open-floor usecase is missing")


def _normalize(row: dict) -> dict:
    if not isinstance(row, dict):
        raise ValueError("cafe usecase must be an object")
    case_id = row.get("id")
    title = row.get("title")
    intent = row.get("intent")
    hints = row.get("hints")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("cafe usecase id must be a non-empty string")
    if not isinstance(title, str) or not title:
        raise ValueError(f"{case_id}: title must be a non-empty string")
    if not isinstance(intent, str) or not intent:
        raise ValueError(f"{case_id}: intent must be a non-empty string")
    if not isinstance(hints, list) or not hints or any(not isinstance(hint, str) or not hint for hint in hints):
        raise ValueError(f"{case_id}: hints must be a non-empty list of strings")
    marker = bool(row.get("marker", "x" in row and "z" in row))
    case = {"id": case_id, "title": title, "intent": intent, "hints": list(hints), "marker": marker}
    if not marker:
        return case
    try:
        x = float(row["x"])
        z = float(row["z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{case_id}: marker needs finite x and z") from exc
    if not (math.isfinite(x) and math.isfinite(z)):
        raise ValueError(f"{case_id}: marker needs finite x and z")
    case["x"] = x
    case["z"] = z
    return case
