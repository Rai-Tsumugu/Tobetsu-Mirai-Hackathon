/* eslint-disable @typescript-eslint/no-explicit-any */
// E02: versioned, approval-gated JSON rules for fictional labor estimates. 元: e02.py
import {
  type Dict, dedupe, deepcopy, get, isDict, isList, isNumber, isStr, item, keysAre, keysOf, or, pyEq, pyInt, pyRound, repr, truthy,
} from "./py";
import { BANDS, referenceLabor } from "./contract";

export const ENGINE_ID = "e02_versioned_json";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const OPERATION_KEYS: Record<string, string> = {
  base_service: "base_service", included_carry: "replacement_carry",
  replacement_carry: "replacement_carry", snow_melt: "snow_melt",
  penetrant_wait: "penetrant_wait", parts_wait: "parts_wait", wash: "wash",
};
const REQUIRED_SCENARIO_OPERATION: Record<string, string> = {
  base_service: "base_service", replacement_carry: "replacement_carry",
  snow_melt: "snow_melt", penetrant_wait: "penetrant_wait",
  parts_wait: "parts_wait", wash: "wash",
};
const RULE_KEYS = new Set(["base_service", "replacement_carry", "snow_melt", "penetrant_wait", "parts_wait", "wash", "rotor_seizure"]);
const PACK_KEYS = new Set(["engine_id", "rule_version", "status", "approved_by", "approver", "effective_from", "source", "basis_unit", "basis_definition", "rules"]);
const nonEmptyStr = (v: any) => isStr(v) && v.trim().length > 0;
const own = (o: Dict, k: any) => typeof k === "string" && Object.prototype.hasOwnProperty.call(o, k);

function obs(scenario: Dict, key: string): [any, string, any] {
  const raw = get(or(get(scenario, "fields"), {}), key);
  if (isDict(raw) && "value" in raw) return [get(raw, "value"), get(raw, "status", "unknown"), get(raw, "source")];
  return [raw, raw !== null ? "declared" : "unknown", null];
}

export function rangeOf(value: any): Dict | null {
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

function nullRanges(labor: Dict): void {
  const nr = () => ({ low: null, typical: null, high: null });
  labor.person_hours = nr();
  labor.elapsed_hours = nr();
  for (const row of get(labor, "breakdown", [])) {
    row.hours = nr();
    if ("elapsed_hours" in row) row.elapsed_hours = nr();
    row.status = "missing-required";
  }
}

function ruleMatches(rule: Dict, scenario: Dict): boolean {
  if (!pyEq(get(rule, "job_id"), get(scenario, "job_id"))) return false;
  const condition = get(rule, "condition");
  if (!isDict(condition)) return false;
  const [value, status] = obs(scenario, item(condition, "field"));
  if (status === null || status === "unknown" || status === "assumed") return false;
  if ("equals" in condition) return pyEq(value, condition.equals);
  return isList(value) && value.some((v) => pyEq(v, item(condition, "contains")));
}

function validatePack(pack: Dict, scenario: Dict, gaps: string[]): Record<string, Dict> {
  if (keysOf(pack).some((k) => !PACK_KEYS.has(k))) gaps.push("rule_pack:unknown_top_level_key");
  if (!isStr(get(pack, "rule_version")) || !get(pack, "rule_version", "").trim()) gaps.push("rule_pack:rule_version_required");
  if (get(pack, "engine_id") !== ENGINE_ID && get(pack, "engine_id") !== "e02") gaps.push("rule_pack:engine_id_required");
  if (get(pack, "status") !== "approved") gaps.push("rule_pack:approved_status_required");
  const approver = or(get(pack, "approved_by"), get(pack, "approver"));
  if (!isStr(approver) || !or(get(pack, "approved_by"), get(pack, "approver", "")).trim()) gaps.push("rule_pack:approver_required");
  if (!isStr(get(pack, "effective_from")) || !get(pack, "effective_from", "").trim()) gaps.push("rule_pack:effective_from_required");
  if (!isStr(get(pack, "source")) || !get(pack, "source", "").trim()) gaps.push("rule_pack:source_required");
  if (!pyEq(get(pack, "basis_unit"), get(scenario, "basis_unit")) || !isStr(get(pack, "basis_definition")) || get(pack, "basis_definition") !== get(scenario, "basis_definition")) gaps.push("rule_pack:basis_mismatch");
  const rules = get(pack, "rules");
  if (!isList(rules) || !rules.length) {
    gaps.push("rule_pack:rules_required");
    return {};
  }
  const selected: Record<string, Dict> = {};
  const seen = new Set<string>();
  rules.forEach((rule, index) => {
    if (!isDict(rule) || !keysAre(rule, ["job_id", "operation_key", "condition", "hours", "unit", "source"])) {
      gaps.push(`rule_pack:invalid_rule_schema:${index}`);
      return;
    }
    const key = get(rule, "operation_key");
    if (typeof key !== "string" || !RULE_KEYS.has(key)) {
      gaps.push(`rule_pack:invalid_operation_key:${repr(key)}`);
      return;
    }
    if (seen.has(key)) {
      gaps.push(`rule_pack:duplicate_operation_key:${key}`);
      return;
    }
    seen.add(key);
    const condition = get(rule, "condition");
    if (
      !isStr(rule.job_id) || !rule.job_id.trim() || !isDict(condition) ||
      !["work_scope", "included_operations", "parts_wait_stock_checked", "rotor_relevance"].includes(condition.field) ||
      !(keysAre(condition, ["field", "equals"]) || keysAre(condition, ["field", "contains"])) ||
      ("contains" in condition && condition.field !== "included_operations") ||
      !isStr(rule.source) || !rule.source.trim()
    ) {
      gaps.push(`rule_pack:invalid_rule_schema:${key}`);
      return;
    }
    const expectedUnit = ["snow_melt", "penetrant_wait", "parts_wait"].includes(key) ? "elapsed_hours" : "person_hours";
    if (get(rule, "unit") !== expectedUnit || rangeOf(get(rule, "hours")) === null) {
      gaps.push(`rule_pack:invalid_numeric_range_or_unit:${key}`);
      return;
    }
    if (ruleMatches(rule, scenario)) {
      selected[key] = rule;
      const [observedValue, observedStatus, observedSource] = obs(scenario, rule.condition.field);
      rule._observation = { value: observedValue, status: observedStatus, source: observedSource };
    }
  });
  return selected;
}

function injectRuleValues(scenario: Dict, selected: Record<string, Dict>): void {
  const opById: Record<string, Dict> = {};
  for (const op of get(scenario, "operations", [])) opById[String(get(op, "operation_id"))] = op;
  for (const [key, rule] of Object.entries(selected)) {
    const values = rangeOf(rule.hours)!;
    const typical = values.typical;
    if (key === "base_service" && "base_service" in opById) {
      opById.base_service.hours = typical;
    } else if (key === "replacement_carry" && "replacement_carry" in opById) {
      const count = pyInt(or(get(opById.replacement_carry, "person_count"), 0));
      if (count > 0) opById.replacement_carry.hours_per_person = typical / count;
    } else if (key === "wash" && "wash" in opById) {
      opById.wash.hours = typical;
    } else if (["snow_melt", "penetrant_wait", "parts_wait"].includes(key) && key in opById) {
      if (get(opById[key], "elapsed_hours", get(opById[key], "hours")) !== null) opById[key].elapsed_hours = typical;
    } else if (key === "rotor_seizure") {
      const raw = get(or(get(scenario, "fields"), {}), "rotor_seizure_hours");
      if (isDict(raw) && "value" in raw) {
        raw.value = { ...values };
      } else {
        if (!("fields" in scenario)) scenario.fields = {};
        scenario.fields.rotor_seizure_hours = { value: { ...values }, status: "confirmed", source: rule.source };
      }
    }
  }
}

export function run(scenarioInput: Dict, rulePack: Dict | null = null): Dict {
  const scenario = deepcopy(scenarioInput);
  const pinnedVersion = get(scenario, "rule_version");
  const pack: Dict | null = isDict(rulePack) ? deepcopy(rulePack) : null;
  const version = or(or(pinnedVersion, get(or(pack, {}), "rule_version")), "unbound");
  const trace: Dict[] = [{ event: "rule_pack_requested", engine_id: ENGINE_ID, rule_version: version }];
  const gaps: string[] = [];
  let selected: Record<string, Dict> = {};

  if (pack === null) {
    gaps.push("rule_pack:required");
  } else {
    if (truthy(pinnedVersion) && !pyEq(get(pack, "rule_version"), pinnedVersion)) gaps.push("rule_pack:pinned_version_mismatch");
    selected = validatePack(pack, scenario, gaps);
    trace.push({ event: "rule_pack_loaded", rule_version: get(pack, "rule_version"), source: get(pack, "source"), status: get(pack, "status"), effective_from: get(pack, "effective_from") });
    for (const [key, rule] of Object.entries(selected)) {
      trace.push({ event: "rule_applied", operation_key: key, job_id: rule.job_id, condition: { ...rule.condition }, hours: { ...rangeOf(rule.hours) }, unit: rule.unit, rule_source: rule.source, rule_version: version, observation: get(rule, "_observation") });
    }
  }

  const [included, includedStatus] = obs(scenario, "included_operations");
  const requiredIncluded = ["remove_install", "rust_observation", "snow_removal"];
  if (!isList(included) || !["confirmed", "declared"].includes(includedStatus)) {
    gaps.push("included_operations:required_confirmed_list");
  } else if (!requiredIncluded.every((k) => included.includes(k))) {
    gaps.push("included_operations:required_keys_missing");
  } else if (included.some((k) => !requiredIncluded.includes(k))) {
    gaps.push("included_operations:unknown_operation_key");
  }

  const operations: Dict[] = get(scenario, "operations", []);
  const scenarioOperationIds = new Set(operations.map((op) => get(op, "operation_id")));
  for (const [ruleKey, operationId] of Object.entries(REQUIRED_SCENARIO_OPERATION)) {
    if (ruleKey in selected && !scenarioOperationIds.has(operationId)) gaps.push(`${operationId}:scenario_operation_missing`);
  }

  for (const operation of operations) {
    const operationId = get(operation, "operation_id");
    const key = typeof operationId === "string" && own(OPERATION_KEYS, operationId) ? OPERATION_KEYS[operationId] : undefined;
    if (key === undefined) gaps.push(`${or(operationId, "operation")}:rule_missing`);
    else if (!(key in selected)) gaps.push(`${operationId}:rule_not_matched`);
  }

  const includedCarry = operations.find((op) => get(op, "operation_id") === "included_carry") ?? null;
  const includedRaw = includedCarry ? get(includedCarry, "hours") : null;
  let includedCredit: Dict | null;
  if (!includedCarry || get(includedCarry, "included_in_base") !== true) {
    includedCredit = null;
    gaps.push("included_transport:confirmed_base_credit_required");
  } else if (isDict(includedRaw)) {
    includedCredit = rangeOf(includedRaw);
    if (includedCredit === null) gaps.push("included_transport:invalid_base_credit_range");
  } else if (isNumber(includedRaw) && typeof includedRaw !== "boolean" && Number.isFinite(includedRaw) && includedRaw >= 0) {
    includedCredit = { low: includedRaw, typical: includedRaw, high: includedRaw };
  } else {
    includedCredit = null;
    gaps.push("included_transport:invalid_base_credit_range");
  }

  const [rotorRelevance, rotorStatus] = obs(scenario, "rotor_relevance");
  const rotorApproval = get(get(or(get(scenario, "metadata"), {}), "approved_condition_widths", {}), "rotor_seizure_hours");
  const rotorRule = selected.rotor_seizure;
  if (rotorRelevance === "relevant") {
    const ruleRange = rotorRule ? rangeOf(get(rotorRule, "hours")) : null;
    if (!["confirmed", "declared"].includes(rotorStatus) || !truthy(ruleRange)) gaps.push("rotor_seizure:confirmed_rule_required");
    if (
      !isDict(rotorApproval) || !nonEmptyStr(get(rotorApproval, "actor")) || !nonEmptyStr(get(rotorApproval, "reason")) ||
      get(rotorApproval, "old_value") !== null || !pyEq(rangeOf(get(rotorApproval, "new_value")), ruleRange)
    ) gaps.push("rotor_seizure:approval_actor_reason_and_matching_old_new_range_required");
  }

  if (!gaps.some((g) => !g.startsWith("trace:"))) injectRuleValues(scenario, selected);

  const [labor, , canonicalUnknowns] = referenceLabor(scenario);
  for (const u of canonicalUnknowns) if (!gaps.includes(u)) gaps.push(u);
  let unknowns = dedupe(gaps.filter((g) => !g.startsWith("trace:")));
  let blocking = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));

  const keyForRow: Record<string, string> = { ...OPERATION_KEYS, rotor_seizure: "rotor_seizure" };
  const person: Dict = { low: 0.0, typical: 0.0, high: 0.0 };
  const elapsed: Dict = { low: 0.0, typical: 0.0, high: 0.0 };
  if (includedCredit === null) includedCredit = { low: 0.0, typical: 0.0, high: 0.0 };
  let netBase: Dict;
  if ("base_service" in selected) {
    const baseRange = rangeOf(selected.base_service.hours)!;
    netBase = {};
    for (const band of BANDS) netBase[band] = baseRange[band] - includedCredit[band];
    if (BANDS.some((b) => netBase[b] < 0)) gaps.push("included_transport:credit_exceeds_base");
    trace.push({ event: "included_base_deduction", operation_key: "included_carry", hours: { ...includedCredit }, source: includedCarry ? get(includedCarry, "source") : null, rule_version: version });
  } else {
    netBase = { low: 0.0, typical: 0.0, high: 0.0 };
  }
  for (const row of labor.breakdown as Dict[]) {
    const operationId = get(row, "operation_id");
    if (operationId === "included_carry") {
      row.operation_key = "included_transport_removed";
      continue;
    }
    const operationKey: any = operationId === "rotor_seizure" ? "rotor_seizure" : (typeof operationId === "string" && own(keyForRow, operationId) ? keyForRow[operationId] : operationId);
    row.operation_key = operationKey;
    const rule = typeof operationKey === "string" ? selected[operationKey] : undefined;
    if (rule) {
      const values: Dict = operationKey === "base_service" ? { ...netBase } : rangeOf(rule.hours)!;
      row.hours = rule.unit === "elapsed_hours" ? { low: 0.0, typical: 0.0, high: 0.0 } : { ...values };
      row.rule_version = version;
      row.rule_source = rule.source;
      row.source = rule.source;
      if (rule.unit === "elapsed_hours") {
        const observedElapsed = get(row, "elapsed_hours");
        if (!(isDict(observedElapsed) && BANDS.some((b) => get(observedElapsed, b) === null))) {
          row.elapsed_hours = { ...values };
          for (const band of BANDS) elapsed[band] += values[band];
        }
      } else {
        for (const band of BANDS) {
          person[band] += values[band];
          if (operationKey === "replacement_carry") continue;
          elapsed[band] += values[band];
        }
        if (operationKey === "replacement_carry") {
          const replacementOp = operations.find((op) => get(op, "operation_id") === "replacement_carry") ?? {};
          const count = Math.max(1, pyInt(or(get(replacementOp, "person_count"), 1)));
          for (const band of BANDS) elapsed[band] += values[band] / count;
        }
      }
    } else if (get(row, "status") === "wait") {
      for (const band of BANDS) elapsed[band] += Number(or(get(or(get(row, "elapsed_hours"), {}), band), 0));
    }
  }

  for (const band of BANDS) {
    person[band] = pyRound(person[band], 10);
    elapsed[band] = pyRound(elapsed[band], 10);
  }

  unknowns = dedupe([...unknowns, ...gaps.filter((g) => !g.startsWith("trace:"))]);
  blocking = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));
  if (blocking.length) {
    nullRanges(labor);
  } else {
    labor.person_hours = person;
    labor.elapsed_hours = unknowns.some((u) => u.endsWith(":elapsed_duration_unknown")) ? { low: null, typical: null, high: null } : elapsed;
  }
  labor.unknowns = unknowns;

  const approvals: Dict[] = [];
  if (pack && get(pack, "status") === "approved") {
    approvals.push({ type: "rule_pack", approver: or(get(pack, "approved_by"), get(pack, "approver")), effective_from: get(pack, "effective_from"), source: get(pack, "source"), rule_version: version });
  }
  if (rotorRelevance === "relevant" && isDict(rotorApproval)) {
    approvals.push({ operation_key: "rotor_seizure", actor: get(rotorApproval, "actor"), reason: get(rotorApproval, "reason"), old_value: deepcopy(get(rotorApproval, "old_value")), new_value: deepcopy(get(rotorApproval, "new_value")), applied_range: deepcopy(rotorRule ? rangeOf(rotorRule.hours) : null), rule_version: version });
  }
  const status = blocking.length ? "missing-required" : unknowns.length ? "partial" : "proposed";
  const operationKeys = Object.keys(selected);
  trace.push({ event: "rule_version_pinned", rule_version: version, source: get(or(pack, {}), "source"), operation_keys: operationKeys });
  return { engine_id: ENGINE_ID, rule_version: version, status, labor, trace, operation_keys: operationKeys, approvals, simulator_notice: SIMULATOR_NOTICE };
}
