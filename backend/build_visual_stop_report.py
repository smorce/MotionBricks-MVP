"""実歩行の結果を既存VRMラボで表示できる形式へまとめる。"""
import json
from pathlib import Path


def main():
    directory = Path('metrics/phase9')
    legacy = json.loads((directory / 'legacy.json').read_text(encoding='utf-8'))
    visual = json.loads((directory / 'visual.json').read_text(encoding='utf-8'))
    candidates = []
    rows = []
    for left, right in zip(legacy['candidates'], visual['candidates']):
        if left['id'] != right['id']:
            raise ValueError('Comparison scenarios differ')
        phases = right.get('phases', [])
        start_index = next((i for i, p in enumerate(phases) if p == 'final_step'), None)
        end_index = next((i for i, p in enumerate(phases) if p == 'settled' and start_index is not None and i > start_index), None)
        events = dict(stop_start=None if start_index is None else start_index / 60,
                      stopped=None if end_index is None else end_index / 60,
                      after_one_second=None if end_index is None else end_index / 60 + 1,
                      last_step=None, landing=None, idle=(len(right['frames'])-1)/60 if right.get('idle_start_seconds') is not None else None)
        if start_index is not None and end_index is not None:
            from final_stop import foot_points, contact_points
            import numpy as np
            heights = []
            for frame in right['frames'][start_index:end_index+1]:
                feet = contact_points(foot_points(np.asarray(frame), visual['rig']['parents'], visual['rig']['joint_names']), visual['rig']['stop_ground'])
                heights.append(max(min(p[2] for p in side.values()) for side in feet.values()))
            peak = int(np.argmax(heights))
            landing = next((i for i in range(peak, len(heights)) if heights[i] < .03), len(heights)-1)
            events.update(last_step=(start_index+peak)/60, landing=(start_index+landing)/60)
        for mode, item in [('従来', left), ('目視11候補', right)]:
            item['events'] = events
            selection = item.get('visual_selection') or {}
            item['scenario'] = item['id']
            item['id'] = mode + ':' + item['id']
            item['label'] = mode + ' / ' + item['scenario'] + ' / ' + item['phase'] + ' / X=' + str(selection.get('x_m', '未確認'))
            item['learning_context'] = dict(selection=selection, original_destination=item['goal_xy'],
                                            actual_arrival_error_m=item['metrics']['arrival_error_m'], human_rating='unknown',
                                            notes='', animation_scale=1, target_adjustment_m=0)
            candidates.append(item)
        rows.append(dict(scenario=left['scenario'], x_m=(right.get('visual_selection') or {}).get('x_m'),
                         legacy_phase=left['phase'], visual_phase=right['phase'],
                         legacy_error_m=left['metrics']['arrival_error_m'], visual_error_m=right['metrics']['arrival_error_m'],
                         human_rating='unknown', same_initial_pose=left['frames'][0] == right['frames'][0],
                         same_destination=left['goal_xy'] == right['goal_xy']))
    result = dict(schema_version=1, source_state_id='phase9-live-comparison', rig=legacy['rig'], candidates=candidates)
    (directory / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    (directory / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
