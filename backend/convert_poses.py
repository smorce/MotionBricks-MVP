"""PoseLoom BVH を SOMA 静止姿勢 JSON へ変換する。

最初の確認用 ID だけを変換し、--all でカタログ全件（単一骨格）へ広げる。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from bvh_io import parse_bvh
from retarget_mhr import retarget_clip
from soma_skeleton import SOMA_JOINT_NAMES

CATALOG = Path(__file__).with_name("poseloom_catalog.json")
OUT_DIR = Path(__file__).with_name("soma_poses")
PILOT_IDS = (
    "F001", "F002", "F003", "F004", "F005", "F006",
    "F011", "F012", "F017",
    "F031", "F032", "F033", "F036", "F038", "F039",
    "F042", "F043", "F045",
)


def download(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "roze-motion-mvp/0.1 (local evaluation)"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def convert_entry(entry: dict) -> str:
    text = download(entry["bvh_url"])
    clip = parse_bvh(text)
    transforms = retarget_clip(clip)
    payload = {"joint_names": SOMA_JOINT_NAMES, "local_transforms": transforms}
    path = OUT_DIR / f"{entry['id']}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def main(argv: list[str]) -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    wanted = {entry["id"] for entry in catalog} if "--all" in argv else set(PILOT_IDS)
    OUT_DIR.mkdir(exist_ok=True)
    written = 0
    skipped = []
    for entry in catalog:
        if entry["id"] not in wanted or "bvh_url" not in entry:
            continue
        try:
            convert_entry(entry)
            written += 1
            print(entry["id"])
        except (OSError, urllib.error.URLError, ValueError, KeyError) as exc:
            skipped.append(f"{entry['id']}: {exc}")
            print(f"skip {entry['id']}: {exc}", file=sys.stderr)
    print(f"Wrote {written} poses to {OUT_DIR}. Skipped {len(skipped)}.")


if __name__ == "__main__":
    main(sys.argv[1:])
