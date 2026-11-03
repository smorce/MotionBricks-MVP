"""停止区間を打ち切らずに測定する診断器。"""

import numpy as np
from collect_stance import knees_valid, knees_continuous, stance


def points_from_world(positions,names):
    return {side:{'ankle':positions[names.index(side.title()+'Foot')].copy(),
                  'toe':positions[names.index(side.title()+'ToeBase')].copy()}
            for side in ('left','right')}


def diagnose_stop(
    frames,
    original,
    goal,
    parents,
    names,
    calibration,
    bones,
    *,
    contacts=None,
    support=None,
    world=None,
):
    from final_stop import contact_points
    from step_cycle import fk

    if world is None:
        world=[fk(p,parents) for p in [original,*frames]]

    points = [
        contact_points(points_from_world(positions,names), calibration)
        for positions,_ in world
    ]
    floor = calibration["floor_z"]
    checks = {}

    def record(name, bad, **metrics):
        checks[name] = dict(
            passed=not bad, frames=sorted(set(map(int, bad))), **metrics
        )

    record(
        "bones",
        [
            r["frame"]
            for r in bones["bone_length_diagnostics"]
            if r["bone_length_delta_m"] > r["tolerance_m"]
        ],
        max_error_m=bones["max_bone_length_error_m"],
    )
    angles = []
    sole_up=[]
    _,initial_rotations=world[0]
    for frame,(positions,world_rotations) in zip(frames,world[1:]):
        row = {}
        for side in ("Left", "Right"):
            hip, knee, ankle = [
                positions[names.index(side + p)] for p in ("Leg", "Shin", "Foot")
            ]
            a, b = knee - hip, ankle - knee
            row[side.lower()] = float(
                np.degrees(
                    np.arccos(
                        np.clip(
                            np.dot(a, b)
                            / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12),
                            -1,
                            1,
                        )
                    )
                )
            )
        angles.append(row)
        sole_up.append({side:float((world_rotations[names.index(side.title()+'Foot')]@
            np.asarray(calibration.get('foot_up_local',{}).get(side,
                initial_rotations[names.index(side.title()+'Foot')].T@np.array([0.,0.,1.]))))[2])
            for side in ('left','right')})
    record(
        "knees",
        [
            i
            for i, p in enumerate(frames)
            if not knees_valid(p, parents, names,positions=world[i+1][0])
            or not knees_continuous(p, original, parents, names,current=world[i+1][0],initial=world[0][0])
        ],
        angles_deg=angles,
    )
    rotations = [
        2 * np.arccos(np.clip(np.abs(np.sum(a[:, 3:] * b[:, 3:], axis=1)), 0, 1))
        for a, b in zip([original, *frames[:-1]], frames)
    ]
    record(
        "ankles",
        [i for i, r in enumerate(rotations) if np.max(r) > 0.35 or min(sole_up[i].values())<-.2],
        max_joint_delta_rad=float(np.max(rotations)),
        sole_up_world_z=sole_up,
    )
    heights = [
        {
            s: {p: float(v[2] - floor) for p, v in feet.items()}
            for s, feet in row.items()
        }
        for row in points[1:]
    ]
    record(
        "feet",
        [
            i
            for i, row in enumerate(heights)
            if min(v for feet in row.values() for v in feet.values()) < -0.02
        ],
        heights_m=heights,
    )
    # 接地区間ごとの開始位置から測り、微小な滑りの累積も検出する。
    anchors = {}
    slips = []
    for i, row in enumerate(points):
        peak = 0.0
        for side in ("left", "right"):
            for part in ("ankle", "toe"):
                identity = (side, part)
                point = row[side][part]
                channel = (0 if side == "left" else 2) + (0 if part == "ankle" else 1)
                planted = (
                    contacts is None
                    or side == support
                    or i == 0
                    or contacts[i - 1][channel] >= 0.5
                )
                if (side == support or point[2] <= floor + 0.02) and planted:
                    anchor = anchors.setdefault(identity, point.copy())
                    peak = max(peak, float(np.linalg.norm(point[:2] - anchor[:2])))
                else:
                    anchors.pop(identity, None)
        if i:
            slips.append(peak)
    record(
        "support",
        [i for i, v in enumerate(slips) if v > 0.02],
        max_slip_m=max(slips),
        contact_source="height proxy"
        if contacts is None
        else "Official confidence >= 0.5 and calibrated height; support always checked",
    )
    landed = all(min(heights[-1][s].values()) <= 0.04 for s in ("left", "right"))
    lift = {s: max(min(row[s][p][2] - floor for p in ('ankle', 'toe')) for row in points)
            for s in ("left", "right")}
    moving = {
        s: max(
            np.linalg.norm(row[s]["ankle"][:2] - points[0][s]["ankle"][:2])
            for row in points
        )
        for s in ("left", "right")
    }
    failed_lift = any(
        moving[s] > 0.02 and lift[s] < 0.025 for s in ("left", "right") if s != support
    )
    record(
        "swing",
        [] if landed and not failed_lift else [len(frames) - 1],
        landed=landed,
        lift_m=lift,
    )
    jumps = np.linalg.norm(
        np.diff(np.asarray([original, *frames])[:, 0, :3], axis=0), axis=1
    )
    record("root", np.flatnonzero(jumps > 0.06).tolist(), max_step_m=float(max(jumps)))
    roots = np.asarray([original, *frames])[:, 0, :3]
    checks["root"]["max_second_difference_m"] = float(
        np.max(np.linalg.norm(np.diff(roots, n=2, axis=0), axis=1))
    )
    error = float(np.linalg.norm(frames[-1, 0, :2] - np.asarray(goal)[:2]))
    record("destination", [] if error <= 0.08 else [len(frames) - 1], error_m=error)
    unstable = [
        i - 1
        for i in range(max(2, len(points) - 3), len(points))
        if any(
            np.linalg.norm(points[i][s][p] - points[i - 1][s][p]) > 0.002
            for s in ("left", "right")
            for p in ("ankle", "toe")
        )
    ]
    record(
        "idle",
        unstable,
        stance_m=list(stance(frames[-1], parents, names)),
        scope="Terminal stability; separate Idle transition not measured",
    )
    return checks
