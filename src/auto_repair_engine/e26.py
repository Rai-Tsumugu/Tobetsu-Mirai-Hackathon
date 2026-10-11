"""E26: append-only actual revisions and rebuildable active views."""
from __future__ import annotations
from copy import deepcopy
from math import isfinite
from typing import Any

ENGINE_ID = "e26_actual_revision"

def active_view(actuals: list[dict], revisions: list[dict] | None = None) -> dict[str, Any]:
    revisions = revisions or []
    if not isinstance(actuals, list) or not isinstance(revisions, list):
        raise ValueError("actuals and revisions must be lists")
    base: dict[str, dict] = {}
    for item in actuals:
        if not isinstance(item, dict) or not isinstance(item.get("event_id"), str) or item["event_id"] in base:
            raise ValueError("actual event IDs must be valid and unique")
        if (not isinstance(item.get("operation_id"), str) or isinstance(item.get("hours"), bool)
                or not isinstance(item.get("hours"), (int, float)) or not isfinite(item["hours"]) or item["hours"] < 0):
            raise ValueError("actual operation_id and nonnegative hours are required")
        count = item.get("person_count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("actual person_count must be a positive integer")
        base[item["event_id"]] = deepcopy(item)
    by_id: dict[str, dict] = {}
    children: dict[str, list[str]] = {}
    for revision in revisions:
        rid, parent = revision.get("revision_id"), revision.get("parent_id")
        if not isinstance(rid, str) or not rid or rid in by_id or rid in base:
            raise ValueError("revision IDs must be valid and unique")
        if parent not in base and parent not in by_id:
            raise ValueError("revision parent reference is missing")
        if not all(isinstance(revision.get(k), str) and revision[k].strip() for k in ("reason", "actor", "rule_version")):
            raise ValueError("revision reason, actor, and rule_version are required")
        delta = revision.get("delta_hours")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not isfinite(delta):
            raise ValueError("delta_hours must be numeric")
        by_id[rid] = deepcopy(revision)
        children.setdefault(parent, []).append(rid)
    if any(len(kids) > 1 for kids in children.values()):
        raise ValueError("revision forks are invalid")
    # Verify each revision chain ends at a base actual, rejecting cycles.
    for rid, revision in by_id.items():
        seen = {rid}
        parent = revision["parent_id"]
        while parent in by_id:
            if parent in seen:
                raise ValueError("revision cycle detected")
            seen.add(parent)
            parent = by_id[parent]["parent_id"]
    heads = [key for key in base if key not in children]
    heads += [key for key in by_id if key not in children]
    view = []
    for head in heads:
        revision_id = head
        if head in by_id:
            chain = []
            while revision_id in by_id:
                chain.append(by_id[revision_id])
                revision_id = by_id[revision_id]["parent_id"]
            original = base[revision_id]
            active = chain[0]
            hours = original["hours"] + sum(revision["delta_hours"] for revision in chain)
            if hours < 0:
                raise ValueError("revision produces negative active hours")
            view.append({**deepcopy(original), "hours": hours, "active_revision_id": active["revision_id"],
                         "revision_rule_version": active["rule_version"]})
        else:
            view.append(deepcopy(base[head]))
    totals: dict[str, float] = {}
    for item in view:
        key = item["operation_id"]
        totals[key] = totals.get(key, 0.0) + float(item["hours"])
    return {"engine_id": ENGINE_ID, "status": "proposed", "active_view": view,
            "bucket_hours": totals, "revision_log": deepcopy(revisions)}

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict:
    if not isinstance(scenario_input, dict) or not isinstance(scenario_input.get("actuals"), list):
        null = {"low": None, "typical": None, "high": None}
        return {"engine_id": ENGINE_ID, "rule_version": (scenario_input or {}).get("rule_version", "e26-1"),
                "status": "missing-required", "labor": {"person_hours": null, "elapsed_hours": dict(null), "breakdown": [], "unknowns": ["actuals:list_required"]},
                "trace": [], "operation_keys": [], "approvals": [],
                "simulator_notice": "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"}
    version = scenario_input.get("rule_version", "e26-1")
    try:
        result = active_view(scenario_input["actuals"], scenario_input.get("revisions", []))
    except (ValueError, TypeError, KeyError) as exc:
        null = {"low": None, "typical": None, "high": None}
        return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
                "labor": {"person_hours": dict(null), "elapsed_hours": dict(null), "breakdown": [], "unknowns": [f"revision:{exc}"]},
                "trace": [], "operation_keys": [], "approvals": [],
                "simulator_notice": "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"}
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": result["status"],
            "labor": {"person_hours": {"low": result["bucket_hours"].get("total", 0), "typical": result["bucket_hours"].get("total", 0), "high": result["bucket_hours"].get("total", 0)},
                      "elapsed_hours": {"low": 0.0, "typical": 0.0, "high": 0.0},
                      "breakdown": [{"operation_id": row["operation_id"], "operation": row["operation_id"],
                                     "hours": {"low": row["hours"], "typical": row["hours"], "high": row["hours"]},
                                     "reason": "append-only actual active view", "status": "proposed"} for row in result["active_view"]],
                      "unknowns": []}, "trace": [{"event": "active_view_rebuilt", "revision_count": len(result["revision_log"])}],
            "operation_keys": list(result["bucket_hours"]), "approvals": [],
            "simulator_notice": "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。",
            "active_view": result["active_view"], "bucket_hours": result["bucket_hours"],
            "revision_log": result["revision_log"]}
