# SmartEvac — 校園火災／有害氣體智慧疏散引導系統（純軟體版）

> **版本說明**：本提案為純雲端、零外接硬體實作版本。唯一的物理裝置是**一台筆電**，扮演展示終端與互動觸發角色；所有感測器、邊緣節點、語音／視覺輸出設備皆以瀏覽器虛擬節點 + AWS 服務取代。原規劃中可選擇性加入的 Raspberry Pi + MQ 感測器版本見 `diff_with_ergoguard.md`。

## I. Abstract

SmartEvac 是一套校園火災／有害氣體智慧疏散引導系統，目標是把傳統「只會響鈴」的火警訊號，升級為「能告訴每位師生『往哪邊跑』」的個人化、動態、即時逃生指引。

本版本採**純雲端架構**，唯一硬體為一台筆電（瀏覽器 + 喇叭）。架構分為兩層：

- **硬體層（筆電瀏覽器）**：扮演 (a) 情境觸發控制台 (b) N 個虛擬走廊節點的視覺＋聽覺輸出 (c) 即時管理儀表板。
- **雲端層（AWS + Google）**：完整實作所有後端邏輯，包含拓撲建模、感測資料流、危害判斷、動態路徑規劃、自然語言指令生成與多節點同步指令分發。

當使用者在筆電上點擊情境按鈕（例：「化學實驗室外洩」），事件流經以下鏈路：

1. **API Gateway → Lambda `ScenarioTrigger`**：將預錄情境的感測讀值序列以 IoT Core publish 灌入系統，模擬多節點 telemetry。
2. **IoT Core Rule → DynamoDB**：時間序列讀值寫入 `TelemetryTable`（TTL 60 秒）。
3. **IoT Core Rule（alert level）→ Lambda `HazardOrchestrator`**：核心編排器啟動。
4. 從 DynamoDB 讀取拓撲與最近 30 秒讀值 → 計算污染分數 → **多源 Dijkstra** 反向計算每個節點到最近安全出口的下一跳。
5. **Google Gemini** 將結構化路徑批次翻譯為 ≤ 25 字繁中口語指令，**Google Cloud Text-to-Speech** 並行合成 N 份 MP3。
6. MP3 上傳 S3，產生 presigned URL；指令以 fan-out 方式平行 publish 至 `smartevac/cmd/<node_id>` 共 N 個 topic。
7. **筆電瀏覽器透過 IoT Core WebSocket 訂閱**所有節點 topic，3 秒內同步翻轉 5 個虛擬節點的方向箭頭、播放專屬語音、切換安全門狀態圖示。

本架構完全沿用 ErgoGuard Flow 2 已驗證的 Lambda + IoT Core + S3 + Gemini + TTS 骨幹，新增 DynamoDB 拓撲建模、Dijkstra 動態路徑規劃、ScenarioTrigger 模擬器與瀏覽器虛擬節點 dashboard。

---

## II. Motivation

### 真實使用情境

**情境一：化學實驗室乙醇外洩（白天）**

某高中三樓化學實驗室因管路老化，乙醇蒸氣外洩。傳統作法：

- 整棟大樓火警鈴同時響起
- 師生根據定期演練「往最近樓梯跑」
- 但**最近的西側樓梯**就在污染源旁邊
- 學生衝到樓梯口才發現氣味刺鼻、頭暈，被迫折返
- 折返與正向人流互撞，疏散時間 +3 分鐘

**SmartEvac 介入後**：

- 西側走廊節點偵測到 NH₃／VOC z-score > 3 持續 1.5 秒，alert 上送雲端
- 雲端 1.2 秒內計算完成：西側走廊污染分數 87，標記為禁行
- 三樓所有節點同步收到指令：
  - 西側節點顯示「→」+ 語音「危險！向右轉，東側樓梯」
  - 中段節點顯示「→」+ 語音「直行右轉，東側樓梯」
  - 東側節點顯示「↓」+ 語音「直行下樓，安全」
- 全棟疏散時間相比傳統作法縮短 40%

**情境二：地下室機房火災（夜間）**

學生宿舍地下室機房深夜起火，煙霧透過樓梯井向上擴散。

- 一樓樓梯口節點偵測煙霧濃度急升 + 溫度上升斜率 +2°C/min
- 系統判斷一樓樓梯井為高危區，二樓以上節點接收到「不要走樓梯，留在房間關門等候」的指令
- 同時透過 MQTT 通知校安中心儀表板，標記出火源位置與蔓延方向

### 為什麼用純軟體版本展示

1. **可重現性**：硬體 demo 受 Wi-Fi、感測器漂移、現場環境影響大；純軟體版本 demo 結果完全可重現，方便評審重看影片驗證。
2. **聚焦核心賣點**：本專案的工程亮點是「**雲端 AI 動態路徑規劃 + 多節點同步 fan-out**」，硬體只是展示載具。純軟體版讓觀眾把注意力放在演算法與雲端設計上。
3. **規模化說服力**：純雲端架構天然支援從 5 個節點擴展到 500 個節點，因為瓶頸都在 Lambda fan-out 而非硬體部署。
4. **零部署成本**：學校採購硬體流程冗長；本版本只要把 dashboard URL 分享給校安單位即可在任何瀏覽器試用。
5. **既有專案資產複用**：ErgoGuard Flow 2 已驗證 Lambda + IoT Core + Gemini + TTS 鏈路，本版本是同骨架的橫向擴展。

---

## III. System Architecture and Design

### 3.1 Functionality

| # | 功能 | 說明 |
|---|---|---|
| F1 | 情境觸發控制台 | 筆電 dashboard 提供 3 個預設情境按鈕（化學外洩、機房火災、瓦斯洩漏），點擊後 Lambda 灌入對應感測序列 |
| F2 | 模擬感測資料流 | `ScenarioTrigger` Lambda 將預錄 JSON 序列以 2 Hz 節奏 publish 到 IoT Core，重現真實邊緣節點上行 |
| F3 | 雲端異常偵測 | IoT Rule SQL 過濾異常讀值，超閾值即觸發 `HazardOrchestrator` Lambda |
| F4 | 危害蔓延建模 | 以時空梯度算每節點污染分數，標記禁行區 |
| F5 | 動態安全路徑規劃 | 多源 Dijkstra 一次計算全圖各節點到最近出口的下一跳方向 |
| F6 | 自然語言指令生成 | Gemini 將結構化路徑批次翻譯為 ≤ 25 字繁中口語指令 |
| F7 | 多節點同步音訊合成 | Google Cloud TTS 並行為每節點合成專屬 MP3，IoT Core fan-out 並行發布 |
| F8 | 虛擬節點視覺＋聽覺輸出 | 瀏覽器渲染 5 個虛擬走廊節點，CSS 大箭頭動畫 + `<audio>` 自動播放 |
| F9 | 即時管理儀表板 | 同一 dashboard 顯示 Live MQTT log、DynamoDB 即時讀值、Lambda 端到端耗時 |
| F10 | 動態危害源轉移 | 「Move Hazard」按鈕觸發第二段情境，全節點箭頭即時重算翻轉 |

### 3.2 System Architecture

#### Cloud Services Used

| 類別 | 服務 | 用途 |
|---|---|---|
| AWS | **S3** | (1) 靜態網站託管 dashboard `index.html`  (2) 儲存 TTS 合成的 MP3 |
| AWS | **IoT Core** | (1) MQTT broker 接收模擬 telemetry、下發指令  (2) **WebSocket endpoint** 讓瀏覽器訂閱 |
| AWS | **Lambda** | (1) `ScenarioTrigger`：模擬情境感測資料注入  (2) `HazardOrchestrator`：核心編排器 |
| AWS | **DynamoDB** | (1) `TopologyTable`：校園拓撲（節點、邊、出口）  (2) `TelemetryTable`：最近 60 秒讀值，啟用 TTL 自動清除 |
| AWS | **API Gateway**（或 Lambda Function URL） | 暴露 `/scenario/{name}` HTTP endpoint，dashboard 按鈕呼叫 |
| AWS | **Cognito Identity Pool** | 賦予瀏覽器 unauth 身份，能以 SigV4 連 IoT Core WebSocket |
| AWS | **CloudWatch Logs** | Lambda 日誌；demo 時並排投影增強可信度 |
| GCP | **Gemini API**（`gemini-2.5-flash-lite`） | 自然語言指令生成（取代被 Learner Lab 封鎖的 Bedrock） |
| GCP | **Cloud Text-to-Speech**（`cmn-TW-Wavenet-A`） | 繁中女聲音訊合成（取代被 Learner Lab 封鎖的 Polly） |

> **為何不用 Bedrock／Polly**：本專案環境為 AWS Academy Learner Lab，SCP 已封鎖 `bedrock:*` 與 `polly:*` 且無法申請開通。改用 Google 等價服務既有免費 tier，又能沿用 ErgoGuard Flow 2 已驗證的整合方式。

#### Hardware / Software Interaction & Data Flow

整體架構嚴格分為 **物理層（筆電）** 與 **雲端層（AWS + Google）**。筆電不執行任何業務邏輯，僅扮演 (a) 觸發者 (b) 訂閱者 (c) 視聽呈現者。所有判斷、規劃、生成皆在雲端完成。

```
┌─ 物理層：筆電（唯一硬體）──────────────────────────────────────────┐
│                                                                       │
│  Chrome / Safari 瀏覽器                                               │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  S3 Static Web Dashboard (HTML/JS)                             │  │
│  │                                                                │  │
│  │  ① 情境控制台                                                  │  │
│  │     [Scenario A]  [Scenario B]  [Move Hazard]  [Reset]         │  │
│  │              │                                                 │  │
│  │              ▼ 按下按鈕 → fetch() HTTPS                        │  │
│  │                                                                │  │
│  │  ② 五個虛擬節點顯示區                                          │  │
│  │     ┌──────┬──────┬──────┬──────┬──────┐                       │  │
│  │     │Node-A│Node-B│Node-C│Node-D│Node-E│  ← CSS 箭頭          │  │
│  │     │  ←   │  →   │  →   │  ↓   │  ↓   │  ← <audio> 自動播放   │  │
│  │     │ 🔓   │ 🔓   │ 🔓   │ 🔓   │ 🔓   │  ← 鎖頭狀態           │  │
│  │     └──────┴──────┴──────┴──────┴──────┘                       │  │
│  │              ▲                                                 │  │
│  │              │ 收到 MQTT 訊息 → 重新渲染 (步驟 ⑩)             │  │
│  │                                                                │  │
│  │  ③ 可信度面板                                                  │  │
│  │     ─ Live MQTT log（即時 JSON 訊息流）                        │  │
│  │     ─ DynamoDB telemetry 即時讀值                              │  │
│  │     ─ Lambda 端到端耗時計時器                                  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  喇叭：MP3 自動播放（presigned URL 直接餵 <audio>）                   │
└─────┬─────────────────────────────────────────────────────────▲──────┘
      │                                                         │
      │ ④ HTTPS POST /scenario/A                                │ ⑩ MQTT
      │   （由按鈕觸發）                                         │   over
      │                                                         │   WebSocket
      ▼                                                         │   (Cognito SigV4)
┌─ 雲端層：AWS ─────────────────────────────────────────────────┴───────┐
│                                                                        │
│      ┌───────────────────┐                                             │
│      │  API Gateway      │                                             │
│      │  /scenario/{name} │                                             │
│      └─────────┬─────────┘                                             │
│                │ ⑤ 呼叫                                                │
│                ▼                                                       │
│      ┌──────────────────────────────────────┐                          │
│      │  Lambda: ScenarioTrigger             │                          │
│      │  ─ 讀預錄 JSON 序列（情境腳本）       │                          │
│      │  ─ 以 2Hz 節奏 publish telemetry     │                          │
│      └─────────┬────────────────────────────┘                          │
│                │ ⑥ iot-data publish                                    │
│                ▼                                                       │
│      ┌──────────────────────────────────────┐                          │
│      │  IoT Core (MQTT broker)              │                          │
│      │  topic: smartevac/telemetry/<node>   │                          │
│      └────┬──────────────────────┬──────────┘                          │
│           │                      │                                     │
│   IoT Rule A:                IoT Rule B:                               │
│   一律寫入 DynamoDB           SQL 過濾異常 (mq2 > 0.5 OR mq135 > 0.5)  │
│           │                      │ ⑦ 觸發                              │
│           ▼                      ▼                                     │
│   ┌──────────────┐    ┌──────────────────────────────────────┐         │
│   │ DynamoDB     │    │  Lambda: HazardOrchestrator          │         │
│   │ ─Telemetry─  │◄───│  (沿用 Flow 2 handler.py 骨架)       │         │
│   │ TTL 60s      │    │                                      │         │
│   │ ─Topology─   │◄───│  Step 1: load_topology()             │         │
│   └──────────────┘    │  Step 2: load_recent_telemetry()     │         │
│                       │  Step 3: score_contamination()       │         │
│                       │  Step 4: plan_routes() ← Dijkstra    │         │
│                       │  Step 5: build_batch_prompt()        │         │
│                       └────┬─────────────────┬───────────────┘         │
│                            │                 │                         │
│                            ▼                 ▼                         │
│                   ┌────────────────┐  ┌────────────────┐               │
│                   │  Gemini API    │  │  Cloud TTS     │               │
│                   │  (1 次批次)    │→ │  (N 次並行)    │               │
│                   └────────────────┘  └───────┬────────┘               │
│                                               │                        │
│                                               ▼                        │
│                                       ┌────────────────┐               │
│                                       │ S3 audio/*.mp3 │               │
│                                       │ + presigned URL│               │
│                                       └───────┬────────┘               │
│                                               │ ⑧ 回填 URL             │
│                                               ▼                        │
│                       ┌──────────────────────────────────────┐         │
│                       │  IoT Core Publish (fan-out × N)      │         │
│                       │  topic: smartevac/cmd/<node_id>      │         │
│                       │  payload: {direction, text, mp3_url} │         │
│                       └─────────────────┬────────────────────┘         │
│                                         │ ⑨ MQTT 推送                  │
│                                         │                              │
│         ┌───────────────────────────────┘                              │
│         │                                                              │
└─────────┼──────────────────────────────────────────────────────────────┘
          │
          └──► 回到瀏覽器（步驟 ⑩，路徑見上方）
```

#### 觸發機制與資料流總覽（步驟對照表）

| 步驟 | 動作 | 載體 | 延遲預算 |
|---|---|---|---|
| ① | 使用者點擊「Scenario A」按鈕 | 筆電瀏覽器 JS | — |
| ② | dashboard 啟動 Lambda 端到端計時器 | 瀏覽器 | 0ms |
| ③ | dashboard 切換 UI 為「Loading」狀態 | 瀏覽器 | < 50ms |
| ④ | `POST /scenario/A` HTTPS 請求 | API Gateway | < 100ms |
| ⑤ | 呼叫 `ScenarioTrigger` Lambda | AWS | — |
| ⑥ | Lambda 以 2Hz publish 預錄 telemetry 序列 | IoT Core | 1.5–2 秒（取決於序列長度） |
| ⑦ | 異常讀值觸發 IoT Rule B → `HazardOrchestrator` | AWS | < 200ms |
| ⑧ | DynamoDB 讀 → Dijkstra → Gemini 批次 → TTS 並行 → S3 | AWS + GCP | 1.5–2 秒 |
| ⑨ | N 條指令並行 publish 至 `smartevac/cmd/<node_id>` | IoT Core | < 100ms |
| ⑩ | 瀏覽器透過 WebSocket 收到指令 → 渲染箭頭 + 播放音訊 | 筆電瀏覽器 | < 100ms |

**端到端總延遲**：3–4 秒（包含模擬 telemetry 注入時間）。實際火災「第一筆異常讀值 → 全節點同步」延遲約 **1.8–2.2 秒**。

#### Data Schema（DynamoDB）

**TopologyTable**（一次性靜態資料，由 `seed_topology.py` 寫入）：

```json
{
  "node_id": "F3-W-01",
  "floor": 3,
  "is_exit": false,
  "neighbors": [
    {"node_id": "F3-W-02", "distance_m": 8},
    {"node_id": "F3-M-01", "distance_m": 12}
  ],
  "human_label": "三樓西側走廊近實驗室"
}
```

**TelemetryTable**（TTL 60 秒，由 IoT Rule A 自動寫入）：

```json
{
  "node_id": "F3-W-01",
  "ts": 1714098000,
  "mq2": 0.32,
  "mq135": 0.78,
  "temp_c": 24.3,
  "alert_level": "warning"
}
```

#### 情境腳本格式（`ScenarioTrigger` 讀取）

```json
{
  "scenario_name": "chemical_lab_leak",
  "description": "三樓西側化學實驗室乙醇外洩",
  "duration_sec": 8,
  "events": [
    {"t": 0.0, "node_id": "F3-W-01", "mq135": 0.15, "mq2": 0.10, "temp_c": 24.0},
    {"t": 0.5, "node_id": "F3-W-01", "mq135": 0.45, "mq2": 0.20, "temp_c": 24.2},
    {"t": 1.0, "node_id": "F3-W-01", "mq135": 0.82, "mq2": 0.35, "temp_c": 25.1},
    {"t": 1.5, "node_id": "F3-W-02", "mq135": 0.30, "mq2": 0.15, "temp_c": 24.5},
    "..."
  ]
}
```

#### Other Required Algorithms or Methods

**1. 雲端異常偵測（取代邊緣 z-score）**

純軟體版把 z-score 邏輯從邊緣節點移到 IoT Rule SQL：

```sql
SELECT *, 'alert' as alert_level
FROM 'smartevac/telemetry/+'
WHERE mq2 > 0.5 OR mq135 > 0.7 OR temp_c > 35
```

更精細的 z-score 計算則在 `HazardOrchestrator` 入口完成：

```python
window = load_recent_telemetry(node_id, seconds=60)
mu, sigma = mean(window.mq135), std(window.mq135)
z = (current.mq135 - mu) / sigma if sigma > 0 else 0
```

**2. 危害蔓延建模（時空梯度）**

從 `TelemetryTable` 讀過去 30 秒所有節點讀值，計算每節點污染分數：

```
contamination_score(node) = α * gas_zscore + β * temp_slope
```

預設 α = 0.7、β = 0.3，分數 > 閾值即標記為禁行節點。

**3. 動態路徑規劃（Multi-Source Dijkstra）**

校園拓撲為加權無向圖，節點 = 走廊段落，邊 = 連通性。邊權重隨污染分數動態調整：

```
edge_weight(u, v) = base_distance(u, v)
                  + contamination_score(u) * 1000
                  + contamination_score(v) * 1000
```

以**所有出口**為源點反向跑一次 Dijkstra，得到每個節點到最近安全出口的「下一跳節點 + 距離」。一次計算，全圖共用，符合 demo「3 秒內全節點同步」的要求。

**4. LLM 批次指令生成（單次呼叫，壓低延遲）**

不對每個節點分別呼叫 Gemini，改為單次批次：

```
prompt: 給定 N 個節點的逃生方向資料 [...]，
       請為每個節點輸出 ≤ 25 字繁中指令，
       回傳 JSON array 對應節點順序。
```

沿用 Flow 2 的 503 retry 機制。比起逐節點呼叫，延遲從 N×800ms 壓到 1×1200ms。

**5. TTS 並行化**

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
    mp3_bytes_list = list(pool.map(synthesize_speech, texts))
```

N=5 時 TTS 階段延遲約 600ms（單次呼叫的時間）。

**6. IoT Publish Fan-Out 並行化**

同樣以 `ThreadPoolExecutor` 平行發布 N 個 topic，總時間 < 100ms。

**7. 瀏覽器虛擬節點訂閱（IoT Core WebSocket）**

dashboard JavaScript 使用 [aws-iot-device-sdk-v2](https://github.com/aws/aws-iot-device-sdk-js-v2) 或更輕量的純 `mqtt.js` + Cognito SigV4 簽章：

```javascript
const client = new mqtt.MqttClient();
const conn = client.new_connection_with_websocket_signing({
    endpoint: IOT_ENDPOINT,
    region: 'us-east-1',
    credentials_provider: cognitoProvider
});
await conn.subscribe('smartevac/cmd/+', QoS.AtLeastOnce, (topic, payload) => {
    const cmd = JSON.parse(payload);
    renderNode(extractNodeId(topic), cmd);
});
```

---

## IV. Presentation

### 4.1 Live Demo（純螢幕版，3–5 分鐘）

**裝置**：一台筆電（接會場投影機或外接螢幕），瀏覽器開啟 dashboard URL。**無任何外接硬體**。

**Demo 腳本（時間軸）**：

| 時間 | 動作 | 觀眾看到 |
|---|---|---|
| 0:00–0:20 | 開場：開啟 dashboard | 五個綠色節點、Live MQTT log 安靜、Lambda 計時器歸零 |
| 0:20–0:30 | 點「Scenario A: 化學實驗室外洩」 | UI 切換到 Loading；計時器啟動 |
| 0:30–0:35 | Telemetry 注入階段 | Live MQTT log 開始滾動；DynamoDB 讀值面板數字跳動；Node-B 變紅 |
| 0:35–0:38 | **魔法時刻** ⭐ | 5 個節點箭頭**同一秒**翻轉、5 個方向各異的語音同步播放、5 個 🔒 → 🔓；Lambda 計時器停在「1.8s」 |
| 0:38–1:30 | 切到「架構圖」分頁 | 投影片講解 IoT Core → Lambda → Gemini → TTS 鏈路；強調為何用 Gemini／TTS 而非 Bedrock／Polly |
| 1:30–2:00 | 點「Move Hazard」 | 危險區轉移到 Node-A，全節點箭頭重算翻轉；證明系統「動態」而非寫死 |
| 2:00–2:30 | 切到「CloudWatch Logs」分頁（嵌 iframe 或截圖） | 對應剛剛事件的真實 AWS 日誌，證明非前端模擬 |
| 2:30–3:00 | 點「Reset」並重跑 Scenario A | 證明可重現；提示開源 GitHub URL |
| 3:00–3:30 | 收尾：成本與規模 | 「目前 5 節點，Lambda 一次 < $0.0001；推到 500 節點僅需修改 DynamoDB 拓撲，無需改一行程式」 |

### 4.2 純軟體版的「可信度補強」

評審可能質疑「這只是個前端動畫」。Dashboard 內建以下面板做即時反證：

| 補強元件 | 證明什麼 |
|---|---|
| **Live MQTT Log 面板** | 即時顯示收到的 MQTT 訊息原文（topic、timestamp、payload）→ 訊號真的來自 IoT Core，不是 setTimeout |
| **Lambda 端到端計時器** | 每次 demo 結束顯示「Lambda 端到端 1.8s」，數字來自 X-Ray／CloudWatch → 證明真實雲端往返 |
| **DynamoDB 即時讀值面板** | 用 AWS SDK in browser 每秒 poll TelemetryTable，數字跳動 → 資料真的存進雲端 |
| **CloudWatch Logs 分頁** | 嵌入 console URL 或截圖 → 第三方驗證點 |

### 4.3 Video Showcase（2 分鐘，作為 GitHub README 與評審 backup）

| 時間 | 內容 |
|---|---|
| 0:00–0:15 | 痛點 hook：剪輯真實校園火災新聞畫面，標題「火警鈴響起時，學生往哪裡跑？」 |
| 0:15–0:30 | 系統概念動畫：Figma／Keynote 平面圖，紅色擴散區 + 綠色逃生箭頭 |
| 0:30–1:30 | Live demo 縮時版：split-screen 同時呈現「按下按鈕」與「五節點同步翻轉」+ Lambda 計時器 |
| 1:30–1:50 | 架構圖配旁白：強調沿用 ErgoGuard 既有 AWS + Google 雙雲架構，純軟體版可零成本部署 |
| 1:50–2:00 | Call to action：dashboard URL（評審可即時試用）+ GitHub QR code |

**製作工具**：OBS（錄螢幕）+ Keynote／Figma（動畫）+ DaVinci Resolve（剪輯，免費）。

### 4.4 Demo 風險預案

| 風險 | 緩解 |
|---|---|
| 現場 Wi-Fi 抖動，IoT WebSocket 斷線 | 自備 4G 行動分享器；dashboard 內建斷線重連邏輯；**並準備預錄完整 demo 影片 backup** |
| Lambda cold start 拉長首次延遲 | demo 前 5 分鐘手動跑一次 Scenario A 暖機；或用 Provisioned Concurrency（Learner Lab 額度允許範圍內） |
| Gemini 503 限流 | 沿用 Flow 2 既有 retry；預先快取一份 Scenario A 的成品 MP3 作 fallback |
| Cognito Identity Pool 認證失敗 | demo 前 30 分鐘從會場網路驗證連線；若不行則改 hardcode access key（demo 用，不上 GitHub） |
| 評審聽不懂中文語音 | 節點 UI 同步顯示英文 caption（簡單字串對照） |
| 觀感「不夠 hardcore」 | 在 GitHub README 與 video 提到「邊緣端 Pi 實作參考 ErgoGuard Flow 2，本 demo 為重現性採純雲端版本」 |

### 4.5 後續硬體擴充路徑（給評審看的 roadmap）

純軟體版本的雲端架構可**無痛擴充**為硬體版：

1. **Phase 1（本版本）**：純雲端 + 瀏覽器虛擬節點。零硬體成本、可即時試用。
2. **Phase 2**：1 個 Raspberry Pi + MQ-2 + ADS1115 取代其中一個虛擬節點，作為「真實感測來源」；其他節點仍為瀏覽器虛擬。雲端不需任何修改。
3. **Phase 3**：每個虛擬節點換成實體 Pi + OLED + 喇叭 + 繼電器，全校部署。雲端 fan-out 邏輯天然支援。

這個 roadmap 在 GitHub README 與 demo 收尾時提及，可化解「為何沒有真硬體」的質疑。

---

## 附錄 A：與既有 ErgoGuard Flow 2 的關係

本提案完整沿用 Flow 2 的下列已驗證資產（細節見 `diff_with_ergoguard.md`）：

- Lambda runtime `python3.12` + LabRole 部署模式
- Gemini + Google Cloud TTS 雙 API key 架構（AI Studio key + Cloud Console key）
- TTS REST 而非 SDK（壓 Lambda 包大小）
- Gemini 503 retry 邏輯
- `cmn-TW-Wavenet-A` 繁中女聲

新增的工程量（約 600 行 Python + HTML/JS）：

- `ScenarioTrigger` Lambda（~80 行）
- `HazardOrchestrator` Lambda（~250 行，其中 ~150 行為 Flow 2 沿用）
- DynamoDB seed 腳本（~30 行）
- Dashboard HTML/JS（~400 行，含 IoT WebSocket、5 節點 UI、可信度面板）
- SAM template 擴充（~50 行）

