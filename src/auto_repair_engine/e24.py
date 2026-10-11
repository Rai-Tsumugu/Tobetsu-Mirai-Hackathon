"""E24: draft and human-approved immutable rule-pack updates."""
from __future__ import annotations
from copy import deepcopy
from datetime import date
import hashlib, json
from math import isfinite
from typing import Any

ENGINE_ID = "e24_approval_version_update"

def _finite_range(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"low", "typical", "high"}
            and all(not isinstance(value[k], bool) and isinstance(value[k], (int, float))
                    and isfinite(value[k]) and value[k] >= 0 for k in ("low", "typical", "high"))
            and value["low"] <= value["typical"] <= value["high"])

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict:
    """Keep estimate envelope available while proposals remain outside applied rules."""
    from .e07 import run as pipeline
    result = pipeline(scenario_input)
    result["engine_id"] = ENGINE_ID
    result["trace"].append({"stage": "approval_version_update", "status": "proposal_only",
                            "applied_rule_version": result["rule_version"],
                            "note": "Call propose/approve to create a new immutable approved rule version."})
    return result

def propose(old_pack: dict, operation_key: str, new_hours: dict, samples: list[dict], reason: str) -> dict:
    """Create a reviewable diff; proposals never alter or apply the old pack."""
    if not isinstance(old_pack, dict) or not isinstance(samples, list) or not samples:
        raise ValueError("old pack and nonempty evidence samples are required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("proposal reason is required")
    before = next((r for r in old_pack.get("rules", []) if r.get("operation_key") == operation_key), None)
    if before is None:
        raise ValueError("operation_key not found in old rule pack")
    if not _finite_range(new_hours):
        raise ValueError("new_hours range is invalid")
    if not _finite_range(before.get("hours")):
        raise ValueError("baseline pack range is invalid")
    proposal = {"engine_id": ENGINE_ID, "status": "draft", "old_rule_version": old_pack.get("rule_version"),
            "old_pack": deepcopy(old_pack), "operation_key": operation_key,
            "old_value": deepcopy(before["hours"]), "new_value": deepcopy(new_hours),
            "samples": deepcopy(samples), "reason": reason.strip(),
            "old_pack_sha256": hashlib.sha256(json.dumps(old_pack, sort_keys=True, default=str).encode()).hexdigest()}
    proposal["proposal_sha256"] = _proposal_hash(proposal)
    return proposal

def _proposal_hash(proposal: dict) -> str:
    body = {k: v for k, v in proposal.items() if k != "proposal_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

def approve(proposal: dict, actor: str, reason: str, new_rule_version: str,
            effective_from: str) -> dict:
    if proposal.get("status") != "draft" or proposal.get("engine_id") != ENGINE_ID:
        raise ValueError("a draft E24 proposal is required")
    if proposal.get("proposal_sha256") != _proposal_hash(proposal):
        raise ValueError("proposal content or evidence was modified")
    if not all(isinstance(v, str) and v.strip() for v in (actor, reason, new_rule_version, effective_from)):
        raise ValueError("actor, approval reason, new version, and effective date are required")
    if new_rule_version == proposal.get("old_rule_version"):
        raise ValueError("approved changes require a new immutable rule_version")
    try:
        date.fromisoformat(effective_from)
    except ValueError as exc:
        raise ValueError("effective_from must be an ISO date") from exc
    pack = deepcopy(proposal["old_pack"])
    if hashlib.sha256(json.dumps(pack, sort_keys=True, default=str).encode()).hexdigest() != proposal["old_pack_sha256"]:
        raise ValueError("old pack snapshot hash mismatch")
    matches = [r for r in pack.get("rules", []) if r.get("operation_key") == proposal["operation_key"]]
    if len(matches) != 1 or matches[0].get("hours") != proposal["old_value"]:
        raise ValueError("proposal diff no longer matches the pinned old pack")
    matches[0]["hours"] = deepcopy(proposal["new_value"])
    pack.update(rule_version=new_rule_version, status="approved", approved_by=actor,
                approval_reason=reason, effective_from=effective_from)
    return {"engine_id": ENGINE_ID, "rule_version": new_rule_version, "status": "approved",
            "rule_pack": pack, "approval": {"actor": actor, "reason": reason,
            "old_rule_version": proposal["old_rule_version"], "new_rule_version": new_rule_version,
            "operation_key": proposal["operation_key"], "old_value": deepcopy(proposal["old_value"]),
            "new_value": deepcopy(proposal["new_value"]), "samples": deepcopy(proposal["samples"]),
            "effective_from": effective_from}}
