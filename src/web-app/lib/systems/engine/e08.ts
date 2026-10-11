/* eslint-disable @typescript-eslint/no-explicit-any */
// E08: extensible method registry over the shared labor contract. 元: e08.py
import {
  type Dict, PyTypeError, PyValueError, codePointCompare, dedupe, deepcopy, get, isDict, isList, isStr, pyErrorName, pyJsonDumps, sha256Hex, truthy,
} from "./py";
import { referenceLabor, validateCoreContract } from "./contract";

export const ENGINE_ID = "e08_plugin_registry";
export const RULE_VERSION = "e08-plugin-registry-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";

export interface Method {
  id: string;
  requires: string[];
  supports: (scenario: Dict) => boolean | string;
  evaluate: (scenario: Dict) => any;
}

const REGISTRY = new Map<string, Method>();

/** Register a trusted in-process method. Duplicate and malformed ids fail. */
export function registerMethod(method: Method): void {
  if (!isDict(method)) throw new PyTypeError("method must be a Method");
  if (!isStr(method.id) || !method.id.trim()) throw new PyValueError("method id must be a non-empty string");
  if (REGISTRY.has(method.id)) throw new PyValueError("method id already registered: " + method.id);
  if (!isList(method.requires) || method.requires.some((x) => !isStr(x) || !x)) throw new PyValueError("requires must be a tuple of non-empty observation paths");
  if (typeof method.supports !== "function" || typeof method.evaluate !== "function") throw new PyTypeError("supports and evaluate must be callable");
  REGISTRY.set(method.id, method);
}

export function unregisterMethod(id: string): void {
  REGISTRY.delete(id);
}

export const registeredMethodIds = (): string[] => [...REGISTRY.keys()].sort(codePointCompare);

function sharedCalculator(scenario: Dict): Dict {
  return referenceLabor(scenario)[0];
}

function commonSupport(scenario: Dict): boolean | string {
  if (get(scenario, "basis_unit") !== "person_hour") return "basis_unit:person_hour_required";
  if (!isStr(get(scenario, "basis_definition")) || !scenario.basis_definition.trim()) return "basis_definition:required";
  if (!isList(get(scenario, "operations"))) return "operations:list_required";
  return true;
}

for (const id of ["S01", "S05", "S19"]) {
  registerMethod({ id, requires: ["basis_unit", "basis_definition", "operations"], supports: commonSupport, evaluate: sharedCalculator });
}

const hashOf = (value: any) => sha256Hex(pyJsonDumps(value, { sortKeys: true, compact: true, ensureAscii: false, defaultStr: true }));

function nullLabor(unknowns: string[]): Dict {
  return {
    person_hours: { low: null, typical: null, high: null },
    elapsed_hours: { low: null, typical: null, high: null },
    breakdown: [],
    unknowns: dedupe(unknowns),
  };
}

function requiredMissing(scenario: Dict, paths: string[]): string[] {
  const missing: string[] = [];
  for (const path of paths) {
    let value: any = scenario;
    for (const part of path.split(".")) value = isDict(value) ? get(value, part) : null;
    if (value === null || value === "") missing.push(path + ":required");
  }
  return missing;
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const original = deepcopy(scenarioInput);
  const snapshot: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const pack: Dict = isDict(rulePack) ? deepcopy(rulePack) : {};
  const methodId = get(pack, "method_id", "S01");
  const version = get(pack, "rule_version", get(snapshot, "rule_version", RULE_VERSION));
  const trace: Dict[] = [{ event: "registry_snapshot", engine_id: ENGINE_ID, rule_version: version, input_hash: hashOf(original), registered_method_ids: registeredMethodIds() }];
  let unknowns: string[] = [];
  const method = isStr(methodId) ? REGISTRY.get(methodId) : undefined;
  if (rulePack !== null && !isDict(rulePack)) unknowns.push("rule_pack:object_required");
  if (!isStr(version) || !version.trim()) unknowns.push("rule_version:required");
  if (method === undefined) unknowns.push("method_id:unknown_or_unregistered");
  const stopped = (labor: Dict): Dict => ({ engine_id: ENGINE_ID, rule_version: version, status: "missing-required", labor, trace, operation_keys: [], approvals: [], simulator_notice: SIMULATOR_NOTICE });
  if (unknowns.length) {
    const labor = nullLabor(unknowns);
    trace.push({ event: "selection_stopped", reason: unknowns[0] });
    return stopped(labor);
  }

  const m = method!;
  const missing = requiredMissing(snapshot, m.requires);
  unknowns.push(...missing);
  const support = m.supports(snapshot);
  if (support !== true) {
    unknowns.push(isStr(support) && support ? support : "method:unsupported_input");
  }
  if (unknowns.length) {
    const labor = nullLabor(unknowns);
    trace.push({ event: "availability_stopped", method_id: m.id, reason: unknowns[0], requires: [...m.requires] });
    return stopped(labor);
  }

  trace.push({ event: "method_selected", method_id: m.id, requires: [...m.requires], method_version: version });
  let labor: any;
  try {
    labor = m.evaluate(deepcopy(snapshot));
  } catch (exc) {
    unknowns.push("method:evaluate_failed:" + pyErrorName(exc));
    labor = nullLabor(unknowns);
    trace.push({ event: "evaluation_stopped", reason: unknowns[unknowns.length - 1] });
    return stopped(labor);
  }
  if (!isDict(labor)) unknowns.push("method:evaluate_must_return_labor_object");
  else unknowns.push(...validateCoreContract(labor));
  if (unknowns.length) labor = nullLabor(unknowns);
  trace.push({ event: "method_evaluated", method_id: m.id, input_hash: hashOf(snapshot), status: !unknowns.length ? "ok" : "invalid_output" });
  if (!unknowns.length) unknowns = [...get(labor, "unknowns", [])];
  const blocking = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));
  const status = blocking.length ? "missing-required" : unknowns.length ? "partial" : "proposed";
  const operationKeys = dedupe(get(labor, "breakdown", []).filter((row: Dict) => truthy(get(row, "operation_id"))).map((row: Dict) => get(row, "operation_id")));
  const approvals = get(labor, "breakdown", []).filter((row: Dict) => isDict(get(row, "approval"))).map((row: Dict) => ({ operation_key: get(row, "operation_id"), ...row.approval }));
  return { engine_id: ENGINE_ID, rule_version: version, status, labor, trace, operation_keys: operationKeys, approvals, simulator_notice: SIMULATOR_NOTICE };
}
