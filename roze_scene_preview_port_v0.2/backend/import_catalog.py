"""Retrieve the searchable PoseLoom text catalog and extract ID, name and category.

This imports METADATA only. It does not convert the BVH skeleton to SOMA.
If the site HTML changes, review the generated JSON before using it.
"""
from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path

URL = 'https://pose-loom.pages.dev/search'
OUT = Path(__file__).with_name('poseloom_catalog.json')


def main():
    from bs4 import BeautifulSoup
    req = urllib.request.Request(URL, headers={'User-Agent':'roze-motion-mvp/0.1 (local evaluation)'})
    with urllib.request.urlopen(req, timeout=30) as res:
        soup = BeautifulSoup(res.read(), 'html.parser')
    # Prefer headings and their enclosing card. Name/category occur near each ID.
    text = soup.get_text('\n', strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    result = []
    seen = set()
    id_re = re.compile(r'^[A-Z]{1,4}\d{3}$')
    for i, line in enumerate(lines):
        if id_re.fullmatch(line) and line not in seen:
            nxt = lines[i+1:i+7]
            if not nxt: continue
            name = nxt[0]
            cat = next((s for s in nxt[1:] if '·' in s or '・' in s), '')
            if not cat: continue
            result.append({'id': line, 'name': name, 'category': cat})
            seen.add(line)
    if len(result) < 25:
        raise RuntimeError(f'Parsed only {len(result)} poses. Site markup likely changed; existing catalog left untouched.')
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {len(result)} entries to {OUT}. Please spot-check labels before use.')


if __name__ == '__main__':
    main()
