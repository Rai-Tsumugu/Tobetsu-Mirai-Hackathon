/* eslint-disable @typescript-eslint/no-explicit-any */
// E07: a hash-linked validation, normalization, expansion and audit pipeline. 元: e07.py
import {
  type Dict, dedupe, deepcopy, get, isDict, isInt, isList, isNumber, isStr, item, keysAre, pyIn, pyJsonDumps, pyRound, pySum, sha256Hex,
  pyFloat, pySorted, truthy,
} from "./py";
import { BANDS, referenceLabor, validateCoreContract } from "./contract";

export const ENGINE_ID = "e07_pipeline";
export const RULE_VERSION = "e07-validation-pipeline-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const REQUIRED = new Set(["base_service", "included_carry", "replacement_carry", "snow_melt", "penetrant_wait", "parts_wait", "wash"]);
const WAIT = new Set(["snow_melt", "penetrant_wait", "parts_wait"]);
const KNOWN = new Set([...REQUIRED, "rotor_seizure"]);

export interface StageResult {
  input_hash: string;
  issues: string[];
  rows: Dict[];
}

export const toDict = (r: StageResult): Dict => deepcopy({ input_hash: r.input_hash, issues: r.issues, rows: r.rows });

export function hashOf(value: any): string {
  return sha256Hex(pyJsonDumps(value, { sortKeys: true, compact: true, ensureAscii: false, defaultStr: true }));
}

const finiteNonnegative = (v: any): boolean => isNumber(v) && Number.isFinite(v) && v >= 0;
const isPositiveInt = (v: any): boolean => isInt(v) && v > 0;

export function validateStage(scenarioInput: any): StageResult {
  const issues: string[] = [];
  const rows: Dict[] = [];
  if (!isDict(scenarioInput)) return { input_hash: hashOf(scenarioInput), issues: ["scenario_input:object_required"], rows: [] };
  const scenario = scenarioInput;
  if (get(scenario, "basis_unit") !== "person_hour") issues.push("basis_unit:person_hour_required");
  if (!isStr(get(scenario, "basis_definition")) || !scenario.basis_definition.trim()) issues.push("basis_definition:required");
  const topCount = get(scenario, "person_count");
  if (topCount !== null && (typeof topCount === "boolean" || !isInt(topCount) || topCount < 0)) issues.push("person_count:finite_nonnegative_integer_required");
  for (const timeKey of ["duration_hours", "waiting_hours"]) {
    const value = get(scenario, timeKey);
    if (value !== null && !finiteNonnegative(value)) issues.push(`${timeKey}:finite_nonnegative_required`);
  }
  const baseHours = get(scenario, "base_hours");
  if (isDict(baseHours) && get(baseHours, "value") !== null && !finiteNonnegative(baseHours.value)) issues.push("base_hours:value_must_be_finite_nonnegative");
  let fields = get(scenario, "fields");
  if (!isDict(fields)) {
    issues.push("fields:object_required");
    fields = {};
  }
  for (const key of ["work_scope", "included_operations"]) {
    const obs = get(fields, key);
    if (!isDict(obs) || !["confirmed", "declared"].includes(get(obs, "status")) || get(obs, "value") === null) issues.push(`${key}:confirmed_value_required`);
  }
  const included = isDict(get(fields, "included_operations")) ? get(get(fields, "included_operations", {}), "value") : null;
  if (isList(included)) {
    const scope = ["remove_install", "rust_observation", "snow_removal"];
    if (included.some((k) => !scope.includes(k))) issues.push("included_operations:unknown_unit_or_scope_key");
    if (!scope.every((k) => included.includes(k))) issues.push("included_operations:required_scope_keys_missing");
  }
  let operations = get(scenario, "operations");
  if (!isList(operations)) {
    issues.push("operations:list_required");
    operations = [];
  }
  const seen = new Set<string>();
  const byId: Record<string, Dict> = {};
  operations.forEach((op: any, index: number) => {
    const prefix = `operations[${index}]`;
    if (!isDict(op)) {
      issues.push(`${prefix}:object_required`);
      return;
    }
    const opId = get(op, "operation_id");
    if (!isStr(opId) || !KNOWN.has(opId)) {
      issues.push(`${prefix}:unknown_operation_id`);
      return;
    }
    if (seen.has(opId)) issues.push(`${opId}:duplicate_operation_id`);
    seen.add(opId);
    byId[opId] = op;
    for (const timeKey of ["hours", "duration_hours", "elapsed_hours", "hours_per_person"]) {
      const value = get(op, timeKey);
      if (timeKey in op && value !== null && !finiteNonnegative(value)) issues.push(`${opId}:${timeKey}_must_be_finite_nonnegative`);
    }
    const expectedUnit = WAIT.has(opId) ? "elapsed_hours" : "person_hours";
    if (!pyIn(get(op, "unit"), [null, expectedUnit])) issues.push(`${opId}:unit_mismatch_expected_${expectedUnit}`);
    if (WAIT.has(opId)) {
      let duration = get(op, "elapsed_hours", get(op, "duration_hours", get(op, "hours")));
      if (!["elapsed_hours", "duration_hours", "hours"].some((k) => k in op)) duration = null;
      if ("elapsed_hours" in op && op.elapsed_hours === null) duration = null;
      if (duration === null && opId !== "parts_wait") issues.push(`${opId}:elapsed_hours_required_finite_nonnegative`);
      else if (duration !== null && !finiteNonnegative(duration)) issues.push(`${opId}:elapsed_hours_required_finite_nonnegative`);
      if (!pyIn(get(op, "person_count", 0), [0, null])) issues.push(`${opId}:wait_person_count_must_be_zero`);
    } else if (opId === "replacement_carry") {
      const count = get(op, "person_count");
      const perPerson = get(op, "hours_per_person");
      if (!isPositiveInt(count)) issues.push("replacement_carry:person_count_positive_integer_required");
      if (!finiteNonnegative(perPerson)) issues.push("replacement_carry:hours_per_person_must_be_finite_nonnegative");
    } else if (opId === "rotor_seizure") {
      // Condition width and its audit are checked by the canonical calculator.
    } else {
      let hours = get(op, "hours", get(op, "duration_hours"));
      if (!["hours", "duration_hours"].some((k) => k in op)) hours = null;
      if ("hours" in op && op.hours === null) hours = null;
      if (hours === null || !finiteNonnegative(hours)) issues.push(`${opId}:hours_required_finite_nonnegative`);
      const count = get(op, "person_count");
      if (!isPositiveInt(count)) issues.push(`${opId}:person_count_positive_integer_required`);
      if (opId === "base_service" && get(op, "deduplicated") !== true) issues.push("base_service:deduplicated_approval_required");
      if (opId === "base_service" && !("hours" in op)) issues.push("base_service:hours_required_finite_nonnegative");
      if (opId === "included_carry" && get(op, "included_in_base") !== true) issues.push("included_carry:included_status_required");
    }
  });
  for (const opId of pySorted([...REQUIRED].filter((k) => !seen.has(k)))) issues.push(`${opId}:required_operation_missing`);
  for (const [opId, op] of Object.entries(byId)) {
    rows.push({ operation_id: opId, unit: WAIT.has(opId) ? "elapsed_hours" : "person_hours", present: true, status: get(op, "status", "unknown") });
  }
  if (get(get(byId, "parts_wait", {}), "stock_checked") !== true) issues.push("parts_wait:stock_confirmation_required");
  const rotorObs = get(fields, "rotor_seizure_hours");
  if (isDict(rotorObs) && get(rotorObs, "value") !== null) {
    const value = rotorObs.value;
    if (!isDict(value) || !keysAre(value, [...BANDS]) || BANDS.some((k) => !finiteNonnegative(get(value, k))) || !(value.low <= value.typical && value.typical <= value.high)) {
      issues.push("rotor_seizure_hours:invalid_person_hour_range");
    }
  }
  return { input_hash: hashOf(scenarioInput), issues: dedupe(issues), rows };
}

export function normalizeStage(scenarioInput: Dict): StageResult {
  const normalized = deepcopy(scenarioInput);
  const rows: Dict[] = [];
  for (const op of get(normalized, "operations", [])) {
    const opId = get(op, "operation_id");
    const before: Dict = {};
    if (WAIT.has(opId)) {
      if (!("elapsed_hours" in op) && "duration_hours" in op) {
        op.elapsed_hours = op.duration_hours;
        delete op.duration_hours;
        before.duration_hours = op.elapsed_hours;
      } else if (!("elapsed_hours" in op) && "hours" in op) {
        op.elapsed_hours = op.hours;
        before.hours = op.hours;
      }
      if (!("hours" in op)) op.hours = 0.0;
      if (!("person_count" in op)) op.person_count = 0;
    } else if (!("hours" in op) && "duration_hours" in op) {
      op.hours = op.duration_hours;
      before.duration_hours = op.hours;
    }
    rows.push({ operation_id: opId, normalized: deepcopy(op), aliases_resolved: before });
  }
  return { input_hash: hashOf(scenarioInput), issues: [], rows };
}

export function expandStage(normalizedScenario: Dict): [StageResult, Dict] {
  const expanded = deepcopy(normalizedScenario);
  const rows: Dict[] = [];
  for (const op of get(expanded, "operations", [])) {
    const opId = get(op, "operation_id");
    if (opId === "replacement_carry") {
      const count = item(op, "person_count");
      const perPerson = item(op, "hours_per_person");
      const total = pyRound(count * perPerson, 10);
      op._expanded_person_hours = total;
      rows.push({ operation_id: opId, person_count: count, duration_hours: perPerson, person_hours: total, unit: "person_hours" });
    } else if (WAIT.has(opId)) {
      rows.push({ operation_id: opId, person_count: 0, elapsed_hours: get(op, "elapsed_hours"), person_hours: 0.0, unit: "elapsed_hours" });
    } else {
      const count = item(op, "person_count");
      const hours = get(op, "hours", get(op, "duration_hours"));
      const total = opId === "base_service" ? hours : pyRound(hours * count, 10);
      op._expanded_person_hours = total;
      rows.push({ operation_id: opId, person_count: count, duration_hours: hours, person_hours: total, unit: "person_hours" });
    }
  }
  return [{ input_hash: hashOf(normalizedScenario), issues: [], rows }, expanded];
}

export function sumStage(expandedScenario: Dict): [StageResult, Dict, Dict[], string[]] {
  const [labor, rows, issues] = referenceLabor(expandedScenario);
  if (!issues.length || issues.every((i) => i.endsWith(":elapsed_duration_unknown"))) {
    const operations: Record<string, Dict> = {};
    for (const op of get(expandedScenario, "operations", [])) operations[String(get(op, "operation_id"))] = op;
    const lines: Record<string, Dict> = {};
    for (const row of get(labor, "breakdown", [])) lines[String(get(row, "operation_id"))] = row;
    const replacement = item(operations, "replacement_carry");
    const total = pyRound(item(replacement, "hours_per_person") * item(replacement, "person_count"), 10);
    if (truthy(lines.replacement_carry)) lines.replacement_carry.hours = { low: total, typical: total, high: total };
    for (const row of rows) if (get(row, "operation_id") === "replacement_carry") row.hours = { low: total, typical: total, high: total };
    const base = item(item(operations, "base_service"), "hours");
    const included = item(item(operations, "included_carry"), "hours");
    const wash = item(operations, "wash");
    const washTotal = pyRound(item(wash, "hours") * item(wash, "person_count"), 10);
    const rotor: Dict = get(lines.rotor_seizure ?? {}, "hours", { low: 0, typical: 0, high: 0 });
    labor.person_hours = Object.fromEntries(BANDS.map((key) => [key, pyRound(base - included + total + washTotal + rotor[key], 10)]));
    if (issues.some((i) => i.endsWith(":elapsed_duration_unknown"))) {
      labor.elapsed_hours = { low: null, typical: null, high: null };
    } else {
      const waitElapsed = pySum(
        Object.values(operations)
          .filter((op) => WAIT.has(get(op, "operation_id")))
          .map((op) => pyFloat(get(op, "elapsed_hours", get(op, "duration_hours", get(op, "hours"))))),
      );
      const handlingElapsed = replacement.hours_per_person;
      labor.elapsed_hours = Object.fromEntries(BANDS.map((key) => [key, pyRound(base - included + handlingElapsed + wash.hours + rotor[key] + waitElapsed, 10)]));
    }
  }
  return [{ input_hash: hashOf(expandedScenario), issues: [...issues], rows: deepcopy(rows) }, labor, rows, issues];
}

export function auditStage(labor: Dict, inputHash: string): StageResult {
  return { input_hash: inputHash, issues: validateCoreContract(labor), rows: deepcopy(get(labor, "breakdown", [])) };
}

function stoppedLabor(issues: string[]): Dict {
  return {
    person_hours: { low: null, typical: null, high: null },
    elapsed_hours: { low: null, typical: null, high: null },
    breakdown: [],
    unknowns: dedupe(issues),
  };
}

function normalizePayload(scenario: Dict): Dict {
  const value = deepcopy(scenario);
  for (const op of get(value, "operations", [])) {
    if (WAIT.has(get(op, "operation_id"))) {
      if (!("elapsed_hours" in op)) {
        if ("duration_hours" in op) {
          op.elapsed_hours = op.duration_hours;
          delete op.duration_hours;
        } else if ("hours" in op) {
          op.elapsed_hours = op.hours;
        }
      }
      if (!("hours" in op)) op.hours = 0.0;
      if (!("person_count" in op)) op.person_count = 0;
    } else if (!("hours" in op) && "duration_hours" in op) {
      op.hours = op.duration_hours;
    }
  }
  return value;
}

function result(version: any, status: string, labor: Dict, trace: Dict[], operationKeys: any[], approvals: Dict[] | null = null): Dict {
  return { engine_id: ENGINE_ID, rule_version: version, status, labor, trace, operation_keys: operationKeys, approvals: approvals ?? [], simulator_notice: SIMULATOR_NOTICE };
}

export function run(scenarioInput: any, rulePack: Dict | null = null): Dict {
  void rulePack;
  const scenario = isDict(scenarioInput) ? deepcopy(scenarioInput) : scenarioInput;
  const version = isDict(scenario) ? get(scenario, "rule_version", RULE_VERSION) : RULE_VERSION;
  const trace: Dict[] = [];
  const validate = validateStage(scenario);
  trace.push({ stage: "validate", ...toDict(validate) });
  if (validate.issues.length) {
    return result(version, "missing-required", stoppedLabor([...validate.issues]), trace, []);
  }
  const normalized = normalizeStage(scenario);
  trace.push({ stage: "normalize", ...toDict(normalized) });
  const normalizedScenario = normalizePayload(scenario);
  const [expandedResult, expanded] = expandStage(normalizedScenario);
  trace.push({ stage: "expand", ...toDict(expandedResult) });
  const [summed, laborIn, , sumIssues] = sumStage(expanded);
  let labor = laborIn;
  trace.push({ stage: "sum", ...toDict(summed) });
  if (sumIssues.length) {
    const blocking = sumIssues.filter((i) => !i.endsWith(":elapsed_duration_unknown"));
    if (blocking.length) labor = stoppedLabor([...sumIssues]);
  }
  const audit = auditStage(labor, summed.input_hash);
  trace.push({ stage: "audit", ...toDict(audit) });
  const auditIssues = [...audit.issues];
  if (auditIssues.length) labor = stoppedLabor(auditIssues.map((i) => `audit:${i}`));
  const unknowns: string[] = [...get(labor, "unknowns", [])];
  const status = unknowns.some((x) => !x.endsWith(":elapsed_duration_unknown")) ? "missing-required" : unknowns.length ? "partial" : "proposed";
  const operationKeys = dedupe(get(labor, "breakdown", []).map((row: Dict) => get(row, "operation_id", get(row, "operation", ""))));
  const approvals = get(labor, "breakdown", []).filter((row: Dict) => isDict(get(row, "approval"))).map((row: Dict) => row.approval);
  return result(version, status, labor, trace, operationKeys, approvals);
}
