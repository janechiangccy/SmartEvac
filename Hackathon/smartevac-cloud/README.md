# SmartEvac — Cloud（Phase 1：Lambda + IoT Core + Gemini + TTS）

校園火災／有害氣體智慧疏散引導系統的雲端骨幹。本資料夾為**第一階段**，
聚焦 Lambda 程式邏輯 + Gemini + Google TTS + IoT Core publish 鏈路。

## 階段範圍

✅ 本階段交付：

- `ScenarioTrigger` Lambda：API Gateway 觸發，讀預錄 `scenarios/*.json` 後以 2Hz publish 到 IoT Core
- `HazardOrchestrator` Lambda 骨架：被 IoT Rule 觸發 → Gemini 批次 → TTS 並行 → S3 → IoT publish fan-out
- `mocks.py`：拓撲（3 節點）與路徑規劃 stub，待隊友交付 DynamoDB / 真實演算法後抽換
- SAM template：兩支 Lambda、S3 bucket、IoT Rule 觸發、API Gateway

❌ 由隊友負責、本階段不處理：

- DynamoDB `TopologyTable` / `TelemetryTable`
- 真實路徑規劃演算法（3 節點不需要 Dijkstra，但會交付一個演算法模組）
- 邊緣端／瀏覽器 dashboard 的 MQTT 訂閱（憑證、Cognito、訂閱端 UI）

## Pipeline

```
情境按鈕（dashboard 未來實作）
   │
   │ POST /scenario/{name}
   ▼
ScenarioTrigger Lambda
   │ 讀 scenarios/{name}.json，依時間軸 publish
   ▼
IoT Core: smartevac/telemetry/<node_id>
   │
   │ IoT Rule: alert_level = 'alert' 過濾
   ▼
HazardOrchestrator Lambda
   │ 1. parse_iot_alert
   │ 2. mocks.load_topology + score_contamination + plan_routes  ← 隊友會抽換
   │ 3. Gemini 批次 prompt（一次回 N 段指令）
   │ 4. parallel TTS → S3 → presigned URL
   │ 5. parallel publish → smartevac/cmd/<node_id>
   ▼
（下階段：dashboard/Pi 訂閱 smartevac/cmd/+ 渲染箭頭 + 播放 MP3）
```

進入點：

- `src/scenario_trigger/handler.py::lambda_handler`
- `src/hazard_orchestrator/handler.py::lambda_handler`

## 拓撲（3 節點，stub 版本）

```
N1（北側出口） ── N2（中央走廊） ── N3（南側出口）
```

定義在 `src/hazard_orchestrator/mocks.py`，含對應 `plan_routes()` 簡化邏輯：

- 觸發節點為 N3 → N3 留守、N2 向 N1、N1 原地疏散
- 觸發節點為 N1 → N1 留守、N2 向 N3、N3 原地疏散
- 觸發節點為 N2 → N2 留守、N1/N3 各自原地疏散

## 沿用 ErgoGuard Flow 2 的決策（不重新評估）

詳見 `CLAUDE.md`：

- Lambda runtime `python3.12`、SAM 部署、`LabRole` 寫死
- Gemini + Google TTS 雙 API key（AI Studio key 只能 Gemini）
- TTS 走 REST 不走 SDK（壓 Lambda 包大小）
- Gemini 503 sleep 2 秒重試一次
- `cmn-TW-Wavenet-A` 繁中女聲

## 本機開發

```bash
sam build

# 觸發 HazardOrchestrator（模擬 IoT Rule event）
sam local invoke HazardOrchestratorFunction \
  --event tests/events/iot_alert_sample.json \
  --env-vars env.json

# 觸發 ScenarioTrigger（模擬 API Gateway POST）
sam local invoke ScenarioTriggerFunction \
  --event tests/events/scenario_invoke.json \
  --env-vars env.json
```

`env.json` 與 `.env` 都被 `.gitignore` 忽略，不要 commit。
複製 `.env.example` 作為起點。

## 部署

```bash
sam deploy --guided
```

部署參數見 `template.yaml` 的 `Parameters`。Google API key 兩把都要在
互動介面填入（標 `NoEcho`）。

## 與隊友的介面 contract

`mocks.py` 三個 stub 函式，隊友交付時保持簽名相容即可：

```python
load_topology() -> dict[node_id, {is_exit, neighbors, label}]
load_recent_telemetry(window_sec=30) -> dict[node_id, list[reading]]
plan_routes(topology, contaminated: set[str]) -> dict[node_id, {direction, next_hop, hint}]
score_contamination(triggering_node, telemetry) -> set[str]
```

抽換時只要把 `mocks.py` 內部改成 boto3 + 真實演算法，`handler.py` 不必動。
