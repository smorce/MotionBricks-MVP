"""評価済み条件を優先し、未一致時は未評価のA方式を一度試す。"""
import numpy as np
from visual_stop_selector import select_stop, travel_relative_history

PREPARE_M = 1.2
FALLBACK_M = .6


def select_prepared_stop(state, remaining_m, candidates):
    a_candidates = [r for r in candidates if r['specification']['mode'] == 'A']
    strict = select_stop(state, remaining_m, a_candidates)
    if strict['status'] == 'matched':
        if remaining_m <= strict['x_m'] + .12:
            strict['action'] = 'stop'
        strict['selection_basis'] = 'reviewed_state_near_distance'
        strict['preparation_active'] = remaining_m <= PREPARE_M
        strict['distance_delta_m'] = remaining_m - strict['x_m']
        return strict
    current = travel_relative_history(state)
    if current is None:
        return strict

    def proximity(row):
        saved = row['context']
        history = travel_relative_history(saved)
        qa, qb = current[..., 3:], history[..., 3:]
        dots = np.sum(qa*qb, axis=-1) / np.maximum(1e-9, np.linalg.norm(qa, axis=-1)*np.linalg.norm(qb, axis=-1))
        rotation = float(np.sqrt(np.mean((2*np.arccos(np.clip(abs(dots), 0, 1)))**2)))
        speed = abs(state['speed_mps']-saved['speed_mps'])
        support = float(state['support'] != saved['support'])
        contacts = float(np.mean(abs(np.asarray(state['contacts'])-np.asarray(saved['contacts']))))
        distance = abs(min(remaining_m, FALLBACK_M)-row['specification']['distance_m'])
        return rotation/.18 + speed/.4 + support + contacts + distance/.3

    row = min(a_candidates, key=proximity)
    score = proximity(row)
    stopping = remaining_m <= FALLBACK_M
    x = min(FALLBACK_M, remaining_m)
    start = np.asarray(state['root'])[:2] + np.asarray(state['direction'])[:2]*max(0, remaining_m-x)
    return dict(status='experimental' if stopping else 'preparing', action='stop' if stopping else 'walk',
                preparation_active=remaining_m <= PREPARE_M, human_rating='unknown',
                candidate=row['specification'], x_m=x, reference_distance_m=row['specification']['distance_m'],
                reviewed_state=row['state'], source_state_id=row['source_state_id'], review=row['review'],
                similarity=None, reference_difference=score, selection_basis='unreviewed_a_fallback',
                distance_delta_m=remaining_m-row['specification']['distance_m'],
                target_pose_type='F001', target_pose_distance_m=remaining_m,
                stop_start_xy=start.tolist(), state_features=state)
