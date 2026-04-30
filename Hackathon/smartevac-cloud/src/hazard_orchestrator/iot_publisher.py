"""
IoT Core fan-out publisher。

每個節點一個 topic（smartevac/cmd/<node_id>），用 ThreadPoolExecutor 並行 publish。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()

IOT_ENDPOINT = os.environ.get("IOT_ENDPOINT", "")
IOT_TOPIC_PREFIX = os.environ.get("IOT_TOPIC_PREFIX", "smartevac/cmd")

_iot_client = None


def _client():
    global _iot_client
    if _iot_client is None and IOT_ENDPOINT:
        _iot_client = boto3.client(
            "iot-data",
            endpoint_url=f"https://{IOT_ENDPOINT}",
        )
    return _iot_client


def _publish_one(node_id: str, payload: dict) -> bool:
    client = _client()
    if client is None:
        logger.warning(f"⚠️  IOT_ENDPOINT 未設定，跳過 {node_id}")
        return False
    topic = f"{IOT_TOPIC_PREFIX}/{node_id}"
    try:
        client.publish(
            topic=topic,
            qos=1,
            payload=json.dumps(payload, ensure_ascii=False),
        )
        logger.info(f"✅ publish → {topic}")
        return True
    except ClientError as e:
        logger.error(f"publish failed {topic}: {e}")
        return False


def parallel_publish(commands: dict[str, dict]) -> dict[str, bool]:
    """並行 publish 多節點指令。

    Args:
        commands: {node_id: payload_dict}
    Returns:
        {node_id: ok}（失敗不 raise，回 False；mp3 已存 S3 不會丟失）
    """
    if not commands:
        return {}

    results: dict[str, bool] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(commands)) as pool:
        future_map = {
            pool.submit(_publish_one, nid, p): nid for nid, p in commands.items()
        }
        for future in concurrent.futures.as_completed(future_map):
            node_id = future_map[future]
            try:
                results[node_id] = future.result()
            except Exception as e:
                logger.error(f"publish exception {node_id}: {e}")
                results[node_id] = False
    return results
