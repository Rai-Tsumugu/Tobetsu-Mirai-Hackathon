/* eslint-disable @typescript-eslint/no-explicit-any */
// E18: auditable calculation trace trees whose leaves produce the labor totals. 元: e18.py
import {
  type Dict, PyAttributeError, PyKeyError, PyTypeError, PyValueError, dedupe, deepcopy, get, isDict, isList, isNumber, isStr, keysAre, or, pyEq, pyRound, pySum, repr, truthy,
} from "./py";
import { BANDS, referenceLabor } from "./contract";
import * as e07 from "./e07";

export const ENGINE_ID = "e18_calculation_trace_tree";
export const RULE_VERSION = "e18-trace-tree-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const nullRange = () => ({ low: null, typical: null, high: null });
const zeroRange = () => ({ low: 0.0, typical: 0.0, high: 0.0 });
const hashOf = e07.hashOf;

function isRange(value: any): boolean {
  if (!isDict(value) || !keysAre(value, [...BANDS])) return false;
  const vals = BANDS.map((k) => value[k]);
  if (vals.every((v) => v === null)) return true;
  return vals.every((n) => isNumber(n) && n >= 0 && n < Infinity) && vals[0] <= vals[1] && vals[1] <= vals[2];
}

function addRanges(values: Dict[]): Dict {
  if (!values.length) return zeroRange();
  for (const value of values) if (!isRange(value)) throw new PyValueError("trace:invalid_range");
  if (values.some((v) => v.typical === null)) return nullRange();
  return Object.fromEntries(BANDS.map((key) => [key, pyRound(pySum(values.map((v) => v[key])), 10)]));
}

function pairSum(results: Dict[]): Dict {
  return Object.fromEntries(["person_hours", "elapsed_hours"].map((key) => [key, addRanges(results.map((r) => r[key]))]));
}

/** Evaluate only the two declarative node rules supported by this engine. */
export function evaluateTree(traceTree: any): Dict {
  if (!isDict(traceTree)) throw new PyValueError("trace:node_must_be_object");
  const rule = get(traceTree, "rule");
  const children = get(traceTree, "children");
  if (!isList(children)) throw new PyValueError("trace:children_must_be_list");
  if (rule === "operation_contribution") {
    if (children.length) throw new PyValueError("trace:leaf_cannot_have_children");
    const result = get(traceTree, "result");
    if (!isDict(result) || !isRange(get(result, "person_hours")) || !isRange(get(result, "elapsed_hours"))) throw new PyValueError("trace:invalid_leaf_result");
    return deepcopy(result);
  }
  if (rule === "sum_children") return pairSum(children.map((c) => evaluateTree(c)));
  throw new PyValueError("trace:unsupported_rule");
}

/** Resolve a JSON pointer; references cannot call code or access attributes. */
function pointerGet(value: any, pointer: any): any {
  if (!isStr(pointer) || !pointer.startsWith("/")) throw new PyValueError("trace:invalid_input_ref");
  let current = value;
  for (const rawPart of pointer.replace(/^\/+/, "").split("/")) {
    const part = rawPart.replace(/~1/g, "/").replace(/~0/g, "~");
    if (isList(current)) {
      if (!/^[0-9]+$/.test(part) || Number(part) >= current.length) throw new PyKeyError(pointer);
      current = current[Number(part)];
    } else if (isDict(current) && Object.prototype.hasOwnProperty.call(current, part) && current[part] !== undefined) {
      current = current[part];
    } else {
      throw new PyKeyError(pointer);
    }
  }
  return current;
}

function inputRefs(scenario: Dict, operationId: any, row: Dict): Dict[] {
  const refs: Dict[] = [];
  const operations: any[] = get(scenario, "operations", []);
  const findIndex = (id: any) => {
    const i = operations.findIndex((op) => isDict(op) && get(op, "operation_id") === id);
    return i < 0 ? null : i;
  };
  const opIndex = findIndex(operationId);
  const add = (path: string, source: any = null, status: any = null) => {
    let value: any;
    try {
      value = deepcopy(pointerGet(scenario, path));
    } catch (e) {
      if (e instanceof PyKeyError || e instanceof PyValueError) value = null;
      else throw e;
    }
    refs.push({ path, value, source, status });
  };
  if (operationId === "base_service") {
    if (opIndex !== null) {
      const op = operations[opIndex];
      add(`/operations/${opIndex}/hours`, get(op, "source"), get(op, "status"));
    }
    const includedIndex = findIndex("included_carry");
    if (includedIndex !== null) {
      const op = operations[includedIndex];
      add(`/operations/${includedIndex}/hours`, get(op, "source"), get(op, "status"));
    }
  } else if (operationId === "rotor_seizure") {
    for (const field of ["rotor_relevance", "rotor_seizure_hours"]) {
      const obs = get(or(get(scenario, "fields"), {}), field);
      add(`/fields/${field}`, isDict(obs) ? get(obs, "source") : null, isDict(obs) ? get(obs, "status") : "unknown");
    }
    const approval = get(get(or(get(scenario, "metadata"), {}), "approved_condition_widths", {}), "rotor_seizure_hours");
    add("/metadata/approved_condition_widths/rotor_seizure_hours", "human_approval_audit", isDict(approval) ? "approved" : "missing");
  } else if (opIndex !== null) {
    const op = operations[opIndex];
    const fieldList = get(row, "status") === "wait" ? ["elapsed_hours", "duration_hours", "hours"] : operationId === "replacement_carry" ? ["hours_per_person", "person_count"] : ["hours", "duration_hours"];
    for (const field of fieldList) if (field in op) add(`/operations/${opIndex}/${field}`, get(op, "source"), get(op, "status"));
  }
  return refs;
}

const LEAF_RULES: Record<string, string> = {
  base_service: "deduplicated_base_less_included_credit",
  included_carry: "included_credit_excluded_from_additional_labor",
  wash: "performed_nonbillable_work_retained",
  rotor_seizure: "approved_condition_range",
};

function leafResult(row: Dict, scenario: Dict, blocking: boolean): [Dict, string] {
  const operationId = get(row, "operation_id");
  if (blocking || get(row, "status") === "missing-required") return [{ person_hours: nullRange(), elapsed_hours: nullRange() }, "required_evidence_stop"];
  const person = deepcopy(get(row, "hours", zeroRange()));
  if (get(row, "status") === "wait") {
    const elapsed = deepcopy(get(row, "elapsed_hours", nullRange()));
    return [{ person_hours: zeroRange(), elapsed_hours: elapsed }, "wait_elapsed_only"];
  }
  if (operationId === "replacement_carry") {
    const op = get(scenario, "operations", []).find((item: Dict) => get(item, "operation_id") === "replacement_carry") ?? {};
    const elapsedValue = get(op, "hours_per_person");
    const elapsed = elapsedValue === null ? nullRange() : { low: elapsedValue, typical: elapsedValue, high: elapsedValue };
    return [{ person_hours: person, elapsed_hours: elapsed }, "person_count_times_duration"];
  }
  const rule = isStr(operationId) && Object.prototype.hasOwnProperty.call(LEAF_RULES, operationId) ? LEAF_RULES[operationId] : "operation_duration_as_elapsed";
  return [{ person_hours: person, elapsed_hours: deepcopy(person) }, rule];
}

function stopLabor(labor: Dict, unknowns: string[]): Dict {
  const stopped = deepcopy(labor);
  stopped.person_hours = nullRange();
  stopped.elapsed_hours = nullRange();
  stopped.unknowns = dedupe(unknowns);
  for (const row of get(stopped, "breakdown", [])) {
    row.hours = nullRange();
    if ("elapsed_hours" in row) row.elapsed_hours = nullRange();
    row.status = "missing-required";
  }
  return stopped;
}

/** Build a reproducible tree from a deep-copied scenario snapshot. */
export function buildTraceTree(scenarioInput: any, ruleVersion: any = null): Dict {
  if (!isDict(scenarioInput)) throw new PyTypeError("scenario_input must be an object");
  const scenario = deepcopy(scenarioInput);
  let version: any = or(ruleVersion, get(scenario, "rule_version"));
  if (!isStr(version) || !version.trim()) version = "unbound";
  const inputHash = hashOf(scenario);
  let [labor, canonicalRows, unknowns] = referenceLabor(scenario);
  const fields = or(get(scenario, "fields"), {});
  if (!isStr(get(scenario, "rule_version")) || !get(scenario, "rule_version", "").trim()) unknowns = dedupe([...unknowns, "rule_version:required_for_replay"]);
  for (const field of ["work_scope", "included_operations", "subframe_relevance"]) {
    const observation = get(fields, field);
    if (!isDict(observation) || !truthy(get(observation, "source"))) unknowns = dedupe([...unknowns, `${field}:evidence_source_required`]);
  }
  for (const operation of get(scenario, "operations", [])) {
    if (isDict(operation) && ["base_service", "included_carry", "replacement_carry", "snow_melt", "penetrant_wait", "parts_wait", "wash"].includes(get(operation, "operation_id")) && !truthy(get(operation, "source"))) {
      unknowns = dedupe([...unknowns, `${operation.operation_id}:evidence_source_required`]);
    }
  }
  const subframe = get(fields, "subframe_relevance");
  if (!isDict(subframe) || !["confirmed", "declared"].includes(get(subframe, "status")) || get(subframe, "value") === null) {
    unknowns = dedupe([...unknowns, "subframe_relevance:required_not_zero"]);
  }
  const blocking = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));
  if (blocking.length) {
    labor = stopLabor(labor, unknowns);
    canonicalRows = labor.breakdown;
  }
  const leaves: Dict[] = [];
  canonicalRows.forEach((row, index) => {
    const [result, rule] = leafResult(row, scenario, blocking.length > 0);
    leaves.push({
      node_id: `leaf-${index + 1}-${get(row, "operation_id", "operation") === null ? "None" : get(row, "operation_id", "operation")}`,
      rule: "operation_contribution", rule_version: version, input_hash: inputHash,
      input_refs: inputRefs(scenario, get(row, "operation_id"), row),
      operation_id: get(row, "operation_id"), operation: get(row, "operation"), status: get(row, "status"), reason: get(row, "reason"),
      children: [], result, calculation: rule,
    });
  });
  const computed = leaves.length ? pairSum(leaves.map((l) => l.result)) : { person_hours: nullRange(), elapsed_hours: nullRange() };
  const expected = { person_hours: deepcopy(labor.person_hours), elapsed_hours: deepcopy(labor.elapsed_hours) };
  return {
    node_id: "labor-root", rule: "sum_children", rule_version: version, input_hash: inputHash,
    input_refs: [
      { path: "/basis_unit", value: get(scenario, "basis_unit"), source: "scenario", status: "bound" },
      { path: "/rule_version", value: get(scenario, "rule_version"), source: "scenario", status: "bound" },
    ],
    children: leaves, result: computed, audit_expected: expected, issues: dedupe(unknowns), labor_breakdown: deepcopy(get(labor, "breakdown", [])),
  };
}

/** Check shape, input links and stored total against a fresh leaf evaluation. */
export function inspectTrace(traceTree: any, scenarioInput: any = null): Dict {
  const issues: string[] = [];
  if (!isDict(traceTree) || get(traceTree, "rule") !== "sum_children") return { valid: false, issues: ["trace:root_must_sum_children"], input_hash: null };
  const expectedHash = get(traceTree, "input_hash");
  if (!isStr(expectedHash) || expectedHash.length !== 64) issues.push("trace:input_hash_invalid");
  if (scenarioInput !== null && hashOf(scenarioInput) !== expectedHash) issues.push("trace:input_snapshot_hash_mismatch");
  const seen = new Set<any>();
  const nodes = [traceTree, ...(isList(get(traceTree, "children")) ? traceTree.children : [])];
  for (const node of nodes) {
    if (!isDict(node)) {
      issues.push("trace:child_must_be_object");
      continue;
    }
    const nodeId = get(node, "node_id");
    if (!isStr(nodeId) || seen.has(nodeId)) issues.push("trace:node_id_missing_or_duplicate");
    seen.add(nodeId);
    if (!pyEq(get(node, "rule_version"), get(traceTree, "rule_version"))) issues.push("trace:rule_version_mismatch");
    if (!pyEq(get(node, "input_hash"), expectedHash)) issues.push("trace:node_input_hash_mismatch");
    const refs = get(node, "input_refs");
    if (!isList(refs)) {
      issues.push("trace:input_refs_must_be_list");
      continue;
    }
    if (scenarioInput !== null) {
      for (const ref of refs) {
        try {
          const actual = pointerGet(scenarioInput, get(ref, "path"));
          if (!pyEq(actual, get(ref, "value"))) issues.push("trace:input_ref_value_mismatch");
        } catch (e) {
          if (e instanceof PyKeyError || e instanceof PyValueError || e instanceof PyAttributeError) issues.push("trace:input_ref_unresolved");
          else throw e;
        }
      }
    }
  }
  let evaluated: Dict | null;
  try {
    evaluated = evaluateTree(traceTree);
    if (!pyEq(evaluated, get(traceTree, "result"))) issues.push("trace:stored_total_differs_from_leaf_sum");
    if (!pyEq(evaluated, get(traceTree, "audit_expected"))) issues.push("trace:leaf_sum_differs_from_labor_audit");
  } catch (exc) {
    if (exc instanceof PyValueError || exc instanceof PyTypeError) {
      evaluated = null;
      issues.push(exc.message);
    } else if (exc instanceof PyKeyError) {
      evaluated = null;
      issues.push(repr(exc.message));
    } else {
      throw exc;
    }
  }
  return { valid: !issues.length, issues: dedupe(issues), input_hash: expectedHash, evaluated };
}

/** Return the common engine envelope with labor totals audited from tree leaves. */
export function run(scenarioInput: any, rulePack: any = null): Dict {
  if (!isDict(scenarioInput)) throw new PyTypeError("scenario_input must be an object");
  const scenario = deepcopy(scenarioInput);
  const version = get(scenario, "rule_version", "unbound");
  const tree = buildTraceTree(scenario, version);
  if (rulePack !== null) {
    tree.issues = dedupe([...tree.issues, "rule_pack:dynamic_pack_unsupported_by_e18"]);
    tree.audit_expected = { person_hours: nullRange(), elapsed_hours: nullRange() };
    tree.result = deepcopy(tree.audit_expected);
    for (const leaf of tree.children) {
      leaf.result = { person_hours: nullRange(), elapsed_hours: nullRange() };
      leaf.status = "missing-required";
    }
  }
  let [labor, , unknowns] = referenceLabor(scenario);
  if (tree.issues.length) unknowns = dedupe([...unknowns, ...tree.issues]);
  const blocking = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));
  if (blocking.length) labor = stopLabor(labor, unknowns);
  let evaluated = evaluateTree(tree);
  const auditExpected = { person_hours: labor.person_hours, elapsed_hours: labor.elapsed_hours };
  tree.audit_expected = deepcopy(auditExpected);
  const audit = inspectTrace(tree, scenario);
  if (!audit.valid) {
    unknowns = dedupe([...unknowns, ...audit.issues]);
    labor = stopLabor(labor, unknowns);
    tree.audit_expected = { person_hours: nullRange(), elapsed_hours: nullRange() };
    tree.result = deepcopy(tree.audit_expected);
    evaluated = deepcopy(tree.result);
  } else {
    labor.person_hours = evaluated.person_hours;
    labor.elapsed_hours = evaluated.elapsed_hours;
  }
  unknowns = dedupe([...get(labor, "unknowns", []), ...tree.issues]);
  labor.unknowns = unknowns;
  tree.labor_breakdown = deepcopy(get(labor, "breakdown", []));
  const status = unknowns.some((u) => !u.endsWith(":elapsed_duration_unknown")) ? "missing-required" : unknowns.length ? "partial" : "proposed";
  const operationKeys = dedupe(get(labor, "breakdown", []).map((row: Dict) => get(row, "operation_id", get(row, "operation", ""))));
  const approvals = get(labor, "breakdown", []).filter((row: Dict) => isDict(get(row, "approval"))).map((row: Dict) => row.approval);
  const trace = [
    { event: "trace_tree_built", input_hash: tree.input_hash, tree },
    { event: "trace_audit", valid: audit.valid, issues: audit.issues, tree_sum: evaluated, labor_sum: auditExpected },
  ];
  return { engine_id: ENGINE_ID, rule_version: version, status, labor, trace, operation_keys: operationKeys, approvals, simulator_notice: SIMULATOR_NOTICE };
}
