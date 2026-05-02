"""
SmartEvac — Scenario Trigger Lambda

API Gateway POST /scenario/{name} → 讀預錄 scenarios/{name}.json →
依時間軸以 2Hz 節奏 publish 至 smartevac/telemetry/<node_id>，
模擬邊緣節點上行 telemetry。

下游：IoT Rule 偵測 alert_level='alert' 時觸發 HazardOrchestrator。
"""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

IOT_ENDPOINT = os.environ.get("IOT_ENDPOINT", "")
TELEMETRY_TOPIC_PREFIX = os.environ.get(
    "TELEMETRY_TOPIC_PREFIX", "smartevac/telemetry"
)
ALERT_THRESHOLD_MQ2 = float(os.environ.get("ALERT_THRESHOLD_MQ2", "0.5"))
ALERT_THRESHOLD_MQ135 = float(os.environ.get("ALERT_THRESHOLD_MQ135", "0.7"))
ALERT_THRESHOLD_TEMP = float(os.environ.get("ALERT_THRESHOLD_TEMP", "35"))
TELEMETRY_TABLE = os.environ.get("TELEMETRY_TABLE", "SmartEvacTelemetry")

SCENARIO_DIR = Path(__file__).parent / "scenarios"

_iot_client = None
_dynamodb = None


def _client():
    global _iot_client
    if _iot_client is None and IOT_ENDPOINT:
        _iot_client = boto3.client(
            "iot-data",
            endpoint_url=f"https://{IOT_ENDPOINT}",
        )
    return _iot_client


def _dynamo():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return _dynamodb


def _write_telemetry_to_dynamo(reading: dict) -> None:
    """Write telemetry reading to DynamoDB TelemetryTable."""
    if not TELEMETRY_TABLE:
        return
    try:
        table = _dynamo().Table(TELEMETRY_TABLE)
        ts = reading["ts"]
        table.put_item(Item={
            "node_id": reading["node_id"],
            "ts": ts,
            "mq2": Decimal(str(reading.get("mq2", 0.0))),
            "mq135": Decimal(str(reading.get("mq135", 0.0))),
            "temp_c": Decimal(str(reading.get("temp_c", 24.0))),
            "alert_level": reading.get("alert_level", "normal"),
            "ttl": ts + 120,  # expire after 2 minutes
        })
    except Exception as e:
        logger.warning(f"DynamoDB write failed (non-fatal): {e}")


def load_scenario(name: str) -> dict:
    path = SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(name)
    return json.loads(path.read_text(encoding="utf-8"))


def compute_alert_level(reading: dict) -> str:
    """門檻式判斷；超過任一閾值即 alert。"""
    if (
        reading.get("mq2", 0) > ALERT_THRESHOLD_MQ2
        or reading.get("mq135", 0) > ALERT_THRESHOLD_MQ135
        or reading.get("temp_c", 0) > ALERT_THRESHOLD_TEMP
    ):
        return "alert"
    return "normal"


def _resolve_scenario_name(event: dict) -> str | None:
    # API Gateway proxy event
    pp = event.get("pathParameters") or {}
    if pp.get("name"):
        return pp["name"]
    # sam local invoke 直接傳的測試 event
    if event.get("scenario_name"):
        return event["scenario_name"]
    # querystring fallback
    qs = event.get("queryStringParameters") or {}
    if qs.get("name"):
        return qs["name"]
    return None


def lambda_handler(event: dict, context) -> dict:
    name = _resolve_scenario_name(event)
    if not name:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "missing scenario name"}),
        }

    try:
        scenario = load_scenario(name)
    except FileNotFoundError:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": f"unknown scenario: {name}"}),
        }
    except json.JSONDecodeError as e:
        logger.error(f"scenario JSON parse failed: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "invalid scenario file"}),
        }

    client = _client()
    if client is None:
        logger.warning("⚠️  IOT_ENDPOINT 未設定，dry-run（不實際 publish）")

    last_t = 0.0
    published = 0
    threshold_crossings = 0
    hazard_triggers = 0
    # 同一情境內只讓「首次跨越閾值」標 alert_level=alert，
    # 後續跨越降級為 alert_continued，IoT Rule SQL（WHERE alert_level='alert'）
    # 才不會反覆觸發 HazardOrchestrator。
    # （未來真實邊緣節點上線後，此 dedup 應改放 HazardOrchestrator + DynamoDB。）
    alert_emitted_in_run = False
    t_start = time.time()

    # Pre-scan: write ALL above-threshold readings to DynamoDB before the main loop.
    # This ensures HazardOrchestrator sees the full contamination picture when triggered,
    # even if multiple nodes exceed thresholds at different times in the scenario.
    for evt in scenario["events"]:
        pre_reading = {
            "node_id": evt["node_id"],
            "ts": int(time.time()),
            "mq2": float(evt.get("mq2", 0.0)),
            "mq135": float(evt.get("mq135", 0.0)),
            "temp_c": float(evt.get("temp_c", 24.0)),
            "alert_level": "pre_scan",
        }
        if compute_alert_level(pre_reading) == "alert":
            _write_telemetry_to_dynamo(pre_reading)

    for evt in scenario["events"]:
        # 依時間軸節流（cap 1 秒避免 Lambda 卡死，scenario 應 <=8 秒）
        delay = float(evt["t"]) - last_t
        if delay > 0:
            time.sleep(min(delay, 1.0))
        last_t = float(evt["t"])

        node_id = evt["node_id"]
        reading = {
            "node_id": node_id,
            "ts": int(time.time()),
            "mq2": float(evt.get("mq2", 0.0)),
            "mq135": float(evt.get("mq135", 0.0)),
            "temp_c": float(evt.get("temp_c", 24.0)),
        }
        raw_level = compute_alert_level(reading)
        if raw_level == "alert":
            threshold_crossings += 1
            if alert_emitted_in_run:
                reading["alert_level"] = "alert_continued"
            else:
                reading["alert_level"] = "alert"
                alert_emitted_in_run = True
                hazard_triggers += 1
                # IoT Rule handles triggering HazardOrchestrator via SQL filter
                logger.info(f"Alert emitted for {node_id}, IoT Rule will trigger HazardOrchestrator")
        else:
            reading["alert_level"] = raw_level

        topic = f"{TELEMETRY_TOPIC_PREFIX}/{node_id}"
        if client is not None:
            try:
                client.publish(
                    topic=topic,
                    qos=0,
                    payload=json.dumps(reading, ensure_ascii=False),
                )
                published += 1
            except ClientError as e:
                logger.error(f"publish failed {topic}: {e}")
        # Write to DynamoDB so HazardOrchestrator can read recent telemetry
        _write_telemetry_to_dynamo(reading)
        logger.info(
            f"t={evt['t']:.1f} {topic} "
            f"alert={reading['alert_level']} "
            f"mq2={reading['mq2']:.2f} mq135={reading['mq135']:.2f}"
        )

    elapsed_ms = int((time.time() - t_start) * 1000)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "scenario": name,
                "events_total": len(scenario["events"]),
                "published": published,
                "threshold_crossings": threshold_crossings,
                "hazard_triggers": hazard_triggers,
                "elapsed_ms": elapsed_ms,
                "duration_sec": scenario.get("duration_sec"),
            },
            ensure_ascii=False,
        ),
    }
