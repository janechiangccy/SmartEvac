"""
Integration test: DynamoDB topology + Dijkstra routing end-to-end.

This test reads the real topology from DynamoDB (seeded by seed_topology.py),
then runs the Dijkstra routing engine against it.

Run: python test_integration.py
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import boto3

# Ensure we use the right region
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from dynamo import load_topology, load_recent_telemetry
from routing import plan_routes, score_contamination


def _fmt(routes: dict) -> None:
    for nid in sorted(routes):
        r = routes[nid]
        print(f"  {nid}: {r['direction']}  next_hop={r['next_hop']}  hint={r['hint']}")


def test_load_topology():
    """Verify topology loads from DynamoDB and has expected structure."""
    print("\n=== Test: Load topology from DynamoDB ===")
    topology = load_topology()

    assert len(topology) == 5, f"Expected 5 nodes, got {len(topology)}"
    for nid in ["N1", "N2", "N3", "N4", "N5"]:
        assert nid in topology, f"Missing node {nid}"
        assert "is_exit" in topology[nid]
        assert "neighbors" in topology[nid]

    assert topology["N1"]["is_exit"] is True
    assert topology["N5"]["is_exit"] is True
    assert topology["N3"]["is_exit"] is False

    print(f"  Loaded {len(topology)} nodes from DynamoDB")
    for nid in sorted(topology):
        info = topology[nid]
        exit_mark = " [EXIT]" if info["is_exit"] else ""
        nb = [n["node_id"] for n in info["neighbors"]]
        print(f"    {nid}: {info.get('human_label', '?')}{exit_mark}  neighbors={nb}")
    print("  PASSED")
    return topology


def test_routing_with_dynamo_topology(topology: dict):
    """Run Dijkstra on real DynamoDB topology."""
    print("\n=== Test: Dijkstra on DynamoDB topology ===")

    # Scenario: N2 contaminated (lab leak)
    contaminated = {"N2"}
    routes = plan_routes(topology, contaminated)
    print(f"\n  Scenario: N2 contaminated")
    _fmt(routes)

    assert routes["N2"]["direction"] == "🛑"
    assert routes["N1"]["direction"] == "↓"  # exit, safe
    assert routes["N3"]["next_hop"] == "N4"  # route away from N2
    assert routes["N5"]["direction"] == "↓"  # exit, safe
    print("  PASSED")

    # Scenario: N3 contaminated (central hall)
    contaminated = {"N3"}
    routes = plan_routes(topology, contaminated)
    print(f"\n  Scenario: N3 contaminated")
    _fmt(routes)

    assert routes["N3"]["direction"] == "🛑"
    assert routes["N2"]["next_hop"] == "N1"  # go north
    assert routes["N4"]["next_hop"] == "N5"  # go south
    print("  PASSED")


def test_telemetry_write_and_read():
    """Write fake telemetry to DynamoDB, then read it back."""
    print("\n=== Test: Telemetry write + read ===")

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table("SmartEvacTelemetry")

    now = int(time.time())
    # Write a few readings for N2
    for i in range(5):
        table.put_item(Item={
            "node_id": "N2",
            "ts": now - 20 + i * 5,  # spread over last 20 seconds
            "mq2": Decimal("0.10"),
            "mq135": Decimal("0.12"),
            "temp_c": Decimal("24.0"),
            "alert_level": "normal",
            "ttl": now + 60,  # expire in 60 seconds
        })

    # Write a spike reading
    table.put_item(Item={
        "node_id": "N2",
        "ts": now,
        "mq2": Decimal("0.75"),
        "mq135": Decimal("0.88"),
        "temp_c": Decimal("32.0"),
        "alert_level": "alert",
        "ttl": now + 60,
    })

    telemetry = load_recent_telemetry(window_sec=30)
    n2_readings = telemetry.get("N2", [])
    print(f"  N2 readings in last 30s: {len(n2_readings)}")
    assert len(n2_readings) >= 5, f"Expected >= 5 readings, got {len(n2_readings)}"

    # Now test score_contamination with real telemetry
    contaminated = score_contamination("N3", telemetry)
    print(f"  score_contamination(trigger=N3, telemetry) -> {sorted(contaminated)}")
    assert "N3" in contaminated  # triggering node always included
    assert "N2" in contaminated  # spike should trigger contamination
    print("  PASSED")


def test_full_pipeline():
    """Full pipeline: DynamoDB topology + telemetry -> contamination -> Dijkstra."""
    print("\n=== Test: Full pipeline (topology + telemetry -> routing) ===")

    topology = load_topology()
    telemetry = load_recent_telemetry(window_sec=30)

    # Trigger from N3, N2 has spike telemetry from previous test
    contaminated = score_contamination("N3", telemetry)
    routes = plan_routes(topology, contaminated)

    print(f"  Contaminated: {sorted(contaminated)}")
    _fmt(routes)

    # N2 and N3 should be contaminated
    assert "N2" in contaminated
    assert "N3" in contaminated
    # N1 should be exit (safe)
    assert routes["N1"]["direction"] == "↓"
    # N4 should route to N5
    assert routes["N4"]["next_hop"] == "N5"
    assert routes["N5"]["direction"] == "↓"
    print("  PASSED")


if __name__ == "__main__":
    topo = test_load_topology()
    test_routing_with_dynamo_topology(topo)
    test_telemetry_write_and_read()
    test_full_pipeline()
    print("\n" + "=" * 40)
    print("ALL INTEGRATION TESTS PASSED")
    print("=" * 40)
