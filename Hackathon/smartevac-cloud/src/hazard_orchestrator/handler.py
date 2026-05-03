"""
SmartEvac — Hazard Orchestrator Lambda

觸發來源：IoT Rule
    SELECT * FROM 'smartevac/telemetry/+' WHERE alert_level = 'alert'

流程：
    1. parse_iot_alert(event)：取觸發節點與讀值
    2. mocks.{load_topology, score_contamination, plan_routes}
       （Phase 1 為 stub；隊友交付 DynamoDB + 真實演算法後抽換）
    3. llm.generate_batch_instructions：Gemini 一次批次回 N 段繁中指令
    4. tts.parallel_synthesize：N 份 mp3 並行合成
    5. S3 上傳 + presigned URL
    6. iot_publisher.parallel_publish：fan-out 至 smartevac/cmd/<node_id>

注意：
    IoT Rule event 直接就是 SQL SELECT 後的 payload，沒有 S3 那種 Records[] wrapper。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from google.genai import errors as genai_errors

import mocks
from iot_publisher import parallel_publish
from llm import generate_batch_instructions
from tts import parallel_synthesize

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
PRESIGNED_URL_TTL = int(os.environ.get("PRESIGNED_URL_TTL", "600"))
NODE_LABELS_ZH = {
    "N1": "北側出口",
    "N2": "西北走廊",
    "N3": "中央大廳",
    "N4": "東南走廊",
    "N5": "南側出口",
}
SCENARIO_CAUSE_ZH = {
    "chemical_lab_leak": "化學實驗室乙醇外洩，有害氣體濃度過高",
    "chemical_lab_leak_phase2": "化學實驗室乙醇外洩擴散，有害氣體持續蔓延",
    "basement_fire": "地下室火災，偵測到高溫與煙霧",
    "basement_fire_phase2": "地下室火災擴散，煙霧與高溫持續蔓延",
    "gas_leak": "瓦斯洩漏，可燃氣體濃度過高",
    "gas_leak_phase2": "瓦斯洩漏擴散，可燃氣體持續蔓延",
}


def parse_iot_alert(event: dict) -> dict:
    """IoT Rule 觸發時，event 即為 telemetry payload。"""
    if "node_id" not in event:
        raise KeyError("event missing node_id")
    return {
        "node_id": event["node_id"],
        "ts": event.get("ts"),
        "mq2": float(event.get("mq2", 0.0)),
        "mq135": float(event.get("mq135", 0.0)),
        "temp_c": float(event.get("temp_c", 0.0)),
        "alert_level": event.get("alert_level", "unknown"),
        "scenario": event.get("scenario", "unknown"),
        "scenario_run_id": event.get("scenario_run_id", "unknown"),
    }


def _fallback_instruction(node_id: str, route: dict, topology: dict, contaminated: set[str], scenario_name: str) -> str:
    label = topology.get(node_id, {}).get("human_label", node_id)
    next_hop = route.get("next_hop")
    next_label = topology.get(next_hop, {}).get("human_label", next_hop) if next_hop else None
    scenario_label = scenario_name.replace("_phase2", " phase 2").replace("_", " ")
    if node_id in contaminated:
        if next_hop:
            return f"{scenario_label}，{label} 為危險區域，請立即離開，往 {next_label} 方向移動。"
        return f"{scenario_label}，{label} 為危險區域，請就地避難並等待救援。"
    if topology.get(node_id, {}).get("is_exit"):
        return f"{scenario_label}，這裡是安全出口，請依照出口指示離開建築物。"
    if next_hop:
        return f"{scenario_label}，請保持冷靜，往 {next_label} 方向有序疏散。"
    return f"{scenario_label}，目前無安全路徑，請就地避難並等待救援。"


def build_fallback_instructions(routes: dict[str, dict], topology: dict, contaminated: set[str], scenario_name: str) -> dict[str, str]:
    return {
        node_id: _fallback_instruction(node_id, route, topology, contaminated, scenario_name)
        for node_id, route in routes.items()
    }


def normalize_safety_instructions(
    texts: dict[str, str],
    routes: dict[str, dict],
    topology: dict,
    contaminated: set[str],
    scenario_name: str,
) -> dict[str, str]:
    """Keep critical danger-node instructions deterministic across UI, MQTT log, and TTS."""
    normalized = dict(texts)
    cause = SCENARIO_CAUSE_ZH.get(scenario_name, "現場發生環境異常")
    for node_id in contaminated:
        route = routes.get(node_id, {})
        next_hop = route.get("next_hop")
        if next_hop:
            next_label = NODE_LABELS_ZH.get(
                next_hop,
                topology.get(next_hop, {}).get("human_label", next_hop),
            )
            normalized[node_id] = f"{cause}。危險區域，立即離開，往 {next_hop} {next_label} 移動。"
        else:
            normalized[node_id] = f"{cause}。危險區域，請立即依現場指示離開。"
    return normalized


def upload_mp3(node_id: str, mp3_bytes: bytes, run_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    key = f"audio/{run_id}/{timestamp}-{node_id}.mp3"
    s3.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=key,
        Body=mp3_bytes,
        ContentType="audio/mpeg",
    )
    logger.info(f"✅ uploaded s3://{OUTPUT_BUCKET}/{key}")
    return key


def make_presigned_url(s3_key: str) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": OUTPUT_BUCKET, "Key": s3_key},
        ExpiresIn=PRESIGNED_URL_TTL,
    )


def lambda_handler(event: dict, context) -> dict:
    t_start = time.time()
    run_id = uuid.uuid4().hex[:8]
    logger.info(f"[{run_id}] event: {json.dumps(event, ensure_ascii=False)[:300]}")

    # 1. 解析觸發 event
    try:
        alert = parse_iot_alert(event)
    except KeyError as e:
        logger.error(f"event parse failed: {e}")
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}

    triggering_node = alert["node_id"]

    # 2. [stub] 拓撲 + 污染判斷 + 路徑規劃（隊友後續抽換）
    topology = mocks.load_topology()
    if triggering_node not in topology:
        logger.error(f"unknown node: {triggering_node}")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"unknown node {triggering_node}"}),
        }

    contaminated = mocks.score_contamination(
        triggering_node,
        mocks.load_recent_telemetry(scenario_run_id=alert.get("scenario_run_id")),
    )
    routes, dist = mocks.plan_routes(topology, contaminated)
    logger.info(
        f"[{run_id}] contaminated={sorted(contaminated)} "
        f"routes={ {n: r['direction'] for n, r in routes.items()} }"
    )

    # 計算 evacuation_order：dist 越小 = 越靠近出口 = 越遠離污染源 = 越晚播
    # dist 越大（或 inf）= 越靠近污染源 = 越先播（order=1）
    # 污染節點 dist 因 penalty 很大，排在最前面
    sorted_by_dist_desc = sorted(
        routes.keys(),
        key=lambda n: dist.get(n, float("inf")),
        reverse=True,  # 最大 dist（最靠近污染源）排第一
    )
    evacuation_order_map = {nid: i + 1 for i, nid in enumerate(sorted_by_dist_desc)}

    # 3. Gemini 批次指令生成
    # 把所有可用資訊傳入：情境名稱、觸發節點讀值、污染節點集合
    scenario_name = event.get("scenario", "unknown")
    try:
        texts = generate_batch_instructions(
            routes, topology, triggering_node,
            contaminated=contaminated,
            alert=alert,
            scenario_name=scenario_name,
        )
    except (genai_errors.APIError, ValueError, json.JSONDecodeError) as e:
        logger.error(f"Gemini 失敗：{e}")
        texts = build_fallback_instructions(routes, topology, contaminated, scenario_name)
        logger.warning(f"[{run_id}] using deterministic fallback instructions")
    texts = normalize_safety_instructions(
        texts, routes, topology, contaminated, scenario_name
    )

    # 4. 並行 TTS
    try:
        mp3_map = parallel_synthesize(texts)
    except urllib.error.HTTPError as e:
        logger.error(f"TTS HTTP {e.code}: {e.read()[:200]}")
        mp3_map = {}
    except urllib.error.URLError as e:
        logger.error(f"TTS network: {e}")
        mp3_map = {}
    except Exception as e:
        logger.error(f"TTS failed: {e}")
        mp3_map = {}

    # 5. S3 上傳 + presigned URL
    presigned_map: dict[str, str] = {}
    try:
        for node_id, mp3 in mp3_map.items():
            key = upload_mp3(node_id, mp3, run_id)
            presigned_map[node_id] = make_presigned_url(key)
    except ClientError as e:
        logger.error(f"S3 上傳失敗：{e}")
        presigned_map = {}

    # 6. 組指令 payload + 並行 publish
    iso_ts = datetime.now(timezone.utc).isoformat()
    commands = {
        node_id: {
            "node_id": node_id,
            "scenario_run_id": alert.get("scenario_run_id", "unknown"),
            "phase": "phase2" if scenario_name.endswith("_phase2") else "phase1",
            "source_node": triggering_node,
            "generated_at_ms": int(time.time() * 1000),
            "scenario": scenario_name,
            "direction": routes[node_id]["direction"],
            "next_hop": routes[node_id]["next_hop"],
            "text": texts[node_id],
            "mp3_url": presigned_map.get(node_id, ""),
            "is_exit": topology[node_id]["is_exit"],
            "is_contaminated": node_id in contaminated,
            "evacuation_order": evacuation_order_map.get(node_id, 99),
            "run_id": run_id,
            "timestamp": iso_ts,
        }
        for node_id in routes
    }
    publish_results = parallel_publish(commands)

    # 7. 存最新路由結果到 S3（dashboard polling 用）
    try:
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key="latest-routes.json",
            Body=json.dumps(commands, ensure_ascii=False),
            ContentType="application/json",
        )
    except ClientError as e:
        logger.warning(f"latest-routes.json 上傳失敗（非致命）：{e}")

    elapsed_ms = int((time.time() - t_start) * 1000)
    ok_count = sum(1 for v in publish_results.values() if v)
    logger.info(
        f"[{run_id}] done in {elapsed_ms}ms, published {ok_count}/{len(commands)}"
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "run_id": run_id,
                "scenario_run_id": alert.get("scenario_run_id", "unknown"),
                "triggering_node": triggering_node,
                "contaminated": sorted(contaminated),
                "nodes_handled": list(commands.keys()),
                "publish_results": publish_results,
                "elapsed_ms": elapsed_ms,
            },
            ensure_ascii=False,
        ),
    }
