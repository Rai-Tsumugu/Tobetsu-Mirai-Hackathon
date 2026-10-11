"""E30 manual labor-basis bridge with source permission checks."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from math import isfinite
from . import e07

ENGINE_ID = "e30_manual_basis_bridge"
RULE_VERSION = "e30-manual-bridge-v1"
NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_NULL = {"low": None, "typical": None, "high": None}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    version = scenario.get("rule_version", RULE_VERSION)
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else {}
    basis = pack.get("manual_basis") if rule_pack is not None and isinstance(pack, dict) else None
    fallback = rule_pack is None
    pack_issues = []
    if rule_pack is not None and not isinstance(rule_pack, dict):
        pack_issues.append("rule_pack:object_required")
    elif rule_pack is not None:
        if pack.get("engine_id") not in (None, ENGINE_ID): pack_issues.append("rule_pack:engine_id_mismatch")
        if pack.get("rule_version") != version: pack_issues.append("rule_pack:version_mismatch")
    if fallback:
        result = e07.run(scenario)
        result["engine_id"] = ENGINE_ID
        result["trace"].insert(0, {"stage": "manual_basis", "mode": "approved_process_fallback",
                                   "note": "No manual basis supplied; retain the approved fictional process baseline."})
        return result
    issues = list(pack_issues)
    if not isinstance(basis, dict):
        issues.append("manual_basis:object_required")
    else:
        if basis.get("unit") != "person_hour":
            issues.append("manual_basis:person_hour_unit_required")
        if not isinstance(basis.get("definition"), str) or not basis["definition"].strip():
            issues.append("manual_basis:definition_required")
        if not isinstance(basis.get("source"), str) or not basis["source"].strip():
            issues.append("manual_basis:source_required")
        if basis.get("permission_status") != "fictional_only":
            issues.append("manual_basis:permission_unconfirmed")
        value = basis.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            issues.append("manual_basis:value_invalid")
    if issues:
        return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
                "labor": {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [], "unknowns": issues},
                "trace": [{"stage": "manual_basis", "validated": False}], "operation_keys": [],
                "approvals": [], "simulator_notice": NOTICE}
    base = next((op for op in scenario.get("operations", []) if isinstance(op, dict) and op.get("operation_id") == "base_service"), None)
    if base is None:
        return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
                "labor": {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [],
                          "unknowns": ["base_service:required"]}, "trace": [], "operation_keys": [],
                "approvals": [], "simulator_notice": NOTICE}
    base["hours"] = float(basis["value"])
    base["deduplicated"] = True
    result = e07.run(scenario)
    result["engine_id"] = ENGINE_ID
    result["trace"].insert(0, {"stage": "manual_basis", "mode": "manual", "unit": basis["unit"],
                               "definition": basis["definition"], "source": basis["source"],
                               "permission_status": basis["permission_status"], "value": basis["value"]})
    return result
