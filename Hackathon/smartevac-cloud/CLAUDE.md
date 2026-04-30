# SmartEvac Cloud — 開發守則

本檔由 ErgoGuard Flow 2（`../../ergoguard-voice/CLAUDE.md`）橫向擴展而來。
**已驗證的決策不要重新評估**。

## 沿用 Flow 2 的硬性決策

### 為何用 Google（Gemini + Cloud TTS）而非 AWS（Bedrock + Polly）

AWS Academy Learner Lab 的 SCP 擋住 `bedrock:*` 與 `polly:*`，且學生無法
申請開通（IAM 不可改、SCP 在 LabRole 之上）。改走 Google 等價服務，
有充足的免費 tier。

- **Gemini**（預設 `gemini-2.5-flash-lite`）— 文字生成，走 `google-genai` SDK
- **Google Cloud TTS** — 音訊合成，走 REST `POST /v1/text:synthesize?key=…`
  （不用 SDK，壓 Lambda 包大小）

### 兩把 Google API key

AI Studio 建立的 key 被 Google 綁定只能用 Gemini。要呼叫 Cloud TTS 必須
另外從 Cloud Console → APIs & Services → 憑證 建第二把（建議限制
只能呼叫 Cloud Text-to-Speech API）。兩把可在同一個 GCP project（`ergoguard`）。

- `GOOGLE_API_KEY` → Gemini
- `GOOGLE_TTS_API_KEY` → TTS

### 其他沿用

- Lambda runtime `python3.12`（開發機 Homebrew 預設版本）
- SAM 部署、`Role: LabRole` 寫死（Learner Lab 不允許自訂 IAM）
- Gemini 503 → sleep 2 秒重試一次（實測最佳值）
- TTS voice：`cmn-TW-Wavenet-A` 繁中女聲（自然度勝過 Standard，仍在免費 tier）

## 本階段新增的工程決策

### IoT Rule 觸發 vs S3 PutObject 觸發

Flow 2 由 S3 Put（`analysis/*.json`）觸發；本階段改用 IoT Core Rule：

```sql
SELECT * FROM 'smartevac/telemetry/+' WHERE alert_level = 'alert'
```

IoT Rule 的 Lambda event 沒有 `Records[]` wrapper，event 物件 **直接就是**
SQL SELECT 後的 payload。`parse_iot_alert()` 直接讀 `event["node_id"]` 即可，
不要套用 Flow 2 的 `Records[0]` 解析模式。

### 多節點 fan-out 並行化

兩處用 `concurrent.futures.ThreadPoolExecutor`：

1. `tts.parallel_synthesize` — N 份 MP3 並行合成（HTTP REST 是 IO bound）
2. `iot_publisher.parallel_publish` — N 個 topic 並行 publish

`max_workers = max(len(items), 1)` 即可，3 節點規模不需要調 pool 大小。

### Gemini 批次 prompt（壓延遲）

不要對每個節點各呼叫一次 Gemini。組單一 prompt 列出所有節點處置，
要求回 JSON 物件（key=node_id, value=指令字串）。延遲從 N×800ms 壓到 1×1200ms。

注意 Gemini 偶爾會包 ` ```json ... ``` ` code fence，`llm._strip_fence()`
要處理；也要驗證所有預期 node_id 都在回應內。

### Mock 介面 vs DynamoDB

本階段 `mocks.py` 為 stub，提供 4 個函式給 `handler.py` 使用。
**隊友後續抽換時保持函式簽名與回傳結構不變**，handler 不應該動。
3 節點線性拓撲不需要 Dijkstra；隊友若改成 Dijkstra，介面也是這 4 個。

## 不要做的事

- 不要把 mocks 的 hardcoded 資料寫死進 handler.py
- 不要對每個節點分開呼叫 Gemini（延遲爆掉）
- 不要嘗試在 Lambda 內 import 跨資料夾的模組（如 hazard_orchestrator import scenario_trigger）—— 兩支 Lambda 包是分開的
- 不要用 `from . import xxx` 相對 import；Lambda runtime 把 CodeUri 內檔案直接放在 sys.path，要用 `import xxx` 絕對 import
- 不要叫使用者「申請開通 Bedrock 權限」—— 學生在 Learner Lab 做不到

## 在改變 AWS 服務前要先確認的事

Learner Lab 白名單很窄。新增任何 AWS 服務前，先確認 LabRole 可呼叫；
否則預設用 Google Cloud 或外部 API 替代。
