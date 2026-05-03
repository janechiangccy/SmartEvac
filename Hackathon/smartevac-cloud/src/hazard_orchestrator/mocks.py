"""
SmartEvac — mocks.py 整合版（取代 smartevac-cloud/src/hazard_orchestrator/mocks.py）

這是組員需要更動的唯一檔案。
handler.py 完全不動，函式簽名與回傳結構與原 stub 完全相容。

主要差異：
    - load_topology()         : 改從 DynamoDB SmartEvacTopology 讀（5 節點）
    - load_recent_telemetry() : 改從 DynamoDB SmartEvacTelemetry 讀最近 30 秒
    - score_contamination()   : 改用 z-score + 溫度斜率（routing.py）
    - plan_routes()           : 改用多源 Dijkstra（routing.py）

組員操作步驟：
    1. 把此檔案內容複製覆蓋 smartevac-cloud/src/hazard_orchestrator/mocks.py
    2. 把 dynamo.py 和 routing.py 複製到 smartevac-cloud/src/hazard_orchestrator/
    3. 在 requirements.txt 確認 boto3 已列（Lambda runtime 內建，不需額外列）
    4. sam build && sam deploy
"""

from __future__ import annotations

import os
import sys

# 讓 Lambda runtime 能找到 dynamo.py 和 routing.py
# （部署後這兩個檔案會跟 mocks.py 在同一個 /var/task 目錄）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import dynamo
import routing


def load_topology() -> dict:
    """從 DynamoDB SmartEvacTopology 讀 5 節點拓撲。

    回傳格式與原 stub 相容：
        {node_id: {is_exit, neighbors: [{node_id, distance_m}], label, human_label}}
    """
    return dynamo.load_topology()


def load_recent_telemetry(window_sec: int = 30) -> dict:
    """從 DynamoDB SmartEvacTelemetry 讀最近 window_sec 秒讀值。

    回傳：{node_id: [reading_dict, ...]}
    """
    return dynamo.load_recent_telemetry(window_sec=window_sec)


def score_contamination(triggering_node: str, telemetry: dict) -> set[str]:
    """z-score + 溫度斜率判斷污染節點。觸發節點一定包含在內。"""
    return routing.score_contamination(triggering_node, telemetry)


def plan_routes(topology: dict, contaminated: set[str]) -> tuple[dict[str, dict], dict[str, float]]:
    """多源 Dijkstra 路徑規劃。

    回傳格式：
        (routes, dist)
        routes: {node_id: {direction, next_hop, hint}}
        dist:   {node_id: float} — 到最近安全出口的距離
    """
    return routing.plan_routes(topology, contaminated)
