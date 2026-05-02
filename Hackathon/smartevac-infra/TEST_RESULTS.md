# SmartEvac Infra — 測試與整合驗證記錄

**最後更新**：2026-05-01  
**環境**：AWS Academy Learner Lab / us-east-1

---

## 1. 離線路徑規劃測試（不碰 AWS）

執行：`python test_routing.py`

### 拓撲（5 節點）

```
N1 (North Exit) ──8m── N2 (NW Corridor) ──12m── N3 (Central Hall)
                                                       │
                                                      10m
                                                       │
                          N5 (South Exit) ──9m──  N4 (SE Corridor)
```

出口：N1（北側）、N5（南側）

### 測試結果

| 測試案例 | 污染節點 | 預期路徑 | 結果 |
|---|---|---|---|
| 無污染 | — | N1↓ N2←(N1) N3→(N4) N4→(N5) N5↓ | ✅ PASSED |
| N2 污染（實驗室外洩） | {N2} | N1↓ N2🛑 N3→(N4) N4→(N5) N5↓ | ✅ PASSED |
| N3 污染（中央走廊） | {N3} | N1↓ N2←(N1) N3🛑 N4→(N5) N5↓ | ✅ PASSED |
| 雙出口污染 | {N1, N5} | 全節點🛑（無安全出口） | ✅ PASSED |
| N1 污染（北側機房） | {N1} | N1🛑 N2→(N3) N3→(N4) N4→(N5) N5↓ | ✅ PASSED |
| score_contamination z-score | N3 觸發 + N2 spike | contaminated={N2, N3} | ✅ PASSED |

**全部 6 個離線測試通過。**

---

## 2. DynamoDB 整合測試

執行：`python test_integration.py`

### DynamoDB Tables

| Table | PK | SK | TTL | 用途 |
|---|---|---|---|---|
| SmartEvacTopology | node_id (S) | — | — | 靜態拓撲 |
| SmartEvacTelemetry | node_id (S) | ts (N) | ttl | 時間序列讀值（60 秒自動清除） |

### 測試結果

| 測試案例 | 說明 | 結果 |
|---|---|---|
| load_topology() | 從 DynamoDB 讀回 5 節點，結構正確 | ✅ PASSED |
| Dijkstra on DynamoDB topology | N2 污染 / N3 污染兩種情境 | ✅ PASSED |
| Telemetry write + read | 寫入 6 筆讀值，30 秒視窗內讀回 ≥ 5 筆 | ✅ PASSED |
| Full pipeline | DynamoDB 拓撲 + 時間序列 → 污染判斷 → Dijkstra | ✅ PASSED |

**全部 4 個整合測試通過。**

---

## 3. AWS 端到端整合驗證（真實 Lambda 部署）

### 完整流程說明（以 basement_fire 為例）

以下為 2026-05-01 實際 CloudWatch 日誌，完整記錄一次觸發的時間軸：

#### ScenarioTrigger Lambda（15:58:44 ~ 15:58:48，Duration: 3,676ms）

```
15:58:44  START
15:58:44  t=0.0  smartevac/telemetry/N1  alert=normal  mq2=0.12 mq135=0.10
15:58:45  t=0.5  smartevac/telemetry/N2  alert=normal  mq2=0.10 mq135=0.12
15:58:45  t=1.0  smartevac/telemetry/N1  alert=normal  mq2=0.32 mq135=0.20
15:58:46  Alert emitted for N1, IoT Rule will trigger HazardOrchestrator
15:58:46  t=1.5  smartevac/telemetry/N1  alert=alert   mq2=0.65 mq135=0.35  ← IoT Rule 觸發點
15:58:46  t=2.0  smartevac/telemetry/N2  alert=normal
15:58:47  t=2.5  smartevac/telemetry/N1  alert=alert_continued
15:58:47  t=3.0  smartevac/telemetry/N3  alert=normal
15:58:48  t=3.5  smartevac/telemetry/N1  alert=alert_continued
15:58:48  END — Duration: 3,676ms
```

#### HazardOrchestrator Lambda（15:58:46 ~ 15:58:55，Duration: 9,253ms）

```
15:58:46  START — IoT Rule 觸發（收到 N1 alert）
15:58:46  event: {node_id: N1, mq2: 0.65, mq135: 0.35, temp_c: 36.5, alert_level: alert}
15:58:46  contaminated=['N1']
          routes={'N5':'↓', 'N3':'→', 'N4':'→', 'N2':'→', 'N1':'🛑'}
          （Dijkstra 結果：N1 污染，其他節點全往南疏散）
15:58:54  Gemini API → HTTP/1.1 200 OK（批次生成 5 個繁中指令）
15:58:55  TTS 並行合成完成（5 份 MP3）
15:58:55  ✅ uploaded s3://smartevac-lxh/audio/21fb3a56/20260501-155854-N2.mp3
15:58:55  ✅ uploaded s3://smartevac-lxh/audio/21fb3a56/20260501-155855-N4.mp3
15:58:55  ✅ uploaded s3://smartevac-lxh/audio/21fb3a56/20260501-155855-N3.mp3
15:58:55  ✅ uploaded s3://smartevac-lxh/audio/21fb3a56/20260501-155855-N1.mp3
15:58:55  ✅ uploaded s3://smartevac-lxh/audio/21fb3a56/20260501-155855-N5.mp3
15:58:55  ✅ publish → smartevac/cmd/N5
15:58:55  ✅ publish → smartevac/cmd/N3
15:58:55  ✅ publish → smartevac/cmd/N4
15:58:55  ✅ publish → smartevac/cmd/N2
15:58:55  ✅ publish → smartevac/cmd/N1
15:58:55  [21fb3a56] done in 9,253ms, published 5/5
```

#### Dashboard 收到訊息的來源

Dashboard 的節點更新來自 **IoT Core WebSocket**（`smartevac/cmd/+`）。  
HazardOrchestrator 在 15:58:55 fan-out publish 到 5 個 topic，瀏覽器透過 WebSocket 幾乎同時收到並渲染。

S3 polling（`latest-routes.json`，每 1.5 秒）是備用機制，當 IoT WebSocket 收不到訊息時自動接手。

---

### 三個情境的路徑規劃結果

| 情境 | 觸發節點 | 路徑規劃 | 耗時 | IoT publish |
|---|---|---|---|---|
| chemical_lab_leak | N3 | N1↓ N2← N3🛑 N4→ N5↓ | ~3,800ms | 5/5 ✅ |
| basement_fire | N1 | N1🛑 N2→ N3→ N4→ N5↓ | 9,253ms | 5/5 ✅ |
| gas_leak | N2 | N1↓ N2🛑 N3→ N4→ N5↓ | ~3,500ms | 5/5 ✅ |

> basement_fire 耗時較長（9,253ms）是因為 Gemini API 回應較慢，非系統問題。

---

## 4. 效能摘要

| 指標 | 數值 |
|---|---|
| 節點數 | 5 |
| ScenarioTrigger 執行時間 | ~3,700ms（情境腳本 4 秒） |
| HazardOrchestrator 執行時間（warm） | 1,500–3,000ms |
| HazardOrchestrator 執行時間（含 Gemini 慢回應） | 最高 ~9,000ms |
| Gemini 批次呼叫 | 1 次（5 節點同時） |
| TTS 並行合成 | 5 份同時 |
| IoT publish 成功率 | 5/5（100%） |
| DynamoDB 讀取（拓撲） | Scan，< 100ms |
| DynamoDB 讀取（telemetry） | Query per node，< 200ms total |

---

## 5. Dashboard 資料流說明

```
使用者點擊按鈕
    │
    ▼
API Gateway POST /scenario/{name}
    │
    ▼
ScenarioTrigger Lambda（~4s）
  ├─ Pre-scan：把所有超閾值讀值先寫入 DynamoDB（確保 Phase 2 擴散偵測正確）
  ├─ 以 2Hz 節奏 publish 8–9 個感測器事件到 IoT Core
  └─ 第一筆 alert_level=alert 觸發 IoT Rule
    │
    ▼
IoT Rule SQL: WHERE alert_level = 'alert'
    │
    ▼
HazardOrchestrator Lambda（1.5–9s）
  ├─ DynamoDB 讀拓撲（SmartEvacTopology）
  ├─ DynamoDB 讀最近 30 秒 telemetry（SmartEvacTelemetry）
  │   └─ 絕對閾值檢查（mq2>0.5 or mq135>0.7 or temp>35）+ z-score
  ├─ 多源 Dijkstra → routes dict
  ├─ Gemini 批次生成 5 個繁中指令
  ├─ Google TTS 並行合成 5 份 MP3
  ├─ S3 上傳 MP3 + 產生 presigned URL
  ├─ S3 寫入 latest-routes.json（dashboard polling 備用）
  └─ IoT Core fan-out publish → smartevac/cmd/N1~N5
    │
    ▼
Dashboard（瀏覽器）
  ├─ 主要：IoT WebSocket 訂閱 smartevac/cmd/+
  │         收到訊息 → renderNode() → 更新箭頭 + 播放 MP3
  ├─ 備用：S3 polling latest-routes.json（每 1.5 秒）
  │         當 IoT WebSocket 收不到時自動接手
  └─ 感測器面板：訂閱 smartevac/telemetry/+ 取得原始讀值
```

> AWS 資源清單與環境變數詳見 `hackerson/INTEGRATION.md`。
