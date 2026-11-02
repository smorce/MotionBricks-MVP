# AI向け：画面・キャラクター・デバッグ表示の確認手順

確認日：2026-11-02

## 目的と確認済みの方法

ユーザーに毎回スクリーンショットの貼り付けを依頼せず、AI側で `http://127.0.0.1:5188/` を別ブラウザーで開いて撮影・操作・観察する。

この環境ではChrome連携が `The browser access host is unavailable` で失敗した。ネイティブウィンドウの撮影も、現在のURLを検証できないため停止された。一方、Playwrightからインストール済みChromeをヘッドレスで起動する方法で、撮影、床クリック、表示テキスト取得に成功した。

これはユーザーが開いているChromeタブへの接続ではない。別コンテキストなのでカメラ、読み込んだファイル、操作履歴、保存状態が同じとは限らない。また、同じバックエンドに接続するため、操作がユーザー側の状態にも影響する可能性を考慮する。適用中のツール制約で別方式が禁止されている場合は、その制約に従う。

## 初期画面を撮影する

プロジェクトルートでPowerShellを使用する。サーバーは起動済みであること。起動していない場合は既存の起動手順を確認し、5188番ポートで応答する状態にする。

```powershell
npx --yes --package playwright playwright screenshot --browser chromium --channel chrome --viewport-size "1440,1000" --wait-for-timeout 5000 http://127.0.0.1:5188/ "$env:TEMP\motionbricks-preview.png"
```

`npx` は必要ならnpmキャッシュへPlaywrightを取得する。プロジェクトの依存関係を変更する必要はない。`--channel chrome` で既存のChromeを使うため、この方法ではChromiumの追加ダウンロードは不要だった。

撮影後は画像閲覧ツール（`view_image` など）で出力PNGを必ず開く。コマンド成功だけで「画面を見た」と報告しない。`$env:TEMP` の実際の絶対パスを画像閲覧ツールへ渡す。

## 床をクリックし、途中と停止後を記録する

以下は同じページを保持して、初期状態、クリック約1秒後、約8秒後を記録する例。座標 `(1200, 680)` は1440×1000の初期画面で床としてクリックできた位置であり、画面構成やカメラが変わったら最新画像を見て選び直す。固定座標を無条件に使わない。

最初に前節のコマンドでPlaywrightを取得しておく。キャッシュのハッシュ部分を固定したパスに依存しないよう、モジュールを検索して読み込む。

```powershell
$observationPackage = Get-ChildItem -Path "$env:LOCALAPPDATA\npm-cache\_npx\*\node_modules\playwright\package.json" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $observationPackage) { throw 'Playwright package not found in npm cache.' }
$env:MOTIONBRICKS_PLAYWRIGHT_MODULE = Join-Path $observationPackage.DirectoryName 'index.mjs'

@'
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { writeFile } from 'node:fs/promises';

const { chromium } = await import(pathToFileURL(process.env.MOTIONBRICKS_PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto('http://127.0.0.1:5188/');
  await page.waitForTimeout(5000);

  const capture = async (label) => {
    const base = join(process.env.TEMP, `motionbricks-${label}`);
    const text = await page.locator('body').innerText();
    await page.screenshot({ path: `${base}.png` });
    await writeFile(`${base}.txt`, text, 'utf8');
    console.log(JSON.stringify({ label, capturedAt: new Date().toISOString(), image: `${base}.png`, text }));
  };

  await capture('before-click');
  await page.mouse.click(1200, 680);
  await page.waitForTimeout(1000);
  await capture('after-1s');
  await page.waitForTimeout(7000);
  await capture('after-8s');
} finally {
  await browser.close();
}
'@ | node --input-type=module
```

PowerShellでは複雑なJavaScriptを `node -e` の引数へ埋め込むと、引用符が失われる場合がある。この環境で一度失敗したため、上記のように単一引用符のヒアストリングを標準入力へ渡す。

撮影待ちの5秒・1秒・7秒は観察用の間隔であり、ロードや到着の完了を保証する条件ではない。読み込みが終わっていなければ、表示を確認して待機時間を調整する。停止しない場合も、エラーと決めつけず追加観察する。Node処理が継続中ならセッションをポーリングして完了を確認する。

## キャラクターの様子を確認する

生成した各PNGを開き、次を観察する。

- クリック前後で、キャラクターと周囲の家具・床・目標マーカーとの位置関係が変化したか。追従カメラでは画面上のキャラクター位置だけでは判断できない。
- 歩行中の向き、足の前後関係、接地、床へのめり込み・浮き、家具との重なり。
- 停止後の姿勢。足を開いた途中姿勢のままか、待機姿勢へ移ったか。
- 目標マーカーと足元の位置関係。停止したことと目標への到着成功は分けて確認する。

静止画だけで歩容全体の自然さや滑らかさまで断定しない。必要なら同じページで短い間隔の連続画像や動画を記録する。移動操作の成功判定は画像とデバッグ表示を合わせて行う。

## デバッグ表示を確認する

左パネルの「歩行デバッグを表示」「計測ログを保存」の下に状態表示がある。画面下部にも詳細が表示され、同じ文字列が `body.innerText()` に重複して含まれる場合がある。

画像で実際の表示位置とキャラクターの状態を確認し、細かい数値は同じ観察時点のテキストでも読む。

| 表示 | 観察時の扱い |
| --- | --- |
| `stop_failed` | 停止処理の失敗状態として記録する。単に移動できなかったという意味に置き換えない。 |
| `walk 0.00m/s` | 表示速度がゼロ。これだけで正常な停止姿勢とは判断しない。 |
| 左接地・右接地／遊脚 | 表示された左右の状態と画像上の足の姿勢を照合する。 |
| `goal_error_m` | 目標との誤差の表示値を単位付きで記録する。 |
| `stop_prediction_m` | 停止予測に関する表示値として記録する。定義の詳細は実装を確認する。 |
| `final_stop_metrics.reason` / `stop_failure_reason` | 原因文字列をそのまま記録する。文字列だけで根本原因を断定しない。 |
| SOMA足先・VRM足先・差 | 左右それぞれを記録する。座標系・基準の意味や許容値は仕様・実装を確認する。 |

テキスト取得と画像撮影は完全に同時ではない。動的な数値はわずかに変わり得るため、別ブラウザー・別時刻の値まで一致していると報告しない。

## 今回の観察記録

1440×1000の画面で床 `(1200, 680)` をクリックし、8秒後に取得した表示：

```text
stop_failed walk 0.00m/s 左接地/右接地
goal_error_m=0.243m stop_prediction_m=0.250m target
final_stop_metrics.reason=No safe pinned stop target
stop_failure_reason=No safe pinned stop target
left: SOMA足先=0.024m VRM足先=0.030m 差=0.006m
right: SOMA足先=0.043m VRM足先=0.093m 差=0.050m
動作: 停止失敗（歩行停止済み）
```

画像ではキャラクターが移動し、足を前後に開いた姿勢で停止していた。ユーザー側が提示した同様の表示は左VRM足先 `0.035m`、右 `0.095m` など一部の数値が異なっていた。状態・原因文字列の一致と数値の完全一致を区別して伝える。

## AIが報告する際の基準

「操作した」「画像を開いて確認した」「表示テキストを取得した」を実施した範囲で述べる。撮影できる場合は、ユーザーに毎回画像を貼るよう依頼せずAI側で再取得する。ツール接続の失敗とアプリ自体の不具合を混同しない。
