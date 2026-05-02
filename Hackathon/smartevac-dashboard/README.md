# SmartEvac Dashboard

瀏覽器疏散引導儀表板。單一 HTML 檔案，所有 CSS/JS 內嵌。

## 功能

- 5 個虛擬節點（列表視圖 / SVG 平面圖 / 空間佈局）
- 3 個情境按鈕 + 轉移危害源（Phase 2 污染擴散）
- 依角色播放語音（監控模式 / 節點模式）+ 打字機效果
- 每個節點獨立靜音控制
- 感測器即時讀值面板（顏色編碼）+ 側邊欄歷史
- End-to-end 計時器 + Live MQTT Log
- 初始畫面輸入 AWS credentials（不需要 config.js）

## 啟動方式

### 本機

```bash
python -m http.server 8080
# 開 http://localhost:8080
```

### 三台電腦 Demo（ngrok）

```bash
# 同時跑 Python server 和 ngrok
python -m http.server 8080
ngrok http 8080
# 三台電腦開 ngrok 提供的 HTTPS URL
```

## 更新到 S3

```bash
aws s3 cp index.html s3://smartevac-lxh/dashboard/index.html \
  --content-type "text/html; charset=utf-8" --region us-east-1
```

S3 URL（僅供下載，IoT WebSocket 無法連線）：
```
https://smartevac-lxh.s3.us-east-1.amazonaws.com/dashboard/index.html
```

## 調整平面圖節點大小

在 `index.html` 搜尋 `fp-N1`，修改 `r` 值（半徑，目前 40）：

```html
<!-- 節點圓圈 -->
<circle id="fp-N1" cx="80" cy="100" r="40" .../>

<!-- 危險脈衝環（比節點大 4px）-->
<circle id="fp-pulse-N1" cx="80" cy="100" r="44" .../>

<!-- 標籤位置（y = cy ± offset）-->
<text id="fp-label-N1" x="80" y="95" ...>   <!-- cy - 5 -->
<text id="fp-sub-N1"   x="80" y="111" ...>  <!-- cy + 11 -->
```

## 憑證更新

credentials 過期後，重新整理頁面，在初始畫面貼上新的三個值即可。

本機開發用 `config.js`（已加入 `.gitignore`）：
```javascript
const SMARTEVAC_CONFIG = {
  accessKeyId: "ASIA...",
  secretAccessKey: "...",
  sessionToken: "IQoJ...",
  region: "us-east-1",
  iotEndpoint: "a2jqesgqu1ut3m-ats.iot.us-east-1.amazonaws.com",
  cmdTopicPrefix: "smartevac/cmd",
  outputBucket: "smartevac-lxh",
  scenarioApiUrl: "https://j4t0z0xj65.execute-api.us-east-1.amazonaws.com/Prod/scenario/",
};
```
