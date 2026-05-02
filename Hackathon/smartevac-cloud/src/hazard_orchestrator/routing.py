"""
SmartEvac routing engine — contamination scoring + multi-source Dijkstra.

Interface contract (matches smartevac-cloud/mocks.py signatures):
    score_contamination(triggering_node, telemetry) -> set[str]
    plan_routes(topology, contaminated) -> dict[node_id, {direction, next_hop, hint}]
"""

from __future__ import annotations

import heapq
import math
from statistics import mean, stdev

# ── Contamination scoring ────────────────────────────────────────────────

ALPHA = 0.7          # weight for gas z-score
BETA = 0.3           # weight for temperature slope
DEFAULT_THRESHOLD = 3.0  # contamination score threshold


def _z_score(values: list[float]) -> float:
    """Compute z-score of the last value relative to the baseline (all but last)."""
    if len(values) < 3:
        return 0.0
    baseline = values[:-1]
    mu = mean(baseline)
    sigma = stdev(baseline)
    if sigma < 1e-9:
        # Near-zero variance: if last value differs from mean, it's a huge spike
        return abs(values[-1] - mu) * 100 if abs(values[-1] - mu) > 0.01 else 0.0
    return (values[-1] - mu) / sigma


def _temp_slope(values: list[float]) -> float:
    """Simple linear slope (degrees per reading) over the window."""
    if len(values) < 2:
        return 0.0
    # slope = (last - first) / (n - 1)
    return (values[-1] - values[0]) / (len(values) - 1)


def score_contamination(
    triggering_node: str,
    telemetry: dict[str, list[dict]],
    threshold: float = DEFAULT_THRESHOLD,
) -> set[str]:
    """Identify contaminated nodes from recent telemetry.

    Args:
        triggering_node: The node that triggered the alert (always included).
        telemetry: {node_id: [reading_dict, ...]} where each reading has
                   keys: mq2, mq135, temp_c.
        threshold: Contamination score above which a node is marked unsafe.

    Returns:
        Set of contaminated node IDs.
    """
    contaminated = {triggering_node}

    for node_id, readings in telemetry.items():
        if not readings:
            continue

        mq135_vals = [r.get("mq135", 0.0) for r in readings]
        mq2_vals = [r.get("mq2", 0.0) for r in readings]
        temp_vals = [r.get("temp_c", 24.0) for r in readings]

        # Absolute threshold check: if latest reading directly exceeds alert level
        # This handles Phase 2 spread scenarios where there's no baseline history
        latest_mq2 = mq2_vals[-1] if mq2_vals else 0.0
        latest_mq135 = mq135_vals[-1] if mq135_vals else 0.0
        latest_temp = temp_vals[-1] if temp_vals else 24.0
        if latest_mq2 > 0.5 or latest_mq135 > 0.7 or latest_temp > 35:
            contaminated.add(node_id)
            continue

        # Use the higher z-score between mq135 and mq2
        gas_z = max(_z_score(mq135_vals), _z_score(mq2_vals))
        temp_slope = _temp_slope(temp_vals)

        score = ALPHA * abs(gas_z) + BETA * max(temp_slope, 0)
        if score >= threshold:
            contaminated.add(node_id)

    return contaminated


# ── Multi-source Dijkstra ────────────────────────────────────────────────

CONTAMINATION_PENALTY = 1000  # added to edge weight per contaminated endpoint

# Direction arrows based on relative position of next_hop
# We determine direction by looking at neighbor ordering in the topology
DIRECTION_ARROWS = {
    "exit_self": "↓",       # this node IS the exit, evacuate downstairs
    "blocked": "🛑",        # contaminated or no path
}


def plan_routes(
    topology: dict[str, dict],
    contaminated: set[str],
) -> dict[str, dict]:
    """Multi-source Dijkstra from all safe exits, returns per-node evacuation info.

    Args:
        topology: {node_id: {is_exit, neighbors: [{node_id, distance_m}], human_label}}
        contaminated: Set of node IDs marked as unsafe.

    Returns:
        {node_id: {direction: str, next_hop: str|None, hint: str}}
    """
    # Build adjacency list with contamination penalties
    adj: dict[str, list[tuple[str, float]]] = {}
    for nid, info in topology.items():
        adj[nid] = []
        for nb in info.get("neighbors", []):
            nb_id = nb["node_id"]
            base_dist = nb["distance_m"]
            penalty = 0
            if nid in contaminated:
                penalty += CONTAMINATION_PENALTY
            if nb_id in contaminated:
                penalty += CONTAMINATION_PENALTY
            adj[nid].append((nb_id, base_dist + penalty))

    # Multi-source Dijkstra: start from all safe exits
    dist: dict[str, float] = {nid: math.inf for nid in topology}
    # next_toward_exit[node] = the neighbor to go to, heading toward the exit
    # For exit nodes themselves, this is None
    next_toward_exit: dict[str, str | None] = {nid: None for nid in topology}
    exit_for: dict[str, str | None] = {nid: None for nid in topology}

    heap: list[tuple[float, str, str | None]] = []  # (dist, node, came_from_exit)

    for nid, info in topology.items():
        if info["is_exit"] and nid not in contaminated:
            dist[nid] = 0
            exit_for[nid] = nid
            heapq.heappush(heap, (0, nid, nid))

    while heap:
        d, u, src_exit = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, w in adj.get(u, []):
            new_dist = d + w
            if new_dist < dist[v]:
                dist[v] = new_dist
                exit_for[v] = src_exit
                # next_toward_exit[v] = u means "from v, go to u to reach exit"
                next_toward_exit[v] = u
                heapq.heappush(heap, (new_dist, v, src_exit))

    # Build route results
    routes: dict[str, dict] = {}
    for nid, info in topology.items():
        label = info.get("human_label", nid)

        # Contaminated node
        if nid in contaminated:
            routes[nid] = {
                "direction": "🛑",
                "next_hop": None,
                "hint": f"Contamination source ({label}). Shelter in place, close doors.",
            }
            continue

        # Safe exit node
        if info["is_exit"] and nid not in contaminated:
            routes[nid] = {
                "direction": "↓",
                "next_hop": None,
                "hint": f"This is a safe exit ({label}). Evacuate downstairs now.",
            }
            continue

        # Unreachable node (all exits blocked)
        nh = next_toward_exit.get(nid)
        if nh is None or dist[nid] >= CONTAMINATION_PENALTY:
            routes[nid] = {
                "direction": "🛑",
                "next_hop": None,
                "hint": f"All exits blocked. Shelter in place at {label}, close doors and wait for rescue.",
            }
            continue

        # Normal node: determine direction arrow from neighbor index
        neighbor_ids = [nb["node_id"] for nb in info.get("neighbors", [])]
        if nh in neighbor_ids:
            idx = neighbor_ids.index(nh)
            # Convention: first neighbor = left (←), last = right (→)
            if len(neighbor_ids) == 1:
                arrow = "→"
            elif idx == 0:
                arrow = "←"
            else:
                arrow = "→"
        else:
            arrow = "→"

        target_exit = exit_for.get(nid, nh)
        target_label = topology.get(target_exit, {}).get("human_label", target_exit) if target_exit else nh

        routes[nid] = {
            "direction": arrow,
            "next_hop": nh,
            "hint": f"Head toward {target_label} ({'left' if arrow == '←' else 'right'}).",
        }

    return routes
