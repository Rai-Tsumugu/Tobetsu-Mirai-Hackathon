/* eslint-disable @typescript-eslint/no-explicit-any */
// E03: a small, allowlisted DSL interpreted without dynamic code execution. 元: e03.py
import {
  type Dict, dedupe, deepcopy, get, isDict, isInt, isList, isNumber, isStr, item, keysAre, keysOf, or, pyEq, pyRound, truthy,
} from "./py";
import { BANDS, referenceLabor } from "./contract";

export const ENGINE_ID = "e03_restricted_dsl";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";

const ALLOWED_FIELDS = new Set(["work_scope", "included_operations", "parts_wait_stock_checked", "rotor_relevance"]);
const OP_UNITS: Record<string, string> = {
  base_service: "person_hours",
  replacement_carry: "person_hours",
  snow_melt: "elapsed_hours",
  penetrant_wait: "elapsed_hours",
  parts_wait: "elapsed_hours",
  wash: "person_hours",
  rotor_seizure: "person_hours",
};
const OPERATION_IDS = new Set(Object.keys(OP_UNITS));
// Python の re.ASCII の \s に合わせて ASCII 空白だけを許す
const S = "[ \\t\\n\\r\\f\\v]";
const LINE_RE = new RegExp(
  `^${S}*when${S}+([a-z_]+)${S}+equals${S}+` +
    `(true|false|null|-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?|"(?:[^"\\\\]|\\\\[^\\n])*")` +
    `${S}*->${S}*set_range${S}+([a-z_]+)${S}+(\\{[^{}]*\\})${S}+` +
    `(person_hours|elapsed_hours)${S}*$`,
);
const PACK_KEYS = ["engine_id", "rule_version", "status", "approved_by", "effective_from", "source", "basis_unit", "basis_definition", "rules"];
const RULE_KEYS = ["rule_id", "expression", "source", "reason"];

function rangeOf(value: any): Dict | null {
  if (!keysAre(value, ["low", "typical", "high"])) return null;
  const result: Dict = {};
  for (const key of BANDS) {
    const number = value[key];
    if (typeof number === "boolean" || !isNumber(number) || !Number.isFinite(number) || number < 0) return null;
    result[key] = number;
  }
  if (!(result.low <= result.typical && result.typical <= result.high)) return null;
  return result;
}

function observation(scenario: Dict, field: string): [any, string, any] {
  const value = get(or(get(scenario, "fields"), {}), field);
  if (isDict(value) && "value" in value) return [get(value, "value"), get(value, "status", "unknown"), get(value, "source")];
  return [value, value !== null ? "declared" : "unknown", null];
}

export function parseToAst(expression: any): Dict | null {
  if (!isStr(expression)) return null;
  const match = LINE_RE.exec(expression);
  if (!match) return null;
  const [, field, rawValue, operationId, rawRange, unit] = match;
  if (!ALLOWED_FIELDS.has(field) || !OPERATION_IDS.has(operationId)) return null;
  let value: any;
  let numericRange: Dict | null;
  try {
    value = JSON.parse(rawValue);
    numericRange = rangeOf(JSON.parse(rawRange));
  } catch {
    return null;
  }
  if (isDict(value) || isList(value)) return null;
  if (typeof value === "number" && !Number.isFinite(value)) return null;
  if (numericRange === null || unit !== OP_UNITS[operationId]) return null;
  return { when: { field, equals: value }, op: "set_range", operation_id: operationId, range: numericRange, unit };
}

const pyFloatStr = (n: number) => (Number.isInteger(n) ? n.toFixed(1) : String(n));
const rangeJson = (v: Dict) => `{"low":${pyFloatStr(v.low)},"typical":${pyFloatStr(v.typical)},"high":${pyFloatStr(v.high)}}`;

export function defaultRulePack(scenario: Dict): Dict {
  item(scenario, "job_id");
  const rows: [string, string, any, Dict, string][] = [
    ["base_service", "work_scope", "front_brake_service", { low: 1.7, typical: 1.7, high: 1.7 }, "person_hours"],
    ["replacement_carry", "work_scope", "front_brake_service", { low: 0.2, typical: 0.2, high: 0.2 }, "person_hours"],
    ["snow_melt", "work_scope", "front_brake_service", { low: 0.5, typical: 0.5, high: 0.5 }, "elapsed_hours"],
    ["penetrant_wait", "work_scope", "front_brake_service", { low: 0.25, typical: 0.25, high: 0.25 }, "elapsed_hours"],
    ["parts_wait", "parts_wait_stock_checked", true, { low: 0.0, typical: 0.0, high: 0.0 }, "elapsed_hours"],
    ["wash", "work_scope", "front_brake_service", { low: 0.1, typical: 0.1, high: 0.1 }, "person_hours"],
    ["rotor_seizure", "rotor_relevance", "relevant", { low: 0.0, typical: 0.25, high: 0.5 }, "person_hours"],
  ];
  const rules = rows.map(([operationId, field, value, values, unit]) => ({
    rule_id: operationId,
    expression: `when ${field} equals ${JSON.stringify(value)} -> set_range ${operationId} ${rangeJson(values)} ${unit}`,
    source: "fictional_e03_default:" + operationId,
    reason: "共通Simulator fixture用の架空規則",
  }));
  return {
    engine_id: ENGINE_ID,
    rule_version: get(scenario, "rule_version", "fictional-rule-v1"),
    status: "approved",
    approved_by: "fictional_fixture_owner",
    effective_from: "2026-10-11T00:00:00+00:00",
    source: "fictional_e03_default",
    basis_unit: get(scenario, "basis_unit"),
    basis_definition: get(scenario, "basis_definition"),
    rules,
  };
}

function nullLabor(labor: Dict): void {
  const nulls = () => ({ low: null, typical: null, high: null });
  labor.person_hours = nulls();
  labor.elapsed_hours = nulls();
  for (const row of get(labor, "breakdown", [])) {
    row.hours = nulls();
    if ("elapsed_hours" in row) row.elapsed_hours = nulls();
    row.status = "missing-required";
  }
}

function validatePack(pack: any, scenario: Dict, gaps: string[]): [Dict[], string] {
  if (!isDict(pack)) {
    gaps.push("rule_pack:required");
    return [[], "unbound"];
  }
  const rawVersion = get(pack, "rule_version");
  const version = isStr(rawVersion) ? rawVersion : "unbound";
  if (!keysAre(pack, PACK_KEYS)) gaps.push("rule_pack:unknown_or_missing_top_level_key");
  if (get(pack, "engine_id") !== ENGINE_ID && get(pack, "engine_id") !== "e03") gaps.push("rule_pack:engine_id_required");
  if (!isStr(rawVersion) || !rawVersion.trim()) gaps.push("rule_pack:rule_version_required");
  if (isStr(rawVersion) && truthy(get(scenario, "rule_version")) && version !== get(scenario, "rule_version")) gaps.push("rule_pack:pinned_version_mismatch");
  if (get(pack, "status") !== "approved") gaps.push("rule_pack:approved_status_required");
  const approver = get(pack, "approved_by");
  if (!isStr(approver) || !approver.trim()) gaps.push("rule_pack:approver_required");
  for (const key of ["effective_from", "source"]) {
    if (!isStr(get(pack, key)) || !pack[key].trim()) gaps.push(`rule_pack:${key}_required`);
  }
  if (!pyEq(get(pack, "basis_unit"), get(scenario, "basis_unit")) || !isStr(get(pack, "basis_definition")) || get(pack, "basis_definition") !== get(scenario, "basis_definition")) {
    gaps.push("rule_pack:basis_mismatch");
  }
  const rules = get(pack, "rules");
  if (!isList(rules) || !rules.length) {
    gaps.push("rule_pack:rules_required");
    return [[], version];
  }
  const parsed: Dict[] = [];
  const seenIds = new Set<string>();
  const seenOps = new Set<string>();
  rules.forEach((rule: any, index: number) => {
    if (!isDict(rule) || !keysAre(rule, RULE_KEYS)) {
      gaps.push(`rule_pack:invalid_rule_shape:${index}`);
      return;
    }
    const ruleId = get(rule, "rule_id");
    if (!isStr(ruleId) || !ruleId.trim() || seenIds.has(ruleId)) {
      gaps.push(`rule_pack:invalid_or_duplicate_rule_id:${index}`);
      return;
    }
    seenIds.add(ruleId);
    const ast = parseToAst(get(rule, "expression"));
    if (ast === null) {
      gaps.push(`rule_pack:unknown_token_or_invalid_expression:${ruleId}`);
      return;
    }
    const operationId = ast.operation_id;
    if (seenOps.has(operationId)) {
      gaps.push(`rule_pack:duplicate_operation_id:${operationId}`);
      return;
    }
    seenOps.add(operationId);
    if (["source", "reason"].some((key) => !isStr(get(rule, key)) || !rule[key].trim())) {
      gaps.push(`rule_pack:source_and_reason_required:${ruleId}`);
      return;
    }
    Object.assign(ast, { rule_id: ruleId, source: rule.source, reason: rule.reason });
    parsed.push(ast);
  });
  return [parsed, version];
}

function interpret(astRows: Dict[], scenario: Dict, trace: Dict[], gaps: string[]): Record<string, Dict> {
  const operations = new Map<any, Dict>();
  for (const row of get(scenario, "operations", [])) if (isDict(row)) operations.set(get(row, "operation_id"), row);
  const selected: Record<string, Dict> = {};
  for (const ast of astRows) {
    const field = ast.when.field;
    const [observed, status, source] = observation(scenario, field);
    const matches = (status === "confirmed" || status === "declared") && pyEq(observed, ast.when.equals);
    trace.push({ event: "dsl_condition_evaluated", rule_id: ast.rule_id, field, matched: matches, observation_status: status, observation_source: source });
    if (!matches) continue;
    const operationId: string = ast.operation_id;
    const target = operations.get(operationId) ?? null;
    if (target === null && operationId !== "rotor_seizure") {
      gaps.push(`${operationId}:operation_missing`);
      continue;
    }
    const valueRange = { ...ast.range };
    if (ast.unit === "elapsed_hours") {
      if (target !== null) {
        const rawDuration = get(target, "elapsed_hours", get(target, "hours"));
        if (rawDuration === null) {
          selected[operationId] = ast;
          continue;
        }
        target.elapsed_hours = valueRange.typical;
        target.hours = valueRange.typical;
      }
    } else if (operationId === "replacement_carry") {
      const count = truthy(target) ? get(target, "person_count") : null;
      if (!isInt(count) || count <= 0) {
        gaps.push("replacement_carry:person_count_required");
        continue;
      }
      target!.hours_per_person = valueRange.typical / count;
    } else if (operationId === "rotor_seizure") {
      const current = get(or(get(scenario, "fields"), {}), "rotor_seizure_hours");
      const approval = get(get(or(get(scenario, "metadata"), {}), "approved_condition_widths", {}), "rotor_seizure_hours");
      const expected = { low: valueRange.low, typical: valueRange.typical, high: valueRange.high };
      if (!(isDict(current) && get(current, "status") === "confirmed" && pyEq(get(current, "value"), expected) && isDict(approval) && pyEq(get(approval, "new_value"), expected))) {
        gaps.push("rotor_seizure:range_must_match_human_approval");
        continue;
      }
    } else if (target !== null) {
      target.hours = valueRange.typical;
    }
    selected[operationId] = ast;
    trace.push({ event: "dsl_operation_applied", operation_id: operationId, operation_key: operationId, range: valueRange, unit: ast.unit, rule_id: ast.rule_id, rule_source: ast.source });
  }
  return selected;
}

// isinstance(v, (int, float)) は bool も真
const pyNum = (v: any) => typeof v === "number" || typeof v === "boolean";
const asNum = (v: any) => (typeof v === "boolean" ? (v ? 1 : 0) : v);

function applyRanges(labor: Dict, selected: Record<string, Dict>): void {
  const person: Dict = { low: 0.0, typical: 0.0, high: 0.0 };
  const elapsed: Dict = { low: 0.0, typical: 0.0, high: 0.0 };
  let elapsedComplete = true;
  for (const row of get(labor, "breakdown", [])) {
    const opId = get(row, "operation_id");
    let ast: Dict | undefined = typeof opId === "string" ? selected[opId] : undefined;
    if (ast === undefined && opId === "included_carry") {
      row.operation_key = "included_transport_removed";
      continue;
    }
    if (ast === undefined && opId === "replacement_carry") ast = selected.replacement_carry;
    if (ast !== undefined) {
      const values = { ...ast.range };
      row.operation_key = ast.operation_id;
      row.rule_version = get(ast, "_version");
      row.rule_source = ast.source;
      row.source = ast.source;
      row.reason = ast.reason;
      if (ast.unit === "elapsed_hours") {
        row.hours = { low: 0.0, typical: 0.0, high: 0.0 };
        const existingElapsed = get(row, "elapsed_hours");
        if (!(isDict(existingElapsed) && BANDS.every((k) => get(existingElapsed, k) === null))) {
          row.elapsed_hours = values;
          for (const band of BANDS) elapsed[band] += values[band];
        } else {
          elapsedComplete = false;
          labor.elapsed_hours = { low: null, typical: null, high: null };
        }
      } else {
        row.hours = values;
        for (const band of BANDS) {
          person[band] += values[band];
          const count = get(row, "person_count");
          const divisor = isInt(count) && count > 0 ? count : 1;
          elapsed[band] += values[band] / divisor;
        }
      }
    } else if ("elapsed_hours" in row) {
      const values = row.elapsed_hours;
      if (BANDS.every((k) => pyNum(get(values, k)))) {
        for (const band of BANDS) elapsed[band] += Number(asNum(values[band]));
      } else {
        elapsedComplete = false;
        labor.elapsed_hours = { low: null, typical: null, high: null };
      }
    } else {
      const values = or(get(row, "hours"), {});
      for (const band of BANDS) {
        if (pyNum(get(values, band))) {
          person[band] += Number(asNum(values[band]));
          elapsed[band] += Number(asNum(values[band]));
        }
      }
    }
  }
  labor.person_hours = Object.fromEntries(keysOf(person).map((k) => [k, pyRound(person[k], 10)]));
  if (elapsedComplete) labor.elapsed_hours = Object.fromEntries(keysOf(elapsed).map((k) => [k, pyRound(elapsed[k], 10)]));
}

function deductIncludedCredit(scenario: Dict, selected: Record<string, Dict>, gaps: string[], trace: Dict[]): void {
  const base = selected.base_service;
  if (base === undefined) return;
  const included = get(scenario, "operations", []).find((row: any) => isDict(row) && get(row, "operation_id") === "included_carry") ?? null;
  const raw = included ? get(included, "hours") : null;
  let credit: Dict | null;
  if (isDict(raw)) credit = rangeOf(raw);
  else if (isNumber(raw) && Number.isFinite(raw) && raw >= 0) credit = { low: raw, typical: raw, high: raw };
  else credit = null;
  if (!included || get(included, "included_in_base") !== true || credit === null) {
    gaps.push("included_transport:confirmed_base_credit_required");
    return;
  }
  const net: Dict = {};
  for (const key of BANDS) net[key] = base.range[key] - credit[key];
  if (BANDS.some((k) => net[k] < 0)) {
    gaps.push("included_transport:credit_exceeds_base");
    return;
  }
  if (!(net.low <= net.typical && net.typical <= net.high)) {
    gaps.push("included_transport:deducted_range_invalid");
    return;
  }
  base.range = net;
  trace.push({ event: "included_base_deduction", operation_id: "included_carry", hours: credit, rule_version: get(base, "_version") });
}

export function run(scenarioInput: Dict, rulePack: Dict | null = null): Dict {
  const scenario = deepcopy(scenarioInput);
  const pack: any = rulePack !== null ? deepcopy(rulePack) : deepcopy(defaultRulePack(scenario));
  let version: any = isDict(pack) ? get(pack, "rule_version", "unbound") : "unbound";
  const trace: Dict[] = [{ event: "dsl_pack_requested", engine_id: ENGINE_ID, rule_version: version }];
  const gaps: string[] = [];
  const [astRows, packVersion] = validatePack(pack, scenario, gaps);
  version = packVersion;
  trace.push({ event: "dsl_pack_loaded", rule_version: version, source: isDict(pack) ? get(pack, "source") : null, status: isDict(pack) ? get(pack, "status") : null });
  for (const ast of astRows) ast._version = version;
  const selected = interpret(astRows, scenario, trace, gaps);
  deductIncludedCredit(scenario, selected, gaps, trace);

  const operationIds = get(scenario, "operations", []).filter((row: any) => isDict(row)).map((row: Dict) => get(row, "operation_id"));
  for (const operationId of operationIds) {
    if (!isStr(operationId) || !(OPERATION_IDS.has(operationId) || operationId === "included_carry")) gaps.push("operation_id:unsupported");
  }
  if (operationIds.length !== new Set(operationIds.filter((x: any) => isStr(x))).size) gaps.push("operation_id:duplicate");
  for (const operationId of operationIds) {
    const key = operationId === "included_carry" ? "replacement_carry" : operationId;
    if (typeof key === "string" && Object.hasOwn(OP_UNITS, key) && !Object.hasOwn(selected, key)) gaps.push(`${key}:rule_not_matched`);
  }

  const [labor, , canonicalUnknowns] = referenceLabor(scenario);
  for (const u of canonicalUnknowns) if (!gaps.includes(u)) gaps.push(u);
  const unknowns = dedupe(gaps);
  const blocking = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));
  for (const row of get(labor, "breakdown", [])) row.operation_key = or(get(row, "operation_id"), get(row, "operation"));
  if (!blocking.length) {
    applyRanges(labor, selected);
    labor.unknowns = unknowns;
  } else {
    nullLabor(labor);
    labor.unknowns = unknowns;
  }
  for (const row of get(labor, "breakdown", [])) {
    if (!("reason" in row)) row.reason = "共通の架空Simulator計算結果";
    if (!("status" in row)) row.status = "proposed";
  }
  const approvals = get(labor, "breakdown", [])
    .filter((row: Dict) => isDict(get(row, "approval")))
    .map((row: Dict) => ({ operation_key: get(row, "operation_id"), ...row.approval }));
  const status = blocking.length ? "missing-required" : unknowns.length ? "partial" : "proposed";
  return {
    engine_id: ENGINE_ID,
    rule_version: version,
    status,
    labor,
    trace,
    operation_keys: dedupe(Object.values(selected).map((ast) => ast.operation_id)),
    approvals,
    simulator_notice: SIMULATOR_NOTICE,
  };
}
