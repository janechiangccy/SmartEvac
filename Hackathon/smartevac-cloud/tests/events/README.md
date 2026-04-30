# Test Events

本機 `sam local invoke` 用的 fixture。

## HazardOrchestrator 觸發 fixtures（模擬 IoT Rule event）

IoT Rule event 直接就是 SQL SELECT 後的 payload，沒有 `Records[]` wrapper。

| 檔案 | 觸發節點 | 預期路徑規劃 |
|---|---|---|
| `iot_alert_sample.json` | N3（南側出口）| N3 留守、N2 ←、N1 ↓ |
| `iot_alert_n1_fire.json` | N1（北側出口）| N1 留守、N2 →、N3 ↓ |
| `iot_alert_n2_gas.json` | N2（中央）| N2 留守、N1 ↓、N3 ↓（兩側獨立疏散） |

```bash
sam local invoke HazardOrchestratorFunction \
  --event tests/events/iot_alert_sample.json \
  --env-vars env.json
```

## ScenarioTrigger 觸發 fixture（模擬 API Gateway proxy event）

| 檔案 | 觸發情境 |
|---|---|
| `scenario_invoke.json` | POST /scenario/chemical_lab_leak |

```bash
sam local invoke ScenarioTriggerFunction \
  --event tests/events/scenario_invoke.json \
  --env-vars env.json
```

要切換情境，把 `pathParameters.name` 改成 `basement_fire` 或 `gas_leak`。

## env.json 範例

`env.json` 被 gitignore，本機自己建：

```json
{
  "HazardOrchestratorFunction": {
    "GOOGLE_API_KEY": "...",
    "GOOGLE_TTS_API_KEY": "...",
    "GEMINI_MODEL": "gemini-2.5-flash-lite",
    "GOOGLE_TTS_VOICE": "cmn-TW-Wavenet-A",
    "OUTPUT_BUCKET": "smartevac-your-name",
    "IOT_ENDPOINT": "xxxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com",
    "IOT_TOPIC_PREFIX": "smartevac/cmd",
    "PRESIGNED_URL_TTL": "600"
  },
  "ScenarioTriggerFunction": {
    "IOT_ENDPOINT": "xxxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com",
    "TELEMETRY_TOPIC_PREFIX": "smartevac/telemetry"
  }
}
```
