# SmartEvac — 校園火災／有害氣體智慧疏散引導系統

把「只會響鈴」的火警,升級為「告訴每個人往哪邊跑」的即時、個人化、動態逃生指引。任一節點偵測到火災／有害氣體,系統約 **2 秒內**重算全棟每個位置的最佳逃生方向,並同步翻轉各節點箭頭、播放專屬語音。

本專案為課程**期中 Hackathon** 作品,從 [ErgoGuard](https://github.com/janechiangccy/ergoguard)(期末專案)拆出,完整內容在 [`Hackathon/`](Hackathon/)。

## 動機

傳統火警全棟同響,把所有人叫往同一個最近樓梯——但那樓梯可能正在污染源旁。SmartEvac 改為**在火災當下,為每個位置算出各自不同的逃生方向**,並隨危害蔓延動態重算,避免折返人流互撞、縮短疏散時間。採純雲端 + 瀏覽器虛擬節點以求 demo 可重現、聚焦演算法、易規模化(5 → 500 節點只需改拓撲資料)。

## 系統架構

筆電只負責觸發/訂閱/呈現,所有偵測與規劃都在雲端:

```
瀏覽器點情境按鈕 → API Gateway → Lambda(ScenarioTrigger 模擬 telemetry)
   → IoT Core → DynamoDB + 觸發 Lambda(HazardOrchestrator)
       → 污染判斷 → 多源 Dijkstra → Gemini 批次生成 → TTS 並行 → S3 → fan-out publish
   → 瀏覽器(WebSocket)同步翻箭頭 + 播語音    [端到端約 1.8–2.2s]
```

**AWS** IoT Core · Lambda · DynamoDB · S3 · API Gateway · Cognito ｜ **GCP** Gemini(`gemini-2.5-flash-lite`)+ Cloud TTS(`cmn-TW-Wavenet-A`)
> Bedrock／Polly 被 Learner Lab SCP 封鎖,故改用 Google 等價服務。

## 實作方法

- **污染判斷** — z-score(排除最後一筆 baseline,避免 spike 拉高 sigma)+ 溫度斜率,`score = 0.7·|gas_z| + 0.3·temp_slope ≥ 3` 標記禁行。
- **多源 Dijkstra** — 從所有出口反向擴散,一次算出全圖下一跳;污染節點以 `penalty=1000` 邊權重自然繞開。詳見 [`smartevac-infra/DESIGN.md`](Hackathon/smartevac-infra/DESIGN.md)。
- **低延遲** — Gemini 單次批次(N×800ms → 1×1200ms)、TTS 並行、fan-out 並行 publish、跨裝置絕對時間同步播放。
- **儀表板** — 單一 HTML,IoT WebSocket 訂閱;內建 Live MQTT log／DynamoDB 即時讀值／Lambda 計時器反證非前端動畫。

技術棧:`Python 3.12` · `AWS SAM` · `boto3` · `IoT Core` · `DynamoDB` · `Gemini` · `Google Cloud TTS` · 原生 `HTML/JS`

## 快速開始

```bash
cd Hackathon/smartevac-cloud && sam build && sam deploy --guided  # 部署雲端
cd ../smartevac-infra        && python seed_topology.py           # 初始化拓撲
cd ../smartevac-dashboard    && python -m http.server 8080        # 開 dashboard
```

細節見各子目錄 README 與 [`Hackathon/proposal.md`](Hackathon/proposal.md)。
