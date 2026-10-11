"""E25: deterministic replay of pinned scenario snapshots across rule versions."""
from __future__ import annotations
from copy import deepcopy
import hashlib, json
from typing import Any
from .e02 import run as calculate

ENGINE_ID = "e25_version_replay"
_NULL = {"low": None, "typical": None, "high": None}

def _stopped(version: str, unknown: str) -> dict[str, Any]:
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
            "labor": {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [], "unknowns": [unknown]},
            "trace": [], "operation_keys": [], "approvals": [],
            "simulator_notice": "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。",
            "unknowns": [unknown]}

def replay(scenario_input: dict, old_pack: dict, new_pack: dict, *, actor: str,
           reason: str, diff_acknowledged: bool) -> dict[str, Any]:
    if not isinstance(scenario_input, dict) or not isinstance(old_pack, dict) or not isinstance(new_pack, dict):
        return _stopped("replay", "snapshot_and_two_rule_packs_required")
    if (not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str)
            or not reason.strip() or diff_acknowledged is not True):
        return _stopped(scenario_input.get("rule_version", "replay"), "human_actor_reason_and_diff_ack_required")
    if old_pack.get("rule_version") == new_pack.get("rule_version"):
        return _stopped(scenario_input.get("rule_version", "replay"), "distinct_rule_versions_required")
    pinned = deepcopy(scenario_input)
    outputs = []
    for pack in (old_pack, new_pack):
        versioned = deepcopy(pinned)
        versioned["rule_version"] = pack.get("rule_version")
        outputs.append(calculate(versioned, deepcopy(pack)))
    a, b = outputs
    diff = {"person_hours": {k: (round(b["labor"]["person_hours"].get(k) - a["labor"]["person_hours"].get(k), 10)
                                 if isinstance(a["labor"]["person_hours"].get(k), (int, float)) and isinstance(b["labor"]["person_hours"].get(k), (int, float)) else None)
                              for k in ("low", "typical", "high")},
            "elapsed_hours": {k: (round(b["labor"]["elapsed_hours"].get(k) - a["labor"]["elapsed_hours"].get(k), 10)
                                  if isinstance(a["labor"]["elapsed_hours"].get(k), (int, float)) and isinstance(b["labor"]["elapsed_hours"].get(k), (int, float)) else None)
                               for k in ("low", "typical", "high")},
            "old_unknowns": deepcopy(a["labor"].get("unknowns", [])),
            "new_unknowns": deepcopy(b["labor"].get("unknowns", [])),
            "unknowns_changed": a["labor"].get("unknowns", []) != b["labor"].get("unknowns", [])}
    snapshot_hash = hashlib.sha256(json.dumps(pinned, sort_keys=True, default=str).encode()).hexdigest()
    return {"engine_id": ENGINE_ID, "rule_version": b["rule_version"],
            "status": "replayed" if all(x["status"] != "missing-required" for x in outputs) else "partial",
            "labor": deepcopy(b["labor"]), "trace": [{"stage": "pinned_replay", "snapshot_sha256": snapshot_hash}],
            "operation_keys": deepcopy(b.get("operation_keys", [])), "approvals": [],
            "simulator_notice": b.get("simulator_notice", "Fictional simulator data."),
            "snapshot_sha256": snapshot_hash,
            "batches": [{"rule_version": output["rule_version"], "engine_result": output} for output in outputs],
            "diff": diff, "release_gate": {"actor": actor, "reason": reason,
            "diff_acknowledged": diff_acknowledged}, "unknowns": []}

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict:
    if not isinstance(rule_pack, dict) or not {"old_pack", "new_pack", "actor", "reason", "diff_acknowledged"}.issubset(rule_pack):
        version = scenario_input.get("rule_version", "replay") if isinstance(scenario_input, dict) else "replay"
        return _stopped(version, "old_new_packs_and_human_ack_required")
    return replay(scenario_input, rule_pack["old_pack"], rule_pack["new_pack"],
                  actor=rule_pack["actor"], reason=rule_pack["reason"],
                  diff_acknowledged=rule_pack["diff_acknowledged"])
