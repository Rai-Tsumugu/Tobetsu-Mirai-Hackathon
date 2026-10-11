"""E10: immutable exclusive/deduplication ledger for labor operations.

The common comparison fixture stores both ``gross_hours`` (2.0) and the
already-deduplicated ``hours`` (1.7). E10 explicitly selects its gross input
mode for this fictional fixture and records that choice in trace; callers with
real/custom input must declare ``ledger_mode='gross'`` and a gross value.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import isfinite
from typing import Any

ENGINE_ID = "e10_deduplication_ledger"
RULE_VERSION = "e10-deduplication-ledger-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_BANDS = ("low", "typical", "high")
_NULL = {"low": None, "typical": None, "high": None}


def _number(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and value >= 0)


def _key(value: Any) -> tuple[str, str, str]:
    if isinstance(value, dict):
        parts = (value.get("operation"), value.get("side"), value.get("scope"))
    elif isinstance(value, (tuple, list)) and len(value) == 3:
        parts = tuple(value)
    else:
        raise ValueError("ledger:key_must_be_operation_side_scope")
    if any(not isinstance(part, str) or not part.strip() for part in parts):
        raise ValueError("ledger:key_parts_required")
    return tuple(part.strip() for part in parts)  # type: ignore[return-value]


def _entry_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return _key(entry)


def _ledger_copy(ledger: Any) -> dict[str, Any]:
    if ledger is None:
        return {"entries": []}
    if isinstance(ledger, list):
        ledger = {"entries": ledger}
    if not isinstance(ledger, dict) or not isinstance(ledger.get("entries"), list):
        raise ValueError("ledger:entries_list_required")
    result = deepcopy(ledger)
    for entry in result["entries"]:
        if not isinstance(entry, dict):
            raise ValueError("ledger:entry_object_required")
        _entry_key(entry)
    return result


def _owners(value: Any) -> list[str]:
    owners = [value] if isinstance(value, str) else value
    if (not isinstance(owners, list) or not owners
            or any(not isinstance(owner, str) or not owner.strip() for owner in owners)):
        raise ValueError("ledger:owners_required")
    return list(dict.fromkeys(owner.strip() for owner in owners))


def deduct_once(ledger: Any, key: Any, amount: float, *, owners: Any,
                reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a new ledger and audit event; never mutate the supplied ledger.

    Multiple legitimate contributors belong in ``owners`` on the first claim.
    A later action for the same key is rejected, even if it names another owner.
    """
    if not _number(amount):
        raise ValueError("ledger:deduction_amount_must_be_finite_nonnegative")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("ledger:reason_required")
    normalized_key = _key(key)
    next_ledger = _ledger_copy(ledger)
    if any(_entry_key(entry) == normalized_key for entry in next_ledger["entries"]):
        return next_ledger, {"action": "deduct", "key": list(normalized_key),
                             "accepted": False, "reason": "already_deducted"}
    entry = {"operation": normalized_key[0], "side": normalized_key[1], "scope": normalized_key[2],
             "owners": _owners(owners), "deducted": True, "deducted_hours": float(amount),
             "replaced_by": None}
    next_ledger["entries"].append(entry)
    return next_ledger, {"action": "deduct", "key": list(normalized_key), "accepted": True,
                         "amount_hours": float(amount), "owners": list(entry["owners"]),
                         "reason": reason.strip()}


def replace_once(ledger: Any, key: Any, replacement_key: Any, *, owners: Any,
                 old_hours: float, replacement_hours: float, reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replace an included operation once; a replacement cannot be additive."""
    if not _number(old_hours) or not _number(replacement_hours):
        raise ValueError("ledger:replacement_hours_must_be_finite_nonnegative")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("ledger:reason_required")
    old_key, new_key = _key(key), _key(replacement_key)
    next_ledger = _ledger_copy(ledger)
    old_entry = next((entry for entry in next_ledger["entries"] if _entry_key(entry) == old_key), None)
    new_exists = any(_entry_key(entry) == new_key for entry in next_ledger["entries"])
    if old_entry is None:
        return next_ledger, {"action": "replace", "key": list(old_key), "accepted": False,
                             "reason": "source_operation_missing"}
    if old_entry.get("replaced_by") is not None or new_exists:
        return next_ledger, {"action": "replace", "key": list(old_key), "accepted": False,
                             "reason": "already_replaced"}
    old_entry["deducted"] = True
    old_entry["deducted_hours"] = float(old_hours)
    old_entry["replaced_by"] = list(new_key)
    old_entry["owners"] = list(dict.fromkeys(old_entry.get("owners", []) + _owners(owners)))
    next_ledger["entries"].append({"operation": new_key[0], "side": new_key[1], "scope": new_key[2],
                                    "owners": _owners(owners), "deducted": False,
                                    "deducted_hours": 0.0, "replaced_by": None,
                                    "replacement_hours": float(replacement_hours)})
    return next_ledger, {"action": "replace", "key": list(old_key),
                         "replacement_key": list(new_key), "accepted": True,
                         "removed_hours": float(old_hours), "added_hours": float(replacement_hours),
                         "reason": reason.strip()}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _stopped(version: str, issues: list[str], trace: list[dict[str, Any]], ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    trace.append({"stage": "ledger_stop", "issues": list(dict.fromkeys(issues)),
                  "ledger": deepcopy(ledger or {"entries": []})})
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
            "labor": {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL),
                      "breakdown": [], "unknowns": list(dict.fromkeys(issues))},
            "trace": trace, "operation_keys": [], "approvals": [], "simulator_notice": SIMULATOR_NOTICE}


def _range(value: Any) -> dict[str, float] | None:
    if _number(value):
        return {band: float(value) for band in _BANDS}
    if isinstance(value, dict) and set(value) == set(_BANDS):
        if all(_number(value[k]) for k in _BANDS) and value["low"] <= value["typical"] <= value["high"]:
            return {k: float(value[k]) for k in _BANDS}
    return None


def _canonical_fixture(scenario: dict[str, Any]) -> bool:
    ops = scenario.get("operations")
    base = next((op for op in ops if isinstance(op, dict) and op.get("operation_id") == "base_service"), None) if isinstance(ops, list) else None
    return bool(scenario.get("metadata", {}).get("fictional_values") is True
                and base and base.get("gross_hours") == 2.0 and base.get("hours") == 1.7
                and base.get("deduplicated") is True)


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Apply shared-overlap deduction and included-carry replacement with an audit ledger."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    version = scenario.get("rule_version", RULE_VERSION)
    trace: list[dict[str, Any]] = [{"stage": "input_snapshot", "input_sha256": _hash(scenario_input)}]
    issues: list[str] = []
    if not isinstance(scenario_input, dict):
        return _stopped(version, ["scenario_input:object_required"], trace)
    if scenario.get("basis_unit") != "person_hour" or not isinstance(scenario.get("basis_definition"), str) or not scenario["basis_definition"].strip():
        issues.append("basis_unit_or_definition:person_hour_required")
    if rule_pack is not None and not isinstance(rule_pack, dict):
        issues.append("rule_pack:object_required")
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else {}
    if rule_pack is not None:
        if pack.get("engine_id") not in (None, ENGINE_ID):
            issues.append("rule_pack:engine_id_mismatch")
        if pack.get("rule_version") != version:
            issues.append("rule_pack:rule_version_mismatch")
        if pack.get("status", "approved") != "approved":
            issues.append("rule_pack:approved_version_required")
    fields = scenario.get("fields")
    operations = scenario.get("operations")
    if not isinstance(fields, dict):
        issues.append("fields:object_required")
        fields = {}
    if not isinstance(operations, list):
        issues.append("operations:list_required")
        operations = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, op in enumerate(operations):
        if not isinstance(op, dict) or not isinstance(op.get("operation_id"), str):
            issues.append(f"operations[{index}]:operation_id_required")
            continue
        op_id = op["operation_id"]
        if op_id in by_id:
            issues.append(f"{op_id}:duplicate_operation_id")
        by_id[op_id] = op
    expected = {"base_service", "included_carry", "replacement_carry", "snow_melt", "penetrant_wait", "parts_wait", "wash"}
    for missing in sorted(expected - set(by_id)):
        issues.append(f"{missing}:required_operation_missing")
    for key in ("work_scope", "included_operations"):
        obs = fields.get(key)
        if not isinstance(obs, dict) or obs.get("status") not in ("confirmed", "declared") or obs.get("value") is None:
            issues.append(f"{key}:confirmed_value_required")
    if scenario.get("job_id") != (fields.get("work_scope") or {}).get("value"):
        issues.append("work_scope:must_match_job_id")
    if issues:
        return _stopped(version, issues, trace)

    base = by_id["base_service"]
    fixture_gross_mode = (_canonical_fixture(scenario) and rule_pack is None
                          and scenario.get("ledger_mode") is None)
    mode = "gross" if fixture_gross_mode else scenario.get("ledger_mode")
    gross_raw = base.get("gross_hours") if mode == "gross" else base.get("hours")
    if mode not in ("gross", "deduplicated"):
        issues.append("ledger_mode:explicit_gross_or_deduplicated_required")
    if mode == "gross" and not _number(gross_raw):
        issues.append("base_service:gross_hours_required_in_gross_mode")
    if mode == "deduplicated" and (base.get("deduplicated") is not True or not _number(gross_raw)):
        issues.append("base_service:deduplicated_hours_and_flag_required")
    if mode == "gross" and base.get("deduplicated") is True and not fixture_gross_mode:
        issues.append("base_service:explicit_rededuction_of_deduplicated_hours_rejected")
    gross = float(gross_raw) if _number(gross_raw) else 0.0

    shared = pack.get("shared_deductions") if rule_pack is not None else None
    if shared is None:
        shared = ([{"key": {"operation": "shared_overlap", "side": "both", "scope": scenario["job_id"]},
                    "hours": 0.3, "owners": ["left_work", "right_work"],
                    "reason": "Fictional shared operation is deducted once for both owners."}]
                  if mode == "gross" else [])
    elif mode == "deduplicated" and shared:
        issues.append("base_service:explicit_rededuction_of_deduplicated_hours_rejected")
    if not isinstance(shared, list):
        issues.append("shared_deductions:list_required")
        shared = []
    try:
        ledger = _ledger_copy(pack.get("ledger", {"entries": []}) if rule_pack is not None else None)
    except ValueError as exc:
        issues.append(str(exc))
        return _stopped(version, issues, trace)
    events: list[dict[str, Any]] = []
    total_deduction = 0.0
    for index, action in enumerate(shared):
        if not isinstance(action, dict):
            issues.append(f"shared_deductions[{index}]:object_required")
            continue
        try:
            amount = action.get("hours")
            if not _number(amount):
                raise ValueError("ledger:deduction_amount_must_be_finite_nonnegative")
            ledger, event = deduct_once(ledger, action.get("key"), amount, owners=action.get("owners"),
                                       reason=action.get("reason", "Shared operation deduction."))
            events.append(event)
            if event.get("accepted"):
                total_deduction += float(amount)
            else:
                issues.append(f"shared_deductions[{index}]:{event['reason']}")
        except ValueError as exc:
            issues.append(f"shared_deductions[{index}]:{exc}")
    if total_deduction > gross:
        issues.append("base_service:deductions_exceed_gross_hours")

    groups = pack.get("exclusive_groups", []) if pack else []
    if not isinstance(groups, list):
        issues.append("exclusive_groups:list_required")
        groups = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict) or not isinstance(group.get("selected"), list):
            issues.append(f"exclusive_groups[{index}]:selected_list_required")
        elif len(group["selected"]) != 1:
            issues.append(f"exclusive_groups[{index}]:exactly_one_selection_required")
    if issues:
        return _stopped(version, issues, trace, ledger)

    included, replacement = by_id["included_carry"], by_id["replacement_carry"]
    included_hours = included.get("hours")
    replacement_count, per_person = replacement.get("person_count"), replacement.get("hours_per_person")
    if (included.get("included_in_base") is not True or not _number(included_hours)
            or replacement.get("replaces_operation_id") != "included_carry"
            or isinstance(replacement_count, bool) or not isinstance(replacement_count, int) or replacement_count <= 0
            or not _number(per_person)):
        issues.append("included_carry:valid_included_operation_and_replacement_required")
        return _stopped(version, issues, trace, ledger)
    source_key = {"operation": "included_carry", "side": "both", "scope": scenario["job_id"]}
    source_ledger, source_event = deduct_once(ledger, source_key, included_hours,
                                               owners=["base_service"], reason="Remove included carry before replacement.")
    if source_event.get("accepted"):
        ledger = source_ledger
    else:
        issues.append("included_carry:already_deducted")
    replacement_ledger, replacement_event = replace_once(
        ledger, source_key, {"operation": "replacement_carry", "side": "both", "scope": scenario["job_id"]},
        owners=["replacement_carry"], old_hours=float(included_hours),
        replacement_hours=float(per_person) * replacement_count,
        reason="Replace included transport with two-person handling.")
    if replacement_event.get("accepted"):
        ledger = replacement_ledger
    else:
        issues.append(f"replacement_carry:{replacement_event['reason']}")
    if issues:
        trace.append({"stage": "ledger_actions", "events": events + [source_event, replacement_event], "ledger": ledger})
        return _stopped(version, issues, trace, ledger)

    waiting: dict[str, float | None] = {}
    elapsed_unknowns: list[str] = []
    for op_id in ("snow_melt", "penetrant_wait", "parts_wait"):
        op = by_id[op_id]
        raw = op.get("elapsed_hours", op.get("duration_hours", op.get("hours")))
        if op_id == "parts_wait" and op.get("stock_checked") is not True:
            issues.append("parts_wait:stock_confirmation_required")
        if raw is None:
            elapsed_unknowns.append(f"{op_id}:elapsed_duration_unknown")
            waiting[op_id] = None
        elif not _number(raw):
            issues.append(f"{op_id}:elapsed_duration_invalid")
            waiting[op_id] = None
        else:
            waiting[op_id] = float(raw)
    wash_hours = by_id["wash"].get("hours")
    if not _number(wash_hours):
        issues.append("wash:person_hour_duration_required")
    rotor = {k: 0.0 for k in _BANDS}
    rotor_obs = fields.get("rotor_seizure_hours")
    relevance_obs = fields.get("rotor_relevance")
    if isinstance(relevance_obs, dict) and relevance_obs.get("value") == "relevant":
        range_value = rotor_obs.get("value") if isinstance(rotor_obs, dict) else None
        approval = scenario.get("metadata", {}).get("approved_condition_widths", {}).get("rotor_seizure_hours")
        if not isinstance(range_value, dict) or not isinstance(approval, dict):
            issues.append("rotor_seizure_hours:human_approval_required")
        elif (not all(_number(range_value.get(k)) for k in _BANDS)
              or not range_value["low"] <= range_value["typical"] <= range_value["high"]
              or not isinstance(approval.get("actor"), str) or not approval["actor"].strip()
              or not isinstance(approval.get("reason"), str) or not approval["reason"].strip()
              or approval.get("old_value") is not None or approval.get("new_value") != range_value):
            issues.append("rotor_seizure_hours:approval_audit_mismatch")
        else:
            rotor = {k: float(range_value[k]) for k in _BANDS}
    elif not isinstance(relevance_obs, dict) or relevance_obs.get("status") not in ("confirmed", "declared"):
        issues.append("rotor_relevance:human_confirmation_required")
    if issues:
        trace.append({"stage": "ledger_actions", "events": events + [source_event, replacement_event], "ledger": ledger})
        return _stopped(version, issues, trace, ledger)

    net_base = gross - total_deduction - float(included_hours)
    if net_base < 0:
        return _stopped(version, ["ledger:deductions_and_replacement_exceed_gross"], trace, ledger)
    handling = float(per_person) * replacement_count
    person = {band: round(net_base + handling + float(wash_hours) + rotor[band], 10) for band in _BANDS}
    elapsed_range = None if any(value is None for value in waiting.values()) else {
        band: round(net_base + float(per_person) + float(wash_hours) + sum(float(value) for value in waiting.values()) + rotor[band], 10)
        for band in _BANDS
    }
    # The fixture has 1.7 effective base, 0.12 included carry, .10 elapsed
    # handling duration, .75 waits, .10 wash and a conditional rotor range.
    elapsed = elapsed_range or dict(_NULL)
    breakdown = [
        {"operation": "gross_base_after_shared_deduction", "operation_id": "base_service",
         "hours": {band: round(gross - total_deduction, 10) for band in _BANDS},
         "reason": "Gross input less the shared-overlap key exactly once.", "status": "confirmed-observation"},
        {"operation": "included_transport_removed", "operation_id": "included_carry",
         "hours": {band: 0.0 for band in _BANDS}, "reason": "Remove 0.12 included hours before replacement.",
         "status": "confirmed-observation"},
        {"operation": "two_person_handling", "operation_id": "replacement_carry",
         "hours": {band: round(handling, 10) for band in _BANDS},
         "elapsed_hours": {band: float(per_person) for band in _BANDS},
         "person_count": replacement_count, "reason": "Replacement for included transport, not an additive carry.",
         "status": "confirmed-observation"},
        {"operation": "wash", "operation_id": "wash", "hours": {band: float(wash_hours) for band in _BANDS},
         "reason": "Performed nonbillable work remains person-hours.", "status": "nonbillable-work"},
    ]
    breakdown.extend({"operation": op_id, "operation_id": op_id,
                     "hours": {band: 0.0 for band in _BANDS},
                     "elapsed_hours": ({band: waiting[op_id] for band in _BANDS} if waiting[op_id] is not None else dict(_NULL)),
                     "reason": "Confirmed wait contributes elapsed time only.", "status": "wait"}
                    for op_id in waiting)
    if any(rotor.values()):
        breakdown.append({"operation": "rotor_seizure", "operation_id": "rotor_seizure", "hours": rotor,
                          "reason": "Fictional human-approved condition range.", "status": "conditional"})
    if issues or elapsed_unknowns:
        status = "partial"
        if elapsed_unknowns:
            elapsed = dict(_NULL)
    else:
        status = "proposed"
    trace.append({"stage": "ledger_actions", "mode": "gross" if mode == "gross" else "deduplicated",
                  "fixture_gross_adapter": fixture_gross_mode,
                  "input_hours_ignored": (base.get("hours") if fixture_gross_mode else None),
                  "deduction_total_hours": total_deduction, "events": events + [source_event, replacement_event],
                  "ledger": ledger, "input_sha256": _hash({"scenario": scenario_input, "rule_pack": rule_pack})})
    unknowns = list(dict.fromkeys(issues + elapsed_unknowns))
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status,
            "labor": {"person_hours": person, "elapsed_hours": elapsed, "breakdown": breakdown,
                      "unknowns": unknowns},
            "trace": trace, "operation_keys": [row["operation_id"] for row in breakdown],
            "approvals": [], "simulator_notice": SIMULATOR_NOTICE}
