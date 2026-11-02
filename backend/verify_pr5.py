"""保存状態に対してライブ停止経路の品質と生成時間を比較する。"""
import argparse
import importlib.util
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from engine import _load_runtime, _begin_final_stop
from stop_replay import load_replay, compare_runs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    module_spec = importlib.util.spec_from_file_location('baseline_engine', args.baseline)
    baseline = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(baseline)
    rt = _load_runtime()
    wp = rt['wp']
    wp.init()
    wp.set_device('cuda:0')
    assets = rt['load_rig_assets'](rt['ModelRig'].SOMA)
    pool = rt['SmartPrimitiveAssetPool'](assets.clip_registry, assets.reference_pose, assets.model_to_runtime)
    engine = rt['MotionBricksSOMAEngine'](rt['SOMA_N1_FP32_ONNX_PATH'], model_to_runtime=assets.model_to_runtime)
    results = []
    with engine, wp.ScopedStream(engine.stream):
        character = SimpleNamespace(engine=engine, asset_pool=pool)
        for path in sorted(Path('metrics/stop-measured').glob('*.json')):
            if path.name == 'coverage.json':
                continue
            row = dict(case=path.stem)
            for label, begin in [('before', baseline._begin_final_stop), ('after', _begin_final_stop)]:
                runs, timings, metrics = [], [], None
                for _ in range(2):
                    replay = load_replay(path)
                    started = time.perf_counter()
                    with patch('stop_replay.capture_replay', return_value=replay):
                        frames, metrics = begin(character, np.asarray(replay['pose']), replay['metadata']['goal'], rt, wp,
                                                ground=replay['metadata']['ground'])
                    timings.append(time.perf_counter() - started)
                    runs.append(frames)
                row[label] = dict(seconds=timings, accepted=metrics['accepted'], recovery_only=metrics.get('recovery_only', False),
                                  travel_distance_m=metrics.get('travel_distance_m'),
                                  reason=metrics.get('reason'), selected=metrics['search']['selected'],
                                  candidate_reasons=[c['metrics'].get('reason') for c in metrics['search']['candidates']],
                                  repeatability=compare_runs(*runs) if all(f is not None for f in runs) else None)
            results.append(row)
            args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            print(path.stem, row['before']['accepted'], row['after']['accepted'], flush=True)


if __name__ == '__main__':
    main()
