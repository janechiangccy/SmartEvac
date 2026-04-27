# SmartEvac vs ErgoGuard Flow 2 — 差異與遷移建議

本文件比對 SmartEvac 與既有 `ergoguard-voice/` 的差異，標註每個元件的處置方式：
- 🟢 **直接複用**（不動）
- 🟡 **小改**（< 30 行修改）
- 🔴 **新寫或大改**

---

## 1. 觸發鏈路差異

| 項目 | ErgoGuard Flow 2 | SmartEvac | 處置 |
|---|---|---|---|
| 觸發來源 | S3 PutObject（analysis JSON） | IoT Core Rule（MQTT alert） | 🔴 改 |
| 觸發頻率 | 每分析事件一次 | 多節點異常時一次 | 🔴 改 |
| 輸入資料 | analysis.json（單使用者姿態） | MQTT payload + DynamoDB（多節點時間序列） | 🔴 改 |
| 短路條件 | `needs_intervention=False` | 全校無污染節點 | 🟡 改邏輯 |
| 輸出 | 1 條 MQTT 訊息（`ergoguard/voice`） | N 條 MQTT 訊息（`smartevac/cmd/<node_id>`） | 🔴 改 |

---

## 2. 函式級對照（以 `handler.py` 為基準）

| 既有函式 | 行數 | 處置 | 改動內容 |
|---|---|---|---|
| `parse_s3_event()` | 82–93 | 🔴 整個換掉 | 改成 `parse_iot_alert()`，從 MQTT payload 取 `node_id` 與感測讀值 |
| `read_analysis_json()` | 96–104 | 🔴 刪除 | 不再讀 S3，改從 DynamoDB 拉拓撲 + 時間視窗讀值 |
| `should_skip()` | 108–122 | 🟡 改判斷條件 | 改成「全校無污染節點」即略過 |
| `generate_advice_text()` | 126–162 | 🟡 只改 prompt | **函式骨架、503 retry、Gemini client 完全保留**，prompt 改為多節點批次格式 |
| `synthesize_speech()` | 166–197 | 🟢 完全不動 | 直接複用 |
| `upload_mp3()` | 201–215 | 🟢 完全不動 | 直接複用 |
| `make_presigned_url()` | 218–228 | 🟢 完全不動 | 直接複用 |
| `publish_to_iot()` | 232–257 | 🟡 加參數 `topic` | 把 `IOT_TOPIC` 從全域常數改成函式參數，支援動態 per-node topic |
| `lambda_handler()` | 261–335 | 🔴 重寫流程 | 加路徑規劃、loop 處理 N 個節點、平行化 TTS |

### 新增函式

| 新函式 | 預估行數 | 任務 |
|---|---|---|
| `parse_iot_alert(event)` | ~15 | 解析 IoT Core Rule 觸發的 event |
| `load_topology()` | ~10 | 從 DynamoDB 讀拓撲（節點 + 邊 + 出口） |
| `load_recent_telemetry()` | ~15 | 從 DynamoDB 讀過去 30 秒所有節點讀值 |
| `score_contamination(telemetry)` | ~20 | 算每個節點的污染分數 |
| `plan_routes(topology, contaminated)` | ~40 | **多源 Dijkstra**，回傳 `{node_id: {direction, distance, next_hop}}` |
| `build_batch_prompt(routes)` | ~15 | 為多節點組單次 Gemini prompt（壓低延遲） |
| `parallel_synthesize(texts)` | ~15 | `ThreadPoolExecutor` 並行呼叫 TTS |
| `parallel_publish(commands)` | ~15 | 並行 publish 至各 per-node topic |

---

## 3. 環境變數差異

| 變數 | 既有 | SmartEvac |
|---|---|---|
| `OUTPUT_BUCKET` | ✅ | ✅ 保留 |
| `IOT_ENDPOINT` | ✅ | ✅ 保留 |
| `IOT_TOPIC` | `ergoguard/voice` | 🔴 改名為 `IOT_TOPIC_PREFIX = smartevac/cmd` |
| `GOOGLE_API_KEY` | ✅ | ✅ 保留（Gemini） |
| `GOOGLE_TTS_API_KEY` | ✅ | ✅ 保留（TTS） |
| `GEMINI_MODEL` | ✅ | ✅ 保留（建議仍用 `gemini-2.5-flash-lite`） |
| `GOOGLE_TTS_VOICE` | ✅ | ✅ 保留（`cmn-TW-Wavenet-A`） |
| `PRESIGNED_URL_TTL` | ✅ | ✅ 保留 |
| `TOPOLOGY_TABLE` | — | 🆕 新增（DynamoDB 拓撲表名） |
| `TELEMETRY_TABLE` | — | 🆕 新增（DynamoDB 時間序列表名） |
| `CONTAMINATION_THRESHOLD` | — | 🆕 新增（預設 3.0） |

---

## 4. SAM template 差異

| 區塊 | 處置 | 說明 |
|---|---|---|
| `Runtime: python3.12` | 🟢 不動 | 沿用 |
| `Role: LabRole`（hardcoded） | 🟢 不動 | Learner Lab 強制 |
| 所有 Google API Key 參數（NoEcho） | 🟢 不動 | 沿用 |
| S3 bucket | 🟢 不動 | 沿用 |
| `Events.S3Event` | 🔴 改成 `Events.IoTRule` | 觸發器換成 IoT Core SQL 規則 |
| DynamoDB Tables | 🆕 新增兩張 | `TopologyTable`、`TelemetryTable`（後者啟用 TTL） |
| IAM 權限 | 🟢 不動 | LabRole 預設已含 `dynamodb:*`，免改 |

---

## 5. 邊緣端（Raspberry Pi）差異

| 項目 | 既有 ErgoGuard | SmartEvac | 處置 |
|---|---|---|---|
| MQTT 訂閱腳本 | `ergoguard/voice` 單一 topic | `smartevac/cmd/<node_id>` 各節點專屬 | 🟡 改 topic 字串 |
| MP3 下載 + 播放邏輯 | ✅ 已實作 | ✅ 完全沿用 | 🟢 不動 |
| 異常偵測（z-score） | 無 | 🆕 新增 | 🔴 新寫 ~50 行 Python |
| 上行 telemetry publish | 無 | 🆕 新增 | 🔴 新寫 ~30 行 |
| OLED 顯示 | 無 | 🆕 新增 | 🔴 新寫 ~40 行（用 `luma.oled` 套件） |
| 繼電器控制 | 無 | 🆕 新增 | 🔴 新寫 ~10 行（GPIO） |

---

## 6. 工作量總結

| 類別 | 比例 | 說明 |
|---|---|---|
| 🟢 直接複用 | **約 45%** | TTS、S3、presigned URL、Gemini client 初始化、env 載入、log 設定、SAM 骨架 |
| 🟡 小改 | **約 20%** | Gemini prompt、`publish_to_iot` 加 topic 參數、`should_skip` 邏輯、Pi 訂閱 topic |
| 🔴 新寫／大改 | **約 35%** | Dijkstra 路徑規劃、DynamoDB 存取、邊緣端 z-score、OLED／繼電器、多節點 fan-out |

**雲端 Lambda 總新增程式碼預估 150–200 行**，邊緣端每節點新增約 130 行 Python。

---

## 7. 建議的開發順序（風險由低到高）

1. **第一步：DynamoDB 暖身（你最不熟的部分先做）**
   - 寫 `seed_topology.py`：30 行腳本，把 5 節點假拓撲寫入 DynamoDB
   - 寫 `read_test.py`：確認 LabRole 能讀寫
   - **目的**：驗證 LabRole 對 DynamoDB 的權限沒被 SCP 擋

2. **第二步：路徑規劃離線驗證**
   - 寫 `plan_routes.py`：多源 Dijkstra，輸入拓撲 + 污染節點集合，輸出每節點下一跳
   - 純 Python，本地跑測試，**不碰 AWS**
   - **目的**：把演算法正確性與雲端整合解耦

3. **第三步：複製 ErgoGuard handler.py，改成 SmartEvac 骨架**
   - `cp ergoguard-voice/src/voice_advisor/handler.py hackerson/src/handler.py`
   - 砍掉 S3 解析、改 IoT 解析、塞入第二步的 Dijkstra
   - 先用 1 個節點跑通端到端（沿用 Flow 2 模式）
   - **目的**：驗證新觸發鏈路 + DynamoDB + 路徑規劃 + Gemini + TTS

4. **第四步：擴展到多節點 fan-out**
   - Gemini 改成單次批次呼叫
   - TTS + IoT publish 加 `ThreadPoolExecutor`
   - **目的**：把延遲壓進 demo 要求的 3 秒內

5. **第五步：邊緣端開發**
   - 沿用 Flow 2 的 MQTT 訂閱 + MP3 播放程式碼
   - 新增 z-score、OLED、繼電器
   - **目的**：上機測試端到端

6. **第六步：Demo 排練**
   - 至少完整跑 5 次
   - 錄一份完整 backup 影片

---

## 8. 風險清單（按優先級）

| 風險 | 影響 | 緩解 |
|---|---|---|
| LabRole 對 DynamoDB 的細部權限可能受限 | 🔴 高 | 開發第一步就驗證；若不行則改用 S3 JSON 檔模擬 |
| 多節點 fan-out 延遲超過 3 秒 | 🟡 中 | Gemini 批次化 + TTS 並行化；極端狀況預生成方向 MP3 |
| MQ-135 對乙醇等實驗室常見氣體易誤觸 | 🟡 中 | 加 MQ-2 + DHT22 做 multi-sensor 交叉驗證 |
| Gemini 免費 tier 限流 | 🟢 低 | 沿用既有 503 retry；demo 前手動暖機 |
| Pi 端 OLED／繼電器 GPIO pin 衝突 | 🟢 低 | 接線前查 `pinout.xyz`；I2C 與 SPI 分開腳位 |

---

## 9. 不要再做一次的決策（沿用 Flow 2 結論）

下列已在 ErgoGuard Flow 2 經過驗證，SmartEvac 直接照抄即可，**不要重新評估**：

- **Runtime 用 `python3.12`**：開發機 Homebrew 預設版本，Lambda 也支援
- **Gemini + Google TTS 的雙 API key 架構**：AI Studio key 只能用 Gemini，TTS 必須用 Cloud Console 另開的 key
- **TTS 用 REST 而非 SDK**：避免 Lambda 包過大
- **SAM 部署、`LabRole` 寫死**：Learner Lab 不允許自訂 IAM
- **Gemini 503 sleep 2 秒重試一次**：實測最佳值
- **`cmn-TW-Wavenet-A` 女聲**：自然度勝過 Standard，價格在免費 tier 內

這些決策都已寫在 `ergoguard-voice/CLAUDE.md`，SmartEvac 的 `CLAUDE.md` 直接引用即可。
