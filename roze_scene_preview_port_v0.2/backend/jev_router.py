"""Jev pose choice from an explicit, bounded catalog. No vision input is sent."""
from __future__ import annotations
import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CATALOG = Path(__file__).with_name('poseloom_catalog.json')


def load_catalog() -> list[dict]:
    data = json.loads(CATALOG.read_text(encoding='utf-8'))
    return [x for x in data if isinstance(x, dict) and {'id','name','category'} <= x.keys()]


def shortlist(catalog: list[dict], zone: str, limit: int = 24) -> list[dict]:
    # The click location does NOT tell us what a photographed object is.
    # zone is an explicit user/UI annotation: floor / chair / reaction.
    hints = {
        'floor': ('立つ', '待つ', '立ち止まる'),
        'chair': ('椅子', '座'),
        'reaction': ('会話', '感情', 'リアクション'),
    }.get(zone, ('立つ', '待つ'))
    matched = [p for p in catalog if any(h in (p['name'] + p['category']) for h in hints)]
    return (matched or catalog)[:limit]


@dataclass
class Decision:
    pose_id: str
    pose_name: str
    confidence: float
    backend: str


def choose_pose(zone: str, intent: str, distance: float, catalog: list[dict]) -> Decision:
    options = shortlist(catalog, zone)
    if not options:
        return Decision('F001', '自然に立つ', 0.0, 'fallback')
    preferred = next((p for p in options if p['id'] == 'F001'), options[0])
    key = os.getenv('TYPESAFE_API_KEY', '')
    if not key:
        return Decision(preferred['id'], preferred['name'], 0.0, 'fallback-no-api-key')
    criteria = {p['id']: f"{p['name']} / {p['category']}" for p in options}
    body = {
        'model': 'jev-latest',
        'state': {
            'interaction_zone': zone,
            'user_intent': intent,
            'distance_m': round(distance, 2),
            'character': 'one human avatar',
            'goal': 'Select a plausible pose to reach AFTER movement, not a locomotion clip',
        },
        'questions': {
            'arrival_pose': {
                'type': 'choice',
                'instructions': 'Choose the most natural end pose for this action and zone. Avoid motion-only still frames for an arrival pose.',
                'criteria': criteria,
            }
        }
    }
    req = urllib.request.Request(
        'https://api.typesafe.ai/v1/systemone',
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=2.5) as response:
            answer = json.load(response)['answers']['arrival_pose']
        pose_id = answer.get('choice')
        confidence = float(answer.get('confidence', 0.0))
        if pose_id not in criteria or confidence < 0.55:
            return Decision(preferred['id'], preferred['name'], confidence, 'fallback-low-confidence')
        pose = next(p for p in options if p['id'] == pose_id)
        return Decision(pose_id, pose['name'], confidence, 'jev')
    except (OSError, KeyError, ValueError, TypeError):
        return Decision(preferred['id'], preferred['name'], 0.0, 'fallback-api-error')
