# ロゼ × MotionBricks × d3-mini × PoseLoom — 検証用プロトタイプ v0.1

確認日: 2026-10-31 JST

このZIPには、**RTX 4090上のNVIDIA MotionBricks SOMAモデルで実際に歩行を生成し、WebSocketで送ってブラウザ上のVRMへ反映するための試作コード**を入れています。**RTX 4090環境では未実行**です。Pythonの構文チェック、JavaScriptの構文チェック、カタログ選択の単体テストのみ実施済みです。確実な動作を保証するものではありません。

PoseLoom BVH は `backend/convert_poses.py` で SOMA 30 関節の Z-up ローカル姿勢へ変換する。変換済みの `soma_poses/<ID>.json` が無い ID は、NVIDIA 付属の待機ポーズへフォールバックする。二人用 BVH は単一骨格ではないため変換をスキップする。

Jev / TypeSafe API は使いません。到着ポーズ選択はローカル（または別マシン）の **d3-mini Decision API**（`POST /v1/two-stage`）です。呼び出し詳細は [EXTERNAL_API.md](EXTERNAL_API.md) を参照してください。

## 1. 動作する予定の機能

- 背景画像（オプション）とロゼ `.vrm` をブラウザで読み込む
- 画面クリック → 3D仮想床との交点 → 移動目標をWebSocket送信
- MotionBricks公式SOMAの Scene Preview キャラクターで、速度を滑らかに変えながら移動する
- 現在速度から停止開始距離を決め、公式の Idle 遷移で減速してから待機する。PoseLoom の姿勢はその後に生成してつなぐ。到着時の目標誤差を画面に出す
- 出力のSOMAローカル関節変換をブラウザへ送信し、three-vrmの正規化人体ボーンへ近似変換
- d3-mini に PoseLoom から絞った候補を渡し、到着時のポーズIDを選択（API未起動時は安全な固定選択）
- PoseLoomポーズが正しくSOMA用JSONに変換済みなら、停止完了後にその姿勢へ生成して移行する

## 2. Windows 11 / RTX 4090 / uv での起動

事前条件: NVIDIAドライバー、Git、Git LFS、`uv`、Node.js 22以上。依存ライブラリの互換性についてはNVIDIAの`README.md`を優先してください。少なくとも最初に公式デモを起動し、MotionBricks本体の環境を正常にすることが前提です。到着ポーズ選択には、別途 d3-mini の `serve.sh` が `D3_API_URL`（既定 `http://127.0.0.1:8080`）で応答していることが望ましいです。

MotionBricks 本体は OneDrive の外に置く。このディレクトリがアプリ本体で、`MOTIONBRICKS_ROOT` から公式ランタイムを読む。

```powershell
# 1. 公式リポジトリを取得（OneDrive 外）
git lfs install
git clone https://github.com/NVlabs/motionbricks.git C:\Users\kbpsh\src\motionbricks
cd C:\Users\kbpsh\src\motionbricks
git lfs pull
$env:UV_LINK_MODE="copy"
uv sync

# 2. SOMA の歩行生成を確認（ビューアなし。初回は TensorRT プランの作成が必要）
uv run python docs/examples/locomotion_loop.py --model soma

# 3. このアプリのサーバーを、MotionBricks の uv 環境で起動する
$env:MOTIONBRICKS_ROOT="C:\Users\kbpsh\src\motionbricks"
$env:D3_API_URL="http://127.0.0.1:8080"          # 空文字にすると API を呼ばず固定選択
# $env:DECISION_API_KEY="secret"                 # サーバ側で鍵を立てているときだけ
# $env:D3_API_TIMEOUT="60"                       # 秒。既定 60
uv run --with fastapi --with "uvicorn[standard]" -- uvicorn server:app --app-dir "C:\Users\kbpsh\OneDrive\ドキュメント\Playground\MotionBricksMVP\backend" --host 127.0.0.1 --port 8765
```

Web側は別のPowerShellで起動します。

```powershell
cd "C:\Users\kbpsh\OneDrive\ドキュメント\Playground\MotionBricksMVP\web"
npm install
npx vite --host 127.0.0.1 --port 5188
```

5173 が別アプリで使われている場合は 5188 を使う。サーバーの CORS は 5173 と 5188 を許可している。

`http://127.0.0.1:5173` にアクセスして、ロゼの `.vrm` を選択し、画面をクリックします。ブラウザ上の `http://127.0.0.1:8765/health` にて `engine_ready: true` になっていることを確認します。d3-mini 側は `http://127.0.0.1:8080/health` が `status: ready` であること。

### PoseLoomの全件メタデータを取り込みたい場合

公式サイトの検索画面からポーズ名とカテゴリを抽出する**試験的スクリプト**を付属しています。HTMLが変更された場合は動かず、結果は目視確認が必要です。

```powershell
# MotionBricksリポジトリ直下
uv run --with beautifulsoup4 -- python roze_mvp/backend/import_catalog.py
```

初期状態では公式サイトで確認した代表的な18件のみ登録しています。全件の変換が終わっていなくても、選択ロジックを実験できます。

## 3. 各ファイル

```text
roze_mvp/
  backend/
    server.py               # WebSocket/health/pose catalog
    engine.py               # 公式SOMAキャラクターの歩行と Idle 停止
    click_planner.py        # 速度に応じた停止距離と減速
    stop_phase.py           # 停止から到着ポーズまでの段階
    d3_router.py            # d3-mini による到着ポーズ選択 / 候補抽出 / フォールバック
    jev_router.py           # 互換 re-export（実装は d3_router）
    poseloom_catalog.json   # PoseLoom 全件の ID・名前・カテゴリ・特徴・BVH URL
    import_catalog.py       # コレクションページからメタデータ抽出
    convert_poses.py        # PoseLoom BVH を SOMA JSON へ変換
    retarget_mhr.py         # MHR から SOMA への回転差リターゲット
    locomotion_policy.py    # 座標変換。以前の固定距離の到着判定はテストに残している
    soma_pose.py            # SOMA姿勢JSONの厳密な形式チェック
    soma_poses/             # BVHから変換したSOMAポーズを格納する場所
  web/
    index.html              # クリックとモデル入力の画面
    src/main.js             # Three.js, three-vrm, WebSocket,骨格マッピング
  tests/                    # カタログ、移動、リターゲットの単体テスト
  EXTERNAL_API.md           # d3-mini 外部呼び出しガイド
```

## 4. SOMAへ変換済みのPoseLoom静止ポーズの形式

`backend/soma_poses/F043.json` の例としては、次の形が必要です。**このスキーマ例は省略表記のため、そのまま読み込めません。**

```json
{
  "joint_names": ["Hips", "Spine1", "Spine2", "...30 joints in the exact NVIDIA skeleton order..."],
  "local_transforms": [
    [0.0, 0.0, 0.96, 0.0, 0.0, 0.0, 1.0]
  ]
}
```

実ファイルでは `joint_names` に**起動時サーバーが送るSOMA骨格の全ジョイント名をその順番で**記載し、`local_transforms` も同数、全て `XYZ(m), quaternion XYZW`、**Zが上方向**でなければなりません。

`convert_poses.py` は PoseLoom の MHR 立ち姿勢からの回転差を SOMA の基準立ち姿勢へ掛け、骨の長さは SOMA のオフセットを維持する。単位はメートル、ルートは地面 XY を原点、正面を +X、足先の最低点を Z=0 にする。指・顎・目は対応関節が無い場合、基準ローカルを保つ。

## 5. 現時点の制限と品質確認

1. 背景画像はCSSによる**表示のみ**です。クリック位置はThree.jsの仮想床に射線を当てて決めます。写真内の床の遠近感に自動一致はしません。写真へ正確に重ねるには、床の4点校正や3Dシーンを必要とします。
2. SOMA→VRMのボーン変換は全身ワールド回転差を使った**近似変換**です。ロゼ独自の身体比率、TポーズとAポーズの違い、肩・脇・上着と足の干渉は未補正です。ブラウザ画面を見ながら回転軸、各部位オフセット、支持足IKを校正してください。
3. **着席、壁越え、障害物の当たり判定、床までの経路探索、スキップ、ゾンビ歩行は未実装**。公式Scene Previewに存在するSmart Primitiveを段階的に追加します。
4. 生成はCPUのみではありません。公式のMotionBricks SOMAデモはTensorRTとNVIDIA GPUを使用します。
5. MotionBricksモデルとNVIDIA付属モーションのライセンスは異なります。付属サンプルBVHはNVIDIA製品の評価・テスト向け条件です。商用配布する前に、モデル契約・サンプル素材・PoseLoomの再配布条件を再確認してください。
6. 1回の生成時間と「クリックからロゼが動くまで」の時間は違います。GPU推論、d3-mini API通信、WebSocket、VRM描画を別々に計測してください。
7. 開発PCのローカルアクセスのみを想定しています。公開サーバーでの認証・アクセス制御・レート制限は未実装です。

## 6. 検証コマンド

```powershell
python -m unittest discover -s roze_mvp/tests -v
node --check roze_mvp/web/src/main.js
```

**推奨する完了条件**

- MotionBricks公式SOMA demoがRTX 4090で正常に動く
- ロゼVRMが正常にロードされ、クリック先まで歩き、止まる
- 直進・旋回・停止で大きな脚滑りや上着のめり込みがない
- d3-mini が正しい候補群からIDを返し、信頼度や処理時間を記録できる
- 最初の3〜5件をPoseLoom→SOMAへ変換し、到着姿勢として実際に反映できる
- その後に椅子の座面座標、向き、高さを与えSmart Primitiveの着席を追加

## 参考一次資料

- NVIDIA公式: https://github.com/NVlabs/motionbricks
- 公式Runtime API: https://github.com/NVlabs/motionbricks/blob/main/docs/runtime_api.md
- 公式実装例: https://github.com/NVlabs/motionbricks/blob/main/docs/examples/locomotion_loop.py
- 公式SOMAモデル: https://github.com/NVlabs/motionbricks/blob/main/docs/soma_model.md
- NVIDIA ONNX計測値: https://github.com/NVlabs/motionbricks/blob/main/docs/onnx_inference.md
- d3-mini 外部呼び出し: [EXTERNAL_API.md](EXTERNAL_API.md)
- PoseLoom: https://pose-loom.pages.dev/
- Three VRM: https://github.com/pixiv/three-vrm
