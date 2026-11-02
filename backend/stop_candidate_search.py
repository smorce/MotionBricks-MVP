"""独立した再生器を要求する、上限付き候補探索。"""

import copy
import time


def search_candidates(
    specifications, player_factory, generate, diagnose, limit=24, stop_on_first=False
):
    if not 1 <= limit <= 24:
        raise ValueError("Candidate limit must be between 1 and 24")
    rows, safe, players = [], [], []
    for specification in list(specifications)[:limit]:
        spec = copy.deepcopy(specification)
        player = player_factory(spec)
        if any(player is prior for prior in players):
            raise ValueError("Candidate players must be independent")
        players.append(player)
        started = time.perf_counter()
        try:
            frames = generate(player, spec)
            metrics = diagnose(frames)
            if any(not check["passed"] for check in metrics.get("checks", {}).values()):
                metrics["accepted"] = False
            row = dict(specification=spec, metrics=metrics)
            if metrics["accepted"]:
                quality = metrics.get("quality", {})
                rank = (
                    metrics.get("arrival_error_m", float("inf")),
                    quality.get("support_slide_m", float("inf")),
                    quality.get("root_second_difference_m", float("inf")),
                    quality.get("knee_angle_step_deg", float("inf")),
                )
                row["rank"] = rank
                safe.append((rank, len(rows), frames))
        except Exception as exc:
            row = dict(
                specification=spec, metrics=dict(accepted=False, reason=str(exc))
            )
        row['generation_and_validation_seconds'] = time.perf_counter() - started
        rows.append(row)
        if safe and stop_on_first:
            break
    winner = min(safe, key=lambda row: row[:2]) if safe else None
    return dict(
        candidates=rows,
        selected=None if winner is None else winner[1],
        frames=None if winner is None else winner[2],
    )
