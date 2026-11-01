"""PoseLoom（MHR, Y-up, cm）の静止 BVH を SOMA 30 関節の Z-up ローカル姿勢へ変換する。

MHR のレストからポーズへのワールド回転差を、SOMA の基準立ち姿勢へ掛ける。
骨の長さは SOMA のオフセットを維持し、ルートだけ接地と +X 向きに正規化する。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from bvh_io import BvhClip, parse_bvh
from quats import RX90, quat_to_mat
from soma_skeleton import SOMA_JOINT_NAMES, load_soma_reference, locals_from_world, world_from_locals

MHR_REST_PATH = Path(__file__).with_name("mhr_rest.json")

# SOMA 関節 → PoseLoom / MHR の関節。無ければ基準ローカルを保つ。
MHR_SOURCE = {
    "Hips": "Hips",
    "Spine1": "Spine",
    "Spine2": "Spine1",
    "Chest": "Spine2",
    "Neck1": "Neck",
    "Neck2": "Neck",
    "Head": "Head",
    "LeftShoulder": "LeftShoulder",
    "LeftArm": "LeftArm",
    "LeftForeArm": "LeftForeArm",
    "LeftHand": "LeftHand",
    "LeftHandThumbEnd": ("LeftHandThumb4", "LeftHandThumb3", "LeftHandThumb2", "LeftHandThumb1"),
    "LeftHandMiddleEnd": ("LeftHandMiddle4", "LeftHandMiddle3", "LeftHandMiddle2", "LeftHandMiddle1"),
    "RightShoulder": "RightShoulder",
    "RightArm": "RightArm",
    "RightForeArm": "RightForeArm",
    "RightHand": "RightHand",
    "RightHandThumbEnd": ("RightHandThumb4", "RightHandThumb3", "RightHandThumb2", "RightHandThumb1"),
    "RightHandMiddleEnd": ("RightHandMiddle4", "RightHandMiddle3", "RightHandMiddle2", "RightHandMiddle1"),
    "LeftLeg": "LeftUpLeg",
    "LeftShin": "LeftLeg",
    "LeftFoot": "LeftFoot",
    "LeftToeBase": "LeftToeBase",
    "RightLeg": "RightUpLeg",
    "RightShin": "RightLeg",
    "RightFoot": "RightFoot",
    "RightToeBase": "RightToeBase",
}

_FOOTS = ("LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase")


def _source_name(spec, names: set[str]) -> str | None:
    if spec is None:
        return None
    if isinstance(spec, str):
        return spec if spec in names else None
    return next((name for name in spec if name in names), None)


def _apply_basis_and_canonicalize(pos: np.ndarray, rot: np.ndarray, parents: list[int]):
    basis = quat_to_mat(RX90)
    pos = pos @ basis.T
    rot = np.einsum("ij,njk->nik", basis, rot)
    names = {name: i for i, name in enumerate(SOMA_JOINT_NAMES)}
    left = pos[names["LeftLeg"]] - pos[names["RightLeg"]]
    forward = np.array([left[1], -left[0], 0.0])
    norm = float(np.linalg.norm(forward))
    if norm > 1e-6:
        forward /= norm
        yaw = math.atan2(float(forward[1]), float(forward[0]))
        cy, sy = math.cos(-yaw), math.sin(-yaw)
        yaw_m = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
        pos = pos @ yaw_m.T
        rot = np.einsum("ij,njk->nik", yaw_m, rot)
    pos = pos.copy()
    pos[:, 0] -= pos[0, 0]
    pos[:, 1] -= pos[0, 1]
    foot_z = min(float(pos[names[name], 2]) for name in _FOOTS)
    pos[:, 2] -= foot_z
    return locals_from_world(parents, pos, rot)


def load_mhr_rest(path: Path = MHR_REST_PATH) -> dict[str, list[float]]:
    return json.loads(path.read_text(encoding="utf-8"))


def rest_clip_from_pose(clip: BvhClip, rest_rotations: dict[str, list[float]] | None = None) -> np.ndarray:
    """立ち姿勢を MHR のレストにする。単位回転は立ちポーズではない。"""
    rest_rotations = rest_rotations if rest_rotations is not None else load_mhr_rest()
    rotations = np.zeros_like(clip.local_rotations)
    rotations[:, 3] = 1.0
    for index, name in enumerate(clip.names):
        if name in rest_rotations:
            rotations[index] = np.asarray(rest_rotations[name], dtype=np.float64)
    return rotations


def retarget_clip(clip: BvhClip, reference: dict | None = None, mhr_rest: dict | None = None) -> list[list[float]]:
    reference = reference or load_soma_reference()
    parents = list(reference["parents"])
    ref = np.asarray(reference["local_transforms"], dtype=np.float64)
    ref_t, ref_q = ref[:, :3], ref[:, 3:]
    ref_pos, ref_rot = world_from_locals(parents, ref_t, ref_q)

    names = set(clip.names)
    src_index = {name: i for i, name in enumerate(clip.names)}
    rest_rotations = rest_clip_from_pose(clip, mhr_rest)
    _, rest_world = world_from_locals(clip.parents, clip.offsets_m, rest_rotations)
    _, pose_world = world_from_locals(clip.parents, clip.local_translations, clip.local_rotations)

    out_rot = np.zeros_like(ref_rot)
    for joint, name in enumerate(SOMA_JOINT_NAMES):
        source = _source_name(MHR_SOURCE.get(name), names)
        parent = parents[joint]
        if source is None:
            local = quat_to_mat(ref_q[joint])
            out_rot[joint] = local if parent < 0 else out_rot[parent] @ local
            continue
        src = src_index[source]
        delta = pose_world[src] @ rest_world[src].T
        out_rot[joint] = delta @ ref_rot[joint]

    posed_pos = np.zeros_like(ref_pos)
    posed_pos[0] = ref_t[0]
    for joint, parent in enumerate(parents):
        if parent >= 0:
            posed_pos[joint] = posed_pos[parent] + out_rot[parent] @ ref_t[joint]
    translations, rotations = _apply_basis_and_canonicalize(posed_pos, out_rot, parents)
    # 骨長は基準姿勢のまま。高さの正規化はルートだけに残す。
    translations[1:] = ref_t[1:]
    stacked = np.concatenate([translations, rotations], axis=1)
    if not np.isfinite(stacked).all():
        raise ValueError("Retarget produced a non-finite transform")
    return stacked.tolist()


def retarget_bvh_text(text: str) -> list[list[float]]:
    return retarget_clip(parse_bvh(text))
