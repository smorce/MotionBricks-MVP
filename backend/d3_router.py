"""d3-mini pose choice from an explicit, bounded catalog. No vision input is sent."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CATALOG = Path(__file__).with_name('poseloom_catalog.json')
DEFAULT_BASE_URL = 'http://127.0.0.1:8080'
DEFAULT_TIMEOUT_S = 60.0
# 候補が最大24件あると、正しい選択でも confidence は 0.4 前後に留まる。
MIN_CONFIDENCE = 0.35


def load_catalog() -> list[dict]:
    data = json.loads(CATALOG.read_text(encoding='utf-8'))
    return [x for x in data if isinstance(x, dict) and {'id', 'name', 'category'} <= x.keys()]


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
    elapsed_ms: float = 0.0
    category: str = ''
    catalog_size: int = 0


# 正解は単一 ID ではなく、ゾーンに合うカテゴリへ入っていること。
LABELED_CASES = (
    {"zone": "floor", "intent": "stand and wait", "distance": 1.2, "click": (0.4, -0.2), "expect": ("立つ", "待つ")},
    {"zone": "chair", "intent": "sit on the chair", "distance": 2.4, "click": (1.5, 0.2), "expect": ("座", "椅子")},
    {"zone": "reaction", "intent": "wave hello", "distance": 3.5, "click": (-0.8, 1.1), "expect": ("会話", "手", "振る")},
)


def _preferred(options: list[dict]) -> dict:
    return next((p for p in options if p['id'] == 'F001'), options[0])


def _timed(decision: Decision, started: float) -> Decision:
    decision.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return decision


def choose_pose(
    zone: str,
    intent: str,
    distance: float,
    catalog: list[dict],
    click_x: float | None = None,
    click_y: float | None = None,
    pose_summary: str | None = None,
) -> Decision:
    started = time.perf_counter()
    options = shortlist(catalog, zone)
    if not options:
        return _timed(Decision('F001', '自然に立つ', 0.0, 'fallback'), started)
    preferred = _preferred(options)

    base_url = os.getenv('D3_API_URL', DEFAULT_BASE_URL).rstrip('/')
    if not base_url:
        return _timed(Decision(preferred['id'], preferred['name'], 0.0, 'fallback-no-api'), started)

    criteria = {p['id']: f"{p['name']} / {p['category']}" for p in options}
    body = {
        'state': {
            'interaction_zone': zone,
            'user_intent': intent,
            'distance_m': round(distance, 2),
            'click_x': None if click_x is None else round(float(click_x), 2),
            'click_y': None if click_y is None else round(float(click_y), 2),
            'current_pose': pose_summary or 'unknown',
            'character': 'one human avatar',
            'goal': 'Select a plausible pose to reach AFTER movement, not a locomotion clip',
        },
        'questions': {
            'arrival_pose': {
                'type': 'choice',
                'instructions': (
                    'Choose the most natural end pose for this action and zone. '
                    'Avoid motion-only still frames for an arrival pose.'
                ),
                'criteria': criteria,
            }
        },
        'contexts': {
            'zone_and_intent': {
                'required': ['interaction_zone', 'user_intent', 'distance_m'],
                'description': 'ゾーン・意図・距離だけ。キャラクター説明は読まない。',
            },
            'zone_intent_and_pose': {
                'required': ['interaction_zone', 'user_intent', 'distance_m', 'click_x', 'click_y', 'current_pose'],
                'description': 'ゾーン・意図・距離に加え、クリック位置と現在姿勢。',
            },
            'full': {
                'required': [
                    'interaction_zone',
                    'user_intent',
                    'distance_m',
                    'click_x',
                    'click_y',
                    'current_pose',
                    'character',
                    'goal',
                ],
                'description': 'クリック位置、現在姿勢、キャラクター目標を含む。',
            },
        },
    }

    headers = {'Content-Type': 'application/json'}
    api_key = os.getenv('DECISION_API_KEY', '')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    timeout_s = float(os.getenv('D3_API_TIMEOUT', str(DEFAULT_TIMEOUT_S)))
    req = urllib.request.Request(
        f'{base_url}/v1/two-stage',
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            answer = json.load(response)['answers']['arrival_pose']
        pose_id = answer.get('choice')
        confidence = float(answer.get('confidence', 0.0))
        if pose_id not in criteria or confidence < MIN_CONFIDENCE:
            return _timed(Decision(preferred['id'], preferred['name'], confidence, 'fallback-low-confidence'), started)
        pose = next(p for p in options if p['id'] == pose_id)
        return _timed(Decision(pose_id, pose['name'], confidence, 'd3-mini'), started)
    except (OSError, urllib.error.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return _timed(Decision(preferred['id'], preferred['name'], 0.0, 'fallback-api-error'), started)


def confidence_floor(option_count: int) -> float:
    """候補数に応じた採用しきい値。24件前後は 0.35、それ以上は一様分布より明確な山だけ通す。"""
    count = max(1, int(option_count))
    if count <= 24:
        return MIN_CONFIDENCE
    return max(0.04, min(MIN_CONFIDENCE, 3.0 / count))


def _pose_text(pose: dict) -> str:
    features = pose.get('features') or []
    return f"{pose.get('name', '')} {pose.get('category', '')} {' '.join(features)}"


def _fallback_pose(catalog: list[dict], hints: list[str]) -> dict:
    usable = [hint for hint in hints if hint]
    def score(pose: dict) -> int:
        text = _pose_text(pose)
        return sum(1 for hint in usable if hint in text)
    best = max((score(pose) for pose in catalog), default=0)
    pool = [pose for pose in catalog if score(pose) == best] or list(catalog)
    daily = [pose for pose in pool if str(pose.get('category', '')).startswith('日常')]
    return sorted(daily or pool, key=lambda pose: pose['id'])[0]


def _post_answers(base_url: str, body: dict) -> dict:
    headers = {'Content-Type': 'application/json'}
    api_key = os.getenv('DECISION_API_KEY', '')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    timeout_s = float(os.getenv('D3_API_TIMEOUT', str(DEFAULT_TIMEOUT_S)))
    req = urllib.request.Request(
        f'{base_url}/v1/two-stage',
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        return json.load(response)['answers']


def _choice_body(state: dict, question_id: str, instructions: str, criteria: dict[str, str]) -> dict:
    return {
        'state': state,
        'questions': {
            question_id: {
                'type': 'choice',
                'instructions': instructions,
                'criteria': criteria,
            }
        },
        'contexts': {
            'scene': {
                'required': ['usecase', 'user_intent', 'catalog_size', 'distance_m'],
                'description': '場面・意図・カタログ件数・距離。',
            },
            'scene_and_pose': {
                'required': [
                    'usecase',
                    'user_intent',
                    'catalog_size',
                    'distance_m',
                    'click_x',
                    'click_y',
                    'current_pose',
                ],
                'description': '場面に加え、クリック位置と現在姿勢。',
            },
        },
    }


def choose_arrival_pose(
    usecase: dict,
    distance: float,
    catalog: list[dict],
    click_x: float | None = None,
    click_y: float | None = None,
    pose_summary: str | None = None,
) -> Decision:
    """カタログ全件をカテゴリに分け、d3-mini に到着ポーズを1件選ばせる。"""
    started = time.perf_counter()
    catalog_size = len(catalog)
    hints = list(usecase.get('hints') or ['立つ'])

    def pack(pose: dict, confidence: float, backend: str, category: str = '') -> Decision:
        return _timed(
            Decision(
                pose['id'],
                pose['name'],
                confidence,
                backend,
                category=category or str(pose.get('category', '')),
                catalog_size=catalog_size,
            ),
            started,
        )

    if not catalog:
        return pack({'id': 'F001', 'name': '自然に立つ', 'category': ''}, 0.0, 'fallback')
    picked = _fallback_pose(catalog, hints)
    base_url = os.getenv('D3_API_URL', DEFAULT_BASE_URL).rstrip('/')
    if not base_url:
        return pack(picked, 0.0, 'fallback-no-api')

    grouped: dict[str, list[dict]] = {}
    for pose in catalog:
        grouped.setdefault(pose['category'], []).append(pose)
    state = {
        'usecase': usecase.get('title') or usecase.get('id') or 'cafe',
        'user_intent': str(usecase.get('intent') or '')[:400],
        'catalog_size': catalog_size,
        'distance_m': round(float(distance), 2),
        'click_x': None if click_x is None else round(float(click_x), 2),
        'click_y': None if click_y is None else round(float(click_y), 2),
        'current_pose': pose_summary or 'unknown',
        'character': 'one human avatar',
        'goal': 'Select one static arrival pose after walking, from the full catalog',
    }
    category_criteria = {
        category: f"{len(poses)}件。例: " + '、'.join(pose['name'] for pose in poses[:4])
        for category, poses in grouped.items()
    }
    try:
        category_answer = _post_answers(
            base_url,
            _choice_body(
                state,
                'pose_category',
                (
                    f'カタログ全{catalog_size}件は次のカテゴリに分かれています。'
                    'このカフェの場面に着いたあと、一人で取る静止ポーズとして最も自然なカテゴリを1つ選んでください。'
                    '同じように合うなら日常・動作を優先し、格闘・寝姿・グラビア・二人用は場面に明らかに合うときだけ選んでください。'
                ),
                category_criteria,
            ),
        )['pose_category']
        category = category_answer.get('choice')
        category_confidence = float(category_answer.get('confidence', 0.0))
    except (OSError, urllib.error.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return pack(picked, 0.0, 'fallback-api-error')
    if category not in grouped or category_confidence < confidence_floor(len(grouped)):
        return pack(picked, category_confidence, 'fallback-low-confidence')

    poses = grouped[category]
    pose_criteria = {pose['id']: f"{pose['name']} / {pose['category']}" for pose in poses}
    try:
        pose_answer = _post_answers(
            base_url,
            _choice_body(
                state,
                'arrival_pose',
                (
                    f'カテゴリ「{category}」の全{len(poses)}件から、到着後のゴールポーズを1つ選んでください。'
                    '歩行や走行の途中の静止画ではなく、着いたあとに保つ姿勢です。'
                    f'カタログ全体は{catalog_size}件で、このカテゴリ以外は候補にしません。'
                ),
                pose_criteria,
            ),
        )['arrival_pose']
        pose_id = pose_answer.get('choice')
        pose_confidence = float(pose_answer.get('confidence', 0.0))
    except (OSError, urllib.error.HTTPError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return pack(_fallback_pose(poses, hints), 0.0, 'fallback-api-error', category)
    match = next((pose for pose in poses if pose['id'] == pose_id), None)
    if match is None or pose_confidence < confidence_floor(len(poses)):
        return pack(_fallback_pose(poses, hints), pose_confidence, 'fallback-low-confidence', category)
    return pack(match, pose_confidence, 'd3-mini', category)


def pose_matches(pose: dict, expected: tuple[str, ...]) -> bool:
    text = f"{pose.get('name', '')} {pose.get('category', '')}"
    return any(token in text for token in expected)


def measure_selection(catalog: list[dict], cases=LABELED_CASES) -> dict:
    """選択時間と、ゾーンに対するカテゴリ一致率を測る。"""
    rows = []
    for case in cases:
        click_x, click_y = case["click"]
        decision = choose_pose(
            case["zone"],
            case["intent"],
            case["distance"],
            catalog,
            click_x=click_x,
            click_y=click_y,
            pose_summary="root=(0.00,0.00) facing=0deg height=0.95",
        )
        chosen = next((p for p in catalog if p["id"] == decision.pose_id), None)
        ok = chosen is not None and pose_matches(chosen, case["expect"])
        rows.append(
            {
                "zone": case["zone"],
                "pose_id": decision.pose_id,
                "backend": decision.backend,
                "elapsed_ms": round(decision.elapsed_ms, 2),
                "confidence": decision.confidence,
                "correct": ok,
            }
        )
    elapsed = [row["elapsed_ms"] for row in rows]
    return {
        "count": len(rows),
        "correct": sum(1 for row in rows if row["correct"]),
        "accuracy": (sum(1 for row in rows if row["correct"]) / len(rows)) if rows else 0.0,
        "mean_elapsed_ms": (sum(elapsed) / len(elapsed)) if elapsed else 0.0,
        "cases": rows,
    }
