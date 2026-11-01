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
    if not pose_id.isalnum():
        return None
    path = POSES / f'{pose_id}.json'
    if not path.exists():
        return None
    obj = json.loads(path.read_text(encoding='utf-8'))
    raw = obj.get('local_transforms', [])
    if obj.get('joint_names') != skeleton.joint_names or len(raw) != skeleton.num_joints:
        raise ValueError(f'{path.name}: SOMA joint names/order do not match the runtime')
    if any(len(t) != 7 or any(not math.isfinite(float(v)) for v in t) for t in raw):
        raise ValueError(f'{path.name}: invalid 7-float local transform')
    return raw
