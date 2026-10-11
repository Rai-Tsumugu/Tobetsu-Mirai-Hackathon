"""E29 immutable offline snapshot queue with explicit conflict resolution."""
from __future__ import annotations
from copy import deepcopy
import hashlib, json
from typing import Any

ENGINE_ID = "e29_offline_snapshot"
RULE_VERSION = "e29-offline-snapshot-v1"
NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"


def _input_hash(scenario_input: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(scenario_input, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def queue_snapshot(queue: list[dict[str, Any]], snapshot_id: str, scenario_input: dict[str, Any], rule_version: str) -> list[dict[str, Any]]:
    """Append an immutable version-pinned snapshot; identical IDs are idempotent."""
    if not isinstance(queue, list) or not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError("snapshot:id_and_queue_required")
    if not isinstance(scenario_input, dict) or not isinstance(rule_version, str) or not rule_version.strip():
        raise ValueError("snapshot:scenario_and_rule_version_required")
    body = deepcopy(scenario_input)
    digest = _input_hash(body)
    existing = next((item for item in queue if item.get("snapshot_id") == snapshot_id), None)
    if existing:
        if existing.get("input_sha256") != digest or existing.get("rule_version") != rule_version:
            raise ValueError("snapshot:idempotency_conflict")
        return deepcopy(queue)
    return deepcopy(queue) + [{"snapshot_id": snapshot_id, "scenario_input": body,
                               "rule_version": rule_version, "input_sha256": digest, "status": "pending"}]


def sync_snapshot(snapshot: dict[str, Any], server_rule_version: str, *, resolution: str | None = None,
                  actor: str | None = None, reason: str | None = None) -> dict[str, Any]:
    """Version conflict remains pending until a person explicitly resolves it."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot:object_required")
    result = deepcopy(snapshot)
    body = result.get("scenario_input")
    if not isinstance(body, dict) or result.get("input_sha256") != _input_hash(body):
        result["status"] = "snapshot_integrity_error"
        return result
    if result.get("rule_version") == server_rule_version:
        result["status"] = "ready_to_recompute"
        return result
    if resolution is None:
        result["status"] = "version_conflict"
        result["server_rule_version"] = server_rule_version
        return result
    if resolution not in ("keep_snapshot", "rebase_to_server"):
        raise ValueError("resolution:unsupported")
    if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
        raise ValueError("resolution:actor_and_reason_required")
    result["status"] = "ready_to_recompute" if resolution == "rebase_to_server" else "ready_with_pinned_version"
    result["resolution"] = {"choice": resolution, "actor": actor.strip(), "reason": reason.strip(),
                            "old_version": result["rule_version"], "new_version": server_rule_version}
    if resolution == "rebase_to_server":
        result["rule_version"] = server_rule_version
        if "rule_version" in result["scenario_input"]:
            result["scenario_input"]["rule_version"] = server_rule_version
        result["input_sha256"] = _input_hash(result["scenario_input"])
    return result


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    from . import e07
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    result = e07.run(scenario)
    result["engine_id"] = ENGINE_ID
    result["trace"].insert(0, {"stage": "offline_snapshot", "rule_version_pinned": result["rule_version"],
                               "sync_requires_explicit_conflict_resolution": True})
    return result
