"""保存した停止配列を再診断し、機械可読結果とHTMLを出力する。"""
import argparse
import html
import json
from pathlib import Path
import numpy as np
from final_stop import validate_stop_motion
from stop_replay import load_replay


def write_report(results, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(results, ensure_ascii=False, allow_nan=False, indent=2)
    (directory / 'stop_test_results.json').write_text(encoded, encoding='utf-8')
    rows = ''.join('<tr><td>'+html.escape(str(row['case']))+'</td><td>'+
                   html.escape(str(row['metrics']['accepted']))+'</td><td><pre>'+
                   html.escape(json.dumps(row['metrics'], ensure_ascii=False, indent=2))+
                   '</pre></td></tr>' for row in results['cases'])
    (directory / 'stop_test_report.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>停止診断</title>'
        '<style>body{font:16px sans-serif;margin:32px}td{vertical-align:top;padding:12px;border:1px solid #ccc}pre{white-space:pre-wrap}</style>'
        '<h1>停止診断</h1><p>'+html.escape(results['scope'])+'</p>'
        '<table><tr><th>ケース</th><th>採用可否</th><th>測定結果</th></tr>'+rows+'</table>', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('replays', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, default=Path('metrics/stop-tests'))
    args = parser.parse_args()
    cases = []
    for path in args.replays:
        replay = load_replay(path)
        data = replay['metadata']
        metrics = validate_stop_motion(np.asarray(data['frames']), np.asarray(replay['pose']),
            data['goal'], data['parents'], data['names'], data['ground'])
        cases.append(dict(case=str(path), metrics=metrics))
    write_report(dict(scope='保存済みSOMA配列の再診断。GPU再推論とVRM映像品質は未検証。', cases=cases), args.output)


if __name__ == '__main__':
    main()
