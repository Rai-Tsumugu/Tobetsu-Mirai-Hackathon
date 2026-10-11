"""E09: precedence- and worker-constrained labor scheduling."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import isfinite
from typing import Any

from .e07 import run as run_pipeline

ENGINE_ID = "e09_process_dag"
RULE_VERSION = "e09-process-dag-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_NULL_RANGE = {"low": None, "typical": None, "high": None}


def _valid_number(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and value >= 0)


def _stop(version: str, issues: list[str], trace: list[dict[str, Any]]) -> dict[str, Any]:
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
            "labor": {"person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE),
                      "breakdown": [], "unknowns": issues},
            "trace": trace, "operation_keys": [], "approvals": [], "simulator_notice": SIMULATOR_NOTICE}


def _range(raw: Any) -> dict[str, float] | None:
    if _valid_number(raw):
        return {"low": float(raw), "typical": float(raw), "high": float(raw)}
    if isinstance(raw, dict) and set(raw) == {"low", "typical", "high"}:
        values = [raw[k] for k in ("low", "typical", "high")]
        if all(_valid_number(v) for v in values) and values[0] <= values[1] <= values[2]:
            return {k: float(raw[k]) for k in ("low", "typical", "high")}
    return None


def _schedule(nodes: list[dict[str, Any]], edges: list[tuple[str, str]], limit: int,
              durations: dict[str, float]) -> tuple[dict[str, tuple[float, float]], float]:
    """Stable list scheduler; makespan is feasible, not guaranteed optimal."""
    by_id = {n["operation_id"]: n for n in nodes}
    deps = {key: set() for key in by_id}
    children = {key: set() for key in by_id}
    for before, after in edges:
        deps[after].add(before)
        children[before].add(after)
    order = {n["operation_id"]: i for i, n in enumerate(nodes)}
    ready = sorted((key for key, required in deps.items() if not required), key=order.get)
    scheduled: dict[str, tuple[float, float]] = {}
    worker_intervals: list[tuple[float, float, int]] = []
    while ready:
        key = ready.pop(0)
        node = by_id[key]
        start = max((scheduled[dep][1] for dep in deps[key]), default=0.0)
        count = node["person_count"] if node["kind"] == "work" else 0
        duration = durations[key]
        if count:
            while True:
                overlapping = [(a, b, c) for a, b, c in worker_intervals
                               if a < start + duration and start < b]
                conflict_times = sorted({start, *(a for a, b, _ in overlapping if start <= a < start + duration)})
                conflict = next((point for point in conflict_times
                                 if sum(c for a, b, c in overlapping if a <= point < b) + count > limit), None)
                if conflict is None:
                    break
                start = min(b for a, b, c in overlapping if a <= conflict < b)
        finish = start + duration
        scheduled[key] = (start, finish)
        if count and duration:
            worker_intervals.append((start, finish, count))
        newly_ready = [child for child in children[key] if child not in scheduled and child not in ready
                       and deps[child].issubset(scheduled)]
        ready.extend(newly_ready)
        ready.sort(key=order.get)
    return scheduled, max((finish for _, finish in scheduled.values()), default=0.0)


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Use the shared fixture only when no explicit rule pack was supplied."""
    scenario = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    version = scenario.get("rule_version", RULE_VERSION)
    if rule_pack is None:
        result = run_pipeline(scenario_input)
        result["engine_id"] = ENGINE_ID
        result["trace"].append({"stage": "e09_schedule", "mode": "shared_fixture_adapter",
                                "rule_version": version,
                                "note": "No explicit DAG supplied; common fixture calculation retained."})
        return result

    trace: list[dict[str, Any]] = [{"stage": "input_snapshot", "rule_version": version}]
    issues: list[str] = []
    if not isinstance(rule_pack, dict):
        return _stop(version, ["rule_pack:object_required"], trace)
    nodes, raw_edges = rule_pack.get("nodes"), rule_pack.get("edges")
    limit = rule_pack.get("resource_limit")
    if rule_pack.get("engine_id") not in (None, ENGINE_ID):
        issues.append("rule_pack:engine_id_mismatch")
    if rule_pack.get("rule_version") != version:
        issues.append("rule_pack:rule_version_mismatch")
    if rule_pack.get("status", "approved") != "approved":
        issues.append("rule_pack:approved_version_required")
    if not isinstance(nodes, list) or not nodes:
        issues.append("nodes:nonempty_list_required")
        nodes = []
    if not isinstance(raw_edges, list):
        issues.append("edges:list_required")
        raw_edges = []
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        issues.append("resource_limit:positive_integer_required")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    durations: dict[str, dict[str, float] | None] = {}
    for index, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            issues.append(f"nodes[{index}]:object_required")
            continue
        op_id = raw.get("operation_id")
        if not isinstance(op_id, str) or not op_id.strip():
            issues.append(f"nodes[{index}]:operation_id_required")
            continue
        if op_id in seen:
            issues.append(f"{op_id}:duplicate_operation_id")
            continue
        seen.add(op_id)
        kind = raw.get("kind", "work")
        if kind not in ("work", "wait"):
            issues.append(f"{op_id}:kind_must_be_work_or_wait")
            continue
        count = raw.get("person_count", 1 if kind == "work" else 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or (kind == "work" and count == 0):
            issues.append(f"{op_id}:person_count_invalid")
        elif kind == "wait" and count != 0:
            issues.append(f"{op_id}:wait_person_count_must_be_zero")
        if kind == "work" and isinstance(limit, int) and count > limit:
            issues.append(f"{op_id}:worker_capacity_exceeded")
        raw_duration = raw.get("duration_hours")
        duration = _range(raw_duration) if raw_duration is not None else None
        if raw_duration is not None and duration is None:
            issues.append(f"{op_id}:duration_range_invalid")
        elif raw_duration is None and kind == "work":
            issues.append(f"{op_id}:required_person_hour_duration_unknown")
        normalized.append({"operation_id": op_id, "operation": raw.get("operation", op_id),
                           "kind": kind, "person_count": count, "source": raw.get("source"),
                           "reason": raw.get("reason", "Explicit E09 process DAG."),
                           "status": raw.get("status", "proposed")})
        durations[op_id] = duration
    edges: list[tuple[str, str]] = []
    for index, edge in enumerate(raw_edges):
        if isinstance(edge, dict):
            before, after = edge.get("before"), edge.get("after")
        elif isinstance(edge, (list, tuple)) and len(edge) == 2:
            before, after = edge
        else:
            issues.append(f"edges[{index}]:before_after_required")
            continue
        if before not in seen or after not in seen:
            issues.append(f"edges[{index}]:missing_node_reference")
        elif before == after:
            issues.append(f"edges[{index}]:self_cycle")
        else:
            edges.append((before, after))
    if not issues:
        # Detect cycles before scheduling.
        indegree = {key: 0 for key in seen}
        for before, after in edges:
            indegree[after] += 1
        queue = [n["operation_id"] for n in normalized if indegree[n["operation_id"]] == 0]
        visited = 0
        children = {key: [] for key in seen}
        for before, after in edges:
            children[before].append(after)
        while queue:
            current = queue.pop(0)
            visited += 1
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if visited != len(seen):
            issues.append("dag:cycle_detected")
    if issues:
        trace.append({"stage": "validate", "issues": issues, "input_sha256": hashlib.sha256(
            json.dumps(rule_pack, sort_keys=True, default=str).encode()).hexdigest()})
        return _stop(version, issues, trace)

    missing_waits = [node["operation_id"] for node in normalized
                     if node["kind"] == "wait" and durations[node["operation_id"]] is None]
    person_totals: dict[str, float] = {}
    elapsed_totals: dict[str, float | None] = {}
    schedules: dict[str, Any] = {}
    for band in ("low", "typical", "high"):
        known = {key: value[band] for key, value in durations.items() if value is not None}
        if missing_waits:
            person_totals[band] = sum(known[n["operation_id"]] * n["person_count"]
                                      for n in normalized if n["kind"] == "work")
            elapsed_totals[band] = None
            schedules[band] = None
        else:
            scheduled, makespan = _schedule(normalized, edges, limit, known)
            person_totals[band] = sum(known[n["operation_id"]] * n["person_count"]
                                      for n in normalized if n["kind"] == "work")
            elapsed_totals[band] = round(makespan, 10)
            schedules[band] = {key: {"start": round(v[0], 10), "finish": round(v[1], 10)}
                               for key, v in scheduled.items()}
    rows = []
    for node in normalized:
        duration = durations[node["operation_id"]]
        work = node["kind"] == "work"
        rows.append({"operation_id": node["operation_id"], "operation": node["operation"],
                     "hours": ({k: round(duration[k] * node["person_count"], 10) for k in ("low", "typical", "high")}
                               if duration is not None and work else {"low": 0.0, "typical": 0.0, "high": 0.0}),
                     "elapsed_hours": ({k: duration[k] for k in ("low", "typical", "high")} if duration else dict(_NULL_RANGE)),
                     "person_count": node["person_count"], "kind": node["kind"], "reason": node["reason"],
                     "status": "nonbillable-work" if work and node.get("billable") is False else node["status"],
                     "source": node["source"]})
    issues = [f"{key}:elapsed_duration_unknown" for key in missing_waits]
    labor = {"person_hours": {k: round(person_totals[k], 10) for k in person_totals},
             "elapsed_hours": {k: elapsed_totals[k] for k in elapsed_totals},
             "breakdown": rows, "unknowns": issues}
    payload_hash = hashlib.sha256(json.dumps({"scenario": scenario, "rule_pack": rule_pack}, sort_keys=True,
                                              default=str).encode()).hexdigest()
    trace.append({"stage": "schedule", "algorithm": "stable_list_scheduler", "optimality": "not_guaranteed",
                  "resource_limit": limit, "precedence": [list(edge) for edge in edges],
                  "schedules": schedules, "input_sha256": payload_hash, "rule_version": version})
    return {"engine_id": ENGINE_ID, "rule_version": version,
            "status": "partial" if issues else "proposed", "labor": labor, "trace": trace,
            "operation_keys": [n["operation_id"] for n in normalized], "approvals": [],
            "simulator_notice": SIMULATOR_NOTICE}
