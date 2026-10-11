"""E14: simulator photo candidates require an auditable human decision."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib, json, re
from typing import Any
from . import e07

ENGINE_ID = "e14_photo_candidate_approval_queue"
RULE_VERSION = "e14-photo-candidate-approval-v1"
SIMULATOR_NOTICE = "写真分類はローカルの架空Simulator候補です。画像・顧客情報・外部AIは使用しません。"
_NULL = {"low": None, "typical": None, "high": None}
_DEFAULT_ALLOWED = {"rotor_relevance": ["relevant", "unrelated"], "rotor_seizure_hours": "person_hour_range", "subframe_relevance": ["relevant", "unrelated"]}
_AREA = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_REF_ID = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
_CANDIDATE_KEYS = {"candidate_id", "photo_ref", "ai_candidate", "status", "human_audit", "human_value"}
_AUDIT_LOG_KEY = "photo_candidate_audit_log"

def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()

def _field_snapshot(fields: dict[str, Any], field: str) -> dict[str, Any]:
    return {"present": field in fields, "value": deepcopy(fields.get(field))}

def _snapshot_value(snapshot: dict[str, Any]) -> Any:
    field_state = snapshot.get("value")
    return deepcopy(field_state.get("value")) if snapshot.get("present") and isinstance(field_state, dict) else (deepcopy(field_state) if snapshot.get("present") else None)

def _valid_value(field: str, value: Any, allowed: dict[str, Any]) -> bool:
    options = allowed.get(field)
    if options == "person_hour_range":
        return (isinstance(value, dict) and set(value) == {"low", "typical", "high"}
                and all(isinstance(value[k], (int, float)) and not isinstance(value[k], bool) and 0 <= value[k] < float("inf") for k in ("low", "typical", "high"))
                and value["low"] <= value["typical"] <= value["high"])
    return isinstance(options, list) and value in options

def _rules(rule_pack: Any, scenario: dict[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
    issues: list[str] = []
    version = scenario.get("rule_version", RULE_VERSION)
    allowed = deepcopy(_DEFAULT_ALLOWED)
    if rule_pack is not None:
        if not isinstance(rule_pack, dict):
            issues.append("rule_pack:object_required")
        else:
            pack = deepcopy(rule_pack)
            if pack.get("engine_id") not in (None, ENGINE_ID): issues.append("rule_pack:engine_id_mismatch")
            if pack.get("rule_version") != version: issues.append("rule_pack:rule_version_mismatch")
            if pack.get("status", "approved") != "approved": issues.append("rule_pack:approved_version_required")
            if set(pack) - {"engine_id", "rule_version", "status", "allowed_values"}: issues.append("rule_pack:unknown_key")
            if "allowed_values" in pack:
                custom = pack["allowed_values"]
                if not isinstance(custom, dict) or set(custom) != set(_DEFAULT_ALLOWED):
                    issues.append("rule_pack:allowed_values_must_define_known_fields")
                else:
                    for field, values in custom.items():
                        valid = values == "person_hour_range" if field == "rotor_seizure_hours" else (isinstance(values, list) and bool(values) and all(isinstance(v, str) and v for v in values) and len(values) == len(set(values)))
                        if not valid: issues.append(f"rule_pack:{field}_invalid_allowed_values")
                    if not issues: allowed = deepcopy(custom)
    if not isinstance(version, str) or not version.strip():
        issues.append("rule_version:required"); version = RULE_VERSION
    return allowed, version, list(dict.fromkeys(issues))

def _photo_ref(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"area", "id"} and isinstance(value["area"], str)
            and _AREA.fullmatch(value["area"]) is not None and isinstance(value["id"], str) and _REF_ID.fullmatch(value["id"]) is not None)

def _candidate_issues(candidates: Any, allowed: dict[str, Any]) -> list[str]:
    if not isinstance(candidates, list): return ["photo_candidates:list_required"]
    issues: list[str] = []; seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        prefix = f"photo_candidates[{index}]"
        if not isinstance(candidate, dict): issues.append(f"{prefix}:object_required"); continue
        if set(candidate) - _CANDIDATE_KEYS: issues.append(f"{prefix}:unknown_or_private_data_rejected")
        cid = candidate.get("candidate_id")
        if not isinstance(cid, str) or not _REF_ID.fullmatch(cid): issues.append(f"{prefix}:candidate_id_invalid")
        elif cid in seen: issues.append(f"{cid}:duplicate_candidate_id")
        else: seen.add(cid)
        if not _photo_ref(candidate.get("photo_ref")): issues.append(f"{prefix}:anonymous_photo_ref_required")
        ai = candidate.get("ai_candidate")
        if not isinstance(ai, dict) or set(ai) != {"field", "value"}: issues.append(f"{prefix}:simulator_candidate_shape")
        elif not isinstance(ai.get("field"), str) or not _valid_value(ai["field"], ai.get("value"), allowed): issues.append(f"{prefix}:candidate_value_not_allowed")
        status = candidate.get("status", "pending")
        if status not in {"pending", "approved", "modified", "rejected"}: issues.append(f"{prefix}:invalid_state")
        audit = candidate.get("human_audit")
        if status in {"approved", "modified", "rejected"}:
            if (not isinstance(audit, dict) or set(audit) != {"actor", "reason", "old_value", "new_value", "timestamp", "before_sha256", "after_sha256"}
                or not all(isinstance(audit.get(k), str) and audit[k].strip() for k in ("actor", "reason", "timestamp"))):
                issues.append(f"{prefix}:human_audit_required")
            elif status == "rejected":
                if audit["new_value"] != "rejected": issues.append(f"{prefix}:rejected_audit_mismatch")
            elif audit["new_value"] != candidate.get("human_value") or not _valid_value(ai.get("field"), audit["new_value"], allowed):
                issues.append(f"{prefix}:observation_audit_mismatch")
        elif audit is not None or "human_value" in candidate: issues.append(f"{prefix}:pending_must_not_have_human_audit")
    return issues

def propose_candidates(scenario_input: dict, candidates: list[dict]) -> dict[str, Any]:
    """Append simulator proposals as pending, without mutating either argument."""
    if not isinstance(scenario_input, dict) or not isinstance(candidates, list): raise ValueError("scenario_input:object_and_candidates:list_required")
    result = deepcopy(scenario_input); queued = deepcopy(result.get("photo_candidates", []))
    if not isinstance(queued, list): raise ValueError("photo_candidates:list_required")
    for item in deepcopy(candidates):
        if not isinstance(item, dict): raise ValueError("candidate:object_required")
        if {"status", "human_audit", "human_value"} & set(item): raise ValueError("candidate:proposal_cannot_set_human_state")
        queued.append({**item, "status": "pending"})
    result["photo_candidates"] = queued
    return result

def _decision(scenario_input: dict, candidate_id: str, actor: str, reason: str, status: str,
              observed_value: Any = None, timestamp: str | None = None) -> dict[str, Any]:
    if not isinstance(scenario_input, dict): raise ValueError("scenario_input:object_required")
    if not all(isinstance(v, str) and v.strip() for v in (candidate_id, actor, reason)): raise ValueError("candidate_id_actor_reason:required")
    result = deepcopy(scenario_input); candidates = result.get("photo_candidates")
    if not isinstance(candidates, list): raise ValueError("photo_candidates:list_required")
    matches = [c for c in candidates if isinstance(c, dict) and c.get("candidate_id") == candidate_id]
    if len(matches) != 1: raise ValueError("candidate_id:must_match_exactly_one_pending_candidate")
    candidate = matches[0]
    if candidate.get("status", "pending") != "pending": raise ValueError("candidate:only_pending_can_transition")
    ai = candidate.get("ai_candidate")
    if not isinstance(ai, dict) or set(ai) != {"field", "value"}: raise ValueError("candidate:simulator_candidate_shape")
    fields_before = result.get("fields", {})
    if not isinstance(fields_before, dict): raise ValueError("fields:object_required")
    before_snapshot = _field_snapshot(fields_before, ai["field"])
    old_value = _snapshot_value(before_snapshot)
    final_value = deepcopy(ai.get("value") if status == "approved" else observed_value)
    allowed, _, rule_issues = _rules(None, result)
    if rule_issues or not _valid_value(ai.get("field"), final_value, allowed): raise ValueError("observed_value:not_allowed")
    stamp = timestamp or datetime.now(timezone.utc).isoformat()
    try: parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc: raise ValueError("timestamp:iso8601_required") from exc
    if parsed.tzinfo is None: raise ValueError("timestamp:timezone_required")
    candidate["status"] = status; candidate["human_value"] = final_value
    candidate["human_audit"] = {"actor": actor.strip(), "reason": reason.strip(), "old_value": old_value,
                                "new_value": "rejected" if status == "rejected" else deepcopy(final_value), "timestamp": stamp}
    if status != "rejected":
        fields = result.setdefault("fields", {})
        fields[ai["field"]] = {"value": deepcopy(final_value), "status": "confirmed", "source": "human-confirmed-photo-candidate", "confirmed_at": stamp}
    after_snapshot = _field_snapshot(fields_before if status == "rejected" else fields, ai["field"])
    candidate["human_audit"]["before_sha256"] = _hash(before_snapshot)
    candidate["human_audit"]["after_sha256"] = _hash(after_snapshot)
    metadata = result.setdefault("metadata", {})
    if not isinstance(metadata, dict): raise ValueError("metadata:object_required")
    audit_log = metadata.setdefault(_AUDIT_LOG_KEY, [])
    if not isinstance(audit_log, list): raise ValueError("photo_candidate_audit_log:list_required")
    audit_log.append({"candidate_id": candidate_id, "field": ai["field"],
                      "before_snapshot": deepcopy(before_snapshot), "after_snapshot": deepcopy(after_snapshot),
                      "before_sha256": candidate["human_audit"]["before_sha256"],
                      "after_sha256": candidate["human_audit"]["after_sha256"]})
    if status != "rejected":
        if ai["field"] == "rotor_seizure_hours":
            approvals = metadata.setdefault("approved_condition_widths", {})
            if not isinstance(approvals, dict): raise ValueError("approved_condition_widths:object_required")
            approvals["rotor_seizure_hours"] = {"actor": actor.strip(), "reason": reason.strip(), "old_value": old_value, "new_value": deepcopy(final_value)}
    return result

def confirm_candidate(scenario_input: dict, candidate_id: str, actor: str, reason: str, timestamp: str | None = None) -> dict[str, Any]:
    """Accept the simulator's value as an observation after explicit human review."""
    return _decision(scenario_input, candidate_id, actor, reason, "approved", timestamp=timestamp)

def modify_candidate(scenario_input: dict, candidate_id: str, observed_value: Any, actor: str, reason: str, timestamp: str | None = None) -> dict[str, Any]:
    """Accept a human-corrected value with old/new values preserved."""
    return _decision(scenario_input, candidate_id, actor, reason, "modified", observed_value, timestamp)

def reject_candidate(scenario_input: dict, candidate_id: str, actor: str, reason: str, timestamp: str | None = None) -> dict[str, Any]:
    """Reject a proposal without writing its suggested condition to observations."""
    if not isinstance(scenario_input, dict): raise ValueError("scenario_input:object_required")
    candidates = scenario_input.get("photo_candidates")
    candidate = next((c for c in candidates if isinstance(c, dict) and c.get("candidate_id") == candidate_id), None) if isinstance(candidates, list) else None
    if candidate is None or not isinstance(candidate.get("ai_candidate"), dict): raise ValueError("candidate_id:pending_candidate_required")
    return _decision(scenario_input, candidate_id, actor, reason, "rejected", deepcopy(candidate["ai_candidate"].get("value")), timestamp)

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Promote only auditable decisions; pending/rejected proposals stay out of fields."""
    original = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    allowed, version, issues = _rules(rule_pack, original); candidates = original.get("photo_candidates", [])
    issues.extend(_candidate_issues(candidates, allowed))
    if issues:
        labor = {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [], "unknowns": list(dict.fromkeys(issues))}
        return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required", "labor": labor,
                "trace": [{"stage": "photo_candidate_stop", "rule_sha256": _hash(allowed), "input_sha256": _hash(original), "issues": labor["unknowns"]}],
                "operation_keys": [], "approvals": [], "simulator_notice": SIMULATOR_NOTICE}
    scenario = deepcopy(original); scenario.pop("photo_candidates", None)
    fields = scenario.setdefault("fields", {})
    if not isinstance(fields, dict): fields = {}; scenario["fields"] = fields
    metadata = scenario.get("metadata", {})
    audit_log = metadata.get(_AUDIT_LOG_KEY, []) if isinstance(metadata, dict) else None
    if not isinstance(audit_log, list): issues.append("photo_candidate_audit_log:list_required")
    else:
        log_by_id = {}
        for entry in audit_log:
            if not isinstance(entry, dict) or set(entry) != {"candidate_id", "field", "before_snapshot", "after_snapshot", "before_sha256", "after_sha256"}:
                issues.append("photo_candidate_audit_log:entry_invalid"); continue
            cid = entry.get("candidate_id")
            if (not isinstance(cid, str) or not _REF_ID.fullmatch(cid) or entry.get("field") not in allowed
                or not all(isinstance(entry.get(key), dict) and set(entry[key]) == {"present", "value"}
                           and isinstance(entry[key].get("present"), bool) for key in ("before_snapshot", "after_snapshot"))
                or not all(isinstance(entry.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", entry[key])
                           for key in ("before_sha256", "after_sha256"))):
                issues.append("photo_candidate_audit_log:entry_invalid"); continue
            if cid in log_by_id: issues.append(f"{cid}:duplicate_audit_snapshot")
            log_by_id[cid] = entry
    for candidate in candidates:
        if candidate.get("status", "pending") not in {"approved", "modified", "rejected"}: continue
        ai = candidate["ai_candidate"]; field = ai["field"]; value = candidate["human_value"]; audit = candidate["human_audit"]
        entry = log_by_id.get(candidate["candidate_id"]) if isinstance(audit_log, list) else None
        if not isinstance(entry, dict):
            issues.append(f"{candidate['candidate_id']}:confirmed_observation_missing_or_mismatch"); continue
        before_snapshot, after_snapshot = entry["before_snapshot"], entry["after_snapshot"]
        if (_hash(before_snapshot) != entry["before_sha256"] or _hash(after_snapshot) != entry["after_sha256"]
            or audit.get("before_sha256") != entry["before_sha256"] or audit.get("after_sha256") != entry["after_sha256"]
            or audit.get("old_value") != _snapshot_value(before_snapshot)
            or (candidate.get("status") == "rejected" and (before_snapshot != after_snapshot or audit.get("new_value") != "rejected"))
            or (candidate.get("status") != "rejected" and _snapshot_value(after_snapshot) != audit.get("new_value"))
            or entry.get("field") != field):
            issues.append(f"{candidate['candidate_id']}:condition_approval_audit_mismatch"); continue
        if candidate.get("status") == "rejected": continue
        current = fields.get(field)
        if (not isinstance(current, dict) or current != after_snapshot["value"]
            or current.get("value") != value or current.get("status") != "confirmed" or current.get("confirmed_at") != audit["timestamp"]):
            issues.append(f"{candidate['candidate_id']}:confirmed_observation_missing_or_mismatch"); continue
        if field == "rotor_seizure_hours":
            metadata = scenario.get("metadata", {}); approvals = metadata.get("approved_condition_widths", {}) if isinstance(metadata, dict) else {}
            expected = {"actor": audit["actor"], "reason": audit["reason"], "old_value": audit["old_value"], "new_value": audit["new_value"]}
            if approvals.get(field) != expected: issues.append(f"{candidate['candidate_id']}:condition_approval_audit_mismatch")
    if isinstance(audit_log, list):
        approved_ids = {c["candidate_id"] for c in candidates if c.get("status") in {"approved", "modified", "rejected"}}
        if set(log_by_id) != approved_ids: issues.append("photo_candidate_audit_log:candidate_state_mismatch")
    if issues:
        labor = {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [], "unknowns": list(dict.fromkeys(issues))}; status, inner = "missing-required", None
    else:
        inner = e07.run(scenario, None); labor, status = inner["labor"], inner["status"]
    trace = [{"stage": "photo_candidate_queue", "input_sha256": _hash(original), "rule_sha256": _hash(allowed), "rule_version": version,
              "candidate_states": [{"candidate_id": c["candidate_id"], "status": c.get("status", "pending"), "photo_ref": deepcopy(c["photo_ref"]), "ai_candidate": deepcopy(c["ai_candidate"])} for c in candidates],
              "confirmed_observation_count": sum(c.get("status") in {"approved", "modified"} for c in candidates)}]
    if inner: trace.extend(deepcopy(inner["trace"]))
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status, "labor": deepcopy(labor), "trace": trace,
            "operation_keys": list(inner.get("operation_keys", [])) if inner else [], "approvals": deepcopy(inner.get("approvals", [])) if inner else [], "simulator_notice": SIMULATOR_NOTICE}
