"""E16: copy job context while expiring vehicle observations between visits."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .contract import reference_labor

ENGINE_ID = "e16_previous_visit_expiry_copy"
RULE_VERSION = "e16-previous-visit-expiry-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証は行いません。"
_NULL_RANGE = {"low": None, "typical": None, "high": None}
_PRESERVED_FIELDS = {"work_scope", "included_operations"}
_CONDITION_FIELDS = {
    "rotor_relevance", "rotor_seizure_hours", "subframe_relevance",
    "parts_wait_stock_checked", "rust_observation", "snow_observation",
}


def _field_value(item: Any) -> Any:
    return item.get("value") if isinstance(item, dict) and "value" in item else item


def copy_previous_visit(previous_visit: dict[str, Any], current_visit_id: str,
                        observed_at: str) -> dict[str, Any]:
    """Create a new immutable visit snapshot, marking every carried condition unknown."""
    if not isinstance(previous_visit, dict):
        raise ValueError("previous_visit:object_required")
    token = previous_visit.get("vehicle_token")
    if not isinstance(token, str) or not re.fullmatch(r"(?:veh|vehicle)_[A-Za-z0-9_-]{4,120}", token):
        raise ValueError("previous_visit:anonymous_vehicle_token_required")
    old_time = previous_visit.get("observed_at")
    conditions = previous_visit.get("conditions")
    if not isinstance(old_time, str) or not old_time.strip() or not isinstance(conditions, dict):
        raise ValueError("previous_visit:observed_at_and_conditions_required")
    if not isinstance(current_visit_id, str) or not current_visit_id.strip():
        raise ValueError("current_visit_id:required")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise ValueError("observed_at:required")
    expired = sorted(set(conditions) & _CONDITION_FIELDS)
    carried = {
        key: deepcopy(value)
        for key, value in conditions.items() if key in _PRESERVED_FIELDS
    }
    carried.update({
        key: {"value": None, "status": "unknown", "source": "e16_expired_copy",
              "copied_value": deepcopy(_field_value(value)), "copied_from": old_time}
        for key, value in conditions.items() if key in _CONDITION_FIELDS
    })
    return {
        "visit_id": current_visit_id.strip(), "vehicle_token": token.strip(),
        "observed_at": observed_at.strip(), "conditions": carried,
        "copied_from": {"visit_id": previous_visit.get("visit_id"), "observed_at": old_time},
        "expired_fields": expired, "observations": [],
    }


def current_confirm(visit: dict[str, Any], field: str, value: Any, actor: str,
                    reason: str, observed_at: str | None = None) -> dict[str, Any]:
    """Return a new visit with one current observation appended and auditable."""
    copied = deepcopy(visit) if isinstance(visit, dict) else None
    if copied is None:
        return {"visit": None, "approval": None, "error": "visit:object_required"}
    if field not in _CONDITION_FIELDS or field not in copied.get("conditions", {}):
        return {"visit": copied, "approval": None, "error": "field:not_expired_condition"}
    if field in {"rotor_relevance", "subframe_relevance"} and value not in {"relevant", "unrelated"}:
        return {"visit": copied, "approval": None, "error": "confirmation:invalid_relevance"}
    if field in {"parts_wait_stock_checked"} and not isinstance(value, bool):
        return {"visit": copied, "approval": None, "error": "confirmation:boolean_required"}
    if field in {"rust_observation", "snow_observation"} and value not in {"present", "absent"}:
        return {"visit": copied, "approval": None, "error": "confirmation:invalid_condition"}
    if field == "rotor_seizure_hours":
        if (not isinstance(value, dict) or set(value) != {"low", "typical", "high"}
                or any(not isinstance(value[key], (int, float)) or isinstance(value[key], bool) or value[key] < 0
                       for key in ("low", "typical", "high"))
                or not value["low"] <= value["typical"] <= value["high"]):
            return {"visit": copied, "approval": None, "error": "confirmation:invalid_condition_range"}
    if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
        return {"visit": copied, "approval": None, "error": "confirmation:actor_and_reason_required"}
    if not isinstance(observed_at or copied.get("observed_at"), str) or not (observed_at or copied.get("observed_at")).strip():
        return {"visit": copied, "approval": None, "error": "confirmation:observed_at_required"}
    prior = copied["conditions"][field]
    old_value = prior.get("value") if isinstance(prior, dict) else prior
    observation = {"field": field, "value": deepcopy(value), "status": "confirmed",
                   "source": "e16_current_visit", "actor": actor.strip(), "reason": reason.strip(),
                   "observed_at": (observed_at or copied["observed_at"]).strip()}
    copied["conditions"][field] = {"value": deepcopy(value), "status": "confirmed",
                                   "source": "e16_current_visit", "confirmed_at": observation["observed_at"]}
    copied.setdefault("observations", []).append(observation)
    approval = {"field": field, "old_value": old_value, "new_value": deepcopy(value),
                "actor": actor.strip(), "reason": reason.strip(), "observed_at": observation["observed_at"]}
    return {"visit": copied, "approval": approval, "error": None}


def _null_labor(unknowns: list[str]) -> dict[str, Any]:
    return {"person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE),
            "breakdown": [], "unknowns": list(dict.fromkeys(unknowns))}


def _visit_valid(visit: Any) -> bool:
    return (isinstance(visit, dict) and isinstance(visit.get("vehicle_token"), str)
            and bool(visit["vehicle_token"].strip()) and isinstance(visit.get("observed_at"), str)
            and isinstance(visit.get("conditions"), dict))


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else None
    version = scenario.get("rule_version") or RULE_VERSION
    issues: list[str] = []
    trace: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    if not isinstance(scenario_input, dict):
        issues.append("scenario_input:object_required")
    if rule_pack is not None:
        if pack is None:
            issues.append("rule_pack:object_required")
        else:
            if set(pack) - {"engine_id", "rule_version", "previous_visit", "current_confirm"}:
                issues.append("rule_pack:unknown_key")
            if pack.get("engine_id") not in (None, ENGINE_ID, "e16"):
                issues.append("rule_pack:engine_id_mismatch")
            if "rule_version" in pack and (not isinstance(pack["rule_version"], str) or not pack["rule_version"].strip()):
                issues.append("rule_pack:rule_version_required")
            if pack.get("rule_version") and scenario.get("rule_version") and pack["rule_version"] != scenario["rule_version"]:
                issues.append("rule_pack:pinned_version_mismatch")
            version = pack.get("rule_version") or version
            if "previous_visit" in pack:
                previous = pack["previous_visit"]
                try:
                    copied = copy_previous_visit(previous, scenario.get("visit_id"), scenario.get("observed_at"))
                    if previous.get("job_id") is not None:
                        if scenario.get("job_id") not in (None, previous.get("job_id")):
                            issues.append("previous_visit:job_id_mismatch")
                        else:
                            scenario["job_id"] = previous["job_id"]
                    # Include any condition facts in the copied estimate, even when
                    # the Visit omitted them, so old stock/snow flags cannot leak through.
                    scenario_fields = scenario.get("fields", {})
                    if isinstance(scenario_fields, dict):
                        for key in _CONDITION_FIELDS:
                            if key in scenario_fields:
                                raw = scenario_fields[key]
                                if (isinstance(raw, dict) and raw.get("status") == "unknown"
                                        and raw.get("value") is None):
                                    continue
                                if key not in copied["expired_fields"]:
                                    copied["expired_fields"].append(key)
                                copied["conditions"].setdefault(key, {
                                    "value": None, "status": "unknown", "source": "e16_expired_copy",
                                    "copied_value": deepcopy(_field_value(scenario_fields[key])),
                                    "copied_from": previous.get("observed_at")})
                    trace.append({"event": "previous_visit_copied", "copied_from": deepcopy(copied["copied_from"]),
                                  "expired_fields": list(copied["expired_fields"]), "vehicle_token": copied["vehicle_token"]})
                    current = pack.get("current_confirm", [])
                    if not isinstance(current, list):
                        issues.append("current_confirm:list_required")
                    else:
                        for confirmation in current:
                            if not isinstance(confirmation, dict):
                                issues.append("current_confirm:object_required")
                                continue
                            result = current_confirm(copied, confirmation.get("field"), confirmation.get("value"),
                                                    confirmation.get("actor"), confirmation.get("reason"),
                                                    confirmation.get("observed_at"))
                            if result["error"]:
                                issues.append(result["error"])
                            else:
                                copied = result["visit"]
                                approvals.append(result["approval"])
                    scenario["visit"] = copied
                    fields = scenario.setdefault("fields", {})
                    if not isinstance(fields, dict):
                        issues.append("scenario_input:fields_must_be_object")
                    else:
                        for key in _CONDITION_FIELDS:
                            if key in copied["conditions"]:
                                fields[key] = deepcopy(copied["conditions"][key])
                        # A copied snapshot cannot carry fields omitted from Visit.conditions as current facts.
                        for key in _CONDITION_FIELDS:
                            if key in fields and key not in copied["conditions"]:
                                fields[key] = {"value": None, "status": "unknown", "source": "e16_expired_copy"}
                    for approval in approvals:
                        if approval["field"] == "rotor_seizure_hours":
                            scenario.setdefault("metadata", {}).setdefault("approved_condition_widths", {})[
                                "rotor_seizure_hours"] = {
                                    "actor": approval["actor"], "reason": approval["reason"],
                                    "old_value": approval["old_value"], "new_value": approval["new_value"]}
                    # Keep wait operations tied to this visit's observations.
                    if isinstance(fields, dict):
                        stock = fields.get("parts_wait_stock_checked", {})
                        for operation in scenario.get("operations", []):
                            if operation.get("operation_id") == "parts_wait":
                                operation["stock_checked"] = (
                                    stock.get("value") is True and stock.get("status") == "confirmed"
                                    if isinstance(stock, dict) else False)
                        snow = fields.get("snow_observation", {})
                        if isinstance(snow, dict) and snow.get("status") == "confirmed" and snow.get("value") == "absent":
                            for operation in scenario.get("operations", []):
                                if operation.get("operation_id") == "snow_melt":
                                    operation["elapsed_hours"] = 0.0
                                    operation["hours"] = 0.0
                                    operation["source"] = "e16_current_snow_absent"
                    missing_confirmations = [key for key in copied["expired_fields"]
                                             if copied["conditions"].get(key, {}).get("status") != "confirmed"]
                    relevance = copied["conditions"].get("rotor_relevance", {})
                    if (isinstance(relevance, dict) and relevance.get("status") == "confirmed"
                            and relevance.get("value") == "unrelated"):
                        missing_confirmations = [key for key in missing_confirmations
                                                 if key != "rotor_seizure_hours"]
                    if missing_confirmations:
                        issues.append("current_confirm:required_for_expired_fields:" + ",".join(sorted(missing_confirmations)))
                    trace.append({"event": "current_visit_confirmations_applied", "count": len(approvals),
                                  "remaining_expired_fields": [key for key in copied["expired_fields"]
                                                               if copied["conditions"].get(key, {}).get("status") != "confirmed"]})
                except (ValueError, TypeError) as exc:
                    issues.append(str(exc))
            elif "current_confirm" in pack:
                issues.append("previous_visit:required_for_current_confirm")
    if not isinstance(version, str) or not version.strip():
        issues.append("rule_version:required")
    if isinstance(scenario_input, dict):
        if not isinstance(scenario.get("fields", {}), dict):
            issues.append("scenario_input:fields_must_be_object")
        if not isinstance(scenario.get("operations", []), list):
            issues.append("scenario_input:operations_must_be_list")
        elif any(not isinstance(operation, dict) for operation in scenario.get("operations", [])):
            issues.append("scenario_input:operations_must_contain_objects")
    if issues:
        labor = _null_labor(issues)
        status = "missing-required"
    else:
        labor, _, _ = reference_labor(scenario)
        labor = deepcopy(labor)
        blocking = [item for item in labor.get("unknowns", []) if not item.endswith(":elapsed_duration_unknown")]
        status = "missing-required" if blocking else ("partial" if labor.get("unknowns") else "proposed")
        trace.append({"event": "labor_calculated", "rule_version": version,
                      "operation_keys": [row.get("operation_id") for row in labor.get("breakdown", [])
                                         if row.get("operation_id")]})
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status, "labor": labor,
            "trace": trace, "operation_keys": [row.get("operation_id") for row in labor.get("breakdown", [])
                                                  if row.get("operation_id")],
            "approvals": approvals, "simulator_notice": SIMULATOR_NOTICE}
