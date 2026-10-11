"""E27 Python parity bridge for the pure browser calculator."""
from __future__ import annotations
from copy import deepcopy
import hashlib, json
from typing import Any
from . import e07

ENGINE_ID = "e27_browser_pure_function"
RULE_VERSION = "e27-browser-pure-v1"
NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_NULL = {"low": None, "typical": None, "high": None}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Recompute from the immutable snapshot and reject a mismatched browser proposal."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    result = e07.run(scenario, None)
    result["engine_id"] = ENGINE_ID
    result["rule_version"] = scenario.get("rule_version", RULE_VERSION)
    if rule_pack is not None and not isinstance(rule_pack, dict):
        result["status"] = "missing-required"
        result["labor"] = {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [],
                            "unknowns": ["rule_pack:object_required"]}
    proposal = rule_pack.get("client_proposal") if isinstance(rule_pack, dict) else None
    if isinstance(rule_pack, dict) and rule_pack.get("rule_version") not in (None, result["rule_version"]):
        proposal = {"rule_version_mismatch": True}
    expected = result.get("labor")
    if proposal is not None and (not isinstance(proposal, dict) or not isinstance(proposal.get("labor"), dict)
                                 or proposal.get("rule_version") != result["rule_version"]
                                 or (proposal.get("status") is not None and proposal.get("status") != result.get("status"))
                                 or proposal.get("labor", {}).get("person_hours") != expected.get("person_hours")
                                 or proposal.get("labor", {}).get("elapsed_hours") != expected.get("elapsed_hours")):
        result["status"] = "missing-required"
        result["labor"] = {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [],
                            "unknowns": ["browser_proposal:server_parity_validation_failed"]}
    payload = json.dumps(scenario_input, sort_keys=True, ensure_ascii=False, default=str)
    result["trace"].insert(0, {"stage": "browser_parity", "input_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                               "client_proposal_checked": proposal is not None,
                               "server_recomputed": True})
    return result
