"""E21: evidence-gated additions to a scenario estimate."""
from __future__ import annotations
from copy import deepcopy
from math import isfinite
from typing import Any
from .e07 import run as calculate

ENGINE_ID = "e21_evidence_additions"
RULE_VERSION = "e21-evidence-additions-v1"

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    result = calculate(deepcopy(scenario_input))
    additions = deepcopy(rule_pack.get("additions", []) if isinstance(rule_pack, dict) else [])
    issues = ["rule_pack:object_required"] if rule_pack is not None and not isinstance(rule_pack, dict) else []
    if not isinstance(additions, list): additions = []; issues.append("additions:list_required")
    accepted = []
    for i, item in enumerate(additions):
        if not isinstance(item, dict): issues.append("addition[%d]:object_required" % i); continue
        value, audit = item.get("hours"), item.get("approval")
        if not isinstance(item.get("operation_id"), str) or not item["operation_id"]: issues.append("addition[%d]:operation_id_required" % i)
        if item.get("unit") != "person_hour": issues.append("addition[%d]:person_hour_unit_required" % i)
        if not isinstance(item.get("source"), str) or not item["source"].strip(): issues.append("addition[%d]:source_required" % i)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0: issues.append("addition[%d]:finite_nonnegative_hours_required" % i)
        prior = next((row for row in scenario_input.get("operations", [])
                      if row.get("operation_id") == item.get("operation_id")), None) if isinstance(scenario_input, dict) else None
        observed_old = prior.get("hours") if prior else None
        declared_old = item.get("old_value")
        expected_new = {"hours": value, "unit": item.get("unit"), "source": item.get("source")}
        if (prior is not None and declared_old != observed_old) or (prior is None and declared_old is not None):
            issues.append("addition[%d]:old_value_does_not_match_observation" % i)
        if (not isinstance(audit, dict) or not isinstance(audit.get("actor"), str) or not audit["actor"].strip()
                or not isinstance(audit.get("reason"), str) or not audit["reason"].strip()
                or audit.get("old_value") != declared_old
                or audit.get("new_value") != expected_new or audit.get("rule_version") != RULE_VERSION):
            issues.append("addition[%d]:effective_approval_required" % i)
        if not issues: accepted.append(item)
    result.update({"engine_id": ENGINE_ID, "rule_version": RULE_VERSION,
                   "evidence_additions": {"accepted": accepted, "issues": issues}})
    if issues:
        nulls = {"low": None, "typical": None, "high": None}
        result["status"] = "missing-required"; result["labor"]["person_hours"] = dict(nulls); result["labor"]["elapsed_hours"] = dict(nulls)
        for row in result["labor"].get("breakdown", []):
            row["hours"] = dict(nulls)
            if "elapsed_hours" in row: row["elapsed_hours"] = dict(nulls)
            row["status"] = "missing-required"
        result["labor"]["unknowns"] = list(dict.fromkeys(result["labor"].get("unknowns", []) + issues))
    elif accepted:
        added = sum(item["hours"] for item in accepted)
        for key in ("low", "typical", "high"):
            result["labor"]["person_hours"][key] = round(result["labor"]["person_hours"][key] + added, 10)
        for item in accepted:
            result["labor"]["breakdown"].append({"operation": item["operation_id"], "operation_id": item["operation_id"],
                "hours": {k: item["hours"] for k in ("low", "typical", "high")}, "reason": item["approval"]["reason"],
                "status": "conditional", "source": item["source"], "approval": item["approval"]})
        result["operation_keys"] = list(dict.fromkeys(result["operation_keys"] + [i["operation_id"] for i in accepted]))
    return result
