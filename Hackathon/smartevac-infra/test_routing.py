"""
Offline routing tests — no AWS needed.

Validates multi-source Dijkstra on the 5-node topology.

    N1 (Exit) ──8m── N2 ──12m── N3 ──10m── N4 ──9m── N5 (Exit)

Run: python test_routing.py
"""

from topology import TOPOLOGY
from routing import plan_routes, score_contamination


def _fmt(routes: dict) -> None:
    for nid in sorted(routes):
        r = routes[nid]
        print(f"  {nid}: {r['direction']}  next_hop={r['next_hop']}  hint={r['hint']}")


def test_no_contamination():
    """No contamination: each node goes to nearest exit."""
    print("\n=== Test: No contamination ===")
    routes = plan_routes(TOPOLOGY, set())
    _fmt(routes)

    # N1 is exit -> evacuate
    assert routes["N1"]["direction"] == "↓"
    # N2 is 8m from N1, 24m from N5 -> go left to N1
    assert routes["N2"]["next_hop"] == "N1"
    assert routes["N2"]["direction"] == "←"
    # N3 is 20m from N1, 19m from N5 -> go right to N4 (toward N5)
    assert routes["N3"]["next_hop"] == "N4"
    assert routes["N3"]["direction"] == "→"
    # N4 is 30m from N1, 9m from N5 -> go right to N5
    assert routes["N4"]["next_hop"] == "N5"
    assert routes["N4"]["direction"] == "→"
    # N5 is exit -> evacuate
    assert routes["N5"]["direction"] == "↓"
    print("  PASSED")


def test_n2_contaminated():
    """N2 contaminated (near lab): N3 should route toward N5 instead of N1."""
    print("\n=== Test: N2 contaminated ===")
    routes = plan_routes(TOPOLOGY, {"N2"})
    _fmt(routes)

    assert routes["N2"]["direction"] == "🛑"
    # N1 is exit, still safe
    assert routes["N1"]["direction"] == "↓"
    # N3 can't go through N2 (penalty), should go right to N4 -> N5
    assert routes["N3"]["next_hop"] == "N4"
    assert routes["N3"]["direction"] == "→"
    assert routes["N4"]["next_hop"] == "N5"
    assert routes["N5"]["direction"] == "↓"
    print("  PASSED")


def test_n3_contaminated():
    """N3 contaminated (central hall): splits the graph."""
    print("\n=== Test: N3 contaminated ===")
    routes = plan_routes(TOPOLOGY, {"N3"})
    _fmt(routes)

    assert routes["N3"]["direction"] == "🛑"
    # N1 side: N1 exit, N2 -> N1
    assert routes["N1"]["direction"] == "↓"
    assert routes["N2"]["next_hop"] == "N1"
    assert routes["N2"]["direction"] == "←"
    # N5 side: N5 exit, N4 -> N5
    assert routes["N5"]["direction"] == "↓"
    assert routes["N4"]["next_hop"] == "N5"
    assert routes["N4"]["direction"] == "→"
    print("  PASSED")


def test_both_exits_contaminated():
    """Both exits contaminated: all interior nodes shelter in place."""
    print("\n=== Test: Both exits (N1, N5) contaminated ===")
    routes = plan_routes(TOPOLOGY, {"N1", "N5"})
    _fmt(routes)

    assert routes["N1"]["direction"] == "🛑"
    assert routes["N5"]["direction"] == "🛑"
    # Interior nodes should shelter in place (no safe exit reachable)
    assert routes["N2"]["direction"] == "🛑"
    assert routes["N3"]["direction"] == "🛑"
    assert routes["N4"]["direction"] == "🛑"
    print("  PASSED")


def test_n1_contaminated():
    """N1 (north exit) contaminated: everyone routes south."""
    print("\n=== Test: N1 contaminated ===")
    routes = plan_routes(TOPOLOGY, {"N1"})
    _fmt(routes)

    assert routes["N1"]["direction"] == "🛑"
    # N2 should go right toward N3 -> N4 -> N5
    assert routes["N2"]["next_hop"] == "N3"
    assert routes["N2"]["direction"] == "→"
    assert routes["N3"]["next_hop"] == "N4"
    assert routes["N3"]["direction"] == "→"
    assert routes["N4"]["next_hop"] == "N5"
    assert routes["N4"]["direction"] == "→"
    assert routes["N5"]["direction"] == "↓"
    print("  PASSED")


def test_score_contamination_basic():
    """score_contamination always includes triggering node."""
    print("\n=== Test: score_contamination basic ===")
    result = score_contamination("N3", {})
    assert "N3" in result
    print(f"  triggering_node=N3, empty telemetry -> contaminated={sorted(result)}")

    # With telemetry showing high z-score on N2
    # Need enough baseline readings so the spike produces z > threshold
    telemetry = {
        "N2": [
            {"mq135": 0.10, "mq2": 0.08, "temp_c": 24.0},
            {"mq135": 0.12, "mq2": 0.09, "temp_c": 24.0},
            {"mq135": 0.11, "mq2": 0.08, "temp_c": 24.1},
            {"mq135": 0.10, "mq2": 0.09, "temp_c": 24.0},
            {"mq135": 0.11, "mq2": 0.08, "temp_c": 24.1},
            {"mq135": 0.12, "mq2": 0.09, "temp_c": 24.0},
            {"mq135": 0.10, "mq2": 0.08, "temp_c": 24.0},
            {"mq135": 0.11, "mq2": 0.09, "temp_c": 24.1},
            {"mq135": 0.85, "mq2": 0.75, "temp_c": 32.0},  # spike
        ],
    }
    result2 = score_contamination("N3", telemetry)
    print(f"  triggering_node=N3, N2 spike telemetry -> contaminated={sorted(result2)}")
    assert "N3" in result2
    assert "N2" in result2
    print("  PASSED")


if __name__ == "__main__":
    test_no_contamination()
    test_n2_contaminated()
    test_n3_contaminated()
    test_both_exits_contaminated()
    test_n1_contaminated()
    test_score_contamination_basic()
    print("\n" + "=" * 40)
    print("ALL ROUTING TESTS PASSED")
    print("=" * 40)
