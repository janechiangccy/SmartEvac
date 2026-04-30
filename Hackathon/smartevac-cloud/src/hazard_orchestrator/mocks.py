"""
[Stub] 拓撲 / Telemetry / 路徑規劃介面。

本檔提供 4 個函式給 handler.py 使用。
隊友交付 DynamoDB + 真實演算法時，把函式內部換成 boto3 + 真實邏輯即可，
**handler.py 不應該動到**。

3 節點線性拓撲（不需要 Dijkstra）：

    N1（北側出口）──── N2（中央走廊）──── N3（南側出口）

規劃規則：
    - 觸發節點 = 唯一污染點
    - 出口節點若沒被污染 → 原地疏散（direction = "↓"）
    - 中段 N2 → 找鄰居中還活著的出口；都掛了就留守
    - 污染節點本身 → 留守（direction = "🛑"）
"""

from __future__ import annotations

# 三節點線性拓撲。鄰居順序代表方向：第 0 個是「左」(←)，最後一個是「右」(→)
TOPOLOGY: dict[str, dict] = {
    "N1": {
        "is_exit": True,
        "neighbors": ["N2"],
        "label": "北側走廊出口",
    },
    "N2": {
        "is_exit": False,
        "neighbors": ["N1", "N3"],
        "label": "中央走廊",
    },
    "N3": {
        "is_exit": True,
        "neighbors": ["N2"],
        "label": "南側走廊出口",
    },
}


def load_topology() -> dict:
    """[Stub] 之後改從 DynamoDB TopologyTable 讀。"""
    return TOPOLOGY


def load_recent_telemetry(window_sec: int = 30) -> dict:
    """[Stub] 之後改從 DynamoDB TelemetryTable 撈最近 window_sec 秒讀值。

    回傳：{node_id: [reading, ...]}
    Phase 1 不需要時間視窗判斷（污染節點直接由觸發 event 決定），所以回空 dict。
    """
    return {}


def score_contamination(triggering_node: str, telemetry: dict) -> set[str]:
    """[Stub] 簡化版：觸發節點即為唯一污染點。

    隊友抽換時可改為 z-score + 時空梯度蔓延模型。
    """
    return {triggering_node}


def plan_routes(topology: dict, contaminated: set[str]) -> dict[str, dict]:
    """[Stub] 簡化版路徑規劃（3 節點線性拓撲，不需要 Dijkstra）。

    Args:
        topology: load_topology() 回傳
        contaminated: 被標記為禁行的節點 ID 集合

    Returns:
        {node_id: {
            "direction": str,    # "←" / "→" / "↓" / "🛑"
            "next_hop":  str | None,
            "hint":      str,    # 給 Gemini prompt 用的方向描述（中文）
        }}
    """
    safe_exits = {
        nid for nid, info in topology.items()
        if info["is_exit"] and nid not in contaminated
    }

    routes: dict[str, dict] = {}
    for node_id, info in topology.items():
        # 自己就是污染源 → 留守
        if node_id in contaminated:
            routes[node_id] = {
                "direction": "🛑",
                "next_hop": None,
                "hint": f"本節點即為污染源（{info['label']}），原地避難並關閉門窗",
            }
            continue

        # 自己就是出口 → 原地疏散
        if info["is_exit"]:
            routes[node_id] = {
                "direction": "↓",
                "next_hop": None,
                "hint": f"本節點為安全出口（{info['label']}），就地下樓疏散",
            }
            continue

        # 中段節點：往最近的還活著的出口走
        chosen = None
        for idx, neighbor in enumerate(info["neighbors"]):
            if neighbor in safe_exits:
                chosen = (idx, neighbor)
                break
        if chosen is not None:
            idx, neighbor = chosen
            arrow = "←" if idx == 0 else "→"
            routes[node_id] = {
                "direction": arrow,
                "next_hop": neighbor,
                "hint": (
                    f"前往 {topology[neighbor]['label']}（"
                    f"{'向左' if arrow == '←' else '向右'}）"
                ),
            }
        else:
            # 兩側都封了
            routes[node_id] = {
                "direction": "🛑",
                "next_hop": None,
                "hint": "兩側出口皆為禁行，原地避難並關閉門窗等待救援",
            }

    return routes
