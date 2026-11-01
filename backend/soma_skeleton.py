"""MotionBricks SOMA の 30 関節。順序は soma_n1.json に合わせる。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from bvh_io import parse_bvh
from quats import mat_to_quat, quat_to_mat

SOMA_JOINT_NAMES = [
    "Hips",
    "Spine1",
    "Spine2",
    "Chest",
    "Neck1",
    "Neck2",
    "Head",
    "Jaw",
    "LeftEye",
    "RightEye",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "LeftHandThumbEnd",
    "LeftHandMiddleEnd",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "RightHandThumbEnd",
    "RightHandMiddleEnd",
    "LeftLeg",
    "LeftShin",
    "LeftFoot",
    "LeftToeBase",
    "RightLeg",
    "RightShin",
    "RightFoot",
    "RightToeBase",
]

REFERENCE_PATH = Path(__file__).with_name("soma_reference.json")

# 指の途中関節は SOMA に無いので、End は手の直下として合成する。
_PARENT_NAME = {
    "Spine1": "Hips",
    "Spine2": "Spine1",
    "Chest": "Spine2",
    "Neck1": "Chest",
    "Neck2": "Neck1",
    "Head": "Neck2",
    "Jaw": "Head",
    "LeftEye": "Head",
    "RightEye": "Head",
    "LeftShoulder": "Chest",
    "LeftArm": "LeftShoulder",
    "LeftForeArm": "LeftArm",
    "LeftHand": "LeftForeArm",
    "LeftHandThumbEnd": "LeftHand",
    "LeftHandMiddleEnd": "LeftHand",
    "RightShoulder": "Chest",
    "RightArm": "RightShoulder",
    "RightForeArm": "RightArm",
    "RightHand": "RightForeArm",
    "RightHandThumbEnd": "RightHand",
    "RightHandMiddleEnd": "RightHand",
    "LeftLeg": "Hips",
    "LeftShin": "LeftLeg",
    "LeftFoot": "LeftShin",
    "LeftToeBase": "LeftFoot",
    "RightLeg": "Hips",
    "RightShin": "RightLeg",
    "RightFoot": "RightShin",
    "RightToeBase": "RightFoot",
}


def soma_parents() -> list[int]:
    index = {name: i for i, name in enumerate(SOMA_JOINT_NAMES)}
    return [-1 if name == "Hips" else index[_PARENT_NAME[name]] for name in SOMA_JOINT_NAMES]


def world_from_locals(parents: list[int], translations: np.ndarray, rotations: np.ndarray):
    count = len(parents)
    pos = np.zeros((count, 3), dtype=np.float64)
    rot = np.zeros((count, 3, 3), dtype=np.float64)
    for joint, parent in enumerate(parents):
        local_r = quat_to_mat(rotations[joint])
        local_t = np.asarray(translations[joint], dtype=np.float64)
        if parent < 0:
            rot[joint] = local_r
            pos[joint] = local_t
        else:
            rot[joint] = rot[parent] @ local_r
            pos[joint] = pos[parent] + rot[parent] @ local_t
    return pos, rot


def locals_from_world(parents: list[int], pos: np.ndarray, rot: np.ndarray):
    translations = np.zeros((len(parents), 3), dtype=np.float64)
    rotations = np.zeros((len(parents), 4), dtype=np.float64)
    for joint, parent in enumerate(parents):
        if parent < 0:
            translations[joint] = pos[joint]
            rotations[joint] = mat_to_quat(rot[joint])
        else:
            parent_r = rot[parent]
            translations[joint] = parent_r.T @ (pos[joint] - pos[parent])
            rotations[joint] = mat_to_quat(parent_r.T @ rot[joint])
    return translations, rotations


def reference_from_soma_bvh(path: Path) -> dict:
    clip = parse_bvh(path.read_text(encoding="utf-8"), frame=0)
    index = {name: i for i, name in enumerate(clip.names)}
    missing = [name for name in SOMA_JOINT_NAMES if name not in index]
    if missing:
        raise ValueError(f"SOMA BVH is missing joints: {missing}")
    pos, rot = world_from_locals(clip.parents, clip.local_translations, clip.local_rotations)
    parents = soma_parents()
    kept_pos = np.zeros((len(SOMA_JOINT_NAMES), 3))
    kept_rot = np.zeros((len(SOMA_JOINT_NAMES), 3, 3))
    for joint, name in enumerate(SOMA_JOINT_NAMES):
        kept_pos[joint] = pos[index[name]]
        kept_rot[joint] = rot[index[name]]
    translations, rotations = locals_from_world(parents, kept_pos, kept_rot)
    transforms = np.concatenate([translations, rotations], axis=1)
    return {
        "joint_names": SOMA_JOINT_NAMES,
        "parents": parents,
        "local_transforms": transforms.round(8).tolist(),
        "space": "y-up-meters",
    }


def load_soma_reference(path: Path = REFERENCE_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("joint_names") != SOMA_JOINT_NAMES:
        raise ValueError("soma_reference.json joint order does not match SOMA")
    return data
