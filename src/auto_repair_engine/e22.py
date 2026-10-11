"""E22: join scoped estimates to actual person-time observations."""
from __future__ import annotations
from copy import deepcopy
from math import isfinite
from typing import Any
from .e07 import run as calculate

ENGINE_ID = "e22_actual_join"
RULE_VERSION = "e22-actual-join-v1"

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    result = calculate(deepcopy(scenario_input))
    pack = rule_pack if isinstance(rule_pack, dict) else {}
    steps = deepcopy(pack.get("actual_steps", []))
    issues = []
    expected_scope = scenario_input.get("job_id") if isinstance(scenario_input, dict) else None
    if pack.get("scope_id") != expected_scope: issues.append("scope_id:estimate_actual_mismatch")
    if pack.get("rule_version") != result.get("rule_version"): issues.append("rule_version:estimate_actual_mismatch")
    if not isinstance(steps, list): steps = []; issues.append("actual_steps:list_required")
    total = 0.0; matched = set(); actual_rows = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict): issues.append("actual_steps[%d]:object_required" % i); continue
        if step.get("is_wait") is True or step.get("unit") == "elapsed_hours":
            actual_rows.append({"index": i, "excluded": "waiting_time"}); continue
        count, duration = step.get("person_count"), step.get("duration_hours")
        if step.get("unit") != "person_hour" or not isinstance(step.get("operation_id"), str) or not step["operation_id"]:
            issues.append("actual_steps[%d]:operation_and_person_hour_required" % i); continue
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0 or isinstance(duration, bool) or not isinstance(duration, (int, float)) or not isfinite(duration) or duration < 0:
            issues.append("actual_steps[%d]:person_count_and_duration_required" % i); continue
        hours = count * duration; total += hours; matched.add(step["operation_id"])
        actual_rows.append({"operation_id": step["operation_id"], "person_count": count, "duration_hours": duration, "person_hours": hours})
    estimate_keys = {row.get("operation_id") for row in result["labor"].get("breakdown", []) if row.get("operation_id") and row.get("status") != "wait"}
    for operation_id in sorted(matched - estimate_keys):
        issues.append("actual_step:unknown_operation_id:" + operation_id)
    complete = not issues and estimate_keys.issubset(matched)
    estimate = result["labor"]["person_hours"].get("typical")
    result.update({"engine_id": ENGINE_ID, "rule_version": RULE_VERSION,
                   "actual_comparison": {"complete": complete, "incomplete": not complete,
                     "actual_person_hours": total if complete else None,
                     "estimate_typical_person_hours": estimate if complete else None,
                     "delta_actual_minus_estimate": round(total - estimate, 10) if complete and estimate is not None else None,
                     "issues": issues, "unknowns": list(issues), "actual_steps": actual_rows}})
    return result
