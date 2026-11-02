"""人間の評価と保存状態の近傍だけを使用する実験用選択器。"""
import json
from pathlib import Path
from zipfile import ZipFile
import numpy as np

LAB = Path(__file__).resolve().parents[1] / 'metrics/stop-distance-lab'


def load_candidates(directory=LAB):
    summary = json.loads((directory / 'human-review-summary.json').read_text(encoding='utf-8'))
    rows = []
    with ZipFile(directory / 'measurements.zip') as measurements, ZipFile(directory / 'human-reviews.zip') as reviews:
        for group in summary['states']:
            prefix = '' if group['state'] == 'stop-distance-lab' else group['state'] + '/'
            data = json.loads(measurements.read(prefix + 'comparison.json'))
            review = json.loads(reviews.read(prefix + 'reviews.json'))
            if review['source_state_id'] != data['source_state_id']:
                raise ValueError('Review source state mismatch')
            marks = {r['id']: r for r in review['reviews']}
            for candidate in data['candidates']:
                if candidate['id'] not in group['natural_ids']:
                    continue
                if marks[candidate['id']]['mark'] != 'good':
                    raise ValueError('Summary differs from human review')
                rows.append(dict(state=group['state'], source_state_id=data['source_state_id'],
                                 context=data['context'], review=marks[candidate['id']],
                                 specification={k: candidate[k] for k in ('id', 'mode', 'distance_m', 'pinned', 'target_pose_type', 'generation_settings')}))
    if len(rows) != 11:
        raise ValueError('Expected eleven visually approved candidates')
    return rows


def similarity(state, reference):
    if any(state.get(k) != reference.get(k) for k in ('support', 'phase')):
        return None
    a, b = np.asarray(state.get('recent_poses', [])), np.asarray(reference['recent_poses'])
    if a.shape != b.shape or a.shape[0] != 4 or not np.isfinite(a).all():
        return None
    contacts = np.asarray(state.get('contacts', []))
    saved = np.asarray(reference['contacts'])
    if contacts.shape != saved.shape or not np.array_equal(contacts >= .5, saved >= .5):
        return None
    speed = abs(state['speed_mps'] - reference['speed_mps']) / .2
    direction = np.asarray(state['direction']); other = np.asarray(reference['direction'])
    angle = np.arccos(np.clip(np.dot(direction, other) / max(1e-9, np.linalg.norm(direction)*np.linalg.norm(other)), -1, 1)) / .26
    qa, qb = a[..., 3:], b[..., 3:]
    dots = np.sum(qa*qb, axis=-1) / np.maximum(1e-9, np.linalg.norm(qa, axis=-1)*np.linalg.norm(qb, axis=-1))
    rotation = float(np.sqrt(np.mean((2*np.arccos(np.clip(abs(dots), 0, 1)))**2))) / .18
    pa, pb = a[..., :3].copy(), b[..., :3].copy()
    pa[:, 0, :2] -= a[-1, 0, :2]; pb[:, 0, :2] -= b[-1, 0, :2]
    position = float(np.sqrt(np.mean((pa-pb)**2))) / .025
    components = [speed, angle, rotation, position]
    if not np.isfinite(components).all() or max(components) > 1:
        return None
    return float(1 - np.mean(components))


def select_stop(state, remaining_m, candidates):
    matches = []
    for row in candidates:
        score = similarity(state, row['context'])
        x = row['specification']['distance_m']
        if score is not None and x <= remaining_m + .04:
            matches.append((row, score))
    if not matches:
        return dict(status='unknown', human_rating='unknown', reason='No similar reviewed state and distance', state_features=state)
    row, score = min(matches, key=lambda pair: (abs(remaining_m-pair[0]['specification']['distance_m']), -pair[1]))
    x = row['specification']['distance_m']
    start = np.asarray(state['root'])[:2] + np.asarray(state['direction'])[:2] * max(0, remaining_m-x)
    return dict(status='matched', human_rating='unknown', candidate=row['specification'], x_m=x,
                stop_start_xy=start.tolist(), target_pose_type=row['specification']['target_pose_type'],
                target_pose_distance_m=remaining_m, review=row['review'], source_state_id=row['source_state_id'],
                similarity=score, action='walk' if remaining_m > x+.04 else 'stop', state_features=state)


def load_additional_reviews(path):
    """新しい人間の評価も、その実行時の姿勢だけに関連づける。"""
    path = Path(path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding='utf-8'))
    rows = []
    for review in payload['reviews']:
        context = review.get('learning_context') or {}
        selected = context.get('selection') or {}
        if review.get('mark') != 'good' or selected.get('status') != 'matched':
            continue
        rows.append(dict(state=review['id'], source_state_id=payload['source_state_id'],
                         context=selected['state_features'], review=review, specification=selected['candidate']))
    return rows
