"""クリックせず保存状態から公式停止探索を繰り返すCLI。"""

import argparse
import json
import time
import numpy as np
from pathlib import Path
from engine import _load_runtime
from stop_replay import load_replay, compare_runs
from stop_runtime import new_character, candidate_specs, refinement_specs, generate_candidate, diagnose
from stop_candidate_search import search_candidates
from stop_test_report import write_report


def selected_specification(result):
    """実際に採用された候補だけを再現対象とする。"""
    selected = result['selected']
    return None if selected is None else result['candidates'][selected]['specification']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = (
        sorted(args.replay.glob("*.json")) if args.replay.is_dir() else [args.replay]
    )
    paths = [path for path in paths if path.name != "coverage.json"]
    results = dict(scope="実測条件の保存履歴から公式モデルを再推論した結果", cases=[])
    rt = _load_runtime()
    wp = rt["wp"]
    wp.init()
    wp.set_device("cuda:0")
    assets = rt["load_rig_assets"](rt["ModelRig"].SOMA)
    pool = rt["SmartPrimitiveAssetPool"](
        assets.clip_registry, assets.reference_pose, assets.model_to_runtime
    )
    engine = rt["MotionBricksSOMAEngine"](
        rt["SOMA_N1_FP32_ONNX_PATH"], model_to_runtime=assets.model_to_runtime
    )
    with engine, wp.ScopedStream(engine.stream):
        for path in paths:
            started = time.perf_counter()
            replay = load_replay(path)
            specs = candidate_specs()
            result = search_candidates(
                specs,
                lambda spec: new_character(rt, engine, pool, replay),
                lambda p, s: generate_candidate(p, replay, s, rt),
                lambda f: diagnose(replay, f),
            )
            frames = result.pop("frames")
            if frames is None:
                refined=search_candidates(refinement_specs(),
                    lambda spec:new_character(rt,engine,pool,replay),
                    lambda p,s:generate_candidate(p,replay,s,rt),lambda f:diagnose(replay,f),limit=12)
                frames=refined.pop('frames')
                if refined['selected'] is not None:
                    result['selected']=len(result['candidates'])+refined['selected']
                result['candidates'].extend(refined['candidates'])
                result['rounds']=2
            chosen = selected_specification(result)
            result['search_seconds'] = time.perf_counter() - started
            if chosen:
                repeated_started = time.perf_counter()
                repeated = [
                    generate_candidate(
                        new_character(rt, engine, pool, replay), replay, chosen, rt
                    )
                    for _ in range(2)
                ]
                result["repeatability"] = compare_runs(*repeated)
                result['repeat_seconds'] = time.perf_counter() - repeated_started
            result.update(
                case=path.stem, metrics=dict(accepted=result["selected"] is not None)
            )
            result["source_state"] = replay["metadata"].get("control", {})
            result["model"] = replay["metadata"].get("model")
            results["cases"].append(result)
            write_report(results, args.output)
            if frames is not None:
                (args.output / (path.stem + "-frames.json")).write_text(
                    json.dumps(np.asarray(frames).tolist()), encoding="utf-8"
                )
            print(path.stem, "Selected:", result["selected"], flush=True)


if __name__ == "__main__":
    main()
