"""PoseLoom のコレクションページからメタデータだけを取り込む。BVH の変換はしない。"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from catalog_html import parse_collection_html

OUT = Path(__file__).with_name("poseloom_catalog.json")
COLLECTIONS = (
    ("日常・動作", "https://pose-loom.pages.dev/collection-general"),
    ("バスケットボール", "https://pose-loom.pages.dev/collection-basketball"),
    ("寝姿・床ヨガ", "https://pose-loom.pages.dev/collection-floor_yoga"),
    ("グラビア・撮影", "https://pose-loom.pages.dev/collection-gravure"),
    ("床に座る", "https://pose-loom.pages.dev/collection-floor_sitting"),
    ("二人の配置", "https://pose-loom.pages.dev/collection-pairs"),
    ("基本モデル・サンプル", "https://pose-loom.pages.dev/collection-models"),
    ("格闘スポーツ", "https://pose-loom.pages.dev/collection-martial"),
)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "roze-motion-mvp/0.1 (local evaluation)"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def load_entries() -> list[dict]:
    entries = []
    seen = set()
    for collection, url in COLLECTIONS:
        rows = parse_collection_html(fetch(url), collection, url)
        if len(rows) < 1 and collection != "基本モデル・サンプル":
            raise RuntimeError(f"Parsed no poses from {url}")
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            entries.append(row)
    if len(entries) < 25:
        raise RuntimeError(f"Parsed only {len(entries)} poses. Existing catalog left untouched.")
    return entries


def main():
    entries = load_entries()
    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(entries)} entries to {OUT}. Spot-check labels before use.")


if __name__ == "__main__":
    main()
