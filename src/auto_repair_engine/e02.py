"""E02: versioned, approval-gated JSON rules for fictional labor estimates."""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

from .contract import reference_labor

ENGINE_ID = "e02_versioned_json"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_OPERATION_KEYS = {
    "base_service": "base_service", "included_carry": "replacement_carry",
    "replacement_carry": "replacement_carry", "snow_melt": "snow_melt",
    "penetrant_wait": "penetrant_wait", "parts_wait": "parts_wait", "wash": "wash",
}
_REQUIRED_SCENARIO_OPERATION = {
    "base_service": "base_service", "replacement_carry": "replacement_carry",
    "snow_melt": "snow_melt", "penetrant_wait": "penetrant_wait",
    "parts_wait": "parts_wait", "wash": "wash",
}
_RULE_KEYS = frozenset({"base_service", "replacement_carry", "snow_melt", "penetrant_wait",
                        "parts_wait", "wash", "rotor_seizure"})
_PACK_KEYS = frozenset({"engine_id", "rule_version", "status", "approved_by", "approver",
                        "effective_from", "source", "basis_unit", "basis_definition", "rules"})


def _obs(scenario: dict[str, Any], key: str) -> tuple[Any, str, str | None]:
    raw = (scenario.get("fields") or {}).get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value"), raw.get("status", "unknown"), raw.get("source")
    return raw, "declared" if raw is not None else "unknown", None


def _range(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict) or set(value) != {"low", "typical", "high"}:
        return None
    result: dict[str, float] = {}
    for key in ("low", "typical", "high"):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not isfinite(number) or number < 0:
            return None
        result[key] = float(number)
    if not result["low"] <= result["typical"] <= result["high"]:
        return None
    return result


def _null_ranges(labor: dict[str, Any]) -> None:
    null_range = {"low": None, "typical": None, "high": None}
    labor["person_hours"] = dict(null_range)
    labor["elapsed_hours"] = dict(null_range)
    for row in labor.get("breakdown", []):
        row["hours"] = dict(null_range)
        if "elapsed_hours" in row:
            row["elapsed_hours"] = dict(null_range)
        row["status"] = "missing-required"


def _rule_matches(rule: dict[str, Any], scenario: dict[str, Any]) -> bool:
    if rule.get("job_id") != scenario.get("job_id"):
        return False
    condition = rule.get("condition")
    if not isinstance(condition, dict):
        return False
    value, status, _ = _obs(scenario, condition["field"])
    if status in (None, "unknown", "assumed"):
        return False
    if "equals" in condition:
        return value == condition["equals"]
    return isinstance(value, list) and condition["contains"] in value


def _validate_pack(pack: dict[str, Any], scenario: dict[str, Any], gaps: list[str]) -> dict[str, dict[str, Any]]:
    if set(pack) - _PACK_KEYS:
        gaps.append("rule_pack:unknown_top_level_key")
    if not isinstance(pack.get("rule_version"), str) or not pack.get("rule_version", "").strip():
        gaps.append("rule_pack:rule_version_required")
    if pack.get("engine_id") not in (ENGINE_ID, "e02"):
        gaps.append("rule_pack:engine_id_required")
    if pack.get("status") != "approved":
        gaps.append("rule_pack:approved_status_required")
    if not isinstance(pack.get("approved_by") or pack.get("approver"), str) or not (pack.get("approved_by") or pack.get("approver", "")).strip():
        gaps.append("rule_pack:approver_required")
    if not isinstance(pack.get("effective_from"), str) or not pack.get("effective_from", "").strip():
        gaps.append("rule_pack:effective_from_required")
    if not isinstance(pack.get("source"), str) or not pack.get("source", "").strip():
        gaps.append("rule_pack:source_required")
    if pack.get("basis_unit") != scenario.get("basis_unit") or not isinstance(pack.get("basis_definition"), str) or pack.get("basis_definition") != scenario.get("basis_definition"):
        gaps.append("rule_pack:basis_mismatch")
    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        gaps.append("rule_pack:rules_required")
        return {}

    selected: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != {"job_id", "operation_key", "condition", "hours", "unit", "source"}:
            gaps.append(f"rule_pack:invalid_rule_schema:{index}")
            continue
        key = rule.get("operation_key")
        if key not in _RULE_KEYS:
            gaps.append(f"rule_pack:invalid_operation_key:{key!r}")
            continue
        if key in seen:
            gaps.append(f"rule_pack:duplicate_operation_key:{key}")
            continue
        seen.add(key)
        condition = rule.get("condition")
        if (not isinstance(rule.get("job_id"), str) or not rule["job_id"].strip()
                or not isinstance(condition, dict) or condition.get("field") not in {"work_scope", "included_operations", "parts_wait_stock_checked", "rotor_relevance"}
                or set(condition) not in ({"field", "equals"}, {"field", "contains"})
                or ("contains" in condition and condition["field"] != "included_operations")
                or not isinstance(rule.get("source"), str) or not rule["source"].strip()):
            gaps.append(f"rule_pack:invalid_rule_schema:{key}")
            continue
        expected_unit = "elapsed_hours" if key in {"snow_melt", "penetrant_wait", "parts_wait"} else "person_hours"
        if rule.get("unit") != expected_unit or _range(rule.get("hours")) is None:
            gaps.append(f"rule_pack:invalid_numeric_range_or_unit:{key}")
            continue
        if _rule_matches(rule, scenario):
            selected[key] = rule
            condition = rule["condition"]
            observed_value, observed_status, observed_source = _obs(scenario, condition["field"])
            # Observation provenance is added to the execution trace by run().
            rule["_observation"] = {"value": observed_value, "status": observed_status, "source": observed_source}
    return selected


def _inject_rule_values(scenario: dict[str, Any], selected: dict[str, dict[str, Any]]) -> None:
    """Feed JSON rule values to the canonical calculator as its scalar inputs."""
    op_by_id = {op.get("operation_id"): op for op in scenario.get("operations", [])}
    for key, rule in selected.items():
        values = _range(rule["hours"])
        typical = values["typical"]
        if key == "base_service" and "base_service" in op_by_id:
            op_by_id["base_service"]["hours"] = typical
        elif key == "replacement_carry" and "replacement_carry" in op_by_id:
            count = int(op_by_id["replacement_carry"].get("person_count") or 0)
            if count > 0:
                op_by_id["replacement_carry"]["hours_per_person"] = typical / count
        elif key == "wash" and "wash" in op_by_id:
            op_by_id["wash"]["hours"] = typical
        elif key in {"snow_melt", "penetrant_wait", "parts_wait"} and key in op_by_id:
            # An explicit unknown duration is scenario evidence. A generic rule
            # range must not turn that unknown observation into a known value.
            if op_by_id[key].get("elapsed_hours", op_by_id[key].get("hours")) is not None:
                op_by_id[key]["elapsed_hours"] = typical
        elif key == "rotor_seizure":
            raw = (scenario.get("fields") or {}).get("rotor_seizure_hours")
            if isinstance(raw, dict) and "value" in raw:
                raw["value"] = dict(values)
            else:
                scenario.setdefault("fields", {})["rotor_seizure_hours"] = {
                    "value": dict(values), "status": "confirmed", "source": rule["source"]}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict:
    """Evaluate the scenario under one immutable, approved JSON rule version."""
    scenario = deepcopy(scenario_input)
    pinned_version = scenario.get("rule_version")
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else None
    version = pinned_version or (pack or {}).get("rule_version") or "unbound"
    trace: list[dict[str, Any]] = [{"event": "rule_pack_requested", "engine_id": ENGINE_ID,
                                    "rule_version": version}]
    gaps: list[str] = []
    selected: dict[str, dict[str, Any]] = {}

    if pack is None:
        gaps.append("rule_pack:required")
    else:
        if pinned_version and pack.get("rule_version") != pinned_version:
            gaps.append("rule_pack:pinned_version_mismatch")
        selected = _validate_pack(pack, scenario, gaps)
        trace.append({"event": "rule_pack_loaded", "rule_version": pack.get("rule_version"),
                      "source": pack.get("source"), "status": pack.get("status"),
                      "effective_from": pack.get("effective_from")})
        for key, rule in selected.items():
            trace.append({"event": "rule_applied", "operation_key": key, "job_id": rule["job_id"],
                          "condition": {k: v for k, v in rule["condition"].items()},
                          "hours": dict(_range(rule["hours"])), "unit": rule["unit"],
                          "rule_source": rule["source"], "rule_version": version,
                          "observation": rule.get("_observation")})

    # Required scope membership is explicit and cannot be bypassed by an
    # otherwise matching generic work_scope rule.
    included, included_status, _ = _obs(scenario, "included_operations")
    required_included = {"remove_install", "rust_observation", "snow_removal"}
    if not isinstance(included, list) or included_status not in ("confirmed", "declared"):
        gaps.append("included_operations:required_confirmed_list")
    elif not required_included.issubset(set(included)):
        gaps.append("included_operations:required_keys_missing")
    elif set(included) - required_included:
        gaps.append("included_operations:unknown_operation_key")

    # A matching pack rule does not prove that the scenario actually contains
    # the corresponding required work. Keep the rule and scenario evidence
    # gates independent so a deleted operation cannot silently disappear.
    scenario_operation_ids = {op.get("operation_id") for op in scenario.get("operations", [])}
    for rule_key, operation_id in _REQUIRED_SCENARIO_OPERATION.items():
        if rule_key in selected and operation_id not in scenario_operation_ids:
            gaps.append(f"{operation_id}:scenario_operation_missing")

    for operation in scenario.get("operations", []):
        operation_id = operation.get("operation_id")
        key = _OPERATION_KEYS.get(operation_id)
        if key is None:
            gaps.append(f"{operation_id or 'operation'}:rule_missing")
        elif key not in selected:
            gaps.append(f"{operation_id}:rule_not_matched")

    included_carry = next((op for op in scenario.get("operations", [])
                           if op.get("operation_id") == "included_carry"), None)
    included_raw = included_carry.get("hours") if included_carry else None
    if not included_carry or included_carry.get("included_in_base") is not True:
        included_credit = None
        gaps.append("included_transport:confirmed_base_credit_required")
    elif isinstance(included_raw, dict):
        included_credit = _range(included_raw)
        if included_credit is None:
            gaps.append("included_transport:invalid_base_credit_range")
    elif isinstance(included_raw, (int, float)) and not isinstance(included_raw, bool) and isfinite(included_raw) and included_raw >= 0:
        credit = float(included_raw)
        included_credit = {"low": credit, "typical": credit, "high": credit}
    else:
        included_credit = None
        gaps.append("included_transport:invalid_base_credit_range")

    rotor_relevance, rotor_status, _ = _obs(scenario, "rotor_relevance")
    rotor_approval = (scenario.get("metadata") or {}).get("approved_condition_widths", {}).get("rotor_seizure_hours")
    rotor_rule = selected.get("rotor_seizure")
    if rotor_relevance == "relevant":
        rule_range = _range(rotor_rule.get("hours")) if rotor_rule else None
        if rotor_status not in ("confirmed", "declared") or not rule_range:
            gaps.append("rotor_seizure:confirmed_rule_required")
        if (not isinstance(rotor_approval, dict)
                or not isinstance(rotor_approval.get("actor"), str) or not rotor_approval["actor"].strip()
                or not isinstance(rotor_approval.get("reason"), str) or not rotor_approval["reason"].strip()
                or rotor_approval.get("old_value") is not None
                or _range(rotor_approval.get("new_value")) != rule_range):
            gaps.append("rotor_seizure:approval_actor_reason_and_matching_old_new_range_required")

    if not any(not gap.startswith("trace:") for gap in gaps):
        _inject_rule_values(scenario, selected)

    labor, _, canonical_unknowns = reference_labor(scenario)
    gaps.extend(item for item in canonical_unknowns if item not in gaps)
    unknowns = list(dict.fromkeys(gap for gap in gaps if not gap.startswith("trace:")))
    blocking = [item for item in unknowns if not item.endswith(":elapsed_duration_unknown")]

    # Apply rule ranges to rows and totals. All supported hours come from JSON;
    # the common fixture pack encodes exactly its canonical fictional values.
    key_for_row = {
        "base_service": "base_service", "included_carry": "replacement_carry",
        "replacement_carry": "replacement_carry", "snow_melt": "snow_melt",
        "penetrant_wait": "penetrant_wait", "parts_wait": "parts_wait", "wash": "wash",
        "rotor_seizure": "rotor_seizure",
    }
    person = {key: 0.0 for key in ("low", "typical", "high")}
    elapsed = {key: 0.0 for key in ("low", "typical", "high")}
    if included_credit is None:
        included_credit = {"low": 0.0, "typical": 0.0, "high": 0.0}
    if "base_service" in selected:
        base_range = _range(selected["base_service"]["hours"])
        net_base = {band: base_range[band] - included_credit[band] for band in person}
        if any(value < 0 for value in net_base.values()):
            gaps.append("included_transport:credit_exceeds_base")
        trace.append({"event": "included_base_deduction", "operation_key": "included_carry",
                      "hours": dict(included_credit), "source": included_carry.get("source") if included_carry else None,
                      "rule_version": version})
    else:
        net_base = {band: 0.0 for band in person}
    for row in labor.get("breakdown", []):
        operation_id = row.get("operation_id")
        if operation_id == "included_carry":
            row["operation_key"] = "included_transport_removed"
            continue
        operation_key = "rotor_seizure" if operation_id == "rotor_seizure" else key_for_row.get(operation_id, operation_id)
        if operation_id == "rotor_seizure" and rotor_relevance == "unrelated":
            operation_key = "rotor_seizure"
        row["operation_key"] = operation_key
        rule = selected.get(operation_key)
        if rule:
            values = dict(net_base) if operation_key == "base_service" else _range(rule["hours"])
            row["hours"] = ({"low": 0.0, "typical": 0.0, "high": 0.0}
                             if rule["unit"] == "elapsed_hours" else dict(values))
            row["rule_version"] = version
            row["rule_source"] = rule["source"]
            row["source"] = rule["source"]
            if rule["unit"] == "elapsed_hours":
                observed_elapsed = row.get("elapsed_hours")
                if not (isinstance(observed_elapsed, dict)
                        and any(observed_elapsed.get(band) is None for band in ("low", "typical", "high"))):
                    row["elapsed_hours"] = dict(values)
                    for band in elapsed:
                        elapsed[band] += values[band]
            else:
                for band in person:
                    person[band] += values[band]
                    if operation_key == "replacement_carry":
                        continue
                    elapsed[band] += values[band]
                if operation_key == "replacement_carry":
                    replacement_op = next((op for op in scenario.get("operations", [])
                                           if op.get("operation_id") == "replacement_carry"), {})
                    count = max(1, int(replacement_op.get("person_count") or 1))
                    for band in elapsed:
                        elapsed[band] += values[band] / count
        elif row.get("status") == "wait":
            for band in elapsed:
                elapsed[band] += float(row.get("elapsed_hours", {}).get(band) or 0)

    for band in elapsed:
        person[band] = round(person[band], 10)
        elapsed[band] = round(elapsed[band], 10)

    unknowns = list(dict.fromkeys([*unknowns, *(gap for gap in gaps if not gap.startswith("trace:"))]))
    blocking = [item for item in unknowns if not item.endswith(":elapsed_duration_unknown")]
    if blocking:
        _null_ranges(labor)
    else:
        labor["person_hours"] = person
        labor["elapsed_hours"] = ({"low": None, "typical": None, "high": None}
                                   if any(item.endswith(":elapsed_duration_unknown") for item in unknowns) else elapsed)
    labor["unknowns"] = unknowns

    approvals: list[dict[str, Any]] = []
    if pack and pack.get("status") == "approved":
        approvals.append({"type": "rule_pack", "approver": pack.get("approved_by") or pack.get("approver"),
                          "effective_from": pack.get("effective_from"), "source": pack.get("source"),
                          "rule_version": version})
    if rotor_relevance == "relevant" and isinstance(rotor_approval, dict):
        approvals.append({"operation_key": "rotor_seizure", "actor": rotor_approval.get("actor"),
                          "reason": rotor_approval.get("reason"),
                          "old_value": deepcopy(rotor_approval.get("old_value")),
                          "new_value": deepcopy(rotor_approval.get("new_value")),
                          "applied_range": deepcopy(_range(rotor_rule["hours"]) if rotor_rule else None),
                          "rule_version": version})
    status = "missing-required" if blocking else ("partial" if unknowns else "proposed")
    operation_keys = list(dict.fromkeys(selected))
    trace.append({"event": "rule_version_pinned", "rule_version": version,
                  "source": (pack or {}).get("source"), "operation_keys": operation_keys})
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status,
            "labor": labor, "trace": trace, "operation_keys": operation_keys,
            "approvals": approvals, "simulator_notice": SIMULATOR_NOTICE}
