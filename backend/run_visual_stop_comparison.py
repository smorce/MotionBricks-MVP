"""従来制御と実験制御の実歩行を同じ入力列で記録する。"""
import argparse
import json
import os
import threading
import time
from pathlib import Path
from queue import Queue
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['legacy', 'visual'], required=True)
    parser.add_argument('--output', type=Path, default=Path('metrics/phase9'))
    args = parser.parse_args()
    from zipfile import ZipFile
    lab = Path('metrics/stop-distance-lab')
    with ZipFile(lab / 'measurements.zip') as archive:
        for name in ('source-replay.json', 'after-turn/source-replay.json'):
            target = lab / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    os.environ['MOTIONBRICKS_VISUAL_STOP'] = '1' if args.mode == 'visual' else '0'
    source = Path('metrics/stop-distance-lab/source-replay.json').resolve()
    os.environ['MOTIONBRICKS_COMPARISON_REPLAY'] = str(source)
    initial = json.loads(source.read_text(encoding='utf-8'))
    from engine import worker
    commands = Queue()
    latest = {}
    active = None
    ready = threading.Event()
    done = threading.Event()
    rig = None

    def publish(message):
        nonlocal rig, active
        if message['type'] == 'rig':
            rig = message
        if message['type'] == 'frame':
            latest.update(message)
            ready.set()
            if active is not None:
                active['frames'].append(message['poses'])
                active['phases'].append(message['phase'])
                active['visual_selection'] = message.get('visual_selection') or active.get('visual_selection')
                if message['phase'] in ('settled', 'stop_failed') and len(active['frames']) > 5:
                    active['phase'] = message['phase']
                    active['gait'] = message.get('gait')
                    done.set()

    thread = threading.Thread(target=worker, args=(commands, publish), daemon=True)
    thread.start()
    if not ready.wait(180):
        raise RuntimeError('Motion engine did not become ready')
    idle_pose = latest['poses']
    results = []
    for index, (name, dx, dy) in enumerate([('30cm', .3, 0), ('30cm-50cm', .5, 0), ('50cm', .5, 0), ('1m', 1, 0), ('2m', 2, 0), ('5m', 5, 0), ('90-turn', 0, .5), ('idle-restart', .3, 0)]):
        scenario_initial = json.loads(Path('metrics/stop-distance-lab/after-turn/source-replay.json').read_text(encoding='utf-8')) if index == 6 else initial
        start = np.asarray(idle_pose if index == 7 else latest['poses'] if index == 1 else scenario_initial['pose'])
        if index == 6:
            from stop_distance_probe import state_features
            direction = state_features(scenario_initial)['direction']
            dx, dy = np.asarray(direction) * .5
        goal = (np.asarray(initial['pose'])[0, :2] + [.8, 0]).tolist() if index == 1 else (start[0, :2] + [dx, dy]).tolist()
        active = dict(id=name, label=name, frames=[start.tolist()], phases=['start'], fps=60, goal_xy=goal,
                      target_distance_m=float(np.hypot(dx, dy)), human_rating='unknown')
        done.clear()
        commands.put(dict(type='move', x=goal[0], y=goal[1], move_id=index+1, hold_stance=True))
        done.wait(35)
        time.sleep(1)
        result = active
        active = None
        result['phase'] = result.get('phase', 'timeout')
        result['metrics'] = dict(arrival_error_m=float(np.linalg.norm(np.asarray(result['frames'][-1])[0, :2]-goal)))
        results.append(result)
        print(args.mode, name, result['phase'], result['metrics'], flush=True)
    commands.put(dict(type='quit'))
    thread.join(5)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f'{args.mode}.json').write_text(json.dumps(dict(rig=rig, candidates=results), ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
