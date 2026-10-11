"""Shared adapter and registry for the thirty independently inspectable engines."""
from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from typing import Any

ENGINE_IDS = tuple(f"e{i:02d}" for i in range(1, 31))


def run_engine(engine_id: str, scenario_input: dict[str, Any], rule_pack: dict[str, Any] | None = None) -> dict[str, Any]:
    if engine_id not in ENGINE_IDS and engine_id != "integrated":
        raise ValueError(f"unknown engine_id: {engine_id}")
    if not isinstance(scenario_input, dict):
        raise TypeError("scenario_input must be an object")
    module = import_module(f"auto_repair_engine.{engine_id}")
    result = module.run(deepcopy(scenario_input), deepcopy(rule_pack))
    if not isinstance(result, dict):
        raise TypeError(f"{engine_id} must return an engine_result object")
    result.setdefault("scenario_id", scenario_input.get("scenario_id"))
    for key in ("engine_id", "rule_version", "status", "labor", "trace", "operation_keys", "approvals"):
        if key not in result:
            raise ValueError(f"{engine_id} engine_result is missing {key}")
    return result


def compare_engines(scenario_input: dict[str, Any], rule_pack: dict[str, Any] | None = None,
                    engine_ids: tuple[str, ...] = ENGINE_IDS) -> list[dict[str, Any]]:
    """Run each engine against a fresh copy of the same immutable scenario."""
    results: list[dict[str, Any]] = []
    for engine_id in engine_ids:
        result = run_engine(engine_id, deepcopy(scenario_input), deepcopy(rule_pack))
        results.append({"engine_id": engine_id, "labor": result.get("labor"), "status": result.get("status"),
                        "rule_version": result.get("rule_version"), "trace": result.get("trace", [])})
    return results
