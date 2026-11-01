"""独立した再生器を要求する、上限付き候補探索。"""
import copy


def search_candidates(specifications, player_factory, generate, diagnose, limit=24):
    if not 1 <= limit <= 24:
        raise ValueError('Candidate limit must be between 1 and 24')
    rows, safe, players = [], [], []
    for specification in list(specifications)[:limit]:
        spec = copy.deepcopy(specification)
        player = player_factory(spec)
        if any(player is prior for prior in players):
            raise ValueError('Candidate players must be independent')
        players.append(player)
        try:
            frames = generate(player, spec)
            metrics = diagnose(frames)
            row = dict(specification=spec, metrics=metrics)
            if metrics['accepted']:
                safe.append((metrics.get('arrival_error_m', float('inf')),
                             metrics.get('support_drift_max_m', float('inf')), len(rows), frames))
        except Exception as exc:
            row = dict(specification=spec, metrics=dict(accepted=False, reason=str(exc)))
        rows.append(row)
    winner = min(safe, key=lambda row:row[:3]) if safe else None
    return dict(candidates=rows, selected=None if winner is None else winner[2],
                frames=None if winner is None else winner[3])
