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
    encoded = json.dumps(results, ensure_ascii=False, allow_nan=False, separators=(',',':'))
    (directory / "stop_test_results.json").write_text(encoded, encoding="utf-8")
    diagnostics={row['case']:[candidate['metrics'] for candidate in row.get('candidates',[])]
                 for row in results['cases']}
    (directory/'stop_diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf-8')
    rows = "".join(
        "<tr><td>"
        + html.escape(str(row["case"]))
        + "</td><td>"
        + html.escape(str(row["metrics"]["accepted"]))
        + "</td><td><details><summary>候補・診断値・生成条件</summary><pre>"
        + html.escape(json.dumps({k:v for k,v in row.items() if k!='preview'}, ensure_ascii=False, separators=(',',':')))
        + "</pre></details></td></tr>"
        for row in results["cases"]
    )
    (directory / "stop_test_report.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>停止診断</title>'
        "<style>body{font:16px sans-serif;margin:32px}td{vertical-align:top;padding:12px;border:1px solid #ccc}pre{white-space:pre-wrap}</style>"
        "<h1>停止診断</h1><p>" + html.escape(results["scope"]) + "</p>"
        "<table><tr><th>ケース</th><th>採用可否</th><th>測定結果</th></tr>"
        + rows
        + "</table>" + preview_html(results),
        encoding="utf-8",
    )


def preview_html(results):
    previews={row['case']:row['preview'] for row in results['cases'] if 'preview' in row}
    if not previews:
        return ''
    payload=json.dumps(previews,allow_nan=False).replace('<','\\u003c')
    return '''<h2>SOMA採用候補の再生</h2><p>骨格のプレビューです。VRMの接地品質とは別に確認してください。</p>
<select id="motion"></select><button id="pause">一時停止</button><input id="frame" type="range" min="0" value="0">
<canvas id="preview" width="800" height="400" style="display:block;background:#eef2f6;max-width:100%"></canvas>
<script>
const motions=PAYLOAD,select=document.querySelector('#motion'),slider=document.querySelector('#frame');
for(const name of Object.keys(motions)){const option=document.createElement('option');option.textContent=name;select.append(option);}
let playing=true,index=0;document.querySelector('#pause').onclick=()=>playing=!playing;
select.onchange=()=>index=0;slider.oninput=()=>{index=+slider.value;playing=false;};
const ctx=document.querySelector('#preview').getContext('2d');
setInterval(()=>{const clip=motions[select.value];slider.max=clip.frames.length-1;
if(playing)index=(index+1)%clip.frames.length;slider.value=index;
const points=clip.frames[index],root=points[0];ctx.clearRect(0,0,800,400);
ctx.strokeStyle='#273b53';ctx.lineWidth=3;
const project=p=>[400+(p[0]-root[0]+.45*(p[1]-root[1]))*180,365-p[2]*180];
for(let i=1;i<points.length;i++){const parent=clip.parents[i];if(parent<0)continue;const a=project(points[parent]),b=project(points[i]);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();}
ctx.fillText(`frame ${index*2}`,20,24);
},1000/30);
</script>'''.replace('PAYLOAD',payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("replays", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("metrics/stop-tests"))
    args = parser.parse_args()
    cases = []
    for path in args.replays:
        replay = load_replay(path)
        data = replay["metadata"]
        frames = np.asarray(data["frames"])
        if "generated_contacts" in data:
            from stop_runtime import GeneratedStop

            frames = GeneratedStop(
                frames, data["generated_contacts"], data["generated_support"]
            )
        metrics = validate_stop_motion(
            frames,
            np.asarray(replay["pose"]),
            data.get("validation_goal", data["goal"]),
            data["parents"],
            data["names"],
            data["ground"],
        )
        cases.append(dict(case=str(path), metrics=metrics))
    write_report(
        dict(
            scope="保存済みSOMA配列の再診断。GPU再推論とVRM映像品質は未検証。",
            cases=cases,
        ),
        args.output,
    )


if __name__ == "__main__":
    main()
