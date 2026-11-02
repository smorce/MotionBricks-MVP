"""現在の歩行履歴を使う目視評価ベースの生成アダプター。"""
import json
import time
from pathlib import Path
import numpy as np
from stop_distance_probe import pure_generate, state_features
from stop_replay import capture_replay
from stop_runtime import new_character
from visual_stop_selector import LAB, load_additional_reviews, load_candidates, select_stop


class VisualStopRuntime:
    def __init__(self):
        self.candidates = load_candidates()
        self.candidates += load_additional_reviews(LAB.parent / 'phase9/human-reviews.json')
        self.selection = None

    def observe(self, character, goal, ground):
        from final_stop import stop_support
        names = list(character.skeleton.joint_names)
        parents = [character.skeleton.joint_parent(i) for i in range(len(names))]
        pose = character.current_pose.numpy().reshape((-1, 7))
        recorder = character.player.motion_history
        replay = dict(pose=pose.tolist(), history=recorder.poses.numpy().tolist(),
                      delta_times=list(recorder.delta_times), metadata=dict(ground=ground,
                      contacts=character.current_foot_contacts.numpy().reshape(-1).tolist(),
                      support=stop_support(pose, goal, parents, names)))
        state = state_features(replay)
        remaining = float(np.linalg.norm(np.asarray(goal)[:2] - np.asarray(replay['pose'])[0, :2]))
        self.selection = select_stop(state, remaining, self.candidates)
        return self.selection

    def generate(self, character, goal, ground, rt):
        from quats import RX90, quat_mul, quat_to_mat
        replay = capture_replay(character, goal, ground)
        selection = self.observe(character, goal, ground)
        if selection['status'] != 'matched' or selection['action'] != 'stop':
            raise ValueError('Current stop state is unreviewed')
        idle = character.asset_pool.clip_registry.load(rt['DEFAULT_IDLE_CLIPS'][0]).animation.poses.numpy()[:4].copy()
        for pose in idle:
            pose[0, :3] = quat_to_mat(RX90) @ pose[0, :3]
            pose[0, 3:] = quat_mul(RX90, pose[0, 3:])
        scratch = new_character(rt, character.engine, character.asset_pool, replay)
        frames = pure_generate(scratch, replay, selection['candidate'], rt, idle)
        error = float(np.linalg.norm(frames[-1][0, :2] - np.asarray(goal)[:2]))
        record = dict(selection=selection, original_destination=np.asarray(goal).tolist(),
                      actual_arrival_error_m=error, generation_settings=selection['candidate']['generation_settings'],
                      human_rating='unknown', notes='', target_adjustment_m=0, animation_scale=1,
                      frames=np.asarray(frames).tolist(), contacts=frames.contacts)
        directory = Path(__file__).resolve().parents[1] / 'metrics/visual-stop-runs'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f'{time.time_ns()}.json').write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        return frames, dict(accepted=True, acceptance_basis='experimental_playback_only',
                           human_rating='unknown', visual_selection=selection,
                           arrival_error_m=error, travel_distance_m=float(np.linalg.norm(frames[-1][0, :2]-np.asarray(replay['pose'])[0, :2])))
