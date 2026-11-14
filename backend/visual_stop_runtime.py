"""現在の歩行履歴を使う目視評価ベースの生成アダプター。"""
import json
import time
from pathlib import Path
import numpy as np
from engine import _sync_pose
from stop_distance_probe import pure_generate, state_features
from stop_replay import capture_replay
from stop_runtime import new_character
from stop_replay import restore_history
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
        self._character_identity = None
        self._names = None
        self._parents = None
        self._scratch = None
        self._scratch_engine = None
        self._scratch_pool = None
        self._idle_poses = None
        self._idle_pool = None
        self._observe_distance_m = max(
            (float(row["specification"].get("distance_m", 0.0)) for row in self.candidates),
            default=0.0,
        ) + 0.05

    def _get_skeleton(self, character):
        identity = id(character.skeleton)
        if identity != self._character_identity:
            self._character_identity = identity
            self._names = list(character.skeleton.joint_names)
            self._parents = [character.skeleton.joint_parent(i) for i in range(len(self._names))]
        return self._names, self._parents

    def _reset_scratch(self, scratch, rt, replay):
        _sync_pose(scratch, np.asarray(replay["pose"]), rt["wp"])
        restore_history(scratch, replay)
        scratch.actual_velocity.fill(0.0)
        scratch.clear_ik_pins()

    def _get_scratch(self, rt, engine, pool, replay):
        if self._scratch is None or self._scratch_engine is not engine or self._scratch_pool is not pool:
            self._scratch = new_character(rt, engine, pool, replay)
            self._scratch_engine = engine
            self._scratch_pool = pool
        else:
            self._reset_scratch(self._scratch, rt, replay)
        return self._scratch

    def _get_idle_poses(self, character, rt):
        if self._idle_poses is None or self._idle_pool is not character.asset_pool:
            from quats import RX90, quat_mul, quat_to_mat

            idle = character.asset_pool.clip_registry.load(
                rt["DEFAULT_IDLE_CLIPS"][0]
            ).animation.poses.numpy()[:4].copy()
            for pose in idle:
                pose[0, :3] = quat_to_mat(RX90) @ pose[0, :3]
                pose[0, 3:] = quat_mul(RX90, pose[0, 3:])
            self._idle_poses = idle
            self._idle_pool = character.asset_pool
        return self._idle_poses.copy()

    def observe(self, character, goal, ground):
        from final_stop import stop_support
        names, parents = self._get_skeleton(character)
        pose = character.current_pose.numpy().reshape((-1, 7))
        remaining = float(np.linalg.norm(np.asarray(goal)[:2] - pose[0, :2]))
        if remaining > self._observe_distance_m:
            self.selection = dict(
                status="preparing",
                action="walk",
                human_rating="unknown",
                target_pose_distance_m=remaining,
            )
            return self.selection
        recorder = character.player.motion_history
        replay = dict(pose=pose.tolist(), history=recorder.poses.numpy().tolist(),
                      delta_times=list(recorder.delta_times), metadata=dict(ground=ground,
                      contacts=character.current_foot_contacts.numpy().reshape(-1).tolist(),
                      support=stop_support(pose, goal, parents, names)))
        state = state_features(replay)
        if self.prepared:
            from prepared_stop_selector import select_prepared_stop
            self.selection = select_prepared_stop(state, remaining, self.candidates)
        else:
            self.selection = select_stop(state, remaining, self.candidates)
        return self.selection

    def generate(self, character, goal, ground, rt, destination=None, *, cancelled=None):
        replay = capture_replay(character, goal, ground)
        selection = self.selection if self.selection is not None else self.observe(character, goal, ground)
        if selection['status'] not in (('matched', 'experimental') if self.prepared else ('matched',)) or selection['action'] != 'stop':
            raise ValueError('Current stop state is unreviewed')
        idle = self._get_idle_poses(character, rt)
        scratch = self._get_scratch(rt, character.engine, character.asset_pool, replay)
        with TIMINGS.measure('f001_generation'):
            frames = pure_generate(scratch, replay, selection['candidate'], rt, idle, contact_lock=self.prepared, cancelled=cancelled)
        diagnostic_start = time.perf_counter()
        original_goal = goal if destination is None else destination
        error = float(np.linalg.norm(frames[-1][0, :2] - np.asarray(original_goal)[:2]))
        from final_stop import validate_stop_motion, validate_stop_progress
        data = replay['metadata']
        validation = validate_stop_motion(frames, np.asarray(replay['pose']), goal, data['parents'], data['names'], ground)
        reason = validate_stop_progress(frames, np.asarray(replay['pose']), original_goal, frames.support, data['parents'], data['names'],
                                        destination_margin_m=.05 if self.prepared else .02)
        accepted = validation['accepted'] and not reason and error <= .05 + 1e-9
        progress_reason = reason
        decision = None
        if self.prepared:
            from prepared_stop_acceptance import evaluate_prepared_stop
            decision = evaluate_prepared_stop(validation, error, progress_reason)
            accepted = decision['accepted']
            reason = decision['reason']
        TIMINGS.record('stop_diagnostics', (time.perf_counter()-diagnostic_start)*1000)
        record = dict(selection=selection, original_destination=np.asarray(original_goal).tolist(),
                      source_replay=replay, validation=validation, progress_failure=progress_reason,
                      acceptance_policy=decision,
                      experiment='prepared_f001' if self.prepared else 'strict_visual',
                      actual_arrival_error_m=error, generation_settings=selection['candidate']['generation_settings'],
                      human_rating='unknown', notes='', target_adjustment_m=0, animation_scale=1,
                      frames=np.asarray(frames).copy(), contacts=frames.contacts)
        directory = Path(__file__).resolve().parents[1] / 'metrics/visual-stop-runs'
        from replay_writer import WRITER
        WRITER.submit(directory / f'{time.time_ns()}.json', record)
        return frames if accepted else None, dict(accepted=accepted, single_attempt=self.prepared, validation=validation,
                           reason='' if accepted else reason or ('Stop missed destination' if error > .05 else validation.get('reason', '')), acceptance_basis='minimum_guards' if self.prepared else 'validated_playback',
                           policy=decision['policy'] if decision else 'strict_visual',
                           warnings=decision['warnings'] if decision else [],
                           human_rating='unknown', visual_selection=selection,
                           arrival_error_m=error, travel_distance_m=float(np.linalg.norm(frames[-1][0, :2]-np.asarray(replay['pose'])[0, :2])))
