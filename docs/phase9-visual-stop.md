# Phase 9 実験仕様

既存の評価原本と診断を変更せず、状態IDと候補IDの組で自然な11候補のみ読み込む。診断結果は選択に使用しない。

直近4姿勢のルート相対位置と関節回転、速度、方向、支持足、接地、位相で一致範囲を制限する。閾値は実験用であり、近傍一致は新しい生成結果の自然さを保証しない。未確認状態を自然と判定しない。

支持足・保存された位相ラベル・接地4チャネルの0.5判定を一致条件とし、速度差0.2m/s、方向差0.26rad、関節回転RMS差0.18rad、位置RMS差0.025mを上限とする。SOMAの子関節はローカル位置のため、平行移動の正規化はルートにのみ適用する。現在の保存データの位相ラベルはcontact-derivedであり、詳細な位相差は姿勢履歴と接地で区別する。世界方向を回転して同一視する処理は行っていないため、別の向きは未確認になり得る。

目的地は保持する。近い候補がない短距離では伸縮・目標補正を行わず未確認として停止する。実験モードのみ有効にし、通常制御は既定のまま残す。生成は保存済みフレームではなく現在の履歴を復元した独立キャラクターから行う。

比較結果の自然さは人間が入力する。未入力は unknown とし、開始状態、採用候補、生成条件、元の目的地への到着誤差と紐づけて記録する。

## 実行と比較画面

公式MotionBricksのuv環境で `MOTIONBRICKS_ROOT` を設定する。`MOTIONBRICKS_VISUAL_STOP=1` のときだけ実歩行の選択器が有効になる。未設定の通常制御は従来どおり。比較CLI用の `MOTIONBRICKS_COMPARISON_REPLAY` は通常起動では設定しない。

```
uv run --project C:/Users/kbpsh/src/motionbricks --link-mode=copy python backend/run_visual_stop_comparison.py --mode legacy
uv run --project C:/Users/kbpsh/src/motionbricks --link-mode=copy python backend/run_visual_stop_comparison.py --mode visual
uv run --project C:/Users/kbpsh/src/motionbricks --link-mode=copy python backend/append_visual_idle.py
uv run --project C:/Users/kbpsh/src/motionbricks --link-mode=copy python backend/build_visual_stop_report.py
```

`metrics/phase9/measurements.zip` を展開し、既存の `stop-distance-lab.html` で `comparison.json` とロゼVRMを選択する。移動条件で左右比較、全候補で16件の同時再生、時間スライダーと視点選択で比較できる。実測された停止区間には6つの確認時点を用意した。最後の一歩と着地は足高から抽出した確認候補時刻であり、人間が動画で確認する。未確認終了した条件の停止・着地・Idle時点は未記録として表示する。

新しい評価はブラウザに一時保存し、全16件の開始状態・選択X・生成条件・元の目的地への誤差とともにJSONへ書き出す。人間が評価した書き出しを `metrics/phase9/human-reviews.json` に保存すると、次回起動時に good の実行状態だけが追加候補として読み込まれる。原本11候補の評価は変更しない。

## 計測結果（2026-11-02）

|条件|新方式のX|従来の誤差|新方式の誤差|新方式の終端|
|---|---:|---:|---:|---|
|30cm|未確認|0.000m|0.150m|未確認終了|
|30cm→50cmの後半|未確認|0.000m|0.124m|未確認終了|
|50cm|0.500m|0.105m|0.000m|停止生成完了|
|1m|1.000m|0.000m|0.000m|停止生成完了|
|2m|0.600m|0.000m|0.000m|停止生成完了|
|5m|0.500m|0.000m|0.000m|停止生成完了|
|90度旋回後|0.500m|0.000m|0.000m|停止生成完了|
|Idle再歩行|未確認|0.033m|0.129m|未確認終了|

数値は丸めて表示し、元値は `results.json` に保存した。停止生成完了は自然さの合格を意味しない。**新しい実動作の自然さは全条件で人間の評価待ち**。30cm・連続移動・Idle再歩行は、適合状態がなく歩行途中の姿勢を保持して終了するため、自然な停止を実現できていない。評価を得るまでは通常制御を置き換えない。

単独条件は同じ保存姿勢と目的地から開始した。連続移動は両方式とも共通の開始姿勢と同じクリック列を使い、後半は各方式の前半の結果を引き継ぐため、後半の開始姿勢は一致しない。旋回後は既存のafter-turn履歴を復元した。Idle再歩行は公式キャラクターの初期待機姿勢・履歴を復元した。GPU推論乱数の完全一致は保証しない。

停止できた条件では、比較用の追加生成として静止1秒後に公式SOMA Idle4へ遷移させた。これは実際に推論したフレームであり、最終姿勢の貼り付けではない。停止後の履歴は静止姿勢で満たし、接地入力は両足接地を仮定しているため、実際の接地を確認する追加評価が必要。Idle生成には向きの不定性を避ける1mm先の目標を用い、元の目的地を保持してIdle後の誤差も `idle_arrival_error_m` に分けて保存する。通常画面のGroundedIdle移行を置き換える変更ではない。

## 目視確認資料と検証

- 正面・側面・45度: `metrics/phase9/*-front.png`、`*-side.png`、`*-quarter.png`
- 停止開始・最後の一歩候補・着地候補・停止直後・1秒後・Idle後: `metrics/phase9/1m-*-front.png` 等
- 同期比較動画: `metrics/phase9/synchronized.webm`
- 評価用JSON: `metrics/phase9/review-template.json`

[正面](../metrics/phase9/1m-stopped-front.png)・[側面](../metrics/phase9/1m-stopped-side.png)・[45度](../metrics/phase9/1m-stopped-quarter.png)・[同期比較動画](../metrics/phase9/synchronized.webm)・[全姿勢データ](../metrics/phase9/measurements.zip)

Python 133テスト、Web 27テストを実行した。ブラウザ検証は既存Playwrightスクリプトの方式を使用し、実ロゼVRMの読み込み、8条件、3視点、時点選択、16候補同時表示、評価書き出しを確認する。自動安全診断の不合格原因は調査せず、原本の診断値と人間の評価を保持した。
