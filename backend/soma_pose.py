"""Validated bridge for SOMA pose JSON. The converter from PoseLoom BVH is separate.

Shape: {"joint_names": [...], "local_transforms": [[tx,ty,tz,qx,qy,qz,qw], ...]}
Transforms are local SOMA transforms in Z-up world coordinates, in meters.
The root should be at the origin, and one file represents ONE static pose.
"""
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
POSES = HERE / 'soma_poses'


def read_soma_pose(pose_id: str, skeleton):
    if not pose_id.replace('_', '').isalnum():
        return None
    path = POSES / f'{pose_id}.json'
    if not path.exists():
        return None
    obj = json.loads(path.read_text(encoding='utf-8'))
    raw = obj.get('local_transforms', [])
    file_names = obj.get('joint_names')
    if not isinstance(file_names, list) or len(raw) != len(file_names):
        raise ValueError(f'{path.name}: SOMA joint names and transforms differ in length')
    if any(len(t) != 7 or any(not math.isfinite(float(v)) for v in t) for t in raw):
        raise ValueError(f'{path.name}: invalid 7-float local transform')
    runtime_names = list(skeleton.joint_names)
    if file_names == runtime_names:
        return raw
    if set(file_names) == set(runtime_names) and len(file_names) == skeleton.num_joints:
        index = {name: i for i, name in enumerate(file_names)}
        return [raw[index[name]] for name in runtime_names]
    if set(file_names) <= set(runtime_names):
        return None
    raise ValueError(f'{path.name}: SOMA joint names/order do not match the runtime')


def overlay_pose(pose_id: str, joint_names, base):
    """30 関節の JSON を、指などを含む実行時骨格へ重ねる。骨長は base を維持し、回転とルートだけを置き換える。"""
    if not str(pose_id).replace('_', '').isalnum():
        return None
    path = POSES / f'{pose_id}.json'
    if not path.exists():
        return None
    obj = json.loads(path.read_text(encoding='utf-8'))
    raw = obj.get('local_transforms', [])
    file_names = obj.get('joint_names')
    if not isinstance(file_names, list) or len(raw) != len(file_names):
        raise ValueError(f'{path.name}: SOMA joint names and transforms differ in length')
    if any(len(t) != 7 or any(not math.isfinite(float(v)) for v in t) for t in raw):
        raise ValueError(f'{path.name}: invalid 7-float local transform')
    names = list(joint_names)
    if not set(file_names) <= set(names):
        raise ValueError(f'{path.name}: SOMA joint names/order do not match the runtime')
    out = [list(map(float, row)) for row in base]
    index = {name: i for i, name in enumerate(names)}
    for name, transform in zip(file_names, raw):
        slot = index[name]
        values = [float(v) for v in transform]
        if name == 'Hips':
            out[slot] = values
        else:
            out[slot] = list(out[slot][:3]) + values[3:]
    return out
