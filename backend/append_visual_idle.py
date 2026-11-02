"""比較用に停止後1秒と公式Idle4への追加生成を記録する。"""
import copy
import json
from pathlib import Path
from zipfile import ZipFile
import numpy as np
from engine import _load_runtime
from final_stop import facing_of
from quats import RX90, quat_mul, quat_to_mat
from stop_distance_probe import pure_generate
from stop_runtime import new_character


def main():
    rt = _load_runtime()
    wp = rt['wp']; wp.init(); wp.set_device('cuda:0')
    assets = rt['load_rig_assets'](rt['ModelRig'].SOMA)
    pool = rt['SmartPrimitiveAssetPool'](assets.clip_registry, assets.reference_pose, assets.model_to_runtime)
    engine = rt['MotionBricksSOMAEngine'](rt['SOMA_N1_FP32_ONNX_PATH'], model_to_runtime=assets.model_to_runtime)
    with ZipFile('metrics/stop-distance-lab/measurements.zip') as archive:
        source = json.loads(archive.read('source-replay.json'))
    idle = pool.clip_registry.load(rt['DEFAULT_IDLE_CLIPS'][0]).animation.poses.numpy()[:4].copy()
    for pose in idle:
        pose[0, :3] = quat_to_mat(RX90) @ pose[0, :3]
        pose[0, 3:] = quat_mul(RX90, pose[0, 3:])
    with engine, wp.ScopedStream(engine.stream):
        for mode in ('legacy', 'visual'):
            path = Path(f'metrics/phase9/{mode}.json')
            data = json.loads(path.read_text(encoding='utf-8'))
            for row in data['candidates']:
                if row['phase'] != 'settled' or row.get('idle_start_seconds') is not None:
                    continue
                replay = copy.deepcopy(source)
                final = np.asarray(row['frames'][-1])
                replay['pose'] = final.tolist()
                replay['history'] = np.repeat(final[None], len(source['history']), axis=0).tolist()
                replay['metadata']['contacts'] = [1., 1., 1., 1.]
                # 停止1秒後の姿勢履歴は静止した実姿勢で満たす。
                replay['metadata']['goal'] = (final[0, :2] + np.asarray(facing_of(final[0, 3:]))[:2] * .001).tolist()
                scratch = new_character(rt, engine, pool, replay)
                frames = pure_generate(scratch, replay, dict(mode='C', pinned=False), rt, idle)
                row['stop_end_seconds'] = (len(row['frames'])-1)/60
                row['frames'].extend([final.tolist() for _ in range(60)])
                row['idle_start_seconds'] = (len(row['frames'])-1)/60
                row['frames'].extend(np.asarray(frames).tolist())
                row['idle_arrival_error_m'] = float(np.linalg.norm(frames[-1][0, :2]-row['goal_xy']))
                row['idle_human_rating'] = 'unknown'
                print(mode, row['id'], 'Idle4 generated', flush=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
