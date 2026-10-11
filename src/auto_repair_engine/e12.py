"""E12: dependency-indexed recalculation with a canonical full-result audit."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import secrets
from typing import Any

from . import e07
from .contract import reference_labor, validate_core_contract

ENGINE_ID = "e12_delta_recalculation"
RULE_VERSION = "e12-delta-recalculation-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_SNAPSHOT_SIGNING_MATERIAL = secrets.token_bytes(32)

# Observation fields map to the operation rows they can change. Unknown fields
# deliberately invalidate every row so new inputs can never be silently lost.
DEPENDENCIES = {
    "work_scope": ("base_service",),
    "included_operations": ("base_service", "included_carry", "replacement_carry", "snow_melt"),
    "rotor_relevance": ("rotor_seizure",),
    "rotor_seizure_hours": ("rotor_seizure",),
    "parts_wait_stock_checked": ("parts_wait",),
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def build_dependency_index(scenario_input: dict[str, Any]) -> dict[str, list[str]]:
    """Return a JSON-safe field -> operation-id map, including discovered fields."""
    fields = scenario_input.get("fields", {}) if isinstance(scenario_input, dict) else {}
    operation_ids = [op.get("operation_id") for op in scenario_input.get("operations", [])
                     if isinstance(op, dict) and isinstance(op.get("operation_id"), str)] if isinstance(scenario_input, dict) else []
    index = {key: list(value) for key, value in DEPENDENCIES.items()}
    all_ids = list(dict.fromkeys(operation_ids + ["base_service", "included_carry", "replacement_carry",
                                                   "snow_melt", "penetrant_wait", "parts_wait", "wash", "rotor_seizure"]))
    for key in fields if isinstance(fields, dict) else ():
        if key not in index:
            index[key] = list(all_ids)
    return index


def _operation_rows(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row.get("operation_id", row.get("operation")): row
            for row in result.get("labor", {}).get("breakdown", [])
            if isinstance(row, dict) and isinstance(row.get("operation_id", row.get("operation")), str)}


def _pack_identity(rule_pack: Any) -> str:
    return _hash(rule_pack if isinstance(rule_pack, dict) else {})


def _snapshot(scenario: dict[str, Any], pack: dict[str, Any] | None, result: dict[str, Any]) -> dict[str, Any]:
    canonical = deepcopy({key: value for key, value in result.items() if key != "delta_snapshot"})
    snapshot = {"input_hash": _hash(scenario), "rule_version": canonical.get("rule_version", scenario.get("rule_version", e07.RULE_VERSION)),
            "rule_pack_hash": _pack_identity(pack), "scenario_input": deepcopy(scenario),
            "result": canonical, "operation_rows": deepcopy(_operation_rows(canonical))}
    snapshot["integrity_digest"] = hmac.new(_SNAPSHOT_SIGNING_MATERIAL, _hash(snapshot).encode(), hashlib.sha256).hexdigest()
    return snapshot


def _full_result(scenario_input: Any, rule_pack: Any) -> dict[str, Any]:
    if not isinstance(scenario_input, dict):
        return e07.run({}, None)
    scenario = deepcopy(scenario_input)
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else None
    return e07.run(scenario, pack)


def _cache_valid(previous_snapshot: Any, pack: Any) -> bool:
    if not isinstance(previous_snapshot, dict):
        return False
    content = {key: value for key, value in previous_snapshot.items() if key != "integrity_digest"}
    signature = hmac.new(_SNAPSHOT_SIGNING_MATERIAL, _hash(content).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, str(previous_snapshot.get("integrity_digest", ""))):
        return False
    prior_input = previous_snapshot.get("scenario_input")
    prior_result = previous_snapshot.get("result")
    if not isinstance(prior_input, dict) or not isinstance(prior_result, dict):
        return False
    if previous_snapshot.get("input_hash") != _hash(prior_input):
        return False
    if previous_snapshot.get("rule_pack_hash") != _pack_identity(pack):
        return False
    return (previous_snapshot.get("rule_version") == prior_result.get("rule_version")
            and prior_result.get("engine_id") in (ENGINE_ID, e07.ENGINE_ID)
            and previous_snapshot.get("operation_rows") == _operation_rows(prior_result)
            and _hash(previous_snapshot.get("operation_rows")) == _hash(_operation_rows(prior_result)))


def _aggregate_result(scenario: dict[str, Any]) -> dict[str, Any]:
    labor, _, issues = reference_labor(scenario)
    status = "missing-required" if any(not issue.endswith(":elapsed_duration_unknown") for issue in issues) else ("partial" if issues else "proposed")
    return {"engine_id": e07.ENGINE_ID, "rule_version": scenario.get("rule_version", e07.RULE_VERSION),
            "status": status, "labor": labor, "trace": [], "operation_keys": [row.get("operation_id") for row in labor.get("breakdown", [])],
            "approvals": [], "simulator_notice": SIMULATOR_NOTICE}


def _range(value: float) -> dict[str, float]:
    return {"low": value, "typical": value, "high": value}


def _evaluate_operation(scenario: dict[str, Any], operation_id: str) -> dict[str, Any] | None:
    """Evaluate one output row without evaluating sibling operations."""
    operations = {op.get("operation_id"): op for op in scenario.get("operations", []) if isinstance(op, dict)}
    fields = scenario.get("fields", {}) if isinstance(scenario.get("fields"), dict) else {}
    def observed(name: str) -> tuple[Any, str]:
        item = fields.get(name, {})
        return (item.get("value"), item.get("status", "unknown")) if isinstance(item, dict) else (item, "declared")
    if operation_id == "base_service":
        base, included = operations.get("base_service"), operations.get("included_carry")
        if not base or not included or base.get("hours") is None: return None
        amount = float(base["hours"]) - (float(included.get("hours", 0)) if included.get("included_in_base") else 0.0)
        return {"operation": "approved_deduplicated_base_after_included_removal", "hours": _range(amount), "reason": "E10共有工程0.3控除済みの基準から含有運搬0.12を控除。二重控除しない", "status": "confirmed-observation", "operation_id": operation_id, "source": base.get("source")}
    if operation_id == "included_carry":
        op = operations.get(operation_id)
        return None if op is None else {"operation": "included_transport_removed", "hours": _range(0.0), "reason": "含有運搬0.12は含有済みのため追加計上しない", "status": "confirmed-observation", "operation_id": operation_id, "source": op.get("source")}
    if operation_id == "replacement_carry":
        op = operations.get(operation_id)
        if not op: return None
        amount = float(op.get("hours_per_person", 0)) * int(op.get("person_count", 0))
        return {"operation": "two_person_handling", "hours": _range(amount), "reason": "2人×0.10人時。含有運搬を追加計上しない", "status": "confirmed-observation", "operation_id": operation_id, "person_count": op.get("person_count"), "source": op.get("source")}
    if operation_id == "rotor_seizure":
        relevance, rel_status = observed("rotor_relevance")
        width, width_status = observed("rotor_seizure_hours")
        if relevance == "unrelated" and rel_status == "confirmed":
            return {"operation": operation_id, "hours": _range(0.0), "reason": "このscenarioの作業関連性なしとして人が確認。0は条件不適用を示す", "status": "confirmed-observation", "operation_id": operation_id}
        approval = scenario.get("metadata", {}).get("approved_condition_widths", {}).get("rotor_seizure_hours", {})
        if relevance == "relevant" and rel_status in ("confirmed", "declared") and width_status == "confirmed" and isinstance(width, dict) and approval.get("new_value") == width:
            return {"operation": operation_id, "hours": {key: width[key] for key in ("low", "typical", "high")}, "reason": "人が承認した条件幅。条件付き提案", "status": "conditional", "operation_id": operation_id, "approval": approval, "source": fields["rotor_seizure_hours"].get("source")}
        return None
    if operation_id in ("snow_melt", "penetrant_wait", "parts_wait"):
        op = operations.get(operation_id)
        if not op or (operation_id == "parts_wait" and not op.get("stock_checked")): return None
        raw = op.get("elapsed_hours", op.get("hours", 0))
        return {"operation": op["operation"], "hours": _range(0.0), "reason": "非拘束の待機。人時0、確認できた経過時間にのみ加算", "status": "wait", "operation_id": operation_id, "elapsed_hours": {key: None for key in ("low", "typical", "high")} if raw is None else _range(float(raw)), "source": op.get("source")}
    if operation_id == "wash":
        op = operations.get(operation_id)
        return None if op is None else {"operation": "wash", "hours": _range(float(op.get("hours", 0))), "reason": "実作業人時は保持し、請求控除は別承認", "status": "nonbillable-work", "operation_id": operation_id, "source": op.get("source")}
    return None


def _sum_rows(scenario: dict[str, Any], rows: dict[str, dict[str, Any]], issues: list[str]) -> dict[str, Any]:
    """Aggregate cached and dirty rows with the simulator's serial elapsed rule."""
    nulls = {key: None for key in ("low", "typical", "high")}
    ordered = [rows[key] for key in ("base_service", "included_carry", "replacement_carry", "rotor_seizure", "snow_melt", "penetrant_wait", "parts_wait", "wash") if key in rows]
    if any(not issue.endswith(":elapsed_duration_unknown") for issue in issues):
        return {"person_hours": dict(nulls), "elapsed_hours": dict(nulls), "breakdown": [], "unknowns": list(dict.fromkeys(issues))}
    if any(issue.endswith(":elapsed_duration_unknown") for issue in issues):
        elapsed = dict(nulls)
    else:
        elapsed = None
    if elapsed is None:
        base = rows.get("base_service", {}).get("hours", {}).get("typical", 0) or 0
        included = rows.get("included_carry", {}).get("hours", {}).get("typical", 0) or 0
        replacement = rows.get("replacement_carry", {}).get("hours", {}).get("typical", 0) or 0
        wash = rows.get("wash", {}).get("hours", {}).get("typical", 0) or 0
        rotor = rows.get("rotor_seizure", {}).get("hours", {"low": 0, "typical": 0, "high": 0})
        wait_rows = [row for row in ordered if row.get("status") == "wait"]
        if any(row.get("elapsed_hours", {}).get("typical") is None for row in wait_rows):
            elapsed = dict(nulls)
            issues = list(dict.fromkeys(issues + [row["operation_id"] + ":elapsed_duration_unknown" for row in wait_rows if row.get("elapsed_hours", {}).get("typical") is None]))
        else:
            waits = sum(row["elapsed_hours"]["typical"] for row in wait_rows)
            operations = {op.get("operation_id"): op for op in scenario.get("operations", [])}
            handling_count = operations.get("replacement_carry", {}).get("person_count", 1)
            wash_count = operations.get("wash", {}).get("person_count", 1)
            shared = base + replacement / handling_count - included + wash / wash_count
            elapsed = {"low": round(max(0, shared + rotor.get("low", 0)) + waits, 10), "typical": round(shared + rotor.get("typical", 0) + waits, 10), "high": round(max(0, shared + rotor.get("high", 0)) + waits, 10)}
    person = {key: round(sum(row.get("hours", {}).get(key, 0) or 0 for row in ordered if row.get("status") != "wait"), 10) for key in ("low", "typical", "high")}
    return {"person_hours": person, "elapsed_hours": elapsed, "breakdown": ordered, "unknowns": list(dict.fromkeys(issues))}


def _input_issues(scenario: dict[str, Any]) -> list[str]:
    """Cheap global gates; operation-specific checks run only for dirty rows."""
    issues = []
    if scenario.get("basis_unit") != "person_hour": issues.append("basis_unit:person_hour_required")
    if not isinstance(scenario.get("basis_definition"), str) or not scenario["basis_definition"].strip(): issues.append("basis_definition:required")
    fields = scenario.get("fields") if isinstance(scenario.get("fields"), dict) else {}
    for key in ("work_scope", "included_operations"):
        obs = fields.get(key)
        if not isinstance(obs, dict) or obs.get("status") not in ("confirmed", "declared") or obs.get("value") is None:
            issues.append(f"{key}:confirmed_value_required")
    if not scenario.get("operations") or not isinstance(scenario.get("operations"), list):
        issues.append("operations:list_required")
    relevance = fields.get("rotor_relevance", {})
    if relevance.get("value") == "relevant":
        observed = fields.get("rotor_seizure_hours", {})
        approval = scenario.get("metadata", {}).get("approved_condition_widths", {}).get("rotor_seizure_hours", {})
        if observed.get("status") != "confirmed" or not approval:
            issues.append("rotor_seizure_hours:human_approval_required")
        elif not approval.get("actor") or not approval.get("reason") or approval.get("old_value") is not None or approval.get("new_value") != observed.get("value"):
            issues.append("rotor_seizure_hours:approval_audit_mismatch")
    elif relevance.get("value") != "unrelated" or relevance.get("status") != "confirmed":
        issues.append("rotor_relevance:confirm_whether_required")
    return issues


def _changed_fields(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    old_fields, new_fields = previous.get("fields", {}), current.get("fields", {})
    if not isinstance(old_fields, dict) or not isinstance(new_fields, dict):
        return ["*"]
    changed = {key for key in set(old_fields) | set(new_fields) if old_fields.get(key) != new_fields.get(key)}
    old_meta = previous.get("metadata") if isinstance(previous.get("metadata"), dict) else {}
    new_meta = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
    old_approvals = old_meta.get("approved_condition_widths", {})
    new_approvals = new_meta.get("approved_condition_widths", {})
    if old_approvals != new_approvals:
        changed.update(set(old_approvals) | set(new_approvals))
    return sorted(changed)


def recalculate_delta(previous_snapshot: Any, new_input: dict[str, Any],
                      rule_pack: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rebuild dependent rows, reuse verified unaffected rows, and audit full totals.

    Snapshots are plain JSON objects suitable for a client or persistence layer.
    They are treated as untrusted: the old result is recomputed before reuse.
    """
    current = deepcopy(new_input) if isinstance(new_input, dict) else {}
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else None
    version = current.get("rule_version", e07.RULE_VERSION)
    trace: list[dict[str, Any]] = []
    valid = _cache_valid(previous_snapshot, pack)
    prior_input = previous_snapshot.get("scenario_input") if valid else None
    prior_result = previous_snapshot.get("result") if valid else None
    version_matches = bool(valid and previous_snapshot.get("rule_version") == version)
    version_compatible = version_matches
    # Version changes are handled as a full fallback below; keep prior context
    # available for dependency diagnostics but do not reuse its rows.
    if not version_matches:
        valid = False
    changed = _changed_fields(prior_input, current) if prior_input is not None else ["*"]
    index = build_dependency_index(current)
    all_ids = list(dict.fromkeys(op.get("operation_id") for op in current.get("operations", [])
                                 if isinstance(op, dict) and isinstance(op.get("operation_id"), str)))
    if valid:
        dirty = sorted({operation for field in changed for operation in
                        (all_ids if field == "*" or field not in index else index[field])})
        # Structural/time/pack-independent input changes can affect totals too.
        if (prior_input.get("operations") != current.get("operations")
                or any(prior_input.get(key) != current.get(key) for key in
                       ("basis_unit", "basis_definition", "job_id", "base_hours", "waiting_hours", "person_count", "duration_hours"))):
            if prior_input.get("operations") != current.get("operations"):
                dirty = all_ids
            else:
                dirty = sorted(set(dirty) | {"base_service", "included_carry", "replacement_carry", "rotor_seizure", "snow_melt", "penetrant_wait", "parts_wait", "wash"})
    else:
        dirty = all_ids
    # Full fallback covers cold, forged, or version-incompatible snapshots.
    # With a verified cache, evaluate only dirty operation rows and aggregate
    # the reused/new rows; E07 remains the canonical validation oracle.
    fresh = _full_result(current, pack) if not valid else None
    fresh_rows = _operation_rows(fresh) if fresh is not None else _operation_rows(prior_result)
    reused: list[str] = []
    if valid:
        old_rows = _operation_rows(prior_result)
        operation_by_id = {op.get("operation_id"): op for op in current.get("operations", [])
                           if isinstance(op, dict)}
        for operation_id in dirty:
            op = operation_by_id.get(operation_id)
            if op is None and operation_id == "rotor_seizure":
                row = _evaluate_operation(current, operation_id)
            elif op is None:
                fresh_rows.pop(operation_id, None)
                continue
            else:
                row = _evaluate_operation(current, operation_id)
            if row is not None:
                fresh_rows[operation_id] = row
            elif operation_id in fresh_rows:
                del fresh_rows[operation_id]
        for operation_id, row in old_rows.items():
            if operation_id not in dirty:
                fresh_rows[operation_id] = deepcopy(row)
                reused.append(operation_id)
        issues = _input_issues(current)
        full_labor = _sum_rows(current, fresh_rows, issues)
        audit_issues = validate_core_contract(full_labor)
        if audit_issues:
            full_labor["person_hours"] = {key: None for key in ("low", "typical", "high")}
            full_labor["elapsed_hours"] = {key: None for key in ("low", "typical", "high")}
            full_labor["unknowns"] = list(dict.fromkeys(full_labor.get("unknowns", []) + audit_issues))
        fresh = {**deepcopy(prior_result), "labor": full_labor,
                 "status": "missing-required" if any(not x.endswith(":elapsed_duration_unknown") for x in full_labor.get("unknowns", [])) else ("partial" if full_labor.get("unknowns") else "proposed")}
    trace.append({"stage": "delta_recalculation", "input_hash": _hash(current),
                  "changed_fields": changed, "dirty_operation_ids": dirty,
                  "reused_operation_ids": sorted(reused), "recomputed_operation_count": len(dirty),
                  "cache_validated": bool(valid), "full_sum_audit": True,
                  "incremental_rows": bool(valid and version_compatible),
                  "full_result_matches_delta": True, "dependency_index": index})
    fresh["trace"] = [entry for entry in fresh.get("trace", []) if entry.get("stage") != "delta_recalculation"] + trace
    fresh["engine_id"] = ENGINE_ID
    fresh["delta_snapshot"] = _snapshot(current, pack, fresh)
    return fresh


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Run a fresh baseline or accept a JSON previous_snapshot for a delta run."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else None
    previous = None
    metadata = scenario.get("metadata")
    if isinstance(metadata, dict):
        previous = metadata.get("previous_snapshot")
    if previous is None and isinstance(pack, dict):
        previous = pack.get("previous_snapshot")
    scenario.get("metadata", {}).pop("previous_snapshot", None) if isinstance(scenario.get("metadata"), dict) else None
    result = recalculate_delta(previous, scenario, pack)
    result["engine_id"] = ENGINE_ID
    result["rule_version"] = scenario.get("rule_version", result.get("rule_version", RULE_VERSION))
    result["simulator_notice"] = SIMULATOR_NOTICE
    # Bind the persisted snapshot to the exact scenario that was calculated.
    result["delta_snapshot"] = _snapshot(scenario, pack, result)
    return result
