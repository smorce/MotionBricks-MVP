"""現在の歩行履歴を使う目視評価ベースの生成アダプター。"""
import json
import time
from pathlib import Path
import numpy as np
from stop_distance_probe import pure_generate, state_features
from stop_replay import capture_replay
from stop_runtime import new_character
from visual_stop_selector import LAB, load_additional_reviews, load_candidates, select_stop
from timings import TIMINGS


class VisualStopRuntime:
    def __init__(self):
        self.candidates = load_candidates()
        self.candidates += load_additional_reviews(LAB.parent / 'phase9/human-reviews.json')
        from visual_stop_selector import travel_relative_history
        for row in self.candidates:
            row["reference_history"] = travel_relative_history(row["context"])
        self.selection = None
        self.prepared = False

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
        if self.prepared:
            from prepared_stop_selector import select_prepared_stop
            self.selection = select_prepared_stop(state, remaining, self.candidates)
        else:
            self.selection = select_stop(state, remaining, self.candidates)
        return self.selection

    def generate(self, character, goal, ground, rt, destination=None):
        from quats import RX90, quat_mul, quat_to_mat
        replay = capture_replay(character, goal, ground)
        selection = self.selection if self.selection is not None else self.observe(character, goal, ground)
        if selection['status'] not in (('matched', 'experimental') if self.prepared else ('matched',)) or selection['action'] != 'stop':
            raise ValueError('Current stop state is unreviewed')
        idle = character.asset_pool.clip_registry.load(rt['DEFAULT_IDLE_CLIPS'][0]).animation.poses.numpy()[:4].copy()
        for pose in idle:
            pose[0, :3] = quat_to_mat(RX90) @ pose[0, :3]
            pose[0, 3:] = quat_mul(RX90, pose[0, 3:])
        scratch = new_character(rt, character.engine, character.asset_pool, replay)
        with TIMINGS.measure('f001_generation'):
            frames = pure_generate(scratch, replay, selection['candidate'], rt, idle, contact_lock=self.prepared)
        diagnostic_start = time.perf_counter()
        original_goal = goal if destination is None else destination
        error = float(np.linalg.norm(frames[-1][0, :2] - np.asarray(original_goal)[:2]))
        from final_stop import validate_stop_motion, validate_stop_progress
        data = replay['metadata']
        validation = validate_stop_motion(frames, np.asarray(replay['pose']), goal, data['parents'], data['names'], ground)
        reason = validate_stop_progress(frames, np.asarray(replay['pose']), original_goal, frames.support, data['parents'], data['names'],
                                        destination_margin_m=.05 if self.prepared else .02)
        accepted = validation['accepted'] and not reason and error <= .05 + 1e-9
        TIMINGS.record('stop_diagnostics', (time.perf_counter()-diagnostic_start)*1000)
        record = dict(selection=selection, original_destination=np.asarray(original_goal).tolist(),
                      source_replay=replay, validation=validation, progress_failure=reason,
                      experiment='prepared_f001' if self.prepared else 'strict_visual',
                      actual_arrival_error_m=error, generation_settings=selection['candidate']['generation_settings'],
                      human_rating='unknown', notes='', target_adjustment_m=0, animation_scale=1,
                      frames=np.asarray(frames).copy(), contacts=frames.contacts)
        directory = Path(__file__).resolve().parents[1] / 'metrics/visual-stop-runs'
        from replay_writer import WRITER
        WRITER.submit(directory / f'{time.time_ns()}.json', record)
        return frames if accepted else None, dict(accepted=accepted, single_attempt=self.prepared, validation=validation,
                           reason=reason or ('Stop missed destination' if error > .05 else validation.get('reason', '')), acceptance_basis='validated_playback',
                           human_rating='unknown', visual_selection=selection,
                           arrival_error_m=error, travel_distance_m=float(np.linalg.norm(frames[-1][0, :2]-np.asarray(replay['pose'])[0, :2])))
