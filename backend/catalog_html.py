"""PoseLoom のコレクション HTML から ID・名前・カテゴリ・BVH URL を取る。"""
from __future__ import annotations

import re

_ROW = re.compile(r'<div class="row" id="([A-Za-z0-9_]+)">(.*?)</div>\s*</div>', re.S)
_NAME = re.compile(r"<h3>(.*?)</h3>\s*<small>(.*?)</small>", re.S)
_BVH = re.compile(r'href="([^"]+\.bvh)"')
_CATEGORY = re.compile(r"·\s*([^<]+)")


def features_for(name: str, category: str) -> list[str]:
    parts = re.split(r"[·・/,\s]+", f"{name} {category}")
    seen: set[str] = set()
    features: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            features.append(part)
    return features


def parse_collection_html(html: str, collection: str, page_url: str) -> list[dict]:
    base = page_url.rsplit("/", 1)[0]
    entries = []
    seen: set[str] = set()
    for pose_id, body in _ROW.findall(html):
        named = _NAME.search(body)
        if not named:
            continue
        name, small = named.group(1), named.group(2)
        hrefs = _BVH.findall(body)
        if not hrefs:
            continue
        subgroup = _CATEGORY.search(small)
        subgroup_name = subgroup.group(1).strip() if subgroup else small.strip()
        category = f"{collection} · {subgroup_name}" if collection else subgroup_name
        labels = [pose_id] if len(hrefs) == 1 else [f"{pose_id}_p{i}" for i in range(1, len(hrefs) + 1)]
        for label, href in zip(labels, hrefs):
            if label in seen:
                continue
            seen.add(label)
            person = "" if len(hrefs) == 1 else f"（人物{label.rsplit('_p', 1)[-1]}）"
            entry_name = f"{name.strip()}{person}"
            bvh_url = href if href.startswith("http") else f"{base}/{href.lstrip('./')}"
            entries.append(
                {
                    "id": label,
                    "name": entry_name,
                    "category": category,
                    "features": features_for(entry_name, category),
                    "bvh_url": bvh_url,
                }
            )
    return entries
