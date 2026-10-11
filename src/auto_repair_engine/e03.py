"""E03: a small, allowlisted DSL interpreted without dynamic code execution."""
from __future__ import annotations

from copy import deepcopy
import json
import re
from math import isfinite
from typing import Any

from .contract import common_scenario_fixture, reference_labor

ENGINE_ID = "e03_restricted_dsl"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"

_ALLOWED_FIELDS = frozenset({
    "work_scope", "included_operations", "parts_wait_stock_checked", "rotor_relevance",
})
_OP_UNITS = {
    "base_service": "person_hours",
    "replacement_carry": "person_hours",
    "snow_melt": "elapsed_hours",
    "penetrant_wait": "elapsed_hours",
    "parts_wait": "elapsed_hours",
    "wash": "person_hours",
    "rotor_seizure": "person_hours",
}
_OPERATION_IDS = frozenset(_OP_UNITS)
_LINE_RE = re.compile(
    r'\s*when\s+([a-z_]+)\s+equals\s+'
    r'(true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|"(?:[^"\\]|\\.)*")'
    r'\s*->\s*set_range\s+([a-z_]+)\s+(\{[^{}]*\})\s+'
    r'(person_hours|elapsed_hours)\s*',
    re.ASCII,
)
_PACK_KEYS = frozenset({
    "engine_id", "rule_version", "status", "approved_by", "effective_from",
    "source", "basis_unit", "basis_definition", "rules",
})
_RULE_KEYS = frozenset({"rule_id", "expression", "source", "reason"})


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


def _observation(scenario: dict[str, Any], field: str) -> tuple[Any, str, str | None]:
    value = (scenario.get("fields") or {}).get(field)
    if isinstance(value, dict) and "value" in value:
        return value.get("value"), value.get("status", "unknown"), value.get("source")
    return value, "declared" if value is not None else "unknown", None


def parse_to_ast(expression: Any) -> dict[str, Any] | None:
    """Parse exactly one supported statement; every other token is rejected."""
    if not isinstance(expression, str):
        return None
    match = _LINE_RE.fullmatch(expression)
    if not match:
        return None
    field, raw_value, operation_id, raw_range, unit = match.groups()
    if field not in _ALLOWED_FIELDS or operation_id not in _OPERATION_IDS:
        return None
    try:
        value = json.loads(raw_value)
        numeric_range = _range(json.loads(raw_range))
    except (ValueError, TypeError):
        return None
    if isinstance(value, (dict, list)) or (value is not None and not isinstance(value, (str, int, float, bool))):
        return None
    if isinstance(value, float) and not isfinite(value):
        return None
    if numeric_range is None or unit != _OP_UNITS[operation_id]:
        return None
    return {
        "when": {"field": field, "equals": value},
        "op": "set_range",
        "operation_id": operation_id,
        "range": numeric_range,
        "unit": unit,
    }


def _default_rule_pack(scenario: dict[str, Any]) -> dict[str, Any]:
    job_id = scenario["job_id"]
    # Values are explicitly fictional and match the shared fixture. Rotor work
    # is conditional: the DSL cannot manufacture the human approval record.
    rows = [
        ("base_service", "work_scope", "front_brake_service", {"low": 1.7, "typical": 1.7, "high": 1.7}, "person_hours"),
        ("replacement_carry", "work_scope", "front_brake_service", {"low": 0.2, "typical": 0.2, "high": 0.2}, "person_hours"),
        ("snow_melt", "work_scope", "front_brake_service", {"low": 0.5, "typical": 0.5, "high": 0.5}, "elapsed_hours"),
        ("penetrant_wait", "work_scope", "front_brake_service", {"low": 0.25, "typical": 0.25, "high": 0.25}, "elapsed_hours"),
        ("parts_wait", "parts_wait_stock_checked", True, {"low": 0.0, "typical": 0.0, "high": 0.0}, "elapsed_hours"),
        ("wash", "work_scope", "front_brake_service", {"low": 0.1, "typical": 0.1, "high": 0.1}, "person_hours"),
        ("rotor_seizure", "rotor_relevance", "relevant", {"low": 0.0, "typical": 0.25, "high": 0.5}, "person_hours"),
    ]
    rules = []
    for operation_id, field, value, values, unit in rows:
        expression = "when {} equals {} -> set_range {} {} {}".format(
            field, json.dumps(value, separators=(",", ":")), operation_id,
            json.dumps(values, separators=(",", ":")), unit,
        )
        rules.append({
            "rule_id": operation_id,
            "expression": expression,
            "source": "fictional_e03_default:" + operation_id,
            "reason": "共通Simulator fixture用の架空規則",
        })
    return {
        "engine_id": ENGINE_ID,
        "rule_version": scenario.get("rule_version", "fictional-rule-v1"),
        "status": "approved",
        "approved_by": "fictional_fixture_owner",
        "effective_from": "2026-10-11T00:00:00+00:00",
        "source": "fictional_e03_default",
        "basis_unit": scenario.get("basis_unit"),
        "basis_definition": scenario.get("basis_definition"),
        "rules": rules,
    }


DEFAULT_SCENARIO = common_scenario_fixture()
DEFAULT_RULE_PACK = _default_rule_pack(DEFAULT_SCENARIO)


def _null_labor(labor: dict[str, Any]) -> None:
    nulls = {"low": None, "typical": None, "high": None}
    labor["person_hours"] = dict(nulls)
    labor["elapsed_hours"] = dict(nulls)
    for row in labor.get("breakdown", []):
        row["hours"] = dict(nulls)
        if "elapsed_hours" in row:
            row["elapsed_hours"] = dict(nulls)
        row["status"] = "missing-required"


def _validate_pack(pack: Any, scenario: dict[str, Any], gaps: list[str]) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(pack, dict):
        gaps.append("rule_pack:required")
        return [], "unbound"
    raw_version = pack.get("rule_version")
    version = raw_version if isinstance(raw_version, str) else "unbound"
    if set(pack) != _PACK_KEYS:
        gaps.append("rule_pack:unknown_or_missing_top_level_key")
    if pack.get("engine_id") not in (ENGINE_ID, "e03"):
        gaps.append("rule_pack:engine_id_required")
    if not isinstance(raw_version, str) or not raw_version.strip():
        gaps.append("rule_pack:rule_version_required")
    if isinstance(raw_version, str) and scenario.get("rule_version") and version != scenario.get("rule_version"):
        gaps.append("rule_pack:pinned_version_mismatch")
    if pack.get("status") != "approved":
        gaps.append("rule_pack:approved_status_required")
    approver = pack.get("approved_by")
    if not isinstance(approver, str) or not approver.strip():
        gaps.append("rule_pack:approver_required")
    for key in ("effective_from", "source"):
        if not isinstance(pack.get(key), str) or not pack[key].strip():
            gaps.append("rule_pack:{}_required".format(key))
    if (pack.get("basis_unit") != scenario.get("basis_unit")
            or not isinstance(pack.get("basis_definition"), str)
            or pack.get("basis_definition") != scenario.get("basis_definition")):
        gaps.append("rule_pack:basis_mismatch")
    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        gaps.append("rule_pack:rules_required")
        return [], version

    parsed: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_ops: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != _RULE_KEYS:
            gaps.append("rule_pack:invalid_rule_shape:{}".format(index))
            continue
        rule_id = rule.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in seen_ids:
            gaps.append("rule_pack:invalid_or_duplicate_rule_id:{}".format(index))
            continue
        seen_ids.add(rule_id)
        ast = parse_to_ast(rule.get("expression"))
        if ast is None:
            gaps.append("rule_pack:unknown_token_or_invalid_expression:{}".format(rule_id))
            continue
        operation_id = ast["operation_id"]
        if operation_id in seen_ops:
            gaps.append("rule_pack:duplicate_operation_id:{}".format(operation_id))
            continue
        seen_ops.add(operation_id)
        if any(not isinstance(rule.get(key), str) or not rule[key].strip() for key in ("source", "reason")):
            gaps.append("rule_pack:source_and_reason_required:{}".format(rule_id))
            continue
        ast.update({"rule_id": rule_id, "source": rule["source"], "reason": rule["reason"]})
        parsed.append(ast)
    return parsed, version


def _interpret(ast_rows: list[dict[str, Any]], scenario: dict[str, Any], trace: list[dict[str, Any]], gaps: list[str]) -> dict[str, dict[str, Any]]:
    """Apply the allowlisted AST to known input rows; never evaluates Python."""
    operations = {row.get("operation_id"): row for row in scenario.get("operations", []) if isinstance(row, dict)}
    selected: dict[str, dict[str, Any]] = {}
    for ast in ast_rows:
        field = ast["when"]["field"]
        observed, status, source = _observation(scenario, field)
        matches = status in ("confirmed", "declared") and observed == ast["when"]["equals"]
        trace.append({"event": "dsl_condition_evaluated", "rule_id": ast["rule_id"], "field": field,
                      "matched": matches, "observation_status": status, "observation_source": source})
        if not matches:
            continue
        operation_id = ast["operation_id"]
        target = operations.get(operation_id)
        if target is None and operation_id != "rotor_seizure":
            gaps.append("{}:operation_missing".format(operation_id))
            continue
        value_range = dict(ast["range"])
        if ast["unit"] == "elapsed_hours":
            if target is not None:
                # An explicit unknown wait duration must remain unknown. The
                # canonical labor row carries this as a null elapsed range;
                # _apply_ranges preserves that marker while still allowing
                # valid DSL ranges to widen known wait durations.
                raw_duration = target.get("elapsed_hours", target.get("hours"))
                if raw_duration is None:
                    selected[operation_id] = ast
                    continue
                target["elapsed_hours"] = value_range["typical"]
                target["hours"] = value_range["typical"]
        elif operation_id == "replacement_carry":
            count = target.get("person_count") if target else None
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                gaps.append("replacement_carry:person_count_required")
                continue
            target["hours_per_person"] = value_range["typical"] / count
        elif operation_id == "rotor_seizure":
            current = (scenario.get("fields") or {}).get("rotor_seizure_hours")
            approval = (scenario.get("metadata") or {}).get("approved_condition_widths", {}).get("rotor_seizure_hours")
            expected = {key: value_range[key] for key in ("low", "typical", "high")}
            if not (isinstance(current, dict) and current.get("status") == "confirmed"
                    and current.get("value") == expected and isinstance(approval, dict)
                    and approval.get("new_value") == expected):
                gaps.append("rotor_seizure:range_must_match_human_approval")
                continue
        elif target is not None:
            target["hours"] = value_range["typical"]
        selected[operation_id] = ast
        trace.append({"event": "dsl_operation_applied", "operation_id": operation_id,
                      "operation_key": operation_id, "range": value_range, "unit": ast["unit"],
                      "rule_id": ast["rule_id"], "rule_source": ast["source"]})
    return selected


def _apply_ranges(labor: dict[str, Any], selected: dict[str, dict[str, Any]]) -> None:
    """Replace scalar fixture rows with approved widths and recompute totals."""
    person = {key: 0.0 for key in ("low", "typical", "high")}
    elapsed = {key: 0.0 for key in ("low", "typical", "high")}
    elapsed_complete = True
    for row in labor.get("breakdown", []):
        op_id = row.get("operation_id")
        ast = selected.get(op_id)
        if ast is None and op_id == "included_carry":
            row["operation_key"] = "included_transport_removed"
            continue
        if ast is None and op_id == "replacement_carry":
            ast = selected.get("replacement_carry")
        if ast is not None:
            values = dict(ast["range"])
            row["operation_key"] = ast["operation_id"]
            row["rule_version"] = ast.get("_version")
            row["rule_source"] = ast["source"]
            row["source"] = ast["source"]
            row["reason"] = ast["reason"]
            if ast["unit"] == "elapsed_hours":
                row["hours"] = {"low": 0.0, "typical": 0.0, "high": 0.0}
                existing_elapsed = row.get("elapsed_hours")
                if not (isinstance(existing_elapsed, dict)
                        and all(existing_elapsed.get(key) is None for key in ("low", "typical", "high"))):
                    row["elapsed_hours"] = values
                    for band in elapsed:
                        elapsed[band] += values[band]
                else:
                    elapsed_complete = False
                    labor["elapsed_hours"] = {"low": None, "typical": None, "high": None}
            else:
                row["hours"] = values
                for band in person:
                    person[band] += values[band]
                    count = row.get("person_count")
                    divisor = count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 1
                    elapsed[band] += values[band] / divisor
        elif "elapsed_hours" in row:
            values = row["elapsed_hours"]
            if all(isinstance(values.get(key), (int, float)) for key in ("low", "typical", "high")):
                for band in elapsed:
                    elapsed[band] += float(values[band])
            else:
                elapsed_complete = False
                labor["elapsed_hours"] = {"low": None, "typical": None, "high": None}
        else:
            values = row.get("hours") or {}
            for band in person:
                if isinstance(values.get(band), (int, float)):
                    person[band] += float(values[band])
                    elapsed[band] += float(values[band])
    labor["person_hours"] = {key: round(value, 10) for key, value in person.items()}
    if elapsed_complete and all(isinstance(value, (int, float)) for value in elapsed.values()):
        labor["elapsed_hours"] = {key: round(value, 10) for key, value in elapsed.items()}


def _deduct_included_credit(scenario: dict[str, Any], selected: dict[str, dict[str, Any]], gaps: list[str], trace: list[dict[str, Any]]) -> None:
    """The base rule is gross labor; included transport is removed exactly once."""
    base = selected.get("base_service")
    if base is None:
        return
    included = next((row for row in scenario.get("operations", [])
                    if isinstance(row, dict) and row.get("operation_id") == "included_carry"), None)
    raw = included.get("hours") if included else None
    if isinstance(raw, dict):
        credit = _range(raw)
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool) and isfinite(raw) and raw >= 0:
        credit = {key: float(raw) for key in ("low", "typical", "high")}
    else:
        credit = None
    if not included or included.get("included_in_base") is not True or credit is None:
        gaps.append("included_transport:confirmed_base_credit_required")
        return
    net = {key: base["range"][key] - credit[key] for key in ("low", "typical", "high")}
    if any(value < 0 for value in net.values()):
        gaps.append("included_transport:credit_exceeds_base")
        return
    if not net["low"] <= net["typical"] <= net["high"]:
        gaps.append("included_transport:deducted_range_invalid")
        return
    base["range"] = net
    trace.append({"event": "included_base_deduction", "operation_id": "included_carry",
                  "hours": credit, "rule_version": base.get("_version")})


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict:
    scenario = deepcopy(scenario_input)
    pack = deepcopy(rule_pack) if rule_pack is not None else deepcopy(_default_rule_pack(scenario))
    version = pack.get("rule_version", "unbound") if isinstance(pack, dict) else "unbound"
    trace: list[dict[str, Any]] = [{"event": "dsl_pack_requested", "engine_id": ENGINE_ID, "rule_version": version}]
    gaps: list[str] = []
    ast_rows, version = _validate_pack(pack, scenario, gaps)
    trace.append({"event": "dsl_pack_loaded", "rule_version": version,
                  "source": pack.get("source") if isinstance(pack, dict) else None,
                  "status": pack.get("status") if isinstance(pack, dict) else None})
    for ast in ast_rows:
        ast["_version"] = version
    selected = _interpret(ast_rows, scenario, trace, gaps)
    _deduct_included_credit(scenario, selected, gaps, trace)

    operation_ids = [row.get("operation_id") for row in scenario.get("operations", []) if isinstance(row, dict)]
    known_scenario_operations = _OPERATION_IDS | {"included_carry"}
    for operation_id in operation_ids:
        if not isinstance(operation_id, str) or operation_id not in known_scenario_operations:
            gaps.append("operation_id:unsupported")
    if len(operation_ids) != len(set(item for item in operation_ids if isinstance(item, str))):
        gaps.append("operation_id:duplicate")
    for operation_id in operation_ids:
        key = "replacement_carry" if operation_id == "included_carry" else operation_id
        if key in _OP_UNITS and key not in selected:
            gaps.append("{}:rule_not_matched".format(key))

    labor, _, canonical_unknowns = reference_labor(scenario)
    gaps.extend(item for item in canonical_unknowns if item not in gaps)
    unknowns = list(dict.fromkeys(gaps))
    blocking = [item for item in unknowns if not item.endswith(":elapsed_duration_unknown")]
    for row in labor.get("breakdown", []):
        row["operation_key"] = row.get("operation_id") or row.get("operation")
    if not blocking:
        _apply_ranges(labor, selected)
        labor["unknowns"] = unknowns
    else:
        _null_labor(labor)
        labor["unknowns"] = unknowns
    for row in labor.get("breakdown", []):
        row.setdefault("reason", "共通の架空Simulator計算結果")
        row.setdefault("status", "proposed")
    approvals = [
        {"operation_key": row.get("operation_id"), **row["approval"]}
        for row in labor.get("breakdown", []) if isinstance(row.get("approval"), dict)
    ]
    status = "missing-required" if blocking else ("partial" if unknowns else "proposed")
    return {
        "engine_id": ENGINE_ID,
        "rule_version": version,
        "status": status,
        "labor": labor,
        "trace": trace,
        "operation_keys": list(dict.fromkeys(ast["operation_id"] for ast in selected.values())),
        "approvals": approvals,
        "simulator_notice": SIMULATOR_NOTICE,
    }
