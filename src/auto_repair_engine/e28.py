"""E28 server-side recomputation and idempotent save policy."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from . import e07

ENGINE_ID = "e28_server_recompute"
RULE_VERSION = "e28-server-recompute-v1"
NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_NULL = {"low": None, "typical": None, "high": None}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    version = scenario.get("rule_version", RULE_VERSION)
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else {}
    result = e07.run(scenario)
    result["engine_id"] = ENGINE_ID
    result["rule_version"] = version
    proposal = pack.get("client_proposal")
    issues = []
    if rule_pack is not None and not isinstance(rule_pack, dict):
        issues.append("rule_pack:object_required")
    if pack and pack.get("rule_version") != version:
        issues.append("rule_pack:version_mismatch")
    if proposal is not None:
        if (not isinstance(proposal, dict) or proposal.get("rule_version") != version
                or (proposal.get("status") is not None and proposal.get("status") != result.get("status"))):
            issues.append("client_proposal:version_mismatch")
        elif (not isinstance(proposal.get("labor"), dict)
              or proposal["labor"].get("person_hours") != result["labor"].get("person_hours")
              or proposal["labor"].get("elapsed_hours") != result["labor"].get("elapsed_hours")):
            issues.append("client_proposal:server_recomputation_mismatch")
    if issues:
        result["status"] = "missing-required"
        result["labor"] = {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [], "unknowns": issues}
    result["trace"].insert(0, {"stage": "server_recompute", "client_proposal_checked": proposal is not None,
                               "mismatch_rejected": bool(issues), "rule_version": version})
    return result
