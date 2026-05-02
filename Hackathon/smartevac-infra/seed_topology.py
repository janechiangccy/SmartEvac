"""
Seed the DynamoDB TopologyTable with the 5-node campus topology.

Usage:
    python seed_topology.py [--delete]

    --delete : Delete and recreate the tables (use with caution)

Tables created if they don't exist:
    SmartEvacTopology  — PK: node_id (S)
    SmartEvacTelemetry — PK: node_id (S), SK: ts (N), TTL on 'ttl'
"""

from __future__ import annotations

import sys
import time
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from topology import TOPOLOGY

REGION = "us-east-1"
TOPOLOGY_TABLE = "SmartEvacTopology"
TELEMETRY_TABLE = "SmartEvacTelemetry"


def _json_to_dynamo(obj):
    """Convert floats to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _json_to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_to_dynamo(i) for i in obj]
    return obj


def create_topology_table(dynamodb):
    """Create TopologyTable if it doesn't exist."""
    try:
        dynamodb.create_table(
            TableName=TOPOLOGY_TABLE,
            KeySchema=[
                {"AttributeName": "node_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "node_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Creating {TOPOLOGY_TABLE}...")
        dynamodb.Table(TOPOLOGY_TABLE).wait_until_exists()
        print(f"  {TOPOLOGY_TABLE} created.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  {TOPOLOGY_TABLE} already exists.")
        else:
            raise


def create_telemetry_table(dynamodb):
    """Create TelemetryTable if it doesn't exist."""
    try:
        dynamodb.create_table(
            TableName=TELEMETRY_TABLE,
            KeySchema=[
                {"AttributeName": "node_id", "KeyType": "HASH"},
                {"AttributeName": "ts", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "node_id", "AttributeType": "S"},
                {"AttributeName": "ts", "AttributeType": "N"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Creating {TELEMETRY_TABLE}...")
        dynamodb.Table(TELEMETRY_TABLE).wait_until_exists()
        print(f"  {TELEMETRY_TABLE} created.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  {TELEMETRY_TABLE} already exists.")
        else:
            raise

    # Enable TTL on 'ttl' attribute
    client = boto3.client("dynamodb", region_name=REGION)
    try:
        client.update_time_to_live(
            TableName=TELEMETRY_TABLE,
            TimeToLiveSpecification={
                "Enabled": True,
                "AttributeName": "ttl",
            },
        )
        print(f"  TTL enabled on {TELEMETRY_TABLE}.ttl")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "ValidationException" and "already enabled" in str(e).lower():
            print(f"  TTL already enabled on {TELEMETRY_TABLE}.")
        else:
            # Non-fatal: TTL might not be changeable in Learner Lab
            print(f"  TTL setup warning: {e}")


def delete_tables(dynamodb):
    """Delete both tables."""
    for name in [TOPOLOGY_TABLE, TELEMETRY_TABLE]:
        try:
            table = dynamodb.Table(name)
            table.delete()
            print(f"  Deleting {name}...")
            table.wait_until_not_exists()
            print(f"  {name} deleted.")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"  {name} does not exist, skipping.")
            else:
                raise


def seed_topology(dynamodb):
    """Write 5-node topology into TopologyTable."""
    table = dynamodb.Table(TOPOLOGY_TABLE)

    with table.batch_writer() as batch:
        for node_id, info in TOPOLOGY.items():
            item = _json_to_dynamo({
                "node_id": node_id,
                "is_exit": info["is_exit"],
                "neighbors": info["neighbors"],
                "human_label": info["human_label"],
            })
            batch.put_item(Item=item)

    print(f"  Seeded {len(TOPOLOGY)} nodes into {TOPOLOGY_TABLE}.")


def verify_topology(dynamodb):
    """Read back and display topology."""
    table = dynamodb.Table(TOPOLOGY_TABLE)
    response = table.scan()
    items = response.get("Items", [])
    print(f"\n  Verification: {len(items)} nodes in {TOPOLOGY_TABLE}:")
    for item in sorted(items, key=lambda x: x["node_id"]):
        nid = item["node_id"]
        exit_mark = " [EXIT]" if item.get("is_exit") else ""
        neighbors = [n["node_id"] for n in item.get("neighbors", [])]
        print(f"    {nid}: {item.get('human_label', '?')}{exit_mark}  neighbors={neighbors}")


def main():
    do_delete = "--delete" in sys.argv

    dynamodb = boto3.resource("dynamodb", region_name=REGION)

    if do_delete:
        print("\n[1/4] Deleting existing tables...")
        delete_tables(dynamodb)
        time.sleep(2)
    else:
        print("\n[1/4] Skip delete (use --delete to recreate)")

    print("\n[2/4] Creating tables...")
    create_topology_table(dynamodb)
    create_telemetry_table(dynamodb)

    print("\n[3/4] Seeding topology...")
    seed_topology(dynamodb)

    print("\n[4/4] Verifying...")
    verify_topology(dynamodb)

    print("\n Done! Tables ready.")


if __name__ == "__main__":
    main()
