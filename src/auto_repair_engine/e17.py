"""E17: append-only observation events with a deterministic current-state reducer."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from .contract import reference_labor

ENGINE_ID = "e17_observation_events"
RULE_VERSION = "e17-observation-events-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_FIELDS = {"rotor_relevance", "rotor_seizure_hours", "subframe_relevance",
           "parts_wait_stock_checked", "snow_observation"}
_NULL = {"low": None, "typical": None, "high": None}


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _valid_value(target: str, value: Any) -> bool:
    if target in {"rotor_relevance", "subframe_relevance"}:
        return value in {"relevant", "unrelated"}
    if target == "parts_wait_stock_checked":
        return isinstance(value, bool)
    if target == "snow_observation":
        return value in {"present", "absent"}
    if target == "rotor_seizure_hours":
        if not isinstance(value, dict) or set(value) != {"low", "typical", "high"}:
            return False
        values = [value[key] for key in ("low", "typical", "high")]
        return all(isinstance(number, (int, float)) and not isinstance(number, bool) and number >= 0
                   for number in values) and values[0] <= values[1] <= values[2]
    return False


def append_observation_event(events: list[dict[str, Any]], target: str, value: Any,
                             actor: str, reason: str, observed_at: str,
                             event_id: str, supersedes: str | None = None,
                             status: str = "confirmed", source: str = "direct_observation") -> list[dict[str, Any]]:
    """Return a new event list with one validated, auditable observation."""
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        raise ValueError("events:list_of_objects_required")
    if target not in _FIELDS:
        raise ValueError("event:unknown_target")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event:id_required")
    if any(event.get("id") == event_id for event in events):
        raise ValueError("event:duplicate_id")
    if supersedes is not None:
        prior = next((event for event in events if event.get("id") == supersedes), None)
        if prior is None:
            raise ValueError("event:unknown_supersedes")
        if prior.get("target") != target:
            raise ValueError("event:supersedes_target_mismatch")
    if status not in {"confirmed", "pending"}:
        raise ValueError("event:invalid_status")
    if status == "confirmed":
        if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("event:confirmed_actor_reason_required")
        if not _valid_date(observed_at):
            raise ValueError("event:confirmed_date_required")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("event:confirmed_source_required")
        if not _valid_value(target, value):
            raise ValueError("event:invalid_confirmed_value")
    event = {"id": event_id.strip(), "target": target, "value": deepcopy(value),
             "supersedes": supersedes, "actor": actor.strip() if isinstance(actor, str) else None,
             "reason": reason.strip() if isinstance(reason, str) else None,
             "observed_at": observed_at, "source": source, "status": status}
    return [*deepcopy(events), event]


def reduce_observations(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate event references and return the latest confirmed event per target."""
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        raise ValueError("events:list_of_objects_required")
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id.strip() or event_id in by_id:
            raise ValueError("event:duplicate_or_missing_id")
        target = event.get("target")
        if target not in _FIELDS:
            raise ValueError("event:unknown_target")
        if event.get("status") not in {"pending", "confirmed"}:
            raise ValueError("event:invalid_status")
        if event["status"] == "confirmed":
            if (not isinstance(event.get("actor"), str) or not event["actor"].strip()
                    or not isinstance(event.get("reason"), str) or not event["reason"].strip()
                    or not isinstance(event.get("source"), str) or not event["source"].strip()
                    or not _valid_date(event.get("observed_at"))):
                raise ValueError("event:confirmed_audit_required")
            if not _valid_value(target, event.get("value")):
                raise ValueError("event:invalid_confirmed_value")
        by_id[event_id] = event
    superseded: set[str] = set()
    for event in events:
        prior_id = event.get("supersedes")
        if prior_id is None:
            continue
        prior = by_id.get(prior_id)
        if prior is None:
            raise ValueError("event:unknown_supersedes")
        if prior.get("target") != event.get("target"):
            raise ValueError("event:supersedes_target_mismatch")
        if prior_id in superseded:
            raise ValueError("event:sequence_ambiguity")
        superseded.add(prior_id)
    # Supersedes edges must form disjoint linear chains; reject cycles even if no root is present.
    for event_id in by_id:
        seen: set[str] = set()
        cursor = event_id
        while cursor in by_id and by_id[cursor].get("supersedes") is not None:
            if cursor in seen:
                raise ValueError("event:revision_cycle")
            seen.add(cursor)
            cursor = by_id[cursor]["supersedes"]
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("status") not in {"pending", "confirmed"}:
            raise ValueError("event:invalid_status")
        if event["id"] in superseded or event.get("status") != "confirmed":
            continue
        if not _valid_value(event["target"], event.get("value")):
            raise ValueError("event:invalid_confirmed_value")
        current = latest.get(event["target"])
        if current is not None:
            # Two active heads for one target means the event history forked.
            raise ValueError("event:sequence_ambiguity")
        latest[event["target"]] = deepcopy(event)
    return latest


def _fixture_events() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    values = [("rotor_relevance", "unrelated"), ("subframe_relevance", "unrelated"),
              ("parts_wait_stock_checked", True), ("snow_observation", "present")]
    for index, (target, value) in enumerate(values, 1):
        rows = append_observation_event(rows, target, value, "fictional_technician",
                                        "fictional common fixture observation", "2026-10-11T10:00:00+09:00",
                                        "fixture-%02d" % index)
    return rows


def _null_labor(unknowns: list[str]) -> dict[str, Any]:
    return {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL), "breakdown": [],
            "unknowns": list(dict.fromkeys(unknowns))}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else None
    version = scenario.get("rule_version") or RULE_VERSION
    events = pack.get("events") if pack is not None else []
    issues: list[str] = []
    if not isinstance(scenario_input, dict):
        issues.append("scenario_input:object_required")
    if rule_pack is not None and pack is None:
        issues.append("rule_pack:object_required")
    if pack is not None:
        if set(pack) - {"engine_id", "rule_version", "events"}:
            issues.append("rule_pack:unknown_key")
        if pack.get("engine_id") not in (None, ENGINE_ID, "e17"):
            issues.append("rule_pack:engine_id_mismatch")
        if pack.get("rule_version") and scenario.get("rule_version") and pack["rule_version"] != scenario["rule_version"]:
            issues.append("rule_pack:pinned_version_mismatch")
        version = pack.get("rule_version") or version
    try:
        reduced = reduce_observations(events)
    except (ValueError, TypeError) as exc:
        reduced = {}
        issues.append(str(exc))
    # Required condition facts are adopted only from confirmed event heads.
    fields = scenario.setdefault("fields", {})
    if not isinstance(fields, dict):
        issues.append("scenario_input:fields_must_be_object")
        fields = {}
    for target in _FIELDS:
        event = reduced.get(target)
        if event is not None:
            fields[target] = {"value": deepcopy(event["value"]), "status": "confirmed",
                              "source": event["source"], "confirmed_at": event["observed_at"]}
    for operation in scenario.get("operations", []):
        if operation.get("operation_id") == "parts_wait":
            stock = fields.get("parts_wait_stock_checked", {})
            operation["stock_checked"] = isinstance(stock, dict) and stock.get("value") is True and stock.get("status") == "confirmed"
        if operation.get("operation_id") == "snow_melt":
            snow = fields.get("snow_observation", {})
            if isinstance(snow, dict) and snow.get("status") == "confirmed" and snow.get("value") == "absent":
                operation["hours"] = operation["elapsed_hours"] = 0.0
                operation["source"] = "e17_confirmed_snow_absent"
    approvals = [{"type": "observation_event", "id": event["id"], "target": event["target"],
                  "actor": event["actor"], "reason": event["reason"], "old_value": None,
                  "new_value": deepcopy(event["value"]), "observed_at": event["observed_at"],
                  "source": event["source"]} for event in reduced.values()]
    # Revisions retain both immutable records while audit links the prior value.
    by_id = {event.get("id"): event for event in events if isinstance(event, dict)} if isinstance(events, list) else {}
    for approval in approvals:
        current = by_id.get(approval["id"], {})
        prior = by_id.get(current.get("supersedes"))
        if prior:
            approval["old_value"] = deepcopy(prior.get("value"))
    if issues:
        labor = _null_labor(issues)
        status = "missing-required"
    else:
        labor, _, _ = reference_labor(scenario)
        blocking = [item for item in labor.get("unknowns", []) if not item.endswith(":elapsed_duration_unknown")]
        status = "missing-required" if blocking else ("partial" if labor.get("unknowns") else "proposed")
        if blocking:
            for key in ("person_hours", "elapsed_hours"):
                labor[key] = dict(_NULL)
            for row in labor.get("breakdown", []):
                row["hours"] = dict(_NULL)
                row["status"] = "missing-required"
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status, "labor": labor,
            "trace": [{"event": "observation_events_reduced", "event_ids": [e.get("id") for e in events],
                       "confirmed_targets": sorted(reduced)}],
            "operation_keys": [row.get("operation_id") for row in labor.get("breakdown", []) if row.get("operation_id")],
            "approvals": approvals, "simulator_notice": SIMULATOR_NOTICE}
