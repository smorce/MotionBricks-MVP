"""時刻ラベルを使わず、実測した接地・足幅・速度から回帰状態を採取する。"""

import argparse
import json
from pathlib import Path
import numpy as np
from engine import _load_runtime, _prime_walk, _command, DT
from stop_replay import capture_replay
from final_stop import calibrate_stop_ground, contact_points
from step_cycle import foot_points
from collect_stance import stance
from quats import RX90, quat_mul, quat_to_mat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rt = _load_runtime()
    wp = rt["wp"]
    wp.init()
    wp.set_device("cuda:0")
    a = rt["load_rig_assets"](rt["ModelRig"].SOMA)
    pool = rt["SmartPrimitiveAssetPool"](
        a.clip_registry, a.reference_pose, a.model_to_runtime
    )
    e = rt["MotionBricksSOMAEngine"](
        rt["SOMA_N1_FP32_ONNX_PATH"], model_to_runtime=a.model_to_runtime
    )
    coverage = {}
    with e, wp.ScopedStream(e.stream):
        c = rt["SOMACharacter"](
            e,
            asset_pool=pool,
            modes=rt["DEFAULT_LOCOMOTION_MODES"],
            idle_paths=(rt["DEFAULT_IDLE_CLIPS"][0],),
            crouch_idle_paths=rt["DEFAULT_CROUCH_IDLE_CLIPS"],
        )
        names = list(c.skeleton.joint_names)
        parents = [c.skeleton.joint_parent(i) for i in range(len(names))]
        rest = c.skeleton.reference_local_transforms.numpy().reshape((-1, 7)).copy()
        rest[0, :3] = quat_to_mat(RX90) @ rest[0, :3]
        rest[0, 3:] = quat_mul(RX90, rest[0, 3:])
        ground = calibrate_stop_ground(rest, parents, names)
        facing = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        _prime_walk(c, facing)

        def save(label, measurements, distance=0.2):
            if label in coverage:
                return
            p = c.current_pose.numpy().reshape((-1, 7))
            replay = capture_replay(
                c, p[0, :2] + facing[:2] * distance, ground, control=measurements
            )
            (args.output / (label + ".json")).write_text(
                json.dumps(replay, allow_nan=False), encoding="utf-8"
            )
            coverage[label] = measurements

        previous = c.current_pose.numpy().reshape((-1, 7))[0, :2].copy()
        for tick in range(420):
            c.step(DT, _command(rt, facing, facing))
            p = c.current_pose.numpy().reshape((-1, 7))
            v = float(np.linalg.norm(p[0, :2] - previous) / DT)
            previous = p[0, :2].copy()
            contacts = c.current_foot_contacts.numpy().reshape(-1)
            feet = contact_points(foot_points(p, parents, names), ground)
            h = {
                s: float(min(x[2] for x in feet[s].values())) for s in ("left", "right")
            }
            sagittal, width = stance(p, parents, names)
            m = dict(
                speed_mps=v,
                contacts=contacts.tolist(),
                height_m=h,
                sagittal_m=sagittal,
                width_m=width,
                tick=tick,
            )
            if (
                max(contacts[:2]) < 0.4
                and max(contacts[2:]) > 0.5
                and h["left"] > 0.025
            ):
                save("left-swing", m)
            if (
                max(contacts[2:]) < 0.4
                and max(contacts[:2]) > 0.5
                and h["right"] > 0.025
            ):
                save("right-swing", m)
            if min(contacts) > 0.8 and max(h.values()) < 0.02:
                save("double-contact", m)
            if sagittal > 0.26:
                save("large-stride", m)
            if sagittal < 0.15 and v > 0.3:
                save("small-stride", m)
            if 0.8 < v < 2.5:
                save("normal-speed", m)
                for label, d in [
                    ("distance-20cm", 0.2),
                    ("distance-50cm", 0.5),
                    ("distance-1m", 1.0),
                ]:
                    save(label, m, d)
        facing = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        for _ in range(20):
            c.step(DT, _command(rt, facing, facing))
        save("after-turn", dict(command_facing=facing.tolist(), elapsed_s=20 * DT))
        for _ in range(30):
            c.step(DT, _command(rt, facing, facing * 0.2))
        save("decelerating", dict(command_strength=0.2, elapsed_s=30 * DT))
        for _ in range(180):
            c.step(DT, _command(rt, facing, None))
        before = c.state_machine.state.name
        _prime_walk(c, facing)
        for _ in range(20):
            c.step(DT, _command(rt, facing, facing))
        save("idle-restart", dict(previous_state=before, restart_elapsed_s=20 * DT))
    (args.output / "coverage.json").write_text(
        json.dumps(coverage, indent=2), encoding="utf-8"
    )
    print("Measured conditions:", list(coverage), flush=True)


if __name__ == "__main__":
    main()
