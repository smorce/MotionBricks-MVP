"""JSON形式の停止再現記録。pickleやライブオブジェクトを保存しない。"""
import json
from pathlib import Path
import numpy as np


def save_replay(path, *, pose, history, delta_times, metadata):
    payload = dict(schema_version=1, pose=np.asarray(pose).tolist(),
                   history=np.asarray(history).tolist(),
                   delta_times=np.asarray(delta_times).tolist(), metadata=metadata)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def load_replay(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload['schema_version'] != 1:
        raise ValueError('Unsupported stop replay schema')
    pose, history = np.asarray(payload['pose']), np.asarray(payload['history'])
    if (pose.ndim != 2 or pose.shape[-1] != 7 or history.ndim != 3
            or history.shape[1:] != pose.shape or len(history) != len(payload['delta_times'])
            or not np.isfinite(history).all() or not np.isfinite(pose).all()):
        raise ValueError('Invalid stop replay shape or values')
    return payload


def restore_history(character, replay):
    """新規再生器の履歴を復元する。GPU推論器の乱数復元は別途必要。"""
    recorder = character.player.motion_history
    recorder.poses.assign(np.asarray(replay['history'], dtype=np.float32))
    recorder.delta_times[:] = replay['delta_times']
    character.player.refresh_context()


def compare_runs(first, second):
    a, b = np.asarray(first), np.asarray(second)
    return dict(equal=bool(np.array_equal(a,b)), shape_equal=a.shape == b.shape,
                max_absolute_difference=float(np.max(np.abs(a-b))) if a.shape == b.shape else None)
