/* eslint-disable @typescript-eslint/no-explicit-any */
// E11: compare independently calculated methods and require an audited choice. 元: e11.py
import { type Dict, dedupe, deepcopy, get, isDict, isList, isStr, pyEq, pyIn, truthy } from "./py";
import { validateCoreContract } from "./contract";
import * as e07 from "./e07";
import * as e08 from "./e08";

export const ENGINE_ID = "e11_independent_method_comparison";
export const RULE_VERSION = "e11-independent-method-comparison-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
export const DEFAULT_METHODS = ["A", "B"];
const UNAVAILABLE_METHODS: Dict = { C: "method_C:not_implemented" };
const nullRange = () => ({ low: null, typical: null, high: null });

export const hashOf = e07.hashOf;

function stopped(unknowns: string[]): Dict {
  return { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(unknowns) };
}

function runRecord(methodId: string, result: Dict, scenarioInput: any, extraIssues: string[]): Dict {
  const labor = deepcopy(result.labor);
  return {
    method: methodId, labor,
    evidence: get(labor, "breakdown", []).map((row: Dict) => ({ operation_id: get(row, "operation_id"), source: get(row, "source"), status: get(row, "status") })),
    unknowns: [...get(labor, "unknowns", []), ...extraIssues],
    status: result.status, rule_version: result.rule_version, input_hash: hashOf(scenarioInput),
  };
}

/** Evaluate each available method on a fresh immutable copy; expose gaps separately. */
export function compareMethods(scenarioInput: any, methods: any = null, ruleVersion: any = RULE_VERSION): Dict {
  const methodIds: any[] | null = methods === null ? [...DEFAULT_METHODS] : isList(methods) ? [...methods] : null;
  if (methodIds === null || !methodIds.length || methodIds.some((x) => !isStr(x) || !x)) {
    return { runs: [], unavailable: deepcopy(UNAVAILABLE_METHODS), unknowns: ["methods:non_empty_method_id_list_required"] };
  }
  if (methodIds.length !== new Set(methodIds).size) {
    return { runs: [], unavailable: deepcopy(UNAVAILABLE_METHODS), unknowns: ["methods:duplicate_method_id"] };
  }
  const runs: Dict[] = [];
  const unavailable: Dict = deepcopy(UNAVAILABLE_METHODS);
  for (const methodId of methodIds) {
    if (methodId === "A") {
      const result = e07.run(deepcopy(scenarioInput), {});
      runs.push(runRecord(methodId, result, scenarioInput, validateCoreContract(result.labor)));
      continue;
    }
    if (methodId === "B") {
      const result = e08.run(deepcopy(scenarioInput), { method_id: "S01", rule_version: ruleVersion });
      runs.push(runRecord(methodId, result, scenarioInput, validateCoreContract(result.labor)));
      continue;
    }
    if (!e08.registeredMethodIds().includes(methodId)) {
      unavailable[methodId] = "method:not_registered_or_unavailable";
      continue;
    }
    const result = e08.run(deepcopy(scenarioInput), { method_id: methodId, rule_version: ruleVersion });
    runs.push(runRecord(methodId, result, scenarioInput, validateCoreContract(deepcopy(result.labor))));
  }
  const result: Dict = { runs, unavailable, unknowns: [], input_snapshot: deepcopy(scenarioInput), rule_version: ruleVersion };
  const { comparison_hash: _unused, ...rest } = result;
  void _unused;
  result.comparison_hash = hashOf(rest);
  return result;
}

/** Return selected run only when it is available, complete, and human-audited. */
export function selectMethod(comparison: any, selectedMethod: any, actor: any, reason: any, scenarioInput: any = null, ruleVersion: any = null): Dict {
  if (!isDict(comparison)) return { labor: stopped(["comparison:object_required"]), selection: null };
  const runs = get(comparison, "runs");
  if (!isList(runs)) return { labor: stopped(["comparison:runs_required"]), selection: null };
  const expectedHash = get(comparison, "comparison_hash");
  const found = runs.find((row) => isDict(row) && pyEq(get(row, "method"), selectedMethod));
  if (found === undefined) return { labor: stopped(["selected_method:unavailable_or_missing"]), selection: null };
  const storedInput = get(comparison, "input_snapshot");
  const { comparison_hash: _h, ...restOfComparison } = comparison;
  void _h;
  const actualHash = hashOf(restOfComparison);
  if (!isStr(expectedHash) || expectedHash !== actualHash) return { labor: stopped(["comparison:payload_tampered"]), selection: null };
  if (!isDict(storedInput) || (scenarioInput !== null && hashOf(scenarioInput) !== hashOf(storedInput))) {
    return { labor: stopped(["comparison:input_binding_invalid"]), selection: null };
  }
  const effectiveVersion = ruleVersion !== null ? ruleVersion : get(comparison, "rule_version", RULE_VERSION);
  if (!pyEq(effectiveVersion, get(comparison, "rule_version"))) return { labor: stopped(["comparison:rule_version_binding_invalid"]), selection: null };
  if (!pyEq(get(found, "rule_version"), effectiveVersion) && selectedMethod !== "A") return { labor: stopped(["comparison:selected_result_tampered"]), selection: null };
  if (!pyEq(get(found, "input_hash"), hashOf(storedInput))) return { labor: stopped(["comparison:input_hash_invalid"]), selection: null };
  const fresh = compareMethods(deepcopy(storedInput), [...DEFAULT_METHODS], effectiveVersion);
  const recalculated = fresh.runs.find((row: Dict) => pyEq(get(row, "method"), selectedMethod));
  if (recalculated === undefined || !pyEq(get(recalculated, "input_hash"), get(found, "input_hash"))) return { labor: stopped(["comparison:selected_result_tampered"]), selection: null };
  if (!truthy(get(found, "unknowns")) && hashOf(recalculated) !== hashOf(found)) return { labor: stopped(["comparison:selected_result_tampered"]), selection: null };
  if (truthy(get(found, "unknowns")) || !pyIn(get(found, "status"), ["proposed", "partial"])) {
    return { labor: stopped(["selected_method:evidence_incomplete", ...get(found, "unknowns", [])]), selection: null };
  }
  if (!isStr(actor) || !actor.trim() || !isStr(reason) || !reason.trim()) return { labor: stopped(["selection:actor_and_reason_required"]), selection: null };
  return {
    labor: deepcopy(recalculated.labor),
    selection: { method: selectedMethod, actor, reason, original_alternatives: deepcopy(runs), unavailable: deepcopy(get(comparison, "unavailable", {})) },
  };
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const original = deepcopy(scenarioInput);
  const pack: Dict = isDict(rulePack) ? deepcopy(rulePack) : {};
  const version = get(pack, "rule_version", RULE_VERSION);
  const methods = get(pack, "methods", [...DEFAULT_METHODS]);
  const comparison = compareMethods(deepcopy(scenarioInput), methods, version);
  const trace: Dict[] = [{
    event: "independent_method_comparison", input_snapshot: deepcopy(original), method_runs: deepcopy(comparison.runs),
    unavailable: deepcopy(comparison.unavailable), rule_version: version,
  }];
  const issues: string[] = [...comparison.unknowns];
  if (!isStr(version) || !version.trim()) issues.push("rule_version:required");
  const choice = get(pack, "selected_method");
  let selection: Dict | null = null;
  let labor: Dict;
  if (choice === null) {
    issues.push("selected_method:human_choice_required");
    labor = stopped(issues);
  } else {
    const selectionResult = selectMethod(comparison, choice, get(pack, "actor"), get(pack, "reason"), original, version);
    selection = selectionResult.selection;
    labor = selectionResult.labor;
    if (selection === null) {
      issues.push(...labor.unknowns);
    } else {
      issues.push(...get(labor, "unknowns", []));
      trace.push({ event: "method_selected", method: choice, actor: selection.actor, reason: selection.reason });
    }
  }
  const blocking = issues.filter((i) => !i.endsWith(":elapsed_duration_unknown"));
  const status = blocking.length ? "missing-required" : issues.length ? "partial" : "proposed";
  if (blocking.length && Object.values(labor.person_hours).some((v) => v !== null)) labor = stopped(issues);
  else if (issues.length) labor.unknowns = dedupe(issues);
  return {
    engine_id: ENGINE_ID, rule_version: version, status, labor, trace,
    operation_keys: dedupe(get(labor, "breakdown", []).filter((row: Dict) => truthy(get(row, "operation_id"))).map((row: Dict) => get(row, "operation_id"))),
    approvals: [], simulator_notice: SIMULATOR_NOTICE, selection, method_runs: comparison.runs, unavailable_methods: comparison.unavailable,
  };
}
