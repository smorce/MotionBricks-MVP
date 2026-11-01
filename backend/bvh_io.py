"""BVH の階層と先頭フレームを読む。位置はメートル、回転は XYZW。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from quats import euler_channels_to_quat


@dataclass
class BvhClip:
    names: list[str]
    parents: list[int]
    offsets_m: np.ndarray
    local_translations: np.ndarray
    local_rotations: np.ndarray


def parse_bvh(text: str, frame: int = 0) -> BvhClip:
    lines = text.splitlines()
    names: list[str] = []
    parents: list[int] = []
    offsets: list[list[float]] = []
    channels: list[list[str]] = []
    stack: list[int] = []
    in_end = False
    motion_at = None
    for index, line in enumerate(lines):
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "MOTION":
            motion_at = index
            break
        if tokens[0] in ("ROOT", "JOINT"):
            names.append(tokens[1])
            parents.append(stack[-1] if stack else -1)
            offsets.append([0.0, 0.0, 0.0])
            channels.append([])
            stack.append(len(names) - 1)
        elif tokens[:2] == ["End", "Site"]:
            in_end = True
        elif tokens[0] == "}":
            if in_end:
                in_end = False
            elif stack:
                stack.pop()
        elif tokens[0] == "OFFSET" and not in_end and names:
            offsets[-1] = [float(v) for v in tokens[1:4]]
        elif tokens[0] == "CHANNELS" and not in_end and names:
            count = int(tokens[1])
            listed = tokens[2:]
            if count != len(listed):
                raise ValueError(f"BVH joint {names[-1]} declares {count} channels but lists {len(listed)}")
            channels[-1] = listed
    if motion_at is None or not names:
        raise ValueError("BVH hierarchy or MOTION section is missing")
    if sum(1 for parent in parents if parent < 0) != 1:
        raise ValueError("Multiple roots are not supported")

    frame_count = None
    values: list[float] = []
    for line in lines[motion_at + 1 :]:
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "Frames:":
            frame_count = int(tokens[1])
        elif tokens[:2] == ["Frame", "Time:"]:
            continue
        else:
            values.extend(float(v) for v in tokens)
    channel_count = sum(len(c) for c in channels)
    if frame_count is None or channel_count == 0 or len(values) < channel_count * (frame + 1):
        raise ValueError("BVH motion frame is missing")
    if frame_count * channel_count != len(values):
        raise ValueError(f"BVH motion has {len(values)} values, expected {frame_count * channel_count}")

    sample = values[frame * channel_count : (frame + 1) * channel_count]
    translations = np.zeros((len(names), 3), dtype=np.float64)
    rotations = np.zeros((len(names), 4), dtype=np.float64)
    rotations[:, 3] = 1.0
    cursor = 0
    for joint, joint_channels in enumerate(channels):
        degrees: list[float] = []
        axis_ids: list[int] = []
        has_position = False
        position = np.zeros(3, dtype=np.float64)
        for channel in joint_channels:
            value = sample[cursor]
            cursor += 1
            lower = channel.lower()
            if lower.endswith("position"):
                position["xyz".index(lower[0])] = value
                has_position = True
            elif lower.endswith("rotation"):
                degrees.append(value)
                axis_ids.append("xyz".index(lower[0]))
        translations[joint] = (position if has_position else np.asarray(offsets[joint], dtype=np.float64)) * 0.01
        if axis_ids:
            rotations[joint] = euler_channels_to_quat(axis_ids, degrees)
    return BvhClip(names, parents, np.asarray(offsets, dtype=np.float64) * 0.01, translations, rotations)
