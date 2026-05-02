"""
SmartEvac 5-node campus topology definition.

Floor plan (single floor, 5 nodes):

    N1 (North Exit) ──8m── N2 (NW Corridor) ──12m── N3 (Central Hall)
                                                        │
                                                       10m
                                                        │
                           N5 (South Exit) ──9m──  N4 (SE Corridor)

Exits: N1 (north), N5 (south)
Non-exits: N2, N3, N4

This matches the proposal's 5-node demo layout.
"""

TOPOLOGY = {
    "N1": {
        "node_id": "N1",
        "is_exit": True,
        "neighbors": [
            {"node_id": "N2", "distance_m": 8},
        ],
        "human_label": "North corridor exit",
    },
    "N2": {
        "node_id": "N2",
        "is_exit": False,
        "neighbors": [
            {"node_id": "N1", "distance_m": 8},
            {"node_id": "N3", "distance_m": 12},
        ],
        "human_label": "NW corridor near lab",
    },
    "N3": {
        "node_id": "N3",
        "is_exit": False,
        "neighbors": [
            {"node_id": "N2", "distance_m": 12},
            {"node_id": "N4", "distance_m": 10},
        ],
        "human_label": "Central hall",
    },
    "N4": {
        "node_id": "N4",
        "is_exit": False,
        "neighbors": [
            {"node_id": "N3", "distance_m": 10},
            {"node_id": "N5", "distance_m": 9},
        ],
        "human_label": "SE corridor",
    },
    "N5": {
        "node_id": "N5",
        "is_exit": True,
        "neighbors": [
            {"node_id": "N4", "distance_m": 9},
        ],
        "human_label": "South corridor exit",
    },
}
