"""保存した停止失敗の接続元から、公式待機移行を再現して目視用に出力する。"""
import argparse
import json
from pathlib import Path
import numpy as np
from engine import _load_runtime, DT
from stop_runtime import new_character
from failure_relaxation import generate_failure_relaxation
from step_cycle import facing_of
from quats import RX90, quat_mul, quat_to_mat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.source.read_text(encoding='utf-8'))
    replay = record['source_replay']
    rt = _load_runtime(); wp = rt['wp']; wp.init(); wp.set_device('cuda:0')
    assets = rt['load_rig_assets'](rt['ModelRig'].SOMA)
    pool = rt['SmartPrimitiveAssetPool'](assets.clip_registry, assets.reference_pose, assets.model_to_runtime)
    engine = rt['MotionBricksSOMAEngine'](rt['SOMA_N1_FP32_ONNX_PATH'], model_to_runtime=assets.model_to_runtime)
    with engine, wp.ScopedStream(engine.stream):
        character = new_character(rt, engine, pool, replay)
        frames, metrics = generate_failure_relaxation(character, replay['metadata']['ground'], rt, facing_of(np.asarray(replay['pose'])[0, 3:]))
        if frames is None:
            raise RuntimeError(json.dumps(metrics))
        skeleton = character.skeleton
        rest = skeleton.reference_local_transforms.numpy().reshape((-1, 7)).copy()
        rest[0, :3] = quat_to_mat(RX90) @ rest[0, :3]; rest[0, 3:] = quat_mul(RX90, rest[0, 3:])
        goal = record['original_destination'][:2]
        metrics['arrival_error_m'] = float(np.linalg.norm(frames[-1][0, :2]-goal))
        candidate = dict(id='failure-relaxation-1',label='停止失敗後 → SOMA待機（0.5倍速）',
            experiment='failure_relaxation',frames=np.asarray(frames).tolist(),fps=1/DT,goal_xy=goal,
            target_distance_m=float(np.linalg.norm(np.asarray(replay['pose'])[0, :2]-goal)),
            events=dict(stop_start=0.,idle=(len(frames)-1)*DT), metrics=metrics,human_rating='unknown')
        result = dict(schema_version=1,source_state_id='failure-relaxation-review-01',
            rig=dict(rest=rest.tolist(),parents=replay['metadata']['parents'],joint_names=list(skeleton.joint_names)),
            candidates=[candidate])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
        print(json.dumps({name:value for name,value in metrics.items() if name!='bone_length_diagnostics'}),flush=True)


if __name__ == '__main__':
    main()
