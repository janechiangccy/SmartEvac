"""
DynamoDB access layer for SmartEvac.

Implements the first two functions from the mocks.py interface contract:
    load_topology() -> dict[node_id, {is_exit, neighbors, label}]
    load_recent_telemetry(window_sec=30) -> dict[node_id, list[reading]]

Tables:
    TopologyTable — partition key: node_id (S)
    TelemetryTable — partition key: node_id (S), sort key: ts (N), TTL on 'ttl' attribute
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TOPOLOGY_TABLE = os.environ.get("TOPOLOGY_TABLE", "SmartEvacTopology")
TELEMETRY_TABLE = os.environ.get("TELEMETRY_TABLE", "SmartEvacTelemetry")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

_dynamodb = None


def _resource():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb


def _decimal_to_float(obj):
    """Recursively convert Decimal to float for DynamoDB responses."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def load_topology() -> dict:
    """Load full topology from DynamoDB TopologyTable.

    Returns:
        {node_id: {is_exit: bool, neighbors: [{node_id, distance_m}], human_label: str}}

    The returned format matches mocks.py contract. We adapt the DynamoDB schema
    (which stores full items with node_id as PK) to the flat dict format.
    """
    table = _resource().Table(TOPOLOGY_TABLE)
    response = table.scan()
    items = response.get("Items", [])

    topology = {}
    for item in items:
        item = _decimal_to_float(item)
        node_id = item["node_id"]
        topology[node_id] = {
            "is_exit": item.get("is_exit", False),
            "neighbors": item.get("neighbors", []),
            "human_label": item.get("human_label", node_id),
            # Keep label as alias for backward compat with mocks.py consumer
            "label": item.get("human_label", node_id),
        }

    return topology


def load_recent_telemetry(window_sec: int = 30, scenario_run_id: str | None = None) -> dict:
    """Load recent telemetry readings from DynamoDB TelemetryTable.

    Queries each known node for readings within the last `window_sec` seconds.

    Returns:
        {node_id: [reading_dict, ...]}
        Each reading_dict has: mq2, mq135, temp_c, ts, alert_level
    """
    table = _resource().Table(TELEMETRY_TABLE)
    cutoff_ts = int(time.time()) - window_sec

    # First get all known node_ids from topology
    topology = load_topology()
    result: dict[str, list[dict]] = {}

    for node_id in topology:
        response = table.query(
            KeyConditionExpression=(
                Key("node_id").eq(node_id) & Key("ts").gte(cutoff_ts)
            ),
            ScanIndexForward=True,  # oldest first
        )
        items = response.get("Items", [])
        if scenario_run_id:
            items = [
                item for item in items
                if item.get("scenario_run_id") == scenario_run_id
            ]
        result[node_id] = [_decimal_to_float(item) for item in items]

    return result
