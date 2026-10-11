"""E08: extensible method registry over the shared labor contract."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

from .contract import reference_labor, validate_core_contract

ENGINE_ID = "e08_plugin_registry"
RULE_VERSION = "e08-plugin-registry-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"


@dataclass(frozen=True)
class Method:
    """A registered calculator; callables are supplied by trusted Python code."""

    id: str
    requires: tuple[str, ...]
    supports: Callable[[dict[str, Any]], bool | str]
    evaluate: Callable[[dict[str, Any]], dict[str, Any]]


_REGISTRY: dict[str, Method] = {}


def register_method(method: Method) -> None:
    """Register a trusted in-process method. Duplicate and malformed ids fail."""
    if not isinstance(method, Method):
        raise TypeError("method must be a Method")
    if not isinstance(method.id, str) or not method.id.strip():
        raise ValueError("method id must be a non-empty string")
    if method.id in _REGISTRY:
        raise ValueError("method id already registered: " + method.id)
    if not isinstance(method.requires, tuple) or any(not isinstance(x, str) or not x for x in method.requires):
        raise ValueError("requires must be a tuple of non-empty observation paths")
    if not callable(method.supports) or not callable(method.evaluate):
        raise TypeError("supports and evaluate must be callable")
    _REGISTRY[method.id] = method


def registered_method_ids() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def _shared_calculator(scenario: dict[str, Any]) -> dict[str, Any]:
    labor, _, _ = reference_labor(scenario)
    return labor


def _common_support(scenario: dict[str, Any]) -> bool | str:
    if scenario.get("basis_unit") != "person_hour":
        return "basis_unit:person_hour_required"
    if not isinstance(scenario.get("basis_definition"), str) or not scenario["basis_definition"].strip():
        return "basis_definition:required"
    if not isinstance(scenario.get("operations"), list):
        return "operations:list_required"
    return True


for _method_id in ("S01", "S05", "S19"):
    register_method(Method(_method_id, ("basis_unit", "basis_definition", "operations"),
                           _common_support, _shared_calculator))


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _null_labor(unknowns: list[str]) -> dict[str, Any]:
    nulls = {"low": None, "typical": None, "high": None}
    return {"person_hours": dict(nulls), "elapsed_hours": dict(nulls),
            "breakdown": [], "unknowns": list(dict.fromkeys(unknowns))}


def _required_missing(scenario: dict[str, Any], paths: tuple[str, ...]) -> list[str]:
    missing = []
    for path in paths:
        value: Any = scenario
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None or value == "":
            missing.append(path + ":required")
    return missing


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    """Select exactly one registered method and preserve snapshot/version provenance."""
    original = deepcopy(scenario_input)
    snapshot = deepcopy(scenario_input) if isinstance(scenario_input, dict) else {}
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else {}
    method_id = pack.get("method_id", "S01")
    version = pack.get("rule_version", snapshot.get("rule_version", RULE_VERSION))
    trace: list[dict[str, Any]] = [{"event": "registry_snapshot", "engine_id": ENGINE_ID,
                                    "rule_version": version, "input_hash": _hash(original),
                                    "registered_method_ids": list(registered_method_ids())}]
    unknowns: list[str] = []
    method = _REGISTRY.get(method_id) if isinstance(method_id, str) else None
    if rule_pack is not None and not isinstance(rule_pack, dict):
        unknowns.append("rule_pack:object_required")
    if not isinstance(version, str) or not version.strip():
        unknowns.append("rule_version:required")
    if method is None:
        unknowns.append("method_id:unknown_or_unregistered")
    if unknowns:
        labor = _null_labor(unknowns)
        trace.append({"event": "selection_stopped", "reason": unknowns[0]})
        return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
                "labor": labor, "trace": trace, "operation_keys": [], "approvals": [],
                "simulator_notice": SIMULATOR_NOTICE}

    assert method is not None
    missing = _required_missing(snapshot, method.requires)
    if missing:
        unknowns.extend(missing)
    support = method.supports(snapshot)
    if support is not True:
        reason = support if isinstance(support, str) and support else "method:unsupported_input"
        unknowns.append(reason)
    if unknowns:
        labor = _null_labor(unknowns)
        trace.append({"event": "availability_stopped", "method_id": method.id,
                      "reason": unknowns[0], "requires": list(method.requires)})
        return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
                "labor": labor, "trace": trace, "operation_keys": [], "approvals": [],
                "simulator_notice": SIMULATOR_NOTICE}

    trace.append({"event": "method_selected", "method_id": method.id,
                  "requires": list(method.requires), "method_version": version})
    try:
        labor = method.evaluate(deepcopy(snapshot))
    except Exception as exc:  # Plugin failures stop safely; no fallback/averaging.
        unknowns.append("method:evaluate_failed:" + type(exc).__name__)
        labor = _null_labor(unknowns)
        trace.append({"event": "evaluation_stopped", "reason": unknowns[-1]})
        return {"engine_id": ENGINE_ID, "rule_version": version, "status": "missing-required",
                "labor": labor, "trace": trace, "operation_keys": [], "approvals": [],
                "simulator_notice": SIMULATOR_NOTICE}
    if not isinstance(labor, dict):
        unknowns.append("method:evaluate_must_return_labor_object")
    else:
        unknowns.extend(validate_core_contract(labor))
    if unknowns:
        labor = _null_labor(unknowns)
    trace.append({"event": "method_evaluated", "method_id": method.id,
                  "input_hash": _hash(snapshot), "status": "ok" if not unknowns else "invalid_output"})
    if not unknowns:
        unknowns = list(labor.get("unknowns", []))
    blocking = [item for item in unknowns if not item.endswith(":elapsed_duration_unknown")]
    status = "missing-required" if blocking else ("partial" if unknowns else "proposed")
    operation_keys = list(dict.fromkeys(row.get("operation_id") for row in labor.get("breakdown", [])
                                        if row.get("operation_id")))
    approvals = [{"operation_key": row.get("operation_id"), **row["approval"]}
                 for row in labor.get("breakdown", []) if isinstance(row.get("approval"), dict)]
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status,
            "labor": labor, "trace": trace, "operation_keys": operation_keys,
            "approvals": approvals, "simulator_notice": SIMULATOR_NOTICE}
