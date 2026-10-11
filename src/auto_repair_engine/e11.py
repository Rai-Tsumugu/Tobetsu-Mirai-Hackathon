"""E11: compare independently calculated methods and require an audited choice."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from . import e08
from . import e07
from .contract import validate_core_contract

ENGINE_ID = "e11_independent_method_comparison"
RULE_VERSION = "e11-independent-method-comparison-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
DEFAULT_METHODS = ("A", "B")
UNAVAILABLE_METHODS = {"C": "method_C:not_implemented"}
_NULL = {"low": None, "typical": None, "high": None}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _stopped(unknowns: list[str]) -> dict[str, Any]:
    return {"person_hours": dict(_NULL), "elapsed_hours": dict(_NULL),
            "breakdown": [], "unknowns": list(dict.fromkeys(unknowns))}


def compare_methods(scenario_input: dict, methods: list[str] | tuple[str, ...] | None = None,
                    rule_version: str = RULE_VERSION) -> dict[str, Any]:
    """Evaluate each available method on a fresh immutable copy; expose gaps separately."""
    method_ids = list(DEFAULT_METHODS if methods is None else methods) if methods is None or isinstance(methods, (list, tuple)) else None
    if method_ids is None or not method_ids or any(not isinstance(x, str) or not x for x in method_ids):
        return {"runs": [], "unavailable": deepcopy(UNAVAILABLE_METHODS),
                "unknowns": ["methods:non_empty_method_id_list_required"]}
    if len(method_ids) != len(set(method_ids)):
        return {"runs": [], "unavailable": deepcopy(UNAVAILABLE_METHODS),
                "unknowns": ["methods:duplicate_method_id"]}
    runs = []
    unavailable = deepcopy(UNAVAILABLE_METHODS)
    for method_id in method_ids:
        if method_id == "A":
            result = e07.run(deepcopy(scenario_input), {})
            labor = deepcopy(result["labor"])
            runs.append({"method": method_id, "labor": labor,
                         "evidence": [{"operation_id": row.get("operation_id"), "source": row.get("source"),
                                       "status": row.get("status")} for row in labor.get("breakdown", [])],
                         "unknowns": list(labor.get("unknowns", [])) + validate_core_contract(labor),
                         "status": result["status"], "rule_version": result["rule_version"],
                         "input_hash": _hash(scenario_input)})
            continue
        if method_id == "B":
            result = e08.run(deepcopy(scenario_input), {"method_id": "S01", "rule_version": rule_version})
            labor = deepcopy(result["labor"])
            runs.append({"method": method_id, "labor": labor,
                         "evidence": [{"operation_id": row.get("operation_id"), "source": row.get("source"),
                                       "status": row.get("status")} for row in labor.get("breakdown", [])],
                         "unknowns": list(labor.get("unknowns", [])) + validate_core_contract(labor),
                         "status": result["status"], "rule_version": result["rule_version"],
                         "input_hash": _hash(scenario_input)})
            continue
        if method_id not in e08.registered_method_ids():
            unavailable[method_id] = "method:not_registered_or_unavailable"
            continue
        result = e08.run(deepcopy(scenario_input), {"method_id": method_id, "rule_version": rule_version})
        labor = deepcopy(result["labor"])
        issues = validate_core_contract(labor)
        evidence = [{"operation_id": row.get("operation_id"), "source": row.get("source"),
                     "status": row.get("status")} for row in labor.get("breakdown", [])]
        runs.append({"method": method_id, "labor": labor, "evidence": evidence,
                     "unknowns": list(labor.get("unknowns", [])) + issues,
                     "status": result["status"], "rule_version": result["rule_version"],
                     "input_hash": _hash(scenario_input)})
    result = {"runs": runs, "unavailable": unavailable, "unknowns": [],
              "input_snapshot": deepcopy(scenario_input), "rule_version": rule_version}
    result["comparison_hash"] = _hash({key: value for key, value in result.items() if key != "comparison_hash"})
    return result


def select_method(comparison: dict, selected_method: str, actor: str, reason: str,
                  scenario_input: dict | None = None, rule_version: str | None = None) -> dict[str, Any]:
    """Return selected run only when it is available, complete, and human-audited."""
    if not isinstance(comparison, dict):
        return {"labor": _stopped(["comparison:object_required"]), "selection": None}
    runs = comparison.get("runs")
    if not isinstance(runs, list):
        return {"labor": _stopped(["comparison:runs_required"]), "selection": None}
    expected_hash = comparison.get("comparison_hash")
    found = next((row for row in runs if isinstance(row, dict) and row.get("method") == selected_method), None)
    if found is None:
        return {"labor": _stopped(["selected_method:unavailable_or_missing"]), "selection": None}
    stored_input = comparison.get("input_snapshot")
    actual_hash = _hash({key: value for key, value in comparison.items() if key != "comparison_hash"})
    if not isinstance(expected_hash, str) or expected_hash != actual_hash:
        return {"labor": _stopped(["comparison:payload_tampered"]), "selection": None}
    if not isinstance(stored_input, dict) or (scenario_input is not None and _hash(scenario_input) != _hash(stored_input)):
        return {"labor": _stopped(["comparison:input_binding_invalid"]), "selection": None}
    effective_version = rule_version if rule_version is not None else comparison.get("rule_version", RULE_VERSION)
    if effective_version != comparison.get("rule_version"):
        return {"labor": _stopped(["comparison:rule_version_binding_invalid"]), "selection": None}
    if found.get("rule_version") != effective_version and selected_method != "A":
        return {"labor": _stopped(["comparison:selected_result_tampered"]), "selection": None}
    if found.get("input_hash") != _hash(stored_input):
        return {"labor": _stopped(["comparison:input_hash_invalid"]), "selection": None}
    fresh = compare_methods(deepcopy(stored_input), list(DEFAULT_METHODS), effective_version)
    recalculated = next((row for row in fresh["runs"] if row.get("method") == selected_method), None)
    if recalculated is None or recalculated.get("input_hash") != found.get("input_hash"):
        return {"labor": _stopped(["comparison:selected_result_tampered"]), "selection": None}
    if not found.get("unknowns") and _hash(recalculated) != _hash(found):
        return {"labor": _stopped(["comparison:selected_result_tampered"]), "selection": None}
    if found.get("unknowns") or found.get("status") not in ("proposed", "partial"):
        return {"labor": _stopped(["selected_method:evidence_incomplete"] + list(found.get("unknowns", []))),
                "selection": None}
    if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
        return {"labor": _stopped(["selection:actor_and_reason_required"]), "selection": None}
    return {"labor": deepcopy(recalculated["labor"]),
            "selection": {"method": selected_method, "actor": actor, "reason": reason,
                          "original_alternatives": deepcopy(runs),
                          "unavailable": deepcopy(comparison.get("unavailable", {}))}}


def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    original = deepcopy(scenario_input)
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else {}
    version = pack.get("rule_version", RULE_VERSION)
    methods = pack.get("methods", list(DEFAULT_METHODS))
    comparison = compare_methods(deepcopy(scenario_input), methods, version)
    trace = [{"event": "independent_method_comparison", "input_snapshot": deepcopy(original),
              "method_runs": deepcopy(comparison["runs"]), "unavailable": deepcopy(comparison["unavailable"]),
              "rule_version": version}]
    issues = list(comparison["unknowns"])
    if not isinstance(version, str) or not version.strip():
        issues.append("rule_version:required")
    choice = pack.get("selected_method")
    selection = None
    if choice is None:
        issues.append("selected_method:human_choice_required")
        labor = _stopped(issues)
    else:
        selection_result = select_method(comparison, choice, pack.get("actor"), pack.get("reason"),
                                         original, version)
        selection = selection_result["selection"]
        labor = selection_result["labor"]
        if selection is None:
            issues.extend(labor["unknowns"])
        else:
            issues.extend(labor.get("unknowns", []))
            trace.append({"event": "method_selected", "method": choice, "actor": selection["actor"],
                          "reason": selection["reason"]})
    blocking = [item for item in issues if not item.endswith(":elapsed_duration_unknown")]
    status = "missing-required" if blocking else ("partial" if issues else "proposed")
    if blocking and any(v is not None for v in labor["person_hours"].values()):
        labor = _stopped(issues)
    elif issues:
        labor["unknowns"] = list(dict.fromkeys(issues))
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status, "labor": labor,
            "trace": trace, "operation_keys": list(dict.fromkeys(row.get("operation_id") for row in labor.get("breakdown", []) if row.get("operation_id"))),
            "approvals": [], "simulator_notice": SIMULATOR_NOTICE, "selection": selection,
            "method_runs": comparison["runs"], "unavailable_methods": comparison["unavailable"]}
