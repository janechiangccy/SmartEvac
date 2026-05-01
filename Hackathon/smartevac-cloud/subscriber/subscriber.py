"""
SmartEvac — 節點訂閱器（Mac / Pi 共用）

訂閱 IoT Core `smartevac/cmd/+`，收到屬於自己節點的疏散指令時：
    1. 印出方向（←/→/↓/🛑）+ 廣播文字
    2. 下載 mp3 並用系統播放器播放

執行：
    pip install -r requirements.txt
    bash setup_iot_thing.sh    # 一次性，建 IoT 資源 + 下憑證
    NODE_ID=N1 python3 subscriber.py

環境變數：
    NODE_ID         — 本程序代表的節點 ID（N1 / N2 / N3）。預設 N1
    IOT_ENDPOINT    — IoT Data-ATS 端點。預設 a1f4azzpj5k3zw-ats.iot.us-east-1.amazonaws.com
    IOT_CLIENT_ID   — MQTT client ID（須 unique）。預設 smartevac-<NODE_ID>
    IOT_TOPIC       — 訂閱 topic。預設 smartevac/cmd/+（wildcard，靠 payload.node_id 過濾）
    CERT_DIR        — 憑證目錄。預設 ./certs
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from awscrt import mqtt
from awsiot import mqtt_connection_builder

# ── 設定 ────────────────────────────────────────────────────────────────
NODE_ID = os.environ.get("NODE_ID", "N1")
IOT_ENDPOINT = os.environ.get(
    "IOT_ENDPOINT", "a1f4azzpj5k3zw-ats.iot.us-east-1.amazonaws.com"
)
IOT_CLIENT_ID = os.environ.get("IOT_CLIENT_ID", f"smartevac-{NODE_ID}")
IOT_TOPIC = os.environ.get("IOT_TOPIC", "smartevac/cmd/+")
CERT_DIR = Path(os.environ.get("CERT_DIR", str(Path(__file__).parent / "certs")))

CERT_PATH = CERT_DIR / "device.pem.crt"
KEY_PATH = CERT_DIR / "private.pem.key"
CA_PATH = CERT_DIR / "AmazonRootCA1.pem"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def _find_player() -> list[str]:
    """偵測 mp3 播放器：macOS afplay → mpg123 → mpg321 → ffplay。"""
    if shutil.which("afplay"):
        return ["afplay"]
    for cmd in ("mpg123", "mpg321"):
        if shutil.which(cmd):
            return [cmd, "-q"]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    return []


def _play_mp3(url: str) -> None:
    player_cmd = _find_player()
    if not player_cmd:
        print(f"[{_ts()}] ⚠️  找不到 mp3 播放器（afplay / mpg123 / ffplay），略過播放")
        return

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        urllib.request.urlretrieve(url, tmp_path)
        subprocess.run([*player_cmd, tmp_path], check=True)
        print(f"[{_ts()}] 🔊 播放完畢（{player_cmd[0]}）")
    except urllib.error.URLError as e:
        print(f"[{_ts()}] ❌ mp3 下載失敗：{e}")
    except subprocess.CalledProcessError as e:
        print(f"[{_ts()}] ❌ 播放失敗：{e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _on_message(topic: str, payload: bytes, **_kwargs) -> None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        print(f"[{_ts()}] ❌ JSON 解析失敗：{e}")
        return

    payload_node = data.get("node_id")

    # wildcard 訂閱會收到所有節點訊息，過濾掉非自己的
    if payload_node != NODE_ID:
        return

    direction = data.get("direction", "?")
    text = data.get("text", "（無廣播文字）")
    mp3_url = data.get("mp3_url")
    is_contaminated = data.get("is_contaminated", False)
    is_exit = data.get("is_exit", False)
    next_hop = data.get("next_hop")
    run_id = data.get("run_id", "?")

    # 狀態標籤
    if is_contaminated:
        status = "🚨 污染源・原地避難"
    elif is_exit:
        status = "🟢 出口・原地疏散"
    else:
        status = f"🟡 中段・往 {next_hop}"

    print()
    print(f"[{_ts()}] ┌─ Node {NODE_ID} ─ run {run_id} ─────────────────")
    print(f"[{_ts()}] │ 狀態:  {status}")
    print(f"[{_ts()}] │ 方向:  {direction}")
    print(f"[{_ts()}] │ 廣播:  {text}")
    print(f"[{_ts()}] └─────────────────────────────────────")

    if mp3_url:
        _play_mp3(mp3_url)


def main() -> None:
    for label, path in [("憑證", CERT_PATH), ("私鑰", KEY_PATH), ("Root CA", CA_PATH)]:
        if not path.exists():
            print(f"[{_ts()}] ❌ 找不到{label}：{path}")
            print(f"          請先跑 bash setup_iot_thing.sh 建資源 + 下載憑證")
            sys.exit(1)

    print(f"[{_ts()}] 🔌 連線 IoT Core：{IOT_ENDPOINT}")
    print(f"[{_ts()}]    Node ID:   {NODE_ID}")
    print(f"[{_ts()}]    Client ID: {IOT_CLIENT_ID}")
    print(f"[{_ts()}]    Topic:     {IOT_TOPIC}（wildcard，過濾 node_id={NODE_ID}）")

    connection = mqtt_connection_builder.mtls_from_path(
        endpoint=IOT_ENDPOINT,
        cert_filepath=str(CERT_PATH),
        pri_key_filepath=str(KEY_PATH),
        ca_filepath=str(CA_PATH),
        client_id=IOT_CLIENT_ID,
        clean_session=False,
        keep_alive_secs=30,
    )
    connection.connect().result()
    print(f"[{_ts()}] ✅ 已連線")

    sub_future, _ = connection.subscribe(
        topic=IOT_TOPIC,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=_on_message,
    )
    sub_future.result()
    print(f"[{_ts()}] 👂 訂閱完成，等待疏散指令…（Ctrl+C 結束）")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print(f"\n[{_ts()}] 🛑 中斷訊號收到，斷線中…")

    connection.disconnect().result()
    print(f"[{_ts()}] 👋 已斷線")


if __name__ == "__main__":
    main()
