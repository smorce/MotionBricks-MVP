# Decision API（d3-mini）外部呼び出しガイド

確認日: 2026-10-31 JST

MotionBricks MVP の到着ポーズ選択（`backend/d3_router.py`）も、この API を `POST /v1/two-stage` で呼びます。  
クライアント側に torch / transformers は不要です。d3-mini の `serve.sh` が動いているマシンへ HTTP するだけです。  
MotionBricks 本体（WebSocket `8765` / Vite `5173`）とは別プロセスです。Jev / TypeSafe は使いません。

## 前提

1. 起動側で `serve.sh` が動いている
2. 呼び出し側は `BASE_URL`（例: `http://127.0.0.1:8080`）だけ知っていればよい
3. `DECISION_API_KEY` を立てている場合は `Authorization: Bearer <key>` を付ける
4. 他マシンから叩くときは起動側で `HOST=0.0.0.0` にする（ファイアウォールも確認）

## 動作確認結果（ローカル）

| 項目 | 結果 |
|------|------|
| `GET /health` | `200` / `status: ready` |
| モデル | `vllm-sr/d3-mini` |
| 認証 | オフ（`authentication: false`）。Bearer 不要 |
| 既定エンドポイント | `/v1/two-stage` |
| 他エンドポイント | `/decide`, `/v1/grouped` |
| 簡易 payload `POST /v1/two-stage` | `200`（約 0.4s） |
| フル payload（choice + noul + 複数 contexts） | `200`（約 0.5s） |

フル payload の一例:

- `answers.team.choice` = `billing`
- `answers.needs_check.noul` ≈ `0.87`
- 両質問の context 選択は `message_only`

## Python（httpx）

```bash
uv add httpx
```

```python
import os
import httpx

BASE_URL = os.environ.get("D3_API_URL", "http://127.0.0.1:8080")
API_KEY = os.environ.get("DECISION_API_KEY", "")

headers = {"Content-Type": "application/json"}
if API_KEY:
    headers["Authorization"] = f"Bearer {API_KEY}"

payload = {
    "state": {
        "message": "同じ請求が2回届きました。確認して返金してください。",
        "account": "架空の法人アカウント",
    },
    "questions": {
        "team": {
            "type": "choice",
            "instructions": "担当チームを選んでください。",
            "criteria": {
                "billing": "請求・二重課金・返金",
                "engineering": "製品不具合の調査",
                "sales": "新規契約や営業提案",
            },
        },
        "needs_check": {
            "type": "noul",
            "instructions": "請求内容の確認が必要です。",
        },
    },
    "contexts": {
        "message_only": {
            "required": ["message"],
            "description": "問い合わせ本文だけ。アカウント情報は読まない。",
        },
        "message_and_account": {
            "required": ["message", "account"],
            "description": "問い合わせ本文とアカウント識別子。",
        },
    },
}

with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
    health = client.get("/health")
    health.raise_for_status()
    assert health.json()["status"] == "ready"

    # 既定: 二段階推論（/decide でも同じ）
    r = client.post("/v1/two-stage", json=payload, headers=headers)
    r.raise_for_status()
    result = r.json()

print(result["answers"])
print(result["contexts"])  # 1段目で選んだ情報の組
```

`requests` でも同様です。

```python
import os
import requests

BASE_URL = os.environ.get("D3_API_URL", "http://127.0.0.1:8080")
headers = {"Content-Type": "application/json"}
if key := os.environ.get("DECISION_API_KEY"):
    headers["Authorization"] = f"Bearer {key}"

r = requests.post(f"{BASE_URL}/v1/two-stage", json=payload, headers=headers, timeout=120)
r.raise_for_status()
print(r.json()["answers"])
```

## TypeScript / Node（fetch）

```ts
const BASE_URL = process.env.D3_API_URL ?? "http://127.0.0.1:8080";
const headers: Record<string, string> = { "Content-Type": "application/json" };
if (process.env.DECISION_API_KEY) {
  headers.Authorization = `Bearer ${process.env.DECISION_API_KEY}`;
}

const payload = {
  state: { message: "同じ請求が2回届きました。" },
  questions: {
    needs_check: {
      type: "noul",
      instructions: "請求内容の確認が必要です。",
    },
  },
  contexts: {
    message_only: {
      required: ["message"],
      description: "問い合わせ本文だけ。",
    },
  },
};

const res = await fetch(`${BASE_URL}/v1/two-stage`, {
  method: "POST",
  headers,
  body: JSON.stringify(payload),
});
if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
const result = await res.json();
console.log(result.answers, result.contexts);
```

## シェル（他ディレクトリから）

```bash
export D3_API_URL=http://127.0.0.1:8080
# export DECISION_API_KEY=secret   # サーバ側で設定している場合

curl -s -X POST "$D3_API_URL/v1/two-stage" \
  -H 'Content-Type: application/json' \
  ${DECISION_API_KEY:+-H "Authorization: Bearer $DECISION_API_KEY"} \
  -d '{
    "state": {"message": "同じ請求が2回届きました。"},
    "questions": {
      "needs_check": {"type": "noul", "instructions": "請求内容の確認が必要です。"}
    },
    "contexts": {
      "message_only": {
        "required": ["message"],
        "description": "問い合わせ本文だけ。"
      }
    }
  }'
```

PowerShell 例:

```powershell
$env:D3_API_URL = "http://127.0.0.1:8080"
$body = @{
  state = @{ message = "同じ請求が2回届きました。" }
  questions = @{
    needs_check = @{ type = "noul"; instructions = "請求内容の確認が必要です。" }
  }
  contexts = @{
    message_only = @{ required = @("message"); description = "問い合わせ本文だけ。" }
  }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Uri "$env:D3_API_URL/v1/two-stage" -Method POST `
  -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
  -TimeoutSec 120
```

## 呼び出し側の注意

- 初回や長い `state` は数十秒かかることがあるので timeout は長め（目安 60–120 秒）。短文の確認時は 1 秒未満のこともある
- サーバは同時に 1 リクエスト処理（ロックあり）。並列で投げても待ち行列になる
- `DECISION_API_KEY` 未設定のサーバでは Bearer を付けなくてよい（付けても害はないことが多いが、サーバ実装に依存）
- Windows から WSL 上の API を叩く場合、`127.0.0.1:8080` が `wslrelay` 経由で見えることがある
