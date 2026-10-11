"""E07: a hash-linked validation, normalization, expansion and audit pipeline."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite
from typing import Any

from .contract import reference_labor, validate_core_contract

ENGINE_ID = "e07_pipeline"
RULE_VERSION = "e07-validation-pipeline-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_REQUIRED = {"base_service", "included_carry", "replacement_carry", "snow_melt",
             "penetrant_wait", "parts_wait", "wash"}
_WAIT = {"snow_melt", "penetrant_wait", "parts_wait"}
_KNOWN = _REQUIRED | {"rotor_seizure"}


@dataclass(frozen=True)
class StageResult:
    input_hash: str
    issues: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_nonnegative(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and value >= 0)


def validate_stage(scenario_input: Any) -> StageResult:
    issues: list[str] = []
    rows: list[dict[str, Any]] = []
    if not isinstance(scenario_input, dict):
        return StageResult(_hash(scenario_input), ("scenario_input:object_required",), ())
    scenario = scenario_input
    if scenario.get("basis_unit") != "person_hour":
        issues.append("basis_unit:person_hour_required")
    if not isinstance(scenario.get("basis_definition"), str) or not scenario["basis_definition"].strip():
        issues.append("basis_definition:required")
    top_count = scenario.get("person_count")
    if top_count is not None and (isinstance(top_count, bool) or not isinstance(top_count, int) or top_count < 0):
        issues.append("person_count:finite_nonnegative_integer_required")
    for time_key in ("duration_hours", "waiting_hours"):
        value = scenario.get(time_key)
        if value is not None and not _finite_nonnegative(value):
            issues.append(f"{time_key}:finite_nonnegative_required")
    base_hours = scenario.get("base_hours")
    if isinstance(base_hours, dict) and base_hours.get("value") is not None and not _finite_nonnegative(base_hours["value"]):
        issues.append("base_hours:value_must_be_finite_nonnegative")
    fields = scenario.get("fields")
    if not isinstance(fields, dict):
        issues.append("fields:object_required")
        fields = {}
    for key in ("work_scope", "included_operations"):
        obs = fields.get(key)
        if not isinstance(obs, dict) or obs.get("status") not in {"confirmed", "declared"} or obs.get("value") is None:
            issues.append(f"{key}:confirmed_value_required")
    included = fields.get("included_operations", {}).get("value") if isinstance(fields.get("included_operations"), dict) else None
    if isinstance(included, list):
        unknown_scope = [key for key in included if key not in {"remove_install", "rust_observation", "snow_removal"}]
        if unknown_scope:
            issues.append("included_operations:unknown_unit_or_scope_key")
        if not {"remove_install", "rust_observation", "snow_removal"}.issubset(set(included)):
            issues.append("included_operations:required_scope_keys_missing")
    operations = scenario.get("operations")
    if not isinstance(operations, list):
        issues.append("operations:list_required")
        operations = []
    seen: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for index, op in enumerate(operations):
        prefix = f"operations[{index}]"
        if not isinstance(op, dict):
            issues.append(f"{prefix}:object_required")
            continue
        op_id = op.get("operation_id")
        if not isinstance(op_id, str) or op_id not in _KNOWN:
            issues.append(f"{prefix}:unknown_operation_id")
            continue
        if op_id in seen:
            issues.append(f"{op_id}:duplicate_operation_id")
        seen.add(op_id)
        by_id[op_id] = op
        for time_key in ("hours", "duration_hours", "elapsed_hours", "hours_per_person"):
            value = op.get(time_key)
            if time_key in op and value is not None and not _finite_nonnegative(value):
                issues.append(f"{op_id}:{time_key}_must_be_finite_nonnegative")
        expected_unit = "elapsed_hours" if op_id in _WAIT else "person_hours"
        if op.get("unit") not in (None, expected_unit):
            issues.append(f"{op_id}:unit_mismatch_expected_{expected_unit}")
        if op_id in _WAIT:
            duration = op.get("elapsed_hours", op.get("duration_hours", op.get("hours")))
            if not any(key in op for key in ("elapsed_hours", "duration_hours", "hours")):
                duration = None
            if "elapsed_hours" in op and op["elapsed_hours"] is None:
                duration = None
            if duration is None and op_id != "parts_wait":
                issues.append(f"{op_id}:elapsed_hours_required_finite_nonnegative")
            elif duration is not None and not _finite_nonnegative(duration):
                issues.append(f"{op_id}:elapsed_hours_required_finite_nonnegative")
            if op.get("person_count", 0) not in (0, None):
                issues.append(f"{op_id}:wait_person_count_must_be_zero")
        elif op_id == "replacement_carry":
            count, per_person = op.get("person_count"), op.get("hours_per_person")
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                issues.append("replacement_carry:person_count_positive_integer_required")
            if not _finite_nonnegative(per_person):
                issues.append("replacement_carry:hours_per_person_must_be_finite_nonnegative")
        elif op_id == "rotor_seizure":
            pass  # Condition width and its audit are checked by the canonical calculator.
        else:
            hours = op.get("hours", op.get("duration_hours"))
            if not any(key in op for key in ("hours", "duration_hours")):
                hours = None
            if "hours" in op and op["hours"] is None:
                hours = None
            if hours is None or not _finite_nonnegative(hours):
                issues.append(f"{op_id}:hours_required_finite_nonnegative")
            count = op.get("person_count")
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                issues.append(f"{op_id}:person_count_positive_integer_required")
            if op_id == "base_service" and op.get("deduplicated") is not True:
                issues.append("base_service:deduplicated_approval_required")
            if op_id == "base_service" and "hours" not in op:
                issues.append("base_service:hours_required_finite_nonnegative")
            if op_id == "included_carry" and op.get("included_in_base") is not True:
                issues.append("included_carry:included_status_required")
    for op_id in sorted(_REQUIRED - seen):
        issues.append(f"{op_id}:required_operation_missing")
    for op_id, op in by_id.items():
        rows.append({"operation_id": op_id, "unit": "elapsed_hours" if op_id in _WAIT else "person_hours",
                     "present": True, "status": op.get("status", "unknown")})
    if by_id.get("parts_wait", {}).get("stock_checked") is not True:
        issues.append("parts_wait:stock_confirmation_required")
    rotor_obs = fields.get("rotor_seizure_hours")
    if isinstance(rotor_obs, dict) and rotor_obs.get("value") is not None:
        value = rotor_obs["value"]
        if (not isinstance(value, dict) or set(value) != {"low", "typical", "high"}
                or any(not _finite_nonnegative(value.get(key)) for key in ("low", "typical", "high"))
                or not value["low"] <= value["typical"] <= value["high"]):
            issues.append("rotor_seizure_hours:invalid_person_hour_range")
    return StageResult(_hash(scenario_input), tuple(dict.fromkeys(issues)), tuple(rows))


def normalize_stage(scenario_input: dict[str, Any]) -> StageResult:
    """Canonicalize supported duration aliases while preserving missing wait time."""
    normalized = deepcopy(scenario_input)
    rows: list[dict[str, Any]] = []
    for op in normalized.get("operations", []):
        op_id = op.get("operation_id")
        before: dict[str, Any] = {}
        if op_id in _WAIT:
            if "elapsed_hours" not in op and "duration_hours" in op:
                op["elapsed_hours"] = op.pop("duration_hours")
                before["duration_hours"] = op["elapsed_hours"]
            elif "elapsed_hours" not in op and "hours" in op:
                op["elapsed_hours"] = op["hours"]
                before["hours"] = op["hours"]
            op.setdefault("hours", 0.0)
            op.setdefault("person_count", 0)
        else:
            if "hours" not in op and "duration_hours" in op:
                op["hours"] = op["duration_hours"]
                before["duration_hours"] = op["hours"]
        rows.append({"operation_id": op_id, "normalized": deepcopy(op), "aliases_resolved": before})
    return StageResult(_hash(scenario_input), (), tuple(rows))


def expand_stage(normalized_scenario: dict[str, Any]) -> tuple[StageResult, dict[str, Any]]:
    """Expand per-person work into explicit person-hour rows used by summation."""
    expanded = deepcopy(normalized_scenario)
    rows: list[dict[str, Any]] = []
    for op in expanded.get("operations", []):
        op_id = op.get("operation_id")
        if op_id == "replacement_carry":
            count = op["person_count"]
            per_person = op["hours_per_person"]
            total = round(count * per_person, 10)
            op["_expanded_person_hours"] = total
            rows.append({"operation_id": op_id, "person_count": count,
                         "duration_hours": per_person, "person_hours": total,
                         "unit": "person_hours"})
        elif op_id in _WAIT:
            rows.append({"operation_id": op_id, "person_count": 0,
                         "elapsed_hours": op.get("elapsed_hours"),
                         "person_hours": 0.0, "unit": "elapsed_hours"})
        else:
            count = op["person_count"]
            hours = op.get("hours", op.get("duration_hours"))
            # base_service.hours is already a total person-hour basis. Other
            # explicit work durations are per-person and expand by headcount.
            total = hours if op_id == "base_service" else round(hours * count, 10)
            op["_expanded_person_hours"] = total
            rows.append({"operation_id": op_id, "person_count": count,
                         "duration_hours": hours, "person_hours": total,
                         "unit": "person_hours"})
    return StageResult(_hash(normalized_scenario), (), tuple(rows)), expanded


def sum_stage(expanded_scenario: dict[str, Any]) -> tuple[StageResult, dict[str, Any], list[dict[str, Any]], list[str]]:
    labor, rows, issues = reference_labor(expanded_scenario)
    if not issues or all(item.endswith(":elapsed_duration_unknown") for item in issues):
        operations = {op.get("operation_id"): op for op in expanded_scenario.get("operations", [])}
        lines = {row.get("operation_id"): row for row in labor.get("breakdown", [])}
        replacement = operations["replacement_carry"]
        total = round(replacement["hours_per_person"] * replacement["person_count"], 10)
        if lines.get("replacement_carry"):
            lines["replacement_carry"]["hours"] = {key: total for key in ("low", "typical", "high")}
        for row in rows:
            if row.get("operation_id") == "replacement_carry":
                row["hours"] = {key: total for key in ("low", "typical", "high")}
        base = operations["base_service"]["hours"]  # already a total person-hour basis
        included = operations["included_carry"]["hours"]
        wash = operations["wash"]
        wash_total = round(wash["hours"] * wash["person_count"], 10)
        rotor = lines.get("rotor_seizure", {}).get("hours", {"low": 0, "typical": 0, "high": 0})
        labor["person_hours"] = {
            key: round(base - included + total + wash_total + rotor[key], 10)
            for key in ("low", "typical", "high")
        }
        if any(item.endswith(":elapsed_duration_unknown") for item in issues):
            labor["elapsed_hours"] = {"low": None, "typical": None, "high": None}
        else:
            wait_elapsed = sum(float(op.get("elapsed_hours", op.get("duration_hours", op.get("hours"))))
                               for op in operations.values() if op.get("operation_id") in _WAIT)
            handling_elapsed = replacement["hours_per_person"]
            labor["elapsed_hours"] = {
                key: round(base - included + handling_elapsed + wash["hours"] + rotor[key] + wait_elapsed, 10)
                for key in ("low", "typical", "high")
            }
    return StageResult(_hash(expanded_scenario), tuple(issues), tuple(deepcopy(rows))), labor, rows, issues


def audit_stage(labor: dict[str, Any], input_hash: str) -> StageResult:
    issues = validate_core_contract(labor)
    return StageResult(input_hash, tuple(issues), tuple(deepcopy(labor.get("breakdown", []))))


def _stopped_labor(issues: list[str]) -> dict[str, Any]:
    nulls = {"low": None, "typical": None, "high": None}
    return {"person_hours": dict(nulls), "elapsed_hours": dict(nulls), "breakdown": [],
            "unknowns": list(dict.fromkeys(issues))}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Execute the E07 pipeline, preserving intermediate evidence and input hashes."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else scenario_input
    version = scenario.get("rule_version", RULE_VERSION) if isinstance(scenario, dict) else RULE_VERSION
    trace: list[dict[str, Any]] = []
    validate = validate_stage(scenario)
    trace.append({"stage": "validate", **validate.to_dict()})
    if validate.issues:
        labor = _stopped_labor(list(validate.issues))
        return _result(version, "missing-required", labor, trace, [])

    normalized = normalize_stage(scenario)
    trace.append({"stage": "normalize", **normalized.to_dict()})
    normalized_scenario = _normalize_payload(scenario)
    expanded_result, expanded = expand_stage(normalized_scenario)
    trace.append({"stage": "expand", **expanded_result.to_dict()})
    summed, labor, rows, sum_issues = sum_stage(expanded)
    trace.append({"stage": "sum", **summed.to_dict()})
    if sum_issues:
        blocking = [item for item in sum_issues if not item.endswith(":elapsed_duration_unknown")]
        if blocking:
            labor = _stopped_labor(list(sum_issues))
    audit = audit_stage(labor, summed.input_hash)
    trace.append({"stage": "audit", **audit.to_dict()})
    audit_issues = list(audit.issues)
    if audit_issues:
        labor = _stopped_labor([f"audit:{issue}" for issue in audit_issues])
    unknowns = list(labor.get("unknowns", []))
    status = "missing-required" if any(not x.endswith(":elapsed_duration_unknown") for x in unknowns) else (
        "partial" if unknowns else "proposed")
    operation_keys = list(dict.fromkeys(row.get("operation_id", row.get("operation", "")) for row in labor.get("breakdown", [])))
    approvals = [row["approval"] for row in labor.get("breakdown", []) if isinstance(row.get("approval"), dict)]
    return _result(version, status, labor, trace, operation_keys, approvals)


def _normalize_payload(scenario: dict[str, Any]) -> dict[str, Any]:
    """Materialize the exact normalization stage result for the next stage."""
    value = deepcopy(scenario)
    for op in value.get("operations", []):
        if op.get("operation_id") in _WAIT:
            if "elapsed_hours" not in op:
                if "duration_hours" in op:
                    op["elapsed_hours"] = op.pop("duration_hours")
                elif "hours" in op:
                    op["elapsed_hours"] = op["hours"]
            op.setdefault("hours", 0.0)
            op.setdefault("person_count", 0)
        else:
            if "hours" not in op and "duration_hours" in op:
                op["hours"] = op["duration_hours"]
    return value


def _result(version: str, status: str, labor: dict[str, Any], trace: list[dict[str, Any]],
            operation_keys: list[str], approvals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status,
            "labor": labor, "trace": trace, "operation_keys": operation_keys,
            "approvals": approvals or [], "simulator_notice": SIMULATOR_NOTICE}
