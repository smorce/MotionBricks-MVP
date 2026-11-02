"""JSON形式の停止再現記録。pickleやライブオブジェクトを保存しない。"""

import json
from pathlib import Path
import numpy as np
import hashlib
import random
from functools import lru_cache


def save_replay(path, *, pose, history, delta_times, metadata):
    payload = dict(
        schema_version=1,
        pose=np.asarray(pose).tolist(),
        history=np.asarray(history).tolist(),
        delta_times=np.asarray(delta_times).tolist(),
        metadata=metadata,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )


def load_replay(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported stop replay schema")
    pose, history = np.asarray(payload["pose"]), np.asarray(payload["history"])
    dt = np.asarray(payload["delta_times"])
    if (
        pose.ndim != 2
        or pose.shape[-1] != 7
        or history.ndim != 3
        or history.shape[1:] != pose.shape
        or len(history) != len(payload["delta_times"])
        or not np.isfinite(history).all()
        or not np.isfinite(pose).all()
        or not np.isfinite(dt).all()
        or np.any(dt < 0)
    ):
        raise ValueError("Invalid stop replay shape or values")
    return payload


def restore_history(character, replay):
    """新規再生器の履歴を復元する。GPU推論器の乱数復元は別途必要。"""
    recorder = character.player.motion_history
    recorder.poses.assign(np.asarray(replay["history"], dtype=np.float32))
    recorder.delta_times[:] = replay["delta_times"]
    character.player.refresh_context()
    contacts = replay["metadata"].get("contacts")
    if contacts is not None:
        character.current_foot_contacts.assign(np.asarray(contacts, dtype=np.float32))


@lru_cache(maxsize=1)
def model_manifest():
    from motionbricks.model.soma.contract import SOMA_N1_FP32_ONNX_PATH

    path = Path(SOMA_N1_FP32_ONNX_PATH)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return dict(model_name=path.name, sha256=digest.hexdigest())


def compare_runs(first, second):
    a, b = np.asarray(first), np.asarray(second)
    return dict(
        equal=bool(np.array_equal(a, b)),
        shape_equal=a.shape == b.shape,
        max_absolute_difference=float(np.max(np.abs(a - b)))
        if a.shape == b.shape
        else None,
    )


def capture_replay(character, goal, ground, *, control=None):
    """公式生成が参照する姿勢履歴と、診断用制御状態をコピーする。"""
    from final_stop import stop_support, build_stop_target
    from step_cycle import foot_points
    from dataclasses import asdict
    from motionbricks.model.config import MotionBricksInferenceConfig
    from engine import find_motionbricks_root
    import subprocess

    names = list(character.skeleton.joint_names)
    parents = [character.skeleton.joint_parent(i) for i in range(len(names))]
    pose = character.current_pose.numpy().reshape((-1, 7)).copy()
    history = character.player.motion_history
    context = character.engine.create_input(character.skeleton)
    context.update_from_recorder(history, stream=character.engine.stream)
    target = build_stop_target(pose, goal, parents, names, ground)
    root = find_motionbricks_root()
    version = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    rng = np.random.get_state()
    metadata = dict(
        goal=np.asarray(goal).tolist(),
        ground=ground,
        names=names,
        parents=parents,
        feet={
            s: {p: v.tolist() for p, v in feet.items()}
            for s, feet in foot_points(pose, parents, names).items()
        },
        contacts=character.current_foot_contacts.numpy().tolist(),
        support=stop_support(pose, goal, parents, names),
        f001=None if target is None else target.tolist(),
        inference=asdict(MotionBricksInferenceConfig()),
        runtime_commit=version,
        model=model_manifest(),
        numpy_rng=[rng[0], rng[1].tolist(), *rng[2:]],
        python_rng=random.getstate(),
        gpu_rng="Official runtime has no RNG parameter; repeat inference comparison is required",
        control=control or {},
        recent_poses=history.poses.numpy()[-4:].tolist(),
        model_context_poses=context.poses.numpy().tolist(),
    )
    mapping = Path(__file__).resolve().parents[1] / "web/src/main.js"
    metadata["vrm_mapping_sha256"] = hashlib.sha256(mapping.read_bytes()).hexdigest()
    metadata["vrm_mapping_source"] = mapping.read_text(encoding="utf-8")
    metadata['vrm_transform_sources']={name:(mapping.parent/name).read_text(encoding='utf-8')
                                      for name in ('coords.js','stance.js','idleHandoff.js','groundedIdle.js')}
    return dict(
        schema_version=1,
        pose=pose.tolist(),
        history=history.poses.numpy().tolist(),
        delta_times=history.delta_times.tolist(),
        metadata=metadata,
    )
