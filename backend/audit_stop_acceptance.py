"""保存済みの診断から停止条件の選別結果を比較する。推論や人間評価は行わない。"""
import argparse
import json
from collections import Counter
from pathlib import Path
from prepared_stop_acceptance import evaluate_prepared_stop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=Path('metrics/visual-stop-runs'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=150)
    parser.add_argument('--reference-audit', type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    rows = []
    paths = sorted(args.directory.glob('*.json'), reverse=True)
    if args.reference_audit:
        reference = json.loads(args.reference_audit.read_text(encoding='utf-8'))
        paths = [args.directory / Path(row['source']).name for row in reference['rows']]
    for path in paths:
        if not path.stem.isdecimal():
            continue
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('experiment') != 'prepared_f001' or 'validation' not in record:
            continue
        validation = record['validation']; progress = record.get('progress_failure', '')
        error = record['actual_arrival_error_m']
        decision = evaluate_prepared_stop(validation, error, progress)
        rows.append(dict(source=path.name,previous_accepted=bool(validation['accepted'] and not progress and error <= .05+1e-9),
            current_accepted=decision['accepted'],hard_failures=decision['hard_failures'],
            warnings=decision['warnings'],error_m=error,human_rating=record.get('human_rating','unknown')))
        if len(rows) >= args.limit:
            break
    result = dict(scope='Saved diagnostics only; human naturalness is not inferred',records=len(rows),
        previous_accepted=sum(r['previous_accepted'] for r in rows),current_accepted=sum(r['current_accepted'] for r in rows),
        newly_accepted=sum(r['current_accepted'] and not r['previous_accepted'] for r in rows),
        hard_failures=dict(Counter(name for r in rows for name in r['hard_failures'])),
        warnings=dict(Counter(name for r in rows for name in r['warnings'])),rows=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)


if __name__ == '__main__':
    main()
