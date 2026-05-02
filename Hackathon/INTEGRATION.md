# SmartEvac — 整合說明文件

**最後更新**：2026-05-02  
**適用對象**：所有組員

---

## 一、專案結構

```
hackerson/
├── proposal.md                  # 系統提案（架構設計）
├── diff_with_ergoguard.md       # 與 ErgoGuard 的差異與遷移說明
├── INTEGRATION.md               # 本文件（整合唯一入口）
│
├── smartevac-cloud/             # Lambda + IoT + Gemini + TTS
│   ├── src/hazard_orchestrator/
│   │   ├── handler.py           # ★ 主程式（不動）
│   │   ├── mocks.py             # ★ 整合接縫（已換成整合版）
│   │   ├── dynamo.py            # DynamoDB 存取層（整合後加入）
│   │   ├── routing.py           # 多源 Dijkstra（整合後加入）
│   │   ├── llm.py               # Gemini 批次指令生成
│   │   ├── tts.py               # Google TTS 並行合成
│   │   └── iot_publisher.py     # IoT Core fan-out publish
│   ├── src/scenario_trigger/    # ScenarioTrigger Lambda
│   ├── subscriber/              # Pi/Mac 訂閱端
│   └── template.yaml            # SAM template
│
├── smartevac-infra/             # DynamoDB + Dijkstra
│   ├── mocks_integrated.py      # ★ 整合接縫原始版本
│   ├── dynamo.py                # DynamoDB 存取層
│   ├── routing.py               # 多源 Dijkstra + z-score 污染判斷
│   ├── topology.py              # 5 節點拓撲定義
│   ├── seed_topology.py         # 建 DynamoDB tables + 寫入拓撲
│   ├── test_routing.py          # 離線 Dijkstra 測試
│   ├── test_integration.py      # DynamoDB + Dijkstra 整合測試
│   ├── DESIGN.md                # DynamoDB 與 Dijkstra 技術設計說明
│   └── TEST_RESULTS.md          # 測試與 AWS 驗證記錄
│
└── smartevac-dashboard/         # 瀏覽器 Dashboard
    ├── index.html               # 單一 HTML 檔案（含所有 CSS/JS）
    ├── config.js                # AWS credentials（不 commit）
    └── README.md                # 啟動說明
```

---

## 二、各組員負責範圍

| 組員 | 資料夾 | 負責內容 |
|---|---|---|
| 組員 A | `smartevac-cloud/` | ScenarioTrigger Lambda、HazardOrchestrator 骨架、Gemini、TTS、IoT publish、SAM template |
| 組員 A | `smartevac-cloud/subscriber/` | Pi/Mac 訂閱端（IoT Certificate + MQTT over TLS） |
| lxh | `smartevac-infra/` | DynamoDB 拓撲與時間序列、多源 Dijkstra 路徑規劃、z-score 污染判斷、seed 腳本 |
| lxh | `smartevac-dashboard/` | 瀏覽器 Dashboard（SigV4 WebSocket、5 節點 UI、S3 polling fallback、Move Hazard、感測器面板） |

### 訂閱端連線方式對照

| 端點 | 連線方式 | 身份驗證 | 適用場景 |
|---|---|---|---|
| `subscriber/subscriber.py`（Pi/Mac） | MQTT over TLS，port 8883 | IoT X.509 Certificate（不過期） | 長期運行的實體裝置 |
| `smartevac-dashboard/index.html`（瀏覽器） | WebSocket over HTTPS，port 443 | SigV4（IAM session token，幾小時過期） | 瀏覽器 demo 展示 |

兩者訂閱同一個 topic `smartevac/cmd/+`，IoT Core 會同時推送給所有訂閱者，互不干擾。

> **為何瀏覽器只能用 SigV4 而不能用 IoT Certificate？**  
> IoT Certificate 包含私鑰（`.private.pem.key`），私鑰一旦放進瀏覽器，任何人打開 DevTools → Sources 就能看到並複製。瀏覽器是公開環境，沒有安全的方式儲存私鑰。SigV4 使用 IAM session token，雖然也會過期，但 Learner Lab 的 token 本來就是短期的，風險可接受。

> **為何 S3 URL 無法連線 IoT Core WebSocket？**  
> IoT Core WebSocket 的 SigV4 授權需要 IAM principal 有對應的 IoT Policy。Learner Lab 的 `voclabs` role 無法 attach IoT Policy（AWS 限制），因此從 S3 URL 發起的 WebSocket 連線會被拒絕。解決方案是用 ngrok 把 localhost 暴露成公開 HTTPS URL，WebSocket 從本機發出，繞過此限制。

---

## 三、整合點

整合只有**一個接縫**：`smartevac-cloud/src/hazard_orchestrator/mocks.py`

**✅ 已完成整合**

```
整合後：handler.py → mocks.py（整合版）→ dynamo.py → DynamoDB
                                        → routing.py → Dijkstra
```

### 函式簽名對照

| 函式 | stub 版本 | 整合版 | 簽名 |
|---|---|---|---|
| `load_topology()` | hardcoded 3 節點 | DynamoDB 5 節點 | 不變 |
| `load_recent_telemetry(window_sec=30)` | 空 dict | DynamoDB 最近 30 秒 | 不變 |
| `score_contamination(node, telemetry)` | 只回觸發節點 | 絕對閾值 + z-score | 不變 |
| `plan_routes(topology, contaminated)` | 3 節點簡化邏輯 | 多源 Dijkstra | 不變 |

---

## 四、已驗證的整合結果

詳細數據見 `smartevac-infra/TEST_RESULTS.md`。

### Phase 1（單一污染源）

| 情境 | 觸發節點 | 路徑規劃 | 耗時 | IoT publish |
|---|---|---|---|---|
| chemical_lab_leak | N3 | N1↓ N2← N3🛑 N4→ N5↓ | ~2,700ms | 5/5 ✅ |
| basement_fire | N1 | N1🛑 N2→ N3→ N4→ N5↓ | ~1,500ms | 5/5 ✅ |
| gas_leak | N2 | N1↓ N2🛑 N3→ N4→ N5↓ | ~1,500ms | 5/5 ✅ |

### Phase 2（污染擴散）

| 情境 | 污染節點 | 路徑規劃 | 說明 |
|---|---|---|---|
| chemical_lab_leak_phase2 | N2 + N3 | N1↓ N2🛑 N3🛑 N4→ N5↓ | 氣體從 N3 擴散到 N2 |
| basement_fire_phase2 | N1 + N2 | N1🛑 N2🛑 N3→ N4→ N5↓ | 煙霧從 N1 擴散到 N2 |
| gas_leak_phase2 | N2 + N3 | N1↓ N2🛑 N3🛑 N4→ N5↓ | 瓦斯從 N2 擴散到 N3 |

---

## 五、AWS 資源清單

| 資源 | 名稱 |
|---|---|
| Lambda | smartevac-hazard-orchestrator |
| Lambda | smartevac-scenario-trigger |
| S3 Bucket | smartevac-lxh |
| IoT Rule | HazardOrchestratorFunctionTelemetryAlert |
| API Gateway | https://j4t0z0xj65.execute-api.us-east-1.amazonaws.com/Prod/scenario/ |
| DynamoDB | SmartEvacTopology（5 節點已 seed） |
| DynamoDB | SmartEvacTelemetry（TTL 60 秒） |
| IoT Endpoint | a2jqesgqu1ut3m-ats.iot.us-east-1.amazonaws.com |

---

## 六、環境變數總覽

| 變數 | 說明 | 值 |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Learner Lab credentials（每幾小時過期） | AWS Details |
| `AWS_SECRET_ACCESS_KEY` | Learner Lab credentials | AWS Details |
| `AWS_SESSION_TOKEN` | Learner Lab credentials | AWS Details |
| `AWS_DEFAULT_REGION` | 固定 | `us-east-1` |
| `OUTPUT_BUCKET` | S3 bucket | `smartevac-lxh` |
| `GOOGLE_API_KEY` | Gemini key | aistudio.google.com |
| `GOOGLE_TTS_API_KEY` | TTS key（Cloud Console 另建） | Cloud Console |
| `GEMINI_MODEL` | 固定 | `gemini-2.5-flash-lite` |
| `GOOGLE_TTS_VOICE` | 固定 | `cmn-TW-Wavenet-A` |
| `IOT_ENDPOINT` | 固定 | `a2jqesgqu1ut3m-ats.iot.us-east-1.amazonaws.com` |
| `IOT_TOPIC_PREFIX` | 固定 | `smartevac/cmd` |
| `TELEMETRY_TOPIC_PREFIX` | 固定 | `smartevac/telemetry` |
| `TOPOLOGY_TABLE` | DynamoDB 拓撲表 | `SmartEvacTopology` |
| `TELEMETRY_TABLE` | DynamoDB 時間序列表 | `SmartEvacTelemetry` |

> 每個人私底下使用不同的 Learner Lab 帳號開發，Demo 時使用同一個帳號的 AWS 資源。

---

## 七、Dashboard 啟動方式

### 前置條件

`config.js` 需要放在 `hackerson/smartevac-dashboard/` 目錄（不 commit）：

```javascript
const SMARTEVAC_CONFIG = {
  accessKeyId:     "ASIA...",
  secretAccessKey: "...",
  sessionToken:    "IQoJ...",
  region:          "us-east-1",
  iotEndpoint:     "a2jqesgqu1ut3m-ats.iot.us-east-1.amazonaws.com",
  cmdTopicPrefix:  "smartevac/cmd",
  outputBucket:    "smartevac-lxh",
  scenarioApiUrl:  "https://j4t0z0xj65.execute-api.us-east-1.amazonaws.com/Prod/scenario/",
};
```

### 本機開發

```bash
cd hackerson/smartevac-dashboard
python -m http.server 8080
# 開 http://localhost:8080
```

### 三台電腦 Demo（ngrok）

ngrok 把主控台電腦的 localhost 暴露成公開 HTTPS URL，其他電腦連這個 URL 即可，**不需要輸入任何 credentials**。

```bash
# 主控台電腦執行（兩個終端）
python -m http.server 8080
ngrok http 8080

# 取得 URL（從 ngrok 輸出或開 http://localhost:4040）
# 三台電腦開這個 URL，選角色後進入系統
```

**credentials 過期時**：更新主控台電腦的 `config.js`，重新整理頁面即可。其他電腦不需要任何操作。

---

## 八、常見問題

**Q：Learner Lab credentials 過期**  
A：AWS Academy → AWS Details → Show，取得新的三個值，更新 `~/.aws/credentials`、`.env`、`config.js`。

**Q：ngrok URL 失效**  
A：重新執行 `ngrok http 8080`，取得新 URL 分享給三台電腦。

**Q：DynamoDB ResourceNotFoundException**  
A：確認 `TOPOLOGY_TABLE` / `TELEMETRY_TABLE` 環境變數有設，region 是 `us-east-1`。Tables 不見了就執行 `python hackerson/smartevac-infra/seed_topology.py`。

**Q：IoT publish ForbiddenException（本地測試）**  
A：本地 Docker 的 credentials 沒有 IoT publish 權限，預期行為。部署到 AWS 後用 LabRole 就正常。

**Q：sam build 出現 cp950 編碼錯誤（Windows）**  
A：`samconfig.toml` 或 `requirements.txt` 有中文字元。把中文改成英文即可。
