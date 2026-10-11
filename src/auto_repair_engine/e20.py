"""E20: isolated what-if calculation over a cloned scenario snapshot."""
from __future__ import annotations
from copy import deepcopy
import hashlib, json
from typing import Any
from .e07 import run as calculate

ENGINE_ID = "e20_what_if"
RULE_VERSION = "e20-what-if-v1"

def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    original = deepcopy(scenario_input)
    hypothesis = deepcopy(rule_pack.get("hypothesis", {}) if isinstance(rule_pack, dict) else {})
    sandbox = deepcopy(original)
    changes = hypothesis.get("operations", [])
    if not isinstance(changes, list):
        changes = None
    issues = ["rule_pack:object_required"] if rule_pack is not None and not isinstance(rule_pack, dict) else []
    if changes is None:
        issues.append("hypothesis:operations_list_required")
    elif changes and (not hypothesis.get("actor") or not hypothesis.get("reason")):
        issues.append("hypothesis:actor_and_reason_required")
    applied = []
    if not issues:
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("operation_id"), str):
                issues.append("hypothesis:operation_id_required"); break
            target = next((row for row in sandbox.get("operations", []) if row.get("operation_id") == change["operation_id"]), None)
            if target is None:
                issues.append("hypothesis:unknown_operation:" + change["operation_id"]); break
            before = deepcopy(target)
            target.update({key: deepcopy(value) for key, value in change.items() if key != "operation_id"})
            applied.append({"operation_id": change["operation_id"], "old_value": before,
                            "new_value": deepcopy(target), "actor": hypothesis.get("actor"), "reason": hypothesis.get("reason")})
    if issues:
        result = calculate(original)
        result.update({"engine_id": ENGINE_ID, "rule_version": RULE_VERSION,
                       "hypothesis": {"status": "rejected", "issues": issues, "changes": []}})
        return result
    result = calculate(sandbox)
    result.update({"engine_id": ENGINE_ID, "rule_version": RULE_VERSION,
                   "hypothesis": {"status": "sandbox-proposed", "parent_hash": _hash(original),
                                  "hypothesis_hash": _hash(sandbox), "changes": applied,
                                  "approved": False, "overwrote_original": False},
                   "trace": [{"event": "what_if_snapshot_cloned", "parent_hash": _hash(original)}, *result["trace"]]})
    return result
