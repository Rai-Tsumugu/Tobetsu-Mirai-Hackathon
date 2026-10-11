"""E06: immutable, approval-audited JSON rule pack lifecycle."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from typing import Any

from . import e02
from .contract import common_scenario_fixture

ENGINE_ID = "e06_approval_rules"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_PUBLISHED: dict[str, dict[str, Any]] = {}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def payload_hash(pack: dict[str, Any]) -> str:
    """Hash the full immutable pack payload, excluding its integrity hash."""
    payload = deepcopy(pack)
    payload.pop("payload_hash", None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _default_pack(scenario: dict[str, Any]) -> dict[str, Any]:
    base = {"engine_id": ENGINE_ID, "rule_version": scenario.get("rule_version", "fictional-rule-v1"),
            "status": "approved", "approver": "fictional_shop_owner",
            "approval_reason": "fictional fixture approval", "effective_from": "2026-10-11",
            "source": "fictional_fixture", "basis_unit": scenario.get("basis_unit"),
            "basis_definition": scenario.get("basis_definition"), "rules": [
                {"job_id": "front_brake_service", "operation_key": "base_service", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 1.7, "typical": 1.7, "high": 1.7}, "unit": "person_hours", "source": "fictional_fixture:base"},
                {"job_id": "front_brake_service", "operation_key": "replacement_carry", "condition": {"field": "included_operations", "contains": "remove_install"}, "hours": {"low": 0.2, "typical": 0.2, "high": 0.2}, "unit": "person_hours", "source": "fictional_fixture:carry"},
                {"job_id": "front_brake_service", "operation_key": "snow_melt", "condition": {"field": "included_operations", "contains": "snow_removal"}, "hours": {"low": 0.5, "typical": 0.5, "high": 0.5}, "unit": "elapsed_hours", "source": "fictional_fixture:snow"},
                {"job_id": "front_brake_service", "operation_key": "penetrant_wait", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 0.25, "typical": 0.25, "high": 0.25}, "unit": "elapsed_hours", "source": "fictional_fixture:penetrant"},
                {"job_id": "front_brake_service", "operation_key": "parts_wait", "condition": {"field": "parts_wait_stock_checked", "equals": True}, "hours": {"low": 0.0, "typical": 0.0, "high": 0.0}, "unit": "elapsed_hours", "source": "fictional_fixture:parts"},
                {"job_id": "front_brake_service", "operation_key": "wash", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 0.1, "typical": 0.1, "high": 0.1}, "unit": "person_hours", "source": "fictional_fixture:wash"},
                {"job_id": "front_brake_service", "operation_key": "rotor_seizure", "condition": {"field": "rotor_relevance", "equals": "relevant"}, "hours": {"low": 0.0, "typical": 0.25, "high": 0.5}, "unit": "person_hours", "source": "fictional_fixture:rotor"},
            ]}
    base["approval_audit"] = [{"actor": base["approver"], "reason": base["approval_reason"],
                               "operation_key": rule["operation_key"], "old_value": None,
                               "new_value": deepcopy(rule)}
                              for rule in base["rules"]]
    base["payload_hash"] = payload_hash(base)
    return base


def publish_rule_pack(payload: dict[str, Any], actor: str, reason: str,
                      effective_from: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Approve and freeze a JSON payload with an audit row for each change."""
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("approval:actor_required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("approval:reason_required")
    try:
        date.fromisoformat(effective_from)
    except (TypeError, ValueError):
        raise ValueError("approval:effective_from_invalid")
    if not isinstance(payload, dict):
        raise ValueError("publish:payload_required")
    pack = deepcopy(payload)
    pack.pop("payload_hash", None)
    version = pack.get("rule_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("publish:rule_version_required")
    if not isinstance(pack.get("rules"), list) or not pack["rules"]:
        raise ValueError("publish:nonempty_rules_required")
    old_rules = {r.get("operation_key"): r for r in (previous or {}).get("rules", []) if isinstance(r, dict)}
    new_rules = {r.get("operation_key"): r for r in pack.get("rules", []) if isinstance(r, dict)}
    audit = []
    for key in sorted(set(old_rules) | set(new_rules)):
        prior, rule = old_rules.get(key), new_rules.get(key)
        old_value = deepcopy(prior) if prior else None
        new_value = deepcopy(rule) if rule else None
        if old_value != new_value:
            audit.append({"actor": actor.strip(), "reason": reason.strip(), "operation_key": key,
                          "scope": "rule", "old_value": old_value, "new_value": new_value})
    # Rule rows do not describe changes to the pack's own provenance and basis.
    # Record every semantic top-level change, including the effective date.
    old_attrs = {key: value for key, value in (previous or {}).items()
                 if key not in {"engine_id", "rule_version", "status", "approver", "approval_reason",
                                "approval_audit", "payload_hash", "rules"}}
    new_attrs = {key: value for key, value in pack.items()
                 if key not in {"engine_id", "rule_version", "status", "approver", "approval_reason",
                                "approval_audit", "payload_hash", "rules"}}
    new_attrs["effective_from"] = effective_from
    for key in sorted(set(old_attrs) | set(new_attrs)):
        prior, new = old_attrs.get(key), new_attrs.get(key)
        if prior != new:
            audit.append({"actor": actor.strip(), "reason": reason.strip(),
                          "operation_key": "@pack:" + key, "scope": "pack",
                          "old_value": deepcopy(prior), "new_value": deepcopy(new)})
    pack.update({"engine_id": ENGINE_ID, "status": "approved", "approver": actor.strip(),
                 "approval_reason": reason.strip(), "effective_from": effective_from,
                 "approval_audit": audit})
    pack["payload_hash"] = payload_hash(pack)
    prior = _PUBLISHED.get(version)
    if prior is not None:
        if prior["payload_hash"] != pack["payload_hash"]:
            raise ValueError("publish:published_version_is_immutable")
        return deepcopy(prior)
    _PUBLISHED[version] = deepcopy(pack)
    return deepcopy(pack)


def _invalid_pack(pack: Any, scenario: dict[str, Any], reason: str) -> dict[str, Any]:
    result = e02.run(scenario, None)
    result["engine_id"] = ENGINE_ID
    result["trace"].insert(0, {"event": "approval_pack_rejected", "reason": reason})
    if isinstance(pack, dict) and pack.get("rule_version"):
        result["rule_version"] = scenario.get("rule_version") or pack["rule_version"]
    return result


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict:
    """Verify approval, integrity, effective date, and pin before applying rules."""
    scenario = deepcopy(scenario_input)
    pack = _default_pack(scenario) if rule_pack is None else deepcopy(rule_pack)
    if not isinstance(pack, dict):
        return _invalid_pack(None, scenario, "rule_pack_required")
    # The default is an explicitly fictional, pre-approved snapshot. All other
    # packs must match a snapshot registered by publish_rule_pack byte-for-byte.
    if rule_pack is None:
        version = pack.get("rule_version")
        seeded = _PUBLISHED.get(version)
        if seeded is None:
            _PUBLISHED[version] = deepcopy(pack)
        elif _canonical(seeded) != _canonical(pack):
            return _invalid_pack(pack, scenario, "published_snapshot_mismatch")
    if pack.get("status") != "approved":
        return _invalid_pack(pack, scenario, "approved_status_required")
    try:
        actual_hash = payload_hash(pack)
    except (TypeError, ValueError, OverflowError):
        return _invalid_pack(pack, scenario, "payload_not_canonical_json")
    if not pack.get("payload_hash") or actual_hash != pack.get("payload_hash"):
        return _invalid_pack(pack, scenario, "payload_tampered_or_hash_missing")
    registered = _PUBLISHED.get(pack.get("rule_version"))
    if registered is None or _canonical(registered) != _canonical(pack):
        return _invalid_pack(pack, scenario, "published_snapshot_unregistered_or_mismatch")
    if not isinstance(pack.get("rules"), list) or not pack["rules"]:
        return _invalid_pack(pack, scenario, "rules_nonempty_list_required")
    rules = {r.get("operation_key"): r for r in pack["rules"] if isinstance(r, dict)}
    if len(rules) != len(pack["rules"]):
        return _invalid_pack(pack, scenario, "rule_rows_invalid_or_duplicate")
    audit_rows = pack.get("approval_audit")
    if not isinstance(audit_rows, list):
        return _invalid_pack(pack, scenario, "approval_audit_invalid")
    seen_audit = set()
    for row in audit_rows:
        if (not isinstance(row, dict) or not isinstance(row.get("actor"), str) or not row["actor"].strip()
                or not isinstance(row.get("reason"), str) or not row["reason"].strip()
                or not isinstance(row.get("operation_key"), str) or row["operation_key"] in seen_audit):
            return _invalid_pack(pack, scenario, "approval_audit_invalid")
        scope = row.get("scope", "rule")
        key = row["operation_key"]
        if scope == "rule":
            if row.get("new_value") != rules.get(key):
                return _invalid_pack(pack, scenario, "approval_audit_invalid")
        elif scope == "pack" and key.startswith("@pack:"):
            attr = key[len("@pack:"):]
            if not attr or row.get("new_value") != pack.get(attr):
                return _invalid_pack(pack, scenario, "approval_audit_invalid")
        else:
            return _invalid_pack(pack, scenario, "approval_audit_invalid")
        seen_audit.add(row["operation_key"])
    try:
        effective = date.fromisoformat(pack.get("effective_from", ""))
    except (TypeError, ValueError):
        return _invalid_pack(pack, scenario, "effective_from_invalid")
    as_of = scenario.get("as_of", "2026-10-11")
    try:
        current = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return _invalid_pack(pack, scenario, "scenario_as_of_invalid")
    if effective > current:
        return _invalid_pack(pack, scenario, "not_yet_effective")
    pinned = scenario.get("rule_version")
    if pinned and pinned != pack.get("rule_version"):
        return _invalid_pack(pack, scenario, "pinned_version_mismatch")
    if pack.get("engine_id") != ENGINE_ID:
        return _invalid_pack(pack, scenario, "engine_id_mismatch")
    # Ensure calculation adapter sees a valid E02 pack and cannot mutate the signed snapshot.
    adapted = deepcopy(pack)
    adapted["engine_id"] = e02.ENGINE_ID
    adapted.pop("payload_hash", None)
    adapted.pop("approval_reason", None)
    adapted.pop("approval_audit", None)
    underlying = e02.run(scenario, adapted)
    underlying["engine_id"] = ENGINE_ID
    underlying["trace"].insert(0, {"event": "approval_pack_verified", "rule_version": pack["rule_version"],
                                   "payload_hash": pack["payload_hash"], "effective_from": pack["effective_from"]})
    underlying["approvals"].insert(0, {"type": "json_pack_publish", "actor": pack.get("approver"),
                                       "reason": pack.get("approval_reason"), "rule_version": pack["rule_version"],
                                       "effective_from": pack["effective_from"], "payload_hash": pack["payload_hash"],
                                       "changes": deepcopy(pack.get("approval_audit", []))})
    return underlying
