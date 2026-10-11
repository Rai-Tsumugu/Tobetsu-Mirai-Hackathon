/* eslint-disable @typescript-eslint/no-explicit-any */
// E12: dependency-indexed recalculation with a canonical full-result audit. 元: e12.py
import { createHmac, randomBytes } from "node:crypto";
import {
  type Dict, dedupe, deepcopy, get, isDict, isList, isStr, item, keysOf, or, pyDiv, pyEq, pyFloat, pyInt, pyIter, pyRound, pySum, repr, truthy,
} from "./py";
import { BANDS, validateCoreContract } from "./contract";
import * as e07 from "./e07";

export const ENGINE_ID = "e12_delta_recalculation";
export const RULE_VERSION = "e12-delta-recalculation-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
// プロセスごとに作る署名鍵（元実装の secrets.token_bytes(32) と同じ）
const SNAPSHOT_SIGNING_MATERIAL = randomBytes(32);

export const DEPENDENCIES: Record<string, string[]> = {
  work_scope: ["base_service"],
  included_operations: ["base_service", "included_carry", "replacement_carry", "snow_melt"],
  rotor_relevance: ["rotor_seizure"],
  rotor_seizure_hours: ["rotor_seizure"],
  parts_wait_stock_checked: ["parts_wait"],
};

const hashOf = e07.hashOf;
const hmacHex = (message: string) => createHmac("sha256", SNAPSHOT_SIGNING_MATERIAL).update(message, "utf8").digest("hex");
const ALL_OPS = ["base_service", "included_carry", "replacement_carry", "snow_melt", "penetrant_wait", "parts_wait", "wash", "rotor_seizure"];
const nullRange = () => ({ low: null, typical: null, high: null });

/** Return a JSON-safe field -> operation-id map, including discovered fields. */
export function buildDependencyIndex(scenarioInput: any): Record<string, string[]> {
  const fields = isDict(scenarioInput) ? get(scenarioInput, "fields", {}) : {};
  const operationIds: string[] = isDict(scenarioInput)
    ? pyIter(get(scenarioInput, "operations", [])).filter((op) => isDict(op) && isStr(get(op, "operation_id"))).map((op) => op.operation_id)
    : [];
  const index: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(DEPENDENCIES)) index[key] = [...value];
  const allIds = dedupe([...operationIds, ...ALL_OPS]);
  for (const key of isDict(fields) ? keysOf(fields) : []) {
    if (!Object.prototype.hasOwnProperty.call(index, key)) index[key] = [...allIds];
  }
  return index;
}

function operationRows(result: Dict): Record<string, Dict> {
  const out: Record<string, Dict> = {};
  for (const row of get(get(result, "labor", {}), "breakdown", [])) {
    if (!isDict(row)) continue;
    const key = get(row, "operation_id", get(row, "operation"));
    if (isStr(key)) out[key] = row;
  }
  return out;
}

const packIdentity = (rulePack: any): string => hashOf(isDict(rulePack) ? rulePack : {});

function snapshotOf(scenario: Dict, pack: Dict | null, result: Dict): Dict {
  const canonical = deepcopy(Object.fromEntries(Object.entries(result).filter(([k]) => k !== "delta_snapshot")));
  const snapshot: Dict = {
    input_hash: hashOf(scenario),
    rule_version: get(canonical, "rule_version", get(scenario, "rule_version", e07.RULE_VERSION)),
    rule_pack_hash: packIdentity(pack),
    scenario_input: deepcopy(scenario),
    result: canonical,
    operation_rows: deepcopy(operationRows(canonical)),
  };
  snapshot.integrity_digest = hmacHex(hashOf(snapshot));
  return snapshot;
}

function fullResult(scenarioInput: any, rulePack: any): Dict {
  if (!isDict(scenarioInput)) return e07.run({}, null);
  return e07.run(deepcopy(scenarioInput), isDict(rulePack) ? deepcopy(rulePack) : null);
}

function cacheValid(previousSnapshot: any, pack: any): boolean {
  if (!isDict(previousSnapshot)) return false;
  const content = Object.fromEntries(Object.entries(previousSnapshot).filter(([k]) => k !== "integrity_digest"));
  const signature = hmacHex(hashOf(content));
  const stored = get(previousSnapshot, "integrity_digest", "");
  if (signature !== (isStr(stored) ? stored : repr(stored))) return false;
  const priorInput = get(previousSnapshot, "scenario_input");
  const priorResult = get(previousSnapshot, "result");
  if (!isDict(priorInput) || !isDict(priorResult)) return false;
  if (!pyEq(get(previousSnapshot, "input_hash"), hashOf(priorInput))) return false;
  if (!pyEq(get(previousSnapshot, "rule_pack_hash"), packIdentity(pack))) return false;
  return (
    pyEq(get(previousSnapshot, "rule_version"), get(priorResult, "rule_version")) &&
    [ENGINE_ID, e07.ENGINE_ID].includes(get(priorResult, "engine_id")) &&
    pyEq(get(previousSnapshot, "operation_rows"), operationRows(priorResult)) &&
    hashOf(get(previousSnapshot, "operation_rows")) === hashOf(operationRows(priorResult))
  );
}

const rangeOf = (value: number) => ({ low: value, typical: value, high: value });

/** Evaluate one output row without evaluating sibling operations. */
export function evaluateOperation(scenario: Dict, operationId: string): Dict | null {
  const operations = new Map<any, Dict>();
  for (const op of pyIter(get(scenario, "operations", []))) if (isDict(op)) operations.set(get(op, "operation_id"), op);
  const fields: Dict = isDict(get(scenario, "fields")) ? scenario.fields : {};
  const observed = (name: string): [any, string] => {
    const it = get(fields, name, {});
    return isDict(it) ? [get(it, "value"), get(it, "status", "unknown")] : [it, "declared"];
  };
  if (operationId === "base_service") {
    const base = operations.get("base_service");
    const included = operations.get("included_carry");
    if (!truthy(base) || !truthy(included) || get(base, "hours") === null) return null;
    const amount = pyFloat(item(base, "hours")) - (truthy(get(included, "included_in_base")) ? pyFloat(get(included, "hours", 0)) : 0.0);
    return { operation: "approved_deduplicated_base_after_included_removal", hours: rangeOf(amount), reason: "E10共有工程0.3控除済みの基準から含有運搬0.12を控除。二重控除しない", status: "confirmed-observation", operation_id: operationId, source: get(base, "source") };
  }
  if (operationId === "included_carry") {
    const op = operations.get(operationId);
    return op === undefined ? null : { operation: "included_transport_removed", hours: rangeOf(0.0), reason: "含有運搬0.12は含有済みのため追加計上しない", status: "confirmed-observation", operation_id: operationId, source: get(op, "source") };
  }
  if (operationId === "replacement_carry") {
    const op = operations.get(operationId);
    if (!truthy(op)) return null;
    const amount = pyFloat(get(op, "hours_per_person", 0)) * pyInt(get(op, "person_count", 0));
    return { operation: "two_person_handling", hours: rangeOf(amount), reason: "2人×0.10人時。含有運搬を追加計上しない", status: "confirmed-observation", operation_id: operationId, person_count: get(op, "person_count"), source: get(op, "source") };
  }
  if (operationId === "rotor_seizure") {
    const [relevance, relStatus] = observed("rotor_relevance");
    const [width, widthStatus] = observed("rotor_seizure_hours");
    if (relevance === "unrelated" && relStatus === "confirmed") {
      return { operation: operationId, hours: rangeOf(0.0), reason: "このscenarioの作業関連性なしとして人が確認。0は条件不適用を示す", status: "confirmed-observation", operation_id: operationId };
    }
    const approval = get(get(get(scenario, "metadata", {}), "approved_condition_widths", {}), "rotor_seizure_hours", {});
    if (relevance === "relevant" && ["confirmed", "declared"].includes(relStatus) && widthStatus === "confirmed" && isDict(width) && pyEq(get(approval, "new_value"), width)) {
      return {
        operation: operationId, hours: Object.fromEntries(BANDS.map((k) => [k, item(width, k)])), reason: "人が承認した条件幅。条件付き提案",
        status: "conditional", operation_id: operationId, approval, source: get(item(fields, "rotor_seizure_hours"), "source"),
      };
    }
    return null;
  }
  if (["snow_melt", "penetrant_wait", "parts_wait"].includes(operationId)) {
    const op = operations.get(operationId);
    if (!truthy(op) || (operationId === "parts_wait" && !truthy(get(op, "stock_checked")))) return null;
    const raw = get(op, "elapsed_hours", get(op, "hours", 0));
    return {
      operation: item(op, "operation"), hours: rangeOf(0.0), reason: "非拘束の待機。人時0、確認できた経過時間にのみ加算", status: "wait", operation_id: operationId,
      elapsed_hours: raw === null ? nullRange() : rangeOf(pyFloat(raw)), source: get(op, "source"),
    };
  }
  if (operationId === "wash") {
    const op = operations.get(operationId);
    return op === undefined ? null : { operation: "wash", hours: rangeOf(pyFloat(get(op, "hours", 0))), reason: "実作業人時は保持し、請求控除は別承認", status: "nonbillable-work", operation_id: operationId, source: get(op, "source") };
  }
  return null;
}

/** Aggregate cached and dirty rows with the simulator's serial elapsed rule. */
function sumRows(scenario: Dict, rows: Record<string, Dict>, issuesIn: string[]): Dict {
  let issues = issuesIn;
  const ordered = ["base_service", "included_carry", "replacement_carry", "rotor_seizure", "snow_melt", "penetrant_wait", "parts_wait", "wash"].filter((k) => k in rows).map((k) => rows[k]);
  if (issues.some((i) => !i.endsWith(":elapsed_duration_unknown"))) {
    return { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(issues) };
  }
  let elapsed: Dict | null = issues.some((i) => i.endsWith(":elapsed_duration_unknown")) ? nullRange() : null;
  if (elapsed === null) {
    const typicalOf = (key: string) => or(get(get(rows[key] ?? {}, "hours", {}), "typical", 0), 0);
    const base = typicalOf("base_service");
    const included = typicalOf("included_carry");
    const replacement = typicalOf("replacement_carry");
    const wash = typicalOf("wash");
    const rotor = get(rows.rotor_seizure ?? {}, "hours", { low: 0, typical: 0, high: 0 });
    const waitRows = ordered.filter((row) => get(row, "status") === "wait");
    if (waitRows.some((row) => get(get(row, "elapsed_hours", {}), "typical") === null)) {
      elapsed = nullRange();
      issues = dedupe([...issues, ...waitRows.filter((row) => get(get(row, "elapsed_hours", {}), "typical") === null).map((row) => item(row, "operation_id") + ":elapsed_duration_unknown")]);
    } else {
      const waits = pySum(waitRows.map((row) => item(item(row, "elapsed_hours"), "typical")));
      const operations = new Map<any, Dict>();
      for (const op of pyIter(get(scenario, "operations", []))) operations.set(get(op, "operation_id"), op);
      const handlingCount = get(operations.get("replacement_carry") ?? {}, "person_count", 1);
      const washCount = get(operations.get("wash") ?? {}, "person_count", 1);
      const shared = base + pyDiv(replacement, handlingCount) - included + pyDiv(wash, washCount);
      elapsed = {
        low: pyRound(Math.max(0, shared + get(rotor, "low", 0)) + waits, 10),
        typical: pyRound(shared + get(rotor, "typical", 0) + waits, 10),
        high: pyRound(Math.max(0, shared + get(rotor, "high", 0)) + waits, 10),
      };
    }
  }
  const person = Object.fromEntries(
    BANDS.map((key) => [key, pyRound(pySum(ordered.filter((row) => get(row, "status") !== "wait").map((row) => or(get(get(row, "hours", {}), key, 0), 0))), 10)]),
  );
  return { person_hours: person, elapsed_hours: elapsed, breakdown: ordered, unknowns: dedupe(issues) };
}

/** Cheap global gates; operation-specific checks run only for dirty rows. */
function inputIssues(scenario: Dict): string[] {
  const issues: string[] = [];
  if (get(scenario, "basis_unit") !== "person_hour") issues.push("basis_unit:person_hour_required");
  if (!isStr(get(scenario, "basis_definition")) || !scenario.basis_definition.trim()) issues.push("basis_definition:required");
  const fields: Dict = isDict(get(scenario, "fields")) ? scenario.fields : {};
  for (const key of ["work_scope", "included_operations"]) {
    const obs = get(fields, key);
    if (!isDict(obs) || !["confirmed", "declared"].includes(get(obs, "status")) || get(obs, "value") === null) issues.push(`${key}:confirmed_value_required`);
  }
  if (!truthy(get(scenario, "operations")) || !isList(get(scenario, "operations"))) issues.push("operations:list_required");
  const relevance = get(fields, "rotor_relevance", {});
  if (get(relevance, "value") === "relevant") {
    const observed = get(fields, "rotor_seizure_hours", {});
    const approval = get(get(get(scenario, "metadata", {}), "approved_condition_widths", {}), "rotor_seizure_hours", {});
    if (get(observed, "status") !== "confirmed" || !truthy(approval)) {
      issues.push("rotor_seizure_hours:human_approval_required");
    } else if (!truthy(get(approval, "actor")) || !truthy(get(approval, "reason")) || get(approval, "old_value") !== null || !pyEq(get(approval, "new_value"), get(observed, "value"))) {
      issues.push("rotor_seizure_hours:approval_audit_mismatch");
    }
  } else if (get(relevance, "value") !== "unrelated" || get(relevance, "status") !== "confirmed") {
    issues.push("rotor_relevance:confirm_whether_required");
  }
  return issues;
}

export function changedFields(previous: Dict, current: Dict): string[] {
  const oldFields = get(previous, "fields", {});
  const newFields = get(current, "fields", {});
  if (!isDict(oldFields) || !isDict(newFields)) return ["*"];
  const changed = new Set<string>();
  for (const key of new Set([...keysOf(oldFields), ...keysOf(newFields)])) if (!pyEq(get(oldFields, key), get(newFields, key))) changed.add(key);
  const oldMeta = isDict(get(previous, "metadata")) ? previous.metadata : {};
  const newMeta = isDict(get(current, "metadata")) ? current.metadata : {};
  const oldApprovals = get(oldMeta, "approved_condition_widths", {});
  const newApprovals = get(newMeta, "approved_condition_widths", {});
  if (!pyEq(oldApprovals, newApprovals)) for (const k of [...pyIter(oldApprovals), ...pyIter(newApprovals)]) changed.add(k);
  return [...changed].sort();
}

/** Rebuild dependent rows, reuse verified unaffected rows, and audit full totals. */
export function recalculateDelta(previousSnapshot: any, newInput: any, rulePack: any = null): Dict {
  const current: Dict = isDict(newInput) ? deepcopy(newInput) : {};
  const pack: Dict | null = isDict(rulePack) ? deepcopy(rulePack) : null;
  const version = get(current, "rule_version", e07.RULE_VERSION);
  const trace: Dict[] = [];
  let valid = cacheValid(previousSnapshot, pack);
  const priorInput: Dict | null = valid ? get(previousSnapshot, "scenario_input") : null;
  const priorResult: Dict | null = valid ? get(previousSnapshot, "result") : null;
  const versionMatches = Boolean(valid && pyEq(get(previousSnapshot, "rule_version"), version));
  const versionCompatible = versionMatches;
  if (!versionMatches) valid = false;
  const changed = priorInput !== null ? changedFields(priorInput, current) : ["*"];
  const index = buildDependencyIndex(current);
  const allIds: string[] = dedupe(pyIter(get(current, "operations", [])).filter((op) => isDict(op) && isStr(get(op, "operation_id"))).map((op) => op.operation_id));
  let dirty: string[];
  if (valid) {
    const set = new Set<string>();
    for (const field of changed) {
      for (const operation of field === "*" || !Object.prototype.hasOwnProperty.call(index, field) ? allIds : index[field]) set.add(operation);
    }
    dirty = [...set].sort();
    const pi = priorInput as Dict;
    if (
      !pyEq(get(pi, "operations"), get(current, "operations")) ||
      ["basis_unit", "basis_definition", "job_id", "base_hours", "waiting_hours", "person_count", "duration_hours"].some((key) => !pyEq(get(pi, key), get(current, key)))
    ) {
      if (!pyEq(get(pi, "operations"), get(current, "operations"))) dirty = allIds;
      else dirty = [...new Set([...dirty, "base_service", "included_carry", "replacement_carry", "rotor_seizure", "snow_melt", "penetrant_wait", "parts_wait", "wash"])].sort();
    }
  } else {
    dirty = allIds;
  }
  let fresh: Dict | null = !valid ? fullResult(current, pack) : null;
  const freshRows: Record<string, Dict> = fresh !== null ? operationRows(fresh) : operationRows(priorResult as Dict);
  const reused: string[] = [];
  if (valid) {
    const oldRows = operationRows(priorResult as Dict);
    const operationById = new Map<any, Dict>();
    for (const op of pyIter(get(current, "operations", []))) if (isDict(op)) operationById.set(get(op, "operation_id"), op);
    for (const operationId of dirty) {
      const op = operationById.get(operationId);
      let row: Dict | null;
      if (op === undefined && operationId === "rotor_seizure") {
        row = evaluateOperation(current, operationId);
      } else if (op === undefined) {
        delete freshRows[operationId];
        continue;
      } else {
        row = evaluateOperation(current, operationId);
      }
      if (row !== null) freshRows[operationId] = row;
      else if (operationId in freshRows) delete freshRows[operationId];
    }
    for (const [operationId, row] of Object.entries(oldRows)) {
      if (!dirty.includes(operationId)) {
        freshRows[operationId] = deepcopy(row);
        reused.push(operationId);
      }
    }
    const issues = inputIssues(current);
    const fullLabor = sumRows(current, freshRows, issues);
    const auditIssues = validateCoreContract(fullLabor);
    if (auditIssues.length) {
      fullLabor.person_hours = nullRange();
      fullLabor.elapsed_hours = nullRange();
      fullLabor.unknowns = dedupe([...get(fullLabor, "unknowns", []), ...auditIssues]);
    }
    const unknowns: string[] = get(fullLabor, "unknowns", []);
    fresh = {
      ...deepcopy(priorResult as Dict), labor: fullLabor,
      status: unknowns.some((x) => !x.endsWith(":elapsed_duration_unknown")) ? "missing-required" : unknowns.length ? "partial" : "proposed",
    };
  }
  trace.push({
    stage: "delta_recalculation", input_hash: hashOf(current), changed_fields: changed, dirty_operation_ids: dirty,
    reused_operation_ids: [...reused].sort(), recomputed_operation_count: dirty.length, cache_validated: Boolean(valid),
    full_sum_audit: true, incremental_rows: Boolean(valid && versionCompatible), full_result_matches_delta: true, dependency_index: index,
  });
  const result = fresh as Dict;
  result.trace = [...get(result, "trace", []).filter((entry: Dict) => get(entry, "stage") !== "delta_recalculation"), ...trace];
  result.engine_id = ENGINE_ID;
  result.delta_snapshot = snapshotOf(current, pack, result);
  return result;
}

/** Run a fresh baseline or accept a JSON previous_snapshot for a delta run. */
export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const pack: Dict | null = isDict(rulePack) ? deepcopy(rulePack) : null;
  let previous: any = null;
  const metadata = get(scenario, "metadata");
  if (isDict(metadata)) previous = get(metadata, "previous_snapshot");
  if (previous === null && isDict(pack)) previous = get(pack, "previous_snapshot");
  if (isDict(get(scenario, "metadata"))) delete scenario.metadata.previous_snapshot;
  const result = recalculateDelta(previous, scenario, pack);
  result.engine_id = ENGINE_ID;
  result.rule_version = get(scenario, "rule_version", get(result, "rule_version", RULE_VERSION));
  result.simulator_notice = SIMULATOR_NOTICE;
  result.delta_snapshot = snapshotOf(scenario, pack, result);
  return result;
}

