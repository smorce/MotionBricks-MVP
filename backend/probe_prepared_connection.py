"""同じ接続元からF001の生成長と終端指定を比較する。"""
import argparse
import copy
import json
import time
from pathlib import Path
import numpy as np
from engine import _load_runtime
from visual_stop_runtime import VisualStopRuntime
from stop_runtime import new_character


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('record', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding='utf-8'))
    replay = record['source_replay']
    rt = _load_runtime(); wp = rt['wp']; wp.init(); wp.set_device('cuda:0')
    assets = rt['load_rig_assets'](rt['ModelRig'].SOMA)
    pool = rt['SmartPrimitiveAssetPool'](assets.clip_registry, assets.reference_pose, assets.model_to_runtime)
    engine = rt['MotionBricksSOMAEngine'](rt['SOMA_N1_FP32_ONNX_PATH'], model_to_runtime=assets.model_to_runtime)
    results = []
    with engine, wp.ScopedStream(engine.stream):
        for count in (1, 4):
            for length in ((8,), (14,), (8, 14)):
                runtime = VisualStopRuntime(); runtime.prepared = True
                runtime.selection = copy.deepcopy(record['selection'])
                runtime.selection['candidate']['generation_settings'] = dict(num_poses_to_use=count, allowed_token_counts=length)
                character = new_character(rt, engine, pool, replay)
                started = time.perf_counter()
                frames, metrics = runtime.generate(character, replay['metadata']['goal'], replay['metadata']['ground'], rt,
                                                   destination=record['original_destination'])
                result = dict(count=count, length=length, accepted=metrics['accepted'], reason=metrics['reason'],
                              seconds=time.perf_counter()-started, validation=metrics['validation'])
                results.append(result)
                print(json.dumps({k:v for k,v in result.items() if k!='validation'}), flush=True)
    args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')
    from replay_writer import WRITER
    WRITER.flush()


if __name__ == '__main__':main()
