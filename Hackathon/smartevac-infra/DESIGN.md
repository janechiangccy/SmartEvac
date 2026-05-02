# SmartEvac Infra — DynamoDB 與 Dijkstra 設計說明

## 一、DynamoDB 設計

### 1.1 為什麼用兩張 Table

系統需要兩種性質完全不同的資料：

| 資料 | 性質 | 更新頻率 | Table |
|---|---|---|---|
| 校園拓撲（節點、邊、出口） | 靜態 | 只在初始化時寫入一次 | SmartEvacTopology |
| 感測器讀值（氣體、溫度） | 動態時間序列 | 每 0.5 秒一筆 | SmartEvacTelemetry |

分開設計讓兩者的存取模式可以各自最佳化，不互相干擾。

---

### 1.2 TopologyTable（SmartEvacTopology）

**Schema**

```
PK: node_id (String)
```

**Item 結構**

```json
{
  "node_id": "N2",
  "is_exit": false,
  "neighbors": [
    {"node_id": "N1", "distance_m": 8},
    {"node_id": "N3", "distance_m": 12}
  ],
  "human_label": "NW corridor near lab"
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `node_id` | String | 節點 ID，PK |
| `is_exit` | Boolean | 是否為安全出口 |
| `neighbors` | List | 相鄰節點清單，含距離（公尺） |
| `human_label` | String | 人類可讀的位置描述，給 Gemini prompt 用 |

**讀取方式**：`Scan`（全表掃描）

拓撲只有 5 筆，Scan 比 Query 簡單且延遲可忽略（< 10 ms）。未來擴展到數十節點仍適用；若超過 100 節點再考慮改 Query + GSI。

**鄰居順序的意義**

`neighbors` 陣列的順序代表方向，第 0 個是「左」，最後一個是「右」。Dijkstra 計算出 next_hop 後，用 index 決定箭頭方向（← 或 →），不需要座標系。

---

### 1.3 TelemetryTable（SmartEvacTelemetry）

**Schema**

```
PK: node_id (String)
SK: ts     (Number，Unix timestamp 秒)
TTL: ttl   (Number，Unix timestamp，60 秒後自動刪除)
```

**Item 結構**

```json
{
  "node_id": "N2",
  "ts": 1777620524,
  "mq2": 0.55,
  "mq135": 0.85,
  "temp_c": 25.5,
  "alert_level": "alert",
  "ttl": 1777620584
}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `node_id` | String | 節點 ID，PK |
| `ts` | Number | Unix timestamp（秒），SK |
| `mq2` | Number | MQ-2 氣體感測器讀值（0–1 正規化） |
| `mq135` | Number | MQ-135 氣體感測器讀值（0–1 正規化） |
| `temp_c` | Number | 溫度（攝氏） |
| `alert_level` | String | `normal` / `alert` / `alert_continued` |
| `ttl` | Number | DynamoDB TTL，寫入時設為 `ts + 60` |

**讀取方式**：`Query`，條件為 `node_id = :nid AND ts >= :cutoff`

```python
cutoff = int(time.time()) - 30  # 最近 30 秒
table.query(
    KeyConditionExpression=Key("node_id").eq(node_id) & Key("ts").gte(cutoff)
)
```

每個節點各查一次，5 個節點共 5 次 Query，並行執行延遲約 50–100 ms。

**TTL 設計**

TTL 設為 60 秒，讓 DynamoDB 自動清除過期讀值，不需要手動維護。z-score 計算只需要最近 30 秒的 baseline，60 秒的保留期提供足夠的緩衝。

---

### 1.4 拓撲圖（5 節點）

```
N1 (North Exit) ──8m── N2 (NW Corridor) ──12m── N3 (Central Hall)
                                                        │
                                                       10m
                                                        │
                           N5 (South Exit) ──9m──  N4 (SE Corridor)
```

| 節點 | 類型 | 位置描述 | 鄰居（順序代表方向） |
|---|---|---|---|
| N1 | 出口 | North corridor exit | [N2] |
| N2 | 走廊 | NW corridor near lab | [N1←, N3→] |
| N3 | 走廊 | Central hall | [N2←, N4→] |
| N4 | 走廊 | SE corridor | [N3←, N5→] |
| N5 | 出口 | South corridor exit | [N4] |

---

## 二、Dijkstra 路徑規劃設計

### 2.1 核心概念：多源 Dijkstra（Multi-Source Dijkstra）

一般 Dijkstra 從「一個起點」往外擴散。本系統反向操作：從「所有安全出口」同時往外擴散，一次計算就能得到全圖每個節點到最近安全出口的路徑。

**優點**：
- 一次 O((V + E) log V) 計算，全圖共用，不需要對每個節點各跑一次
- 自然支援多個出口，Dijkstra 自動選最近的那個
- 新增出口只需修改拓撲資料，演算法不用改

---

### 2.2 邊權重設計

```
edge_weight(u → v) = base_distance(u, v)
                   + contamination_penalty(u)
                   + contamination_penalty(v)
```

污染節點的 penalty 設為 **1000**（遠大於任何真實距離，最長邊 12m）。

這個設計讓 Dijkstra 自然繞開污染區，不需要特別的「禁行」邏輯——污染節點的邊權重極大，Dijkstra 只有在完全沒有其他路徑時才會選它。

---

### 2.3 演算法流程

```
輸入：topology（拓撲圖）、contaminated（污染節點集合）

Step 1：初始化
  - dist[node] = ∞（所有節點）
  - 找出所有「安全出口」= is_exit=True 且不在 contaminated
  - 把所有安全出口加入 min-heap，dist = 0

Step 2：Dijkstra 擴散
  while heap 不為空：
    取出 dist 最小的節點 u
    對 u 的每個鄰居 v：
      new_dist = dist[u] + edge_weight(u, v)
      if new_dist < dist[v]：
        dist[v] = new_dist
        next_toward_exit[v] = u   ← 記錄「從 v 往哪走能到出口」
        exit_for[v] = 本次擴散的源頭出口

Step 3：輸出路由表
  for 每個節點 node：
    if node in contaminated → direction = 🛑
    elif node is safe exit  → direction = ↓
    elif dist[node] >= 1000 → direction = 🛑（所有出口都被封）
    else：
      next_hop = next_toward_exit[node]
      idx = neighbors.index(next_hop)
      direction = ← if idx == 0 else →
```

---

### 2.4 完整範例

**情境**：N3 污染（中央走廊），N1 和 N5 都是安全出口。

```
拓撲邊（base distance）：
  N1─N2: 8m
  N2─N3: 12m
  N3─N4: 10m
  N4─N5: 9m

N3 污染，penalty = 1000
邊權重：
  N1─N2: 8
  N2─N3: 12 + 1000 = 1012  ← N3 有 penalty
  N3─N4: 10 + 1000 = 1010  ← N3 有 penalty
  N4─N5: 9
```

**Dijkstra 執行過程**：

```
初始 heap: [(0, N1), (0, N5)]

pop (0, N1)：
  N1 → N2: dist[N2] = 0 + 8 = 8, next[N2] = N1

pop (0, N5)：
  N5 → N4: dist[N4] = 0 + 9 = 9, next[N4] = N5

pop (8, N2)：
  N2 → N1: dist[N1] = 8 + 8 = 16 > 0, 跳過
  N2 → N3: dist[N3] = 8 + 1012 = 1020, next[N3] = N2

pop (9, N4)：
  N4 → N5: dist[N5] = 9 + 9 = 18 > 0, 跳過
  N4 → N3: dist[N3] = 9 + 1010 = 1019 < 1020, next[N3] = N4

最終 dist：N1=0, N2=8, N3=1019, N4=9, N5=0
最終 next：N2→N1, N3→N4, N4→N5
```

**輸出路由表**：

| 節點 | dist | next_hop | 輸出 direction | 說明 |
|---|---|---|---|---|
| N1 | 0 | — | ↓ | 安全出口 |
| N2 | 8 | N1 | ← | neighbors=[N1,N3]，N1 在 index 0 → 左 |
| N3 | 1019 | — | 🛑 | 在 contaminated 集合，直接標 🛑 |
| N4 | 9 | N5 | → | neighbors=[N3,N5]，N5 在 index 1 → 右 |
| N5 | 0 | — | ↓ | 安全出口 |

---

### 2.5 污染判斷（score_contamination）

觸發節點一定是污染源。其他節點用 z-score + 溫度斜率判斷是否也受污染：

```
score = α × |gas_z| + β × max(temp_slope, 0)
```

預設 α = 0.7、β = 0.3，score ≥ 3.0 標記為污染。

**gas_z 計算（關鍵設計）**

z-score 用「排除最後一筆的 baseline」計算，而不是整個視窗：

```python
baseline = readings[:-1]          # 排除最後一筆（spike 本身）
mu    = mean([r["mq135"] for r in baseline])
sigma = stdev([r["mq135"] for r in baseline])
z     = (readings[-1]["mq135"] - mu) / sigma
```

這樣 spike 本身不會拉高 sigma，z-score 才能正確反映異常程度。若用整個視窗算，spike 會讓 sigma 變大，z-score 反而被壓低。

**temp_slope 計算**

```python
temp_vals = [r["temp_c"] for r in readings]
slope = (temp_vals[-1] - temp_vals[0]) / (len(temp_vals) - 1)
```

只取正斜率（溫度上升），溫度下降不計入污染分數。

---

### 2.6 邊界情況處理

| 情況 | 處理方式 |
|---|---|
| 所有出口都被污染 | heap 初始為空，dist 全為 ∞，所有節點輸出 🛑 |
| 節點只有一個鄰居 | arrow 固定為 → |
| telemetry 讀值不足 3 筆 | z-score 回傳 0，不觸發污染 |
| sigma ≈ 0（讀值完全平穩） | 若最後一筆與 mean 差距 > 0.01，視為極大 spike |

---

## 三、模組關係圖

```
seed_topology.py
    │ 寫入
    ▼
DynamoDB: SmartEvacTopology ◄── dynamo.load_topology()
                                        │
IoT Core telemetry                      │ topology dict
    │ IoT Rule 寫入                     │
    ▼                                   ▼
DynamoDB: SmartEvacTelemetry ──► dynamo.load_recent_telemetry()
                                        │
                                        │ telemetry dict
                                        ▼
                              routing.score_contamination()
                                        │
                                        │ contaminated set
                                        ▼
                              routing.plan_routes(topology, contaminated)
                                        │
                                        │ routes dict
                                        ▼
                              handler.py → Gemini → TTS → S3 → IoT publish
```
