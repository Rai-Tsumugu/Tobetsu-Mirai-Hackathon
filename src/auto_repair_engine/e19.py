"""E19: side-by-side observation comparison without symmetry inference."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from .e07 import run as calculate

ENGINE_ID = "e19_side_panels"
RULE_VERSION = "e19-side-panels-v1"


def group_by_side(operations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    panels = {"left": [], "right": []}
    for row in operations:
        side = row.get("side")
        if side in panels:
            panels[side].append(deepcopy(row))
    return panels


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    snapshot = deepcopy(scenario_input)
    rows = snapshot.get("operations", []) if isinstance(snapshot, dict) else []
    panels = group_by_side(rows if isinstance(rows, list) else [])
    left_ids = {row.get("operation_id") for row in panels["left"]}
    right_ids = {row.get("operation_id") for row in panels["right"]}
    all_ids = left_ids | right_ids
    comparison = []
    for operation_id in sorted((x for x in all_ids if isinstance(x, str))):
        left = next((row for row in panels["left"] if row.get("operation_id") == operation_id), None)
        right = next((row for row in panels["right"] if row.get("operation_id") == operation_id), None)
        if left is None or right is None:
            difference = {"status": "opposite_unobserved", "hours_delta": None}
        elif isinstance(left.get("hours"), (int, float)) and isinstance(right.get("hours"), (int, float)):
            difference = {"status": "both_observed", "hours_delta": round(right["hours"] - left["hours"], 10)}
        else:
            difference = {"status": "both_observed", "hours_delta": None}
        comparison.append({"operation_id": operation_id, "left": left, "right": right,
                           "difference": difference})
    result = calculate(snapshot, rule_pack)
    result.update({"engine_id": ENGINE_ID, "rule_version": RULE_VERSION,
                   "side_panels": panels, "side_comparison": comparison,
                   "trace": [{"event": "side_observations_grouped", "left_count": len(panels["left"]),
                              "right_count": len(panels["right"]), "unknown_opposite_autofilled": False}, *result["trace"]]})
    return result
