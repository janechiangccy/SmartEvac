# SmartEvac Subscriber（Phase 2A）

訂閱 IoT Core `smartevac/cmd/+`，收到指令時印出方向 + 廣播文字 + 播放 mp3。

**不需要 Pi**：在你的 Mac / Linux 直接跑 3 個 process 即可模擬 3 個節點，靠 `NODE_ID` 環境變數區分。

## 一次性設置

```bash
# 假設 cwd 在 hackerson/smartevac-cloud/subscriber/
# 1. AWS creds 已 export（從上層 .env source 過來）
set -a && source ../.env && set +a

# 2. 安裝 Python 依賴
pip install -r requirements.txt

# 3. 建 IoT Thing / Cert / Policy（idempotent，重跑不會炸）
bash setup_iot_thing.sh
```

完成後 `certs/` 會有：
- `device.pem.crt` — 裝置憑證
- `private.pem.key` — 私鑰（`chmod 600`）
- `AmazonRootCA1.pem` — Root CA
- `cert.arn` — Certificate ARN（給 setup script 自己用）

⚠️ `certs/*` 已加進 `.gitignore`，不會被 commit。

## 跑訂閱端

開 3 個 terminal，各跑一個節點：

```bash
# Terminal 1
NODE_ID=N1 python3 subscriber.py

# Terminal 2  
NODE_ID=N2 python3 subscriber.py

# Terminal 3
NODE_ID=N3 python3 subscriber.py
```

每個 terminal 連線後會印：

```
[15:30:00.123] 🔌 連線 IoT Core：a1f4azzpj5k3zw-ats.iot.us-east-1.amazonaws.com
[15:30:00.456] ✅ 已連線
[15:30:00.789] 👂 訂閱完成，等待疏散指令…
```

## 觸發測試

開第 4 個 terminal：

```bash
curl -X POST https://nbwjc6fhu6.execute-api.us-east-1.amazonaws.com/Prod/scenario/chemical_lab_leak
```

3 個 subscriber terminal 應在約 5 秒內**同時跳出**自己節點的指令，每個各自播 mp3：

```
[15:30:08.123] ┌─ Node N3 ─ run f69a47e1 ─────────────────
[15:30:08.123] │ 狀態:  🚨 污染源・原地避難
[15:30:08.123] │ 方向:  🛑
[15:30:08.123] │ 廣播:  N3 警報，請就地避難並關閉門窗。
[15:30:08.123] └─────────────────────────────────────
[15:30:09.456] 🔊 播放完畢（afplay）
```

## 設計筆記

- **單張 cert 共用**：3 個 subscriber 用同一張 cert 連線，靠不同 `IOT_CLIENT_ID`（預設 `smartevac-<NODE_ID>`）區分。Production 部署應改成每節點一張獨立 cert + 獨立 policy。
- **Wildcard 訂閱**：訂 `smartevac/cmd/+`、靠 `payload.node_id` 過濾。和 dashboard（Phase 2B）邏輯一致，未來瀏覽器訂閱可直接共用同套設計。
- **mp3 播放器自動偵測順序**：
  1. `afplay`（macOS 內建，無需安裝）
  2. `mpg123` / `mpg321`（Linux / Pi 常見）
  3. `ffplay`（fallback，需 ffmpeg）

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `NODE_ID` | `N1` | 本程序代表的節點（用來過濾訊息）|
| `IOT_ENDPOINT` | `a1f4azzpj5k3zw-ats.iot.us-east-1.amazonaws.com` | IoT Data-ATS endpoint |
| `IOT_CLIENT_ID` | `smartevac-<NODE_ID>` | MQTT client ID（須 unique，否則互踢線）|
| `IOT_TOPIC` | `smartevac/cmd/+` | 訂閱 topic（wildcard）|
| `CERT_DIR` | `./certs` | 憑證所在目錄 |

## 排錯

| 症狀 | 可能原因 |
|---|---|
| `❌ 找不到憑證` | `setup_iot_thing.sh` 沒跑成功，或 `CERT_DIR` 路徑錯 |
| 連線後 5 秒就被踢 | 兩個 subscriber 用了同一個 `IOT_CLIENT_ID`（IoT Core 不允許 |
| 連線回 `AUTHORIZATION_FAILURE` | Policy 沒 attach 到 cert，或 region 不對 |
| 收不到訊息 | (1) Lambda 沒成功 publish — 看 CloudWatch；(2) topic 名拼錯；(3) Policy 漏了 `iot:Receive` |
| `afplay` 找不到 | 不是 macOS。裝 `brew install mpg123` 或 `brew install ffmpeg` |
