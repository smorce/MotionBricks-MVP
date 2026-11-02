"""同一リプレイから停止距離を実測する実験専用CLI。通常制御には介入しない。"""
import argparse
import copy
import hashlib
import json
import time
from pathlib import Path
import numpy as np

DISTANCES = (.15, .20, .30, .40, .50, .60, .80, 1., 1.20)


def specifications(distances=DISTANCES):
    return [dict(id=f'{mode}-{distance:.3f}', mode=mode, distance_m=distance,
                 pinned=mode in ('B', 'D'), target_pose_type='F001' if mode in ('A', 'B') else 'SOMA Idle4')
            for distance in distances for mode in 'ABCD']


def recommendations(candidates, reviews):
    safe = [c for c in candidates if c['metrics'].get('accepted') is True]
    natural = [c for c in candidates if reviews.get(c['id']) == 'good']
    natural.sort(key=lambda c: tuple(c['metrics'].get(k, c['metrics'].get('quality', {}).get(k, float('inf'))) for k in
                 ('arrival_error_m', 'support_slide_m', 'generation_seconds')))
    return dict(selection_policy='human_visual_priority',
                safe_ids=[c['id'] for c in safe], recommended_ids=[c['id'] for c in natural],
                diagnostic_failed_recommended_ids=[c['id'] for c in natural if c['metrics'].get('accepted') is False],
                unreviewed_ids=[c['id'] for c in candidates if reviews.get(c['id'], 'unknown') == 'unknown'])


def state_features(replay):
    from final_stop import facing_of
    history = np.asarray(replay['history'])
    dt = float(replay['delta_times'][-2])
    velocity = (history[-1, 0, :2] - history[-2, 0, :2]) / max(dt, 1e-8)
    speed = float(np.linalg.norm(velocity))
    direction = velocity / speed if speed > .01 else np.asarray(facing_of(np.asarray(replay['pose'])[0, 3:]))[:2]
    return dict(root=replay['pose'][0][:3], speed_mps=speed, direction=direction.tolist(),
                support=replay['metadata']['support'], contacts=replay['metadata'].get('contacts'),
                phase=replay['metadata'].get('control', {}).get('phase', 'contact-derived'),
                control=replay['metadata'].get('control', {}), recent_poses=history[-4:].tolist(),
                ground=replay['metadata']['ground'])


def pure_generate(character, replay, spec, rt, idle):
    from engine import DT
    from final_stop import build_stop_target, contact_points, foot_points, facing_of
    from quats import quat_mul
    from stop_runtime import GeneratedStop
    wp = rt['wp']
    data = replay['metadata']
    original = np.asarray(replay['pose'])
    goal = data['goal']
    if spec['mode'] in ('A', 'B'):
        target = build_stop_target(original, goal, data['parents'], data['names'], data['ground'])
        if target is None:
            raise ValueError('Invalid F001 target')
        source = facing_of(target[0, 3:])
        direction = np.asarray(goal)[:2] - original[0, :2]
        angle = np.arctan2(direction[1], direction[0]) - np.arctan2(source[1], source[0])
        target[0, 3:] = quat_mul(np.array([0, 0, np.sin(angle/2), np.cos(angle/2)]), target[0, 3:])
        targets = np.repeat(target[None], 4, axis=0)
        count = 1
    else:
        targets = idle.copy()
        # クリップの骨格寸法を保存状態へ合わせ、連続４フレームの回転を維持する。
        targets[:, 1:, :3] = original[None, 1:, :3]
        source = facing_of(targets[0, 0, 3:])
        direction = np.asarray(goal)[:2] - original[0, :2]
        angle = np.arctan2(direction[1], direction[0]) - np.arctan2(source[1], source[0])
        rotation = np.array([0, 0, np.sin(angle/2), np.cos(angle/2)])
        for target in targets:
            target[0, 3:] = quat_mul(rotation, target[0, 3:])
            target[0, :2] = goal[:2]
        feet = contact_points(foot_points(targets[0], data['parents'], data['names']), data['ground'])
        targets[:, 0, 2] += data['ground']['floor_z'] - min(p[2] for side in feet.values() for p in side.values())
        count = 4
    mask = rt['IKPin'].NONE
    if spec['pinned']:
        mask = rt['IKPin'].LEFT_FOOT if data['support'] == 'left' else rt['IKPin'].RIGHT_FOOT
    character.generate_to_target_poses(wp.array(targets.astype(np.float32), dtype=wp.transform, device=character.engine.device),
        rt['TargetPoseInferenceParams'](transition_early_by_frames=0, num_poses_to_use=count,
                                      ik_pin_mask=mask, allowed_token_counts=(8, 14)))
    if spec['pinned']:
        # 公式APIは目標の足を捕捉するため、歩行開始時の支持足を明示的に捕捉し直す。
        character._target_pose_ik_corrector.capture_pins(
            wp.array(original.astype(np.float32), dtype=wp.transform, device=character.engine.device),
            mask, stream=character.engine.stream)
    frames, contacts = [], []
    for _ in range(480):
        character._sample_playback(DT)
        if spec['pinned']:
            character._target_pose_ik_corrector.apply(character.current_pose, 1.0, stream=character.engine.stream)
        frames.append(character.current_pose.numpy().reshape((-1, 7)).copy())
        contacts.append(character.current_foot_contacts.numpy().reshape(-1).tolist())
        if character.time_to_transition() <= 0:
            break
    else:
        raise RuntimeError('Stop generation timed out')
    generated = GeneratedStop(frames, contacts, data['support'])
    generated.target_poses = targets.tolist()
    return generated


def main():
    from engine import _load_runtime, DT
    from stop_replay import load_replay, compare_runs
    from stop_runtime import new_character, generate_candidate, diagnose
    from quats import RX90, quat_mul, quat_to_mat
    parser = argparse.ArgumentParser()
    parser.add_argument('replay', type=Path)
    parser.add_argument('--output', type=Path, default=Path('metrics/stop-distance-lab'))
    parser.add_argument('--distances', type=float, nargs='+', default=DISTANCES)
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--refine', action='store_true', help='Probe midpoints at safety boundaries')
    parser.add_argument('--evaluate', action='store_true', help='Apply reviews to an existing comparison without inference')
    args = parser.parse_args()
    if args.evaluate:
        if args.reviews is None:
            parser.error('--evaluate requires --reviews')
        comparison = json.loads(args.replay.read_text(encoding='utf-8'))
        review = json.loads(args.reviews.read_text(encoding='utf-8'))
        if comparison['source_state_id'] != review['source_state_id']:
            raise ValueError('Review state mismatch')
        comparison['selection'] = recommendations(comparison['candidates'], {r['id']:r['mark'] for r in review['reviews']})
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/'selection.json').write_text(json.dumps(comparison['selection'], ensure_ascii=False, indent=2), encoding='utf-8')
        return
    replay = load_replay(args.replay)
    identity = hashlib.sha256(args.replay.read_bytes()).hexdigest()
    features = state_features(replay)
    rt = _load_runtime(); wp = rt['wp']; wp.init(); wp.set_device('cuda:0')
    assets = rt['load_rig_assets'](rt['ModelRig'].SOMA)
    pool = rt['SmartPrimitiveAssetPool'](assets.clip_registry, assets.reference_pose, assets.model_to_runtime)
    engine = rt['MotionBricksSOMAEngine'](rt['SOMA_N1_FP32_ONNX_PATH'], model_to_runtime=assets.model_to_runtime)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'source-replay.json').write_bytes(args.replay.read_bytes())
    reviews = {}
    if args.reviews:
        review = json.loads(args.reviews.read_text(encoding='utf-8'))
        if review['source_state_id'] != identity:
            raise ValueError('Review state mismatch')
        reviews = {r['id']:r['mark'] for r in review['reviews']}
    results = dict(schema_version=1, source_state_id=identity, context=features, candidates=[], failures=[],
                   provenance={k:replay['metadata'].get(k) for k in ('model', 'runtime_commit', 'inference', 'vrm_mapping_sha256')},
                   scope='Experimental; terminal stability measured; subsequent Idle transition unverified')
    with engine, wp.ScopedStream(engine.stream):
        c = new_character(rt, engine, pool, replay)
        rest = c.skeleton.reference_local_transforms.numpy().reshape((-1,7)).copy()
        rest[0,:3] = quat_to_mat(RX90) @ rest[0,:3]; rest[0,3:] = quat_mul(RX90, rest[0,3:])
        results['rig'] = dict(joint_names=replay['metadata']['names'], parents=replay['metadata']['parents'], rest=rest.tolist())
        idle = pool.clip_registry.load(rt['DEFAULT_IDLE_CLIPS'][0]).animation.poses.numpy()[:4].copy()
        for pose in idle:
            pose[0, :3] = quat_to_mat(RX90) @ pose[0, :3]
            pose[0, 3:] = quat_mul(RX90, pose[0, 3:])
        # 既存経路は独立した比較対照としてのみ呼ぶ。
        specs = specifications(args.distances) + [dict(id='legacy', mode='legacy', distance_m=.2, pinned=True, target_pose_type='corrected F001')]
        for spec in specs:
            trial = copy.deepcopy(replay)
            goal = np.asarray(replay['pose'])[0,:2] + np.asarray(features['direction']) * spec['distance_m']
            trial['metadata']['goal'] = goal.tolist()
            trial['metadata'].setdefault('control', {})['destination'] = goal.tolist()
            started = time.perf_counter()
            try:
                character = new_character(rt, engine, pool, trial)
                if spec['mode'] == 'legacy':
                    frames = generate_candidate(character, trial, dict(mode='f001', support=features['support'], root_shift=0., root_lower=0., tokens=8), rt)
                else:
                    frames = pure_generate(character, trial, spec, rt, idle)
                seconds = time.perf_counter() - started
                if not results['candidates'] and spec['mode'] != 'legacy':
                    repeated = pure_generate(new_character(rt, engine, pool, trial), trial, spec, rt, idle)
                    results['repeatability'] = compare_runs(frames, repeated)
                metrics = diagnose(trial, frames)
                roots = np.asarray([replay['pose'], *frames])[:,0,:2]
                speeds = np.linalg.norm(np.diff(roots, axis=0), axis=1)/DT
                stopped = next((i*DT for i in range(len(speeds)-5) if np.all(speeds[i:] < .05)), None)
                metrics.update(generation_seconds=seconds, actual_travel_m=float(np.linalg.norm(np.diff(roots,axis=0),axis=1).sum()),
                               duration_seconds=len(frames)*DT, stop_time_seconds=stopped)
                confidence = np.asarray(frames.contacts).reshape((-1, 4))
                metrics['landing_times_seconds'] = {
                    side: [float(i*DT) for i in range(1, len(confidence))
                           if max(confidence[i, start:start+2]) >= .5 and max(confidence[i-1, start:start+2]) < .5]
                    for side, start in (('left', 0), ('right', 2))}
                metrics['first_frame_root_jump_m'] = float(np.linalg.norm(np.asarray(frames)[0, 0, :3]-np.asarray(replay['pose'])[0, :3]))
                candidate = dict(**spec, target_distance_m=spec['distance_m'], fps=60, support=features['support'],
                    ik_pin_mask=features['support'] if spec['pinned'] else 'NONE', goal_xy=goal.tolist(), metrics=metrics,
                    source_state_id=identity, generation_settings=dict(num_poses_to_use=1 if spec['mode'] in 'AB' else 4, allowed_token_counts=[8,14]),
                    target_poses=getattr(frames, 'target_poses', None), contacts=frames.contacts,
                    frames=[replay['pose'], *np.asarray(frames).tolist()])
                results['candidates'].append(candidate)
            except (ValueError, RuntimeError) as error:
                results['failures'].append(dict(specification=spec, error=str(error)))
            results['selection'] = recommendations(results['candidates'], reviews)
            results['safe_distances_m'] = sorted({c['distance_m'] for c in results['candidates'] if c['metrics']['accepted']})
            (args.output/'comparison.json').write_text(json.dumps(results, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
            print(spec['id'], 'done', flush=True)
            if args.refine and spec is specs[-1]:
                extra = []
                for mode in 'ABCD':
                    rows = sorted([c for c in results['candidates'] if c['mode'] == mode], key=lambda c:c['distance_m'])
                    for a, b in zip(rows, rows[1:]):
                        if a['metrics']['accepted'] != b['metrics']['accepted'] and b['distance_m']-a['distance_m'] > .025:
                            midpoint = (a['distance_m']+b['distance_m'])/2
                            extra.extend(s for s in specifications([midpoint]) if s['mode'] == mode)
                specs.extend(extra)


if __name__ == '__main__':
    main()
