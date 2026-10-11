"""E18: auditable calculation trace trees whose leaves produce the labor totals."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from .contract import reference_labor

ENGINE_ID = "e18_calculation_trace_tree"
RULE_VERSION = "e18-trace-tree-v1"
SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。"
_NULL_RANGE = {"low": None, "typical": None, "high": None}
_ZERO_RANGE = {"low": 0.0, "typical": 0.0, "high": 0.0}


def _hash(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _range(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"low", "typical", "high"}:
        return False
    vals = [value[key] for key in ("low", "typical", "high")]
    if all(value is None for value in vals):
        return True
    return (all(isinstance(number, (int, float)) and not isinstance(number, bool)
                and number >= 0 and number < float("inf") for number in vals)
            and vals[0] <= vals[1] <= vals[2])


def _add_ranges(values: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not values:
        return dict(_ZERO_RANGE)
    for value in values:
        if not _range(value):
            raise ValueError("trace:invalid_range")
    if any(value["typical"] is None for value in values):
        return dict(_NULL_RANGE)
    return {key: round(sum(value[key] for value in values), 10)
            for key in ("low", "typical", "high")}


def _pair_sum(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {key: _add_ranges([item[key] for item in results])
            for key in ("person_hours", "elapsed_hours")}


def evaluate_tree(trace_tree: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate only the two declarative node rules supported by this engine."""
    if not isinstance(trace_tree, dict):
        raise ValueError("trace:node_must_be_object")
    rule = trace_tree.get("rule")
    children = trace_tree.get("children")
    if not isinstance(children, list):
        raise ValueError("trace:children_must_be_list")
    if rule == "operation_contribution":
        if children:
            raise ValueError("trace:leaf_cannot_have_children")
        result = trace_tree.get("result")
        if (not isinstance(result, dict) or not _range(result.get("person_hours"))
                or not _range(result.get("elapsed_hours"))):
            raise ValueError("trace:invalid_leaf_result")
        return deepcopy(result)
    if rule == "sum_children":
        return _pair_sum([evaluate_tree(child) for child in children])
    raise ValueError("trace:unsupported_rule")


def _pointer_get(value: Any, pointer: str) -> Any:
    """Resolve a JSON pointer; references cannot call code or access attributes."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("trace:invalid_input_ref")
    current = value
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                raise KeyError(pointer)
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(pointer)
    return current


def _input_refs(scenario: Dict[str, Any], operation_id: Optional[str], row: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    operations = scenario.get("operations", [])
    op_index = next((i for i, op in enumerate(operations)
                     if isinstance(op, dict) and op.get("operation_id") == operation_id), None)

    def add(path: str, source: Any = None, status: Any = None) -> None:
        try:
            value = deepcopy(_pointer_get(scenario, path))
        except (KeyError, ValueError):
            value = None
        refs.append({"path": path, "value": value, "source": source, "status": status})

    if operation_id == "base_service":
        if op_index is not None:
            op = operations[op_index]
            add(f"/operations/{op_index}/hours", op.get("source"), op.get("status"))
        included_index = next((i for i, op in enumerate(operations)
                               if isinstance(op, dict) and op.get("operation_id") == "included_carry"), None)
        if included_index is not None:
            op = operations[included_index]
            add(f"/operations/{included_index}/hours", op.get("source"), op.get("status"))
    elif operation_id == "rotor_seizure":
        for field in ("rotor_relevance", "rotor_seizure_hours"):
            obs = (scenario.get("fields") or {}).get(field)
            add(f"/fields/{field}", obs.get("source") if isinstance(obs, dict) else None,
                obs.get("status") if isinstance(obs, dict) else "unknown")
        approval = (scenario.get("metadata") or {}).get("approved_condition_widths", {}).get("rotor_seizure_hours")
        add("/metadata/approved_condition_widths/rotor_seizure_hours", "human_approval_audit",
            "approved" if isinstance(approval, dict) else "missing")
    elif op_index is not None:
        op = operations[op_index]
        for field in (("elapsed_hours", "duration_hours", "hours") if row.get("status") == "wait"
                      else ("hours_per_person", "person_count") if operation_id == "replacement_carry"
                      else ("hours", "duration_hours")):
            if field in op:
                add(f"/operations/{op_index}/{field}", op.get("source"), op.get("status"))
    return refs


def _leaf_result(row: Dict[str, Any], scenario: Dict[str, Any], blocking: bool) -> Tuple[Dict[str, Any], str]:
    operation_id = row.get("operation_id")
    if blocking or row.get("status") == "missing-required":
        return {"person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE)}, "required_evidence_stop"
    person = deepcopy(row.get("hours", _ZERO_RANGE))
    if row.get("status") == "wait":
        elapsed = deepcopy(row.get("elapsed_hours", _NULL_RANGE))
        return {"person_hours": dict(_ZERO_RANGE), "elapsed_hours": elapsed}, "wait_elapsed_only"
    if operation_id == "replacement_carry":
        op = next((item for item in scenario.get("operations", [])
                   if item.get("operation_id") == "replacement_carry"), {})
        elapsed_value = op.get("hours_per_person")
        elapsed = dict(_NULL_RANGE) if elapsed_value is None else {
            "low": elapsed_value, "typical": elapsed_value, "high": elapsed_value}
        return {"person_hours": person, "elapsed_hours": elapsed}, "person_count_times_duration"
    return {"person_hours": person, "elapsed_hours": deepcopy(person)}, {
        "base_service": "deduplicated_base_less_included_credit",
        "included_carry": "included_credit_excluded_from_additional_labor",
        "wash": "performed_nonbillable_work_retained",
        "rotor_seizure": "approved_condition_range",
    }.get(operation_id, "operation_duration_as_elapsed")


def build_trace_tree(scenario_input: Dict[str, Any], rule_version: Optional[str] = None) -> Dict[str, Any]:
    """Build a reproducible tree from a deep-copied scenario snapshot."""
    if not isinstance(scenario_input, dict):
        raise TypeError("scenario_input must be an object")
    scenario = deepcopy(scenario_input)
    version = rule_version or scenario.get("rule_version")
    if not isinstance(version, str) or not version.strip():
        version = "unbound"
    input_hash = _hash(scenario)
    labor, canonical_rows, unknowns = reference_labor(scenario)
    fields = scenario.get("fields") or {}
    if not isinstance(scenario.get("rule_version"), str) or not scenario.get("rule_version", "").strip():
        unknowns = list(dict.fromkeys([*unknowns, "rule_version:required_for_replay"] ))
    for field in ("work_scope", "included_operations", "subframe_relevance"):
        observation = fields.get(field)
        if not isinstance(observation, dict) or not observation.get("source"):
            unknowns = list(dict.fromkeys([*unknowns, f"{field}:evidence_source_required"] ))
    for operation in scenario.get("operations", []):
        if isinstance(operation, dict) and operation.get("operation_id") in {
            "base_service", "included_carry", "replacement_carry", "snow_melt",
            "penetrant_wait", "parts_wait", "wash"
        } and not operation.get("source"):
            unknowns = list(dict.fromkeys([*unknowns, f"{operation['operation_id']}:evidence_source_required"] ))
    subframe = fields.get("subframe_relevance")
    if not isinstance(subframe, dict) or subframe.get("status") not in ("confirmed", "declared") or subframe.get("value") is None:
        unknowns = list(dict.fromkeys([*unknowns, "subframe_relevance:required_not_zero"] ))
    blocking = [item for item in unknowns if not item.endswith(":elapsed_duration_unknown")]
    if blocking:
        labor = _stop_labor(labor, unknowns)
        canonical_rows = labor["breakdown"]

    leaves: List[Dict[str, Any]] = []
    for index, row in enumerate(canonical_rows):
        result, rule = _leaf_result(row, scenario, bool(blocking))
        leaves.append({
            "node_id": f"leaf-{index + 1}-{row.get('operation_id', 'operation')}",
            "rule": "operation_contribution", "rule_version": version,
            "input_hash": input_hash,
            "input_refs": _input_refs(scenario, row.get("operation_id"), row),
            "operation_id": row.get("operation_id"), "operation": row.get("operation"),
            "status": row.get("status"), "reason": row.get("reason"),
            "children": [], "result": result, "calculation": rule,
        })
    computed = _pair_sum([leaf["result"] for leaf in leaves]) if leaves else {
        "person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE)}
    expected = {key: deepcopy(labor[key]) for key in ("person_hours", "elapsed_hours")}
    return {
        "node_id": "labor-root", "rule": "sum_children", "rule_version": version,
        "input_hash": input_hash,
        "input_refs": [{"path": "/basis_unit", "value": scenario.get("basis_unit"), "source": "scenario", "status": "bound"},
                       {"path": "/rule_version", "value": scenario.get("rule_version"), "source": "scenario", "status": "bound"}],
        "children": leaves, "result": computed, "audit_expected": expected,
        "issues": list(dict.fromkeys(unknowns)),
        "labor_breakdown": deepcopy(labor.get("breakdown", [])),
    }


def _stop_labor(labor: Dict[str, Any], unknowns: List[str]) -> Dict[str, Any]:
    stopped = deepcopy(labor)
    stopped["person_hours"] = dict(_NULL_RANGE)
    stopped["elapsed_hours"] = dict(_NULL_RANGE)
    stopped["unknowns"] = list(dict.fromkeys(unknowns))
    for row in stopped.get("breakdown", []):
        row["hours"] = dict(_NULL_RANGE)
        if "elapsed_hours" in row:
            row["elapsed_hours"] = dict(_NULL_RANGE)
        row["status"] = "missing-required"
    return stopped


def inspect_trace(trace_tree: Dict[str, Any], scenario_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Check shape, input links and stored total against a fresh leaf evaluation."""
    issues: List[str] = []
    if not isinstance(trace_tree, dict) or trace_tree.get("rule") != "sum_children":
        return {"valid": False, "issues": ["trace:root_must_sum_children"], "input_hash": None}
    expected_hash = trace_tree.get("input_hash")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        issues.append("trace:input_hash_invalid")
    if scenario_input is not None and _hash(scenario_input) != expected_hash:
        issues.append("trace:input_snapshot_hash_mismatch")
    seen: set = set()
    nodes = [trace_tree] + (trace_tree.get("children") if isinstance(trace_tree.get("children"), list) else [])
    for node in nodes:
        if not isinstance(node, dict):
            issues.append("trace:child_must_be_object")
            continue
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or node_id in seen:
            issues.append("trace:node_id_missing_or_duplicate")
        seen.add(node_id)
        if node.get("rule_version") != trace_tree.get("rule_version"):
            issues.append("trace:rule_version_mismatch")
        if node.get("input_hash") != expected_hash:
            issues.append("trace:node_input_hash_mismatch")
        refs = node.get("input_refs")
        if not isinstance(refs, list):
            issues.append("trace:input_refs_must_be_list")
            continue
        if scenario_input is not None:
            for ref in refs:
                try:
                    actual = _pointer_get(scenario_input, ref.get("path"))
                    if actual != ref.get("value"):
                        issues.append("trace:input_ref_value_mismatch")
                except (KeyError, ValueError, AttributeError):
                    issues.append("trace:input_ref_unresolved")
    try:
        evaluated = evaluate_tree(trace_tree)
        if evaluated != trace_tree.get("result"):
            issues.append("trace:stored_total_differs_from_leaf_sum")
        if evaluated != trace_tree.get("audit_expected"):
            issues.append("trace:leaf_sum_differs_from_labor_audit")
    except (ValueError, TypeError, KeyError) as exc:
        evaluated = None
        issues.append(str(exc))
    return {"valid": not issues, "issues": list(dict.fromkeys(issues)),
            "input_hash": expected_hash, "evaluated": evaluated}


def run(scenario_input: Dict[str, Any], rule_pack: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return the common engine envelope with labor totals audited from tree leaves."""
    if not isinstance(scenario_input, dict):
        raise TypeError("scenario_input must be an object")
    scenario = deepcopy(scenario_input)
    version = scenario.get("rule_version", "unbound")
    tree = build_trace_tree(scenario, version)
    if rule_pack is not None:
        tree["issues"] = list(dict.fromkeys([*tree["issues"], "rule_pack:dynamic_pack_unsupported_by_e18"] ))
        tree["audit_expected"] = {"person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE)}
        tree["result"] = deepcopy(tree["audit_expected"])
        for leaf in tree["children"]:
            leaf["result"] = {"person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE)}
            leaf["status"] = "missing-required"
    labor, _, unknowns = reference_labor(scenario)
    if tree["issues"]:
        unknowns = list(dict.fromkeys([*unknowns, *tree["issues"]]))
    blocking = [item for item in unknowns if not item.endswith(":elapsed_duration_unknown")]
    if blocking:
        labor = _stop_labor(labor, unknowns)
    # The public totals come from evaluated trace leaves, then are checked
    # against canonical contract labor so trace corruption cannot be hidden.
    evaluated = evaluate_tree(tree)
    audit_expected = {key: labor[key] for key in ("person_hours", "elapsed_hours")}
    tree["audit_expected"] = deepcopy(audit_expected)
    audit = inspect_trace(tree, scenario)
    if not audit["valid"]:
        unknowns = list(dict.fromkeys([*unknowns, *audit["issues"]]))
        labor = _stop_labor(labor, unknowns)
        tree["audit_expected"] = {"person_hours": dict(_NULL_RANGE), "elapsed_hours": dict(_NULL_RANGE)}
        tree["result"] = deepcopy(tree["audit_expected"])
        evaluated = deepcopy(tree["result"])
    else:
        labor["person_hours"] = evaluated["person_hours"]
        labor["elapsed_hours"] = evaluated["elapsed_hours"]
    unknowns = list(dict.fromkeys([*labor.get("unknowns", []), *tree["issues"]]))
    labor["unknowns"] = unknowns
    tree["labor_breakdown"] = deepcopy(labor.get("breakdown", []))
    status = "missing-required" if any(not item.endswith(":elapsed_duration_unknown") for item in unknowns) else (
        "partial" if unknowns else "proposed")
    operation_keys = list(dict.fromkeys(row.get("operation_id", row.get("operation", ""))
                                        for row in labor.get("breakdown", [])))
    approvals = [row["approval"] for row in labor.get("breakdown", []) if isinstance(row.get("approval"), dict)]
    trace = [{"event": "trace_tree_built", "input_hash": tree["input_hash"], "tree": tree},
             {"event": "trace_audit", "valid": audit["valid"], "issues": audit["issues"],
              "tree_sum": evaluated, "labor_sum": audit_expected}]
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": status,
            "labor": labor, "trace": trace, "operation_keys": operation_keys,
            "approvals": approvals, "simulator_notice": SIMULATOR_NOTICE}
