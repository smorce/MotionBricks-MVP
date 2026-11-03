"""公式モデルで連続移動と停止の機械検証を再現する。"""
import argparse
import json
from pathlib import Path
import numpy as np
from engine import _load_runtime, _prime_walk, _command, _sync_pose, DT
from locomotion_cycle import LocomotionCycle
from final_stop import calibrate_stop_ground
from replay_writer import WRITER


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--preview-output', type=Path)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rt = _load_runtime(); wp = rt['wp']; wp.init(); wp.set_device('cuda:0')
    assets = rt['load_rig_assets'](rt['ModelRig'].SOMA)
    pool = rt['SmartPrimitiveAssetPool'](assets.clip_registry, assets.reference_pose, assets.model_to_runtime)
    engine = rt['MotionBricksSOMAEngine'](rt['SOMA_N1_FP32_ONNX_PATH'], model_to_runtime=assets.model_to_runtime)
    results = []; previews = []
    with engine, wp.ScopedStream(engine.stream):
        character = rt['SOMACharacter'](engine, asset_pool=pool, modes=rt['DEFAULT_LOCOMOTION_MODES'],
            idle_paths=(rt['DEFAULT_IDLE_CLIPS'][0],), crouch_idle_paths=rt['DEFAULT_CROUCH_IDLE_CLIPS'])
        for _ in range(300):character.step(DT, _command(rt, np.array([1.,0.,0.]), None))
        skeleton = character.skeleton; names = list(skeleton.joint_names)
        parents = [skeleton.joint_parent(i) for i in range(len(names))]
        rest = skeleton.reference_local_transforms.numpy().reshape((-1,7)).copy()
        from quats import RX90, quat_mul, quat_to_mat
        rest[0,:3] = quat_to_mat(RX90) @ rest[0,:3]; rest[0,3:] = quat_mul(RX90,rest[0,3:])
        ground = calibrate_stop_ground(rest,parents,names)
        from visual_stop_runtime import VisualStopRuntime
        stop = VisualStopRuntime(); stop.prepared = True
        cycle = LocomotionCycle(log=None); cycle.stop_mode = 'prepared'; cycle.preview_stops = True
        for move_id, delta in enumerate(((.735,.072),(2.,0.),(0.,2.),(.3,.02),(1.,1.))*args.rounds,1):
            pose = character.current_pose.numpy().reshape((-1,7)).copy()
            goal = pose[0,:2] + delta; cycle.begin_move(goal,True,move_id)
            cycle.ground_calibration = ground
            previous = pose[0,:2].copy(); attempts = []; trace = []; stop.selection = None
            preview_frames = [pose.tolist()]; stop_start = None
            for tick in range(1200):
                pose = character.current_pose.numpy().reshape((-1,7)).copy()
                speed = float(np.linalg.norm(pose[0,:2]-previous)/DT); previous = pose[0,:2].copy()
                cycle.visual_selection = stop.observe(character, cycle.goal, ground) if cycle.stop_requested_s is None else None
                action = cycle.tick(dict(pose=pose,parents=parents,names=names,dt=DT,actual_speed=speed,
                    facing=character.movement.current_facing.copy(),contacts=character.current_foot_contacts.numpy().reshape(-1),
                    contacts_available=character._playback_source.name!='CLIP',playback=character._playback_source.name,
                    official_state=character.state_machine.state.name))
                trace.append(dict(tick=tick,root=pose[0,:2].tolist(),goal=goal.tolist(),
                                  command=cycle.command_direction.tolist(),
                                  course=None if cycle.course_direction is None else cycle.course_direction.tolist()))
                if action.begin_final_stop:
                    frames, metrics = stop.generate(character, cycle.final_stop_goal, ground, rt, destination=goal)
                    attempts.append(dict(tick=tick,accepted=metrics['accepted'], recovery_only=metrics.get('recovery_only',False),
                                         distance_m=float(np.linalg.norm(goal-pose[0,:2])), reason=metrics.get('reason'),
                                         validation=metrics.get('validation')))
                    if (not metrics['accepted'] or metrics.get('recovery_only')) and cycle.reject_stop_preview(pose):
                        if not cycle.walk_primed:_prime_walk(character,action.facing);cycle.walk_primed=True
                        character.step(DT,_command(rt,cycle._facing(pose,None),cycle._facing(pose,None)))
                    else:
                        cycle.note_final_stop(frames,metrics);character.movement.reset_desired_velocity()
                        stop_start = len(preview_frames) * DT
                elif action.walk:
                    if action.prime_walk:_prime_walk(character,action.facing)
                    character.step(DT,_command(rt,action.facing,action.facing))
                elif action.play:character.step(DT,_command(rt,action.facing,None))
                elif action.pose is not None:
                    _sync_pose(character,action.pose,wp,seed=action.seed)
                    if cycle.phase in ('final_step','stop_retry') and not action.seed:character.player.record_pose(DT,character.current_pose)
                    if action.seed:character.movement.reset_desired_velocity()
                if args.preview_output:
                    preview_frames.append(character.current_pose.numpy().reshape((-1,7)).tolist())
                if cycle.phase in ('settled','stop_failed'):break
            final = character.current_pose.numpy().reshape((-1,7))
            row = dict(delta=delta,phase=cycle.phase,error_m=float(np.linalg.norm(goal-final[0,:2])),
                       reason=cycle.stop_failure_reason,ticks=tick,attempts=attempts)
            args.output.with_name(args.output.stem+f"-trace-{move_id}.json").write_text(json.dumps(trace),encoding="utf-8")
            results.append(row)
            if args.preview_output:
                labels = ('小さな斜めずれ・約74cm', '直進・2m', '旋回後・2m', '短距離・約30cm', '斜め接近・約1.4m')
                previews.append(dict(id=f'prepared-{move_id}', label=labels[(move_id-1)%5],
                    frames=preview_frames, fps=1/DT, goal_xy=goal.tolist(),
                    target_distance_m=float(np.linalg.norm(delta)), target_pose_type='停止準備 → F001接続',
                    events=dict(stop_start=stop_start, idle=(len(preview_frames)-1)*DT),
                    metrics=dict(accepted=row['phase']=='settled', arrival_error_m=row['error_m'],
                                 reason=row['reason']), human_rating='unknown'))
            print(json.dumps({name: value for name, value in row.items() if name != 'attempts'}), flush=True)
            args.output.write_text(json.dumps(results,indent=2),encoding='utf-8')
        if args.preview_output:
            args.preview_output.parent.mkdir(parents=True, exist_ok=True)
            args.preview_output.write_text(json.dumps(dict(schema_version=1,
                source_state_id='prepared-f001-review-20261103',
                rig=dict(rest=rest.tolist(),parents=parents,joint_names=names),
                candidates=previews),separators=(',',':')),encoding='utf-8')
    WRITER.flush()
    if not all(row['phase'] == 'settled' and row['error_m'] <= .05 + 1e-9 for row in results):
        raise SystemExit(1)

if __name__ == '__main__':main()
