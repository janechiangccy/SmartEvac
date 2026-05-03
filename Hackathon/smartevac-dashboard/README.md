# SmartEvac Dashboard

瀏覽器疏散引導儀表板。單一 HTML 檔案，所有 CSS/JS 內嵌。

## 功能

### 指揮中心模式
- 5 個虛擬節點（列表視圖 / SVG 平面圖 / 空間佈局）
- 3 個情境按鈕（化學實驗室外洩 / 地下室火災 / 瓦斯洩漏）+ 轉移危害源（Phase 2）
- 情境按鈕進度提示：⏳ 觸發中 → 📡 接收中 N/5 → ✓ 完成
- 預設靜音，可手動開啟音訊（header 右側按鈕）
- 感測器即時讀值面板（MQ-2 / MQ-135 / 溫度，顏色編碼）+ 側邊欄歷史
- End-to-end 計時器 + Live MQTT Log
- 點擊 Logo 回到身份選擇頁面

### 節點模式（N1–N5）
- 全螢幕大卡片，顯示：節點代碼 / 節點名稱 / 狀態 / 方向箭頭 / 感測器數值 / 語音文字
- 待機時即時顯示感測器數值，並顯示「✓ 系統正常，感測器運作中」
- 語音播放（右下角靜音按鈕可切換）
- 打字機效果與語音同步（audio.timeupdate 即時對齊）

### 跨裝置同步
- 指揮中心預載所有 mp3 取得 duration，計算串接式播放時間表
- 透過 smartevac/play_schedule MQTT topic 廣播給所有節點裝置
- 所有裝置在相同絕對時間點播放，語音不重疊
- 重置時廣播 smartevac/reset 同步清除所有節點狀態

## 情境說明

| 情境 | Phase 1 污染源 | Phase 2 擴散 |
|---|---|---|
| 化學實驗室外洩 | N3（中央大廳） | N2+N3 |
| 地下室火災 | N1（北側出口） | N1+N2 |
| 瓦斯洩漏 | N4（東南走廊） | N4+N5 |

## 啟動方式

### 本機

```bash
cd hackerson/smartevac-dashboard
python -m http.server 8080
# 開 http://localhost:8080
```

### 多裝置 Demo（ngrok）

ngrok 把主控台電腦的 localhost 暴露成公開 HTTPS URL，其他裝置連這個 URL 即可，**不需要輸入任何 credentials**。

```powershell
# 在 hackerson/ 目錄執行（一鍵啟動）
.\start-dashboard.ps1
```

執行後會顯示公開 URL，分享給所有裝置。各自開啟後選擇身份進入系統。

## 身份選擇

| 選項 | 說明 |
|---|---|
| 指揮中心（預設） | 監控所有節點，預設靜音，可手動開啟音訊 |
| N1–N5 | 全螢幕節點模式，顯示該節點的疏散指引與語音 |

## 憑證更新

credentials 過期後，把新的三個值貼到 repo 根目錄的 .aws/credentials，然後執行：

```powershell
.\update-credentials.ps1
```

這個 script 會自動同步到：
- ~/.aws/credentials（AWS CLI 用）
- hackerson/smartevac-cloud/.env
- hackerson/smartevac-dashboard/config.js（ngrok 主控台電腦用）

## 平面圖節點參數

節點圓圈半徑 r=70，viewBox 0 0 680 700。

節點座標：
- N1: cx=108, cy=140
- N2: cx=308, cy=140
- N3: cx=508, cy=140
- N4: cx=508, cy=370
- N5: cx=508, cy=598
