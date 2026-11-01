"""停止区間を打ち切らずに測定する診断器。"""
import numpy as np
from collect_stance import knees_valid, knees_continuous, stance


def diagnose_stop(frames, original, goal, parents, names, calibration, bones):
    from final_stop import contact_points
    from step_cycle import foot_points, fk
    points = [contact_points(foot_points(p, parents, names), calibration)
              for p in [original, *frames]]
    floor = calibration['floor_z']
    checks = {}

    def record(name, bad, **metrics):
        checks[name] = dict(passed=not bad, frames=sorted(set(map(int, bad))), **metrics)

    record('bones', [r['frame'] for r in bones['bone_length_diagnostics']
                     if r['bone_length_delta_m'] > r['tolerance_m']],
           max_error_m=bones['max_bone_length_error_m'])
    angles = []
    for frame in frames:
        positions, _ = fk(frame, parents)
        row = {}
        for side in ('Left', 'Right'):
            hip, knee, ankle = [positions[names.index(side+p)] for p in ('Leg', 'Shin', 'Foot')]
            a, b = knee-hip, ankle-knee
            row[side.lower()] = float(np.degrees(np.arccos(np.clip(
                np.dot(a,b) / max(np.linalg.norm(a)*np.linalg.norm(b), 1e-12), -1, 1))))
        angles.append(row)
    record('knees', [i for i,p in enumerate(frames)
                    if not knees_valid(p, parents, names) or not knees_continuous(p, original, parents, names)], angles_deg=angles)
    rotations = [2*np.arccos(np.clip(np.abs(np.sum(a[:,3:]*b[:,3:], axis=1)),0,1))
                 for a,b in zip([original,*frames[:-1]],frames)]
    record('ankles', [i for i,r in enumerate(rotations) if np.max(r) > .35],
           max_joint_delta_rad=float(np.max(rotations)))
    heights = [{s: {p:float(v[2]-floor) for p,v in feet.items()} for s,feet in row.items()}
               for row in points[1:]]
    record('feet', [i for i,row in enumerate(heights) if min(v for feet in row.values() for v in feet.values()) < -.02], heights_m=heights)
    # 接地区間ごとの開始位置から測り、微小な滑りの累積も検出する。
    anchors = {}
    slips = []
    for i,row in enumerate(points):
        peak = 0.
        for side in ('left','right'):
            for part in ('ankle','toe'):
                identity = (side,part)
                point = row[side][part]
                if point[2] <= floor+.02:
                    anchor = anchors.setdefault(identity, point.copy())
                    peak = max(peak, float(np.linalg.norm(point[:2]-anchor[:2])))
                else:
                    anchors.pop(identity, None)
        if i:
            slips.append(peak)
    record('support', [i for i,v in enumerate(slips) if v > .02], max_slip_m=max(slips))
    landed = all(min(heights[-1][s].values()) <= .04 for s in ('left','right'))
    record('swing', [] if landed else [len(frames)-1], landed=landed)
    jumps = np.linalg.norm(np.diff(np.asarray([original,*frames])[:,0,:3],axis=0),axis=1)
    record('root', np.flatnonzero(jumps > .06).tolist(), max_step_m=float(max(jumps)))
    error = float(np.linalg.norm(frames[-1,0,:2]-np.asarray(goal)[:2]))
    record('destination', [] if error <= .08 else [len(frames)-1], error_m=error)
    unstable = [i-1 for i in range(max(2,len(points)-3),len(points))
                if any(np.linalg.norm(points[i][s][p]-points[i-1][s][p]) > .002
                       for s in ('left','right') for p in ('ankle','toe'))]
    record('idle', unstable, stance_m=list(stance(frames[-1],parents,names)),
           scope='Terminal stability; separate Idle transition not measured')
    return checks
