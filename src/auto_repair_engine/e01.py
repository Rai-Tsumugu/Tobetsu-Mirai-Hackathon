"""E01: fictional typed static-table labor estimator."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import reference_labor


@dataclass(frozen=True)
class RuleRow:
    job_id: str
    operation_key: str
    field_key: str | None
    match_value: Any
    source: str
    reason: str


# These rows describe lookup keys. Scenario observations supply all numerical
# values; no production rates or vehicle facts are embedded in this table.
STATIC_TABLE: tuple[RuleRow, ...] = (
    RuleRow("front_brake_service", "base_service", "work_scope", "front_brake_service", "fictional_static_table:E01/base", "Deduplicated base labor from the fictional scenario."),
    RuleRow("front_brake_service", "replacement_carry", "included_operations", "remove_install", "fictional_static_table:E01/carry", "Replaces included carry with two-person handling."),
    RuleRow("front_brake_service", "rust_observation", "included_operations", "rust_observation", "fictional_static_table:E01/rust", "Rust observation is an explicitly included scope key."),
    RuleRow("front_brake_service", "snow_melt", "included_operations", "snow_removal", "fictional_static_table:E01/wait", "Confirmed waiting contributes elapsed time only."),
    RuleRow("front_brake_service", "penetrant_wait", "work_scope", "front_brake_service", "fictional_static_table:E01/wait", "Confirmed waiting contributes elapsed time only."),
    RuleRow("front_brake_service", "parts_wait", "parts_wait_stock_checked", True, "fictional_static_table:E01/wait", "Stock-checked wait is zero in this fictional fixture."),
    RuleRow("front_brake_service", "wash", "work_scope", "front_brake_service", "fictional_static_table:E01/wash", "Performed wash remains work and is marked nonbillable."),
    RuleRow("front_brake_service", "rotor_seizure", "rotor_relevance", "relevant", "fictional_static_table:E01/condition", "Rotor condition width requires human approval."),
    RuleRow("front_brake_service", "rotor_unrelated", "rotor_relevance", "unrelated", "fictional_static_table:E01/condition", "Human-confirmed unrelated condition is excluded from this scope."),
)
TABLE_VERSION = "e01-static-table-v1"
REQUIRED_INCLUDED_OPERATIONS = frozenset({"remove_install", "rust_observation", "snow_removal"})


def _obs(scenario: dict[str, Any], key: str) -> dict[str, Any]:
    raw = (scenario.get("fields") or {}).get(key)
    if isinstance(raw, dict) and "status" in raw:
        return raw
    return {"value": raw, "status": "declared" if raw is not None else "unknown", "source": None}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict:
    """Select typed table rows by job and observed scope; return a proposed envelope."""
    scenario = scenario_input
    engine_id = "e01_static_table"
    # rule_version belongs to the shared scenario calculation. The static
    # lookup has its own immutable version; custom packs cannot silently alter it.
    rule_version = scenario.get("rule_version", "fictional-rule-v1")
    job_id = scenario.get("job_id")
    fields = scenario.get("fields") or {}
    selected: list[RuleRow] = []
    trace: list[dict[str, Any]] = [{"event": "table_loaded", "table": "STATIC_TABLE", "table_version": TABLE_VERSION, "source": "fictional_static_table:E01", "row_count": len(STATIC_TABLE)}]
    gate_unknowns: list[str] = []
    if rule_pack is not None:
        if rule_pack.get("table_version") != TABLE_VERSION:
            gate_unknowns.append("rule_pack:unbound_to_static_table_version")
        if rule_pack.get("rules"):
            gate_unknowns.append("rule_pack:dynamic_rules_unsupported")
    for row in STATIC_TABLE:
        if row.job_id != job_id:
            continue
        if row.field_key is None:
            selected.append(row)
            continue
        observed = _obs(scenario, row.field_key)
        val = observed.get("value")
        valid_status = observed.get("status") not in (None, "unknown", "assumed")
        matched = valid_status and ((val == row.match_value) or (row.field_key == "included_operations" and isinstance(val, list) and row.match_value in val))
        if matched:
            selected.append(row)
            trace.append({"event": "row_applied", "table": "STATIC_TABLE", "table_version": TABLE_VERSION, "operation_key": row.operation_key, "job_id": row.job_id, "field_key": row.field_key, "matched_value": val, "static_table_source": row.source, "observation_source": observed.get("source"), "observation_status": observed.get("status"), "confirmed_at": observed.get("confirmed_at")})
        elif row.field_key in {"work_scope", "included_operations"}:
            gate_unknowns.append(f"{row.field_key}:static_table_eligibility_failed")
    scope_obs = _obs(scenario, "work_scope")
    if scope_obs.get("value") != "front_brake_service" or scope_obs.get("status") in (None, "unknown", "assumed"):
        gate_unknowns.append("work_scope:confirmed_exact_match_required")
    included_obs = _obs(scenario, "included_operations")
    included_value = included_obs.get("value")
    if (included_obs.get("status") in (None, "unknown", "assumed") or not isinstance(included_value, list)
            or not REQUIRED_INCLUDED_OPERATIONS.issubset(set(included_value))):
        gate_unknowns.append("included_operations:confirmed_required_set_required")
    elif set(included_value) - {row.match_value for row in STATIC_TABLE if row.field_key == "included_operations"}:
        gate_unknowns.append("included_operations:declared_operation_missing_static_table_row")
    rotor_obs = _obs(scenario, "rotor_relevance")
    if rotor_obs.get("value") in {"relevant", "unrelated"} and rotor_obs.get("status") in (None, "unknown", "assumed"):
        gate_unknowns.append("rotor_relevance:confirmed_status_required")
    operations = scenario.get("operations") or []
    if any(op.get("operation_id") == "parts_wait" for op in operations):
        stock_obs = _obs(scenario, "parts_wait_stock_checked")
        if stock_obs.get("value") is not True or stock_obs.get("status") != "confirmed":
            gate_unknowns.append("parts_wait_stock_checked:confirmed_true_required")
    trace.append({"event": "lookup_complete", "job_id": job_id, "matched_operation_keys": [r.operation_key for r in selected]})

    # Numerical calculation and stop semantics are shared across demos. E01
    # contributes only typed-table selection and provenance around this result.
    operation_to_key = {
        "base_service": "base_service", "included_carry": "replacement_carry",
        "replacement_carry": "replacement_carry", "snow_melt": "snow_melt",
        "penetrant_wait": "penetrant_wait", "parts_wait": "parts_wait", "wash": "wash",
    }
    selected_keys_set = {row.operation_key for row in selected}
    filtered_scenario = dict(scenario)
    filtered_scenario["operations"] = []
    for operation in operations:
        operation_id = operation.get("operation_id")
        operation_key = operation_to_key.get(operation_id)
        if operation_key is None:
            gate_unknowns.append(f"{operation_id or 'operation'}:static_table_row_missing")
        elif operation_key not in selected_keys_set:
            gate_unknowns.append(f"{operation_id}:static_table_row_not_matched")
        else:
            filtered_scenario["operations"].append(operation)
    labor, canonical_rows, unknowns = reference_labor(filtered_scenario)
    unknowns = list(dict.fromkeys([*unknowns, *gate_unknowns]))
    blocking_unknowns = [item for item in unknowns if not item.endswith(":elapsed_duration_unknown")]
    if blocking_unknowns:
        null_range = {"low": None, "typical": None, "high": None}
        labor["person_hours"] = dict(null_range)
        labor["elapsed_hours"] = dict(null_range)
        labor["unknowns"] = unknowns
        for row in labor["breakdown"]:
            row["hours"] = dict(null_range)
            if "elapsed_hours" in row:
                row["elapsed_hours"] = dict(null_range)
            row["status"] = "missing-required"
    trace.append({"event": "table_version_pinned", "table": "STATIC_TABLE", "table_version": TABLE_VERSION})
    if not selected:
        unknowns = list(dict.fromkeys([*unknowns, "job_id:unsupported_by_static_table"]))
        blocking_unknowns = list(dict.fromkeys([*blocking_unknowns, "job_id:unsupported_by_static_table"]))
        labor["unknowns"] = unknowns
        labor["person_hours"] = {"low": None, "typical": None, "high": None}
        labor["elapsed_hours"] = {"low": None, "typical": None, "high": None}
        for row in labor["breakdown"]:
            row["hours"] = {"low": None, "typical": None, "high": None}
            if "elapsed_hours" in row:
                row["elapsed_hours"] = {"low": None, "typical": None, "high": None}
            row["status"] = "missing-required"
    for row in labor["breakdown"]:
        op_id = row.get("operation_id")
        if op_id == "rotor_seizure" and rotor_obs.get("value") == "unrelated":
            row["operation_key"] = "rotor_unrelated"
        elif op_id == "included_carry":
            row["operation_key"] = "replacement_carry"
        else:
            row["operation_key"] = op_id if op_id else row["operation"]
        row.setdefault("reason", "Fictional shared contract calculation.")
        row.setdefault("status", "proposed")
    # Output keys are exactly the static-table selections used for this run.
    selected_keys = [r.operation_key for r in selected]
    approvals = [
        {"operation_key": row.get("operation_id"), **row["approval"]}
        for row in labor["breakdown"] if row.get("approval")
    ]
    result_status = "missing-required" if blocking_unknowns else ("partial" if unknowns else "proposed")
    return {"engine_id": engine_id, "rule_version": rule_version, "table_version": TABLE_VERSION, "status": result_status, "labor": labor, "trace": trace, "operation_keys": list(dict.fromkeys(selected_keys)), "approvals": approvals, "simulator_notice": "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"}

