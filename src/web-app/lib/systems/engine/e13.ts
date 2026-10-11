/* eslint-disable @typescript-eslint/no-explicit-any */
// E13: schema-driven condition intake for the fictional repair simulator. 元: e13.py
import {
  type Dict, PyValueError, dedupe, deepcopy, get, isDict, isList, isNumber, isStr, has, isoDate, item, keysAre, pyEq, pyIn, repr, truthy,
} from "./py";
import { BANDS } from "./contract";
import * as e07 from "./e07";

export const ENGINE_ID = "e13_schema_driven_condition_form";
export const RULE_VERSION = "e13-schema-driven-condition-form-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const nullRange = () => ({ low: null, typical: null, high: null });

export const FORM_SCHEMAS: Record<string, Dict[]> = {
  front_brake_service: [
    { field: "work_scope", label: "作業範囲", choices: ["front_brake_service"], required: true, operation_ids: ["base_service"] },
    { field: "included_operations", label: "基準に含まれる作業", choices: ["remove_install", "rust_observation", "snow_removal"], multiple: true, required: true, operation_ids: ["base_service", "included_carry", "replacement_carry", "snow_melt"] },
    { field: "rotor_relevance", label: "ローター固着の関連", choices: ["relevant", "unrelated"], required: true, operation_ids: ["rotor_seizure"] },
    { field: "rotor_seizure_hours", label: "固着対応の条件幅（人時）", kind: "range", required_if: { field: "rotor_relevance", equals: "relevant" }, operation_ids: ["rotor_seizure"] },
    { field: "subframe_relevance", label: "サブフレーム作業の関連", choices: ["relevant", "unrelated", "unknown"], required: true, operation_ids: ["base_service"] },
    { field: "parts_wait_stock_checked", label: "部品在庫を確認済み", choices: [true, false], required: true, operation_ids: ["parts_wait"] },
  ],
};

/** Return the versioned public form definition for a job. */
export function buildSchema(job: any, rulePack: any = null): Dict {
  const pack: Dict = isDict(rulePack) ? rulePack : {};
  const definitions = get(pack, "form_schemas", FORM_SCHEMAS);
  const fields = isDict(definitions) ? get(definitions, job) : null;
  const version = get(pack, "schema_version", RULE_VERSION);
  return {
    schema_id: `${ENGINE_ID}:${job === null ? "None" : isStr(job) ? job : repr(job)}`,
    schema_version: isStr(version) ? version : repr(version),
    job_id: job,
    fields: isList(fields) ? deepcopy(fields) : [],
  };
}

function active(definition: Dict, fields: Dict): boolean {
  const condition = get(definition, "required_if");
  if (!isDict(condition)) return true;
  const observed = get(fields, get(condition, "field"), {});
  const value = isDict(observed) ? get(observed, "value") : observed;
  return pyEq(value, get(condition, "equals"));
}

function hasValue(fields: Dict, key: string): boolean {
  const it = get(fields, key);
  return isDict(it) && get(it, "value") !== null && ["confirmed", "declared"].includes(get(it, "status"));
}

/** Describe fields and ask only for active missing or unknown observations. */
export function renderForm(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? scenarioInput : {};
  const job = get(scenario, "job_id");
  const schema = buildSchema(job, rulePack);
  const fields: Dict = isDict(get(scenario, "fields")) ? scenario.fields : {};
  const questions: Dict[] = [];
  for (const definition of schema.fields) {
    const isActive = active(definition, fields);
    const current = get(fields, item(definition, "field"));
    const unknown = isDict(current) && get(current, "status") === "unknown";
    const required = truthy(get(definition, "required", false)) || (get(definition, "required_if") !== null && isActive);
    if (isActive && required && (!hasValue(fields, definition.field) || unknown)) questions.push(deepcopy(definition));
  }
  return { schema, questions };
}

function validValue(definition: Dict, value: any): boolean {
  if (get(definition, "kind") === "range") {
    return (
      isDict(value) && keysAre(value, [...BANDS]) &&
      BANDS.every((k) => isNumber(value[k]) && value[k] >= 0) &&
      value.low <= value.typical && value.typical <= value.high
    );
  }
  const choices = get(definition, "choices");
  if (truthy(get(definition, "multiple"))) {
    return isList(value) && value.length === new Set(value.map((v: any) => (typeof v === "object" ? JSON.stringify(v) : v))).size && value.every((v: any) => pyIn(v, choices));
  }
  return pyIn(value, choices);
}

function validDate(confirmedAt: any): boolean {
  try {
    if (isStr(confirmedAt)) isoDate(confirmedAt.slice(0, 10));
    return isStr(confirmedAt) && confirmedAt.length > 0;
  } catch (e) {
    if (e instanceof PyValueError) return false;
    throw e;
  }
}

/** Apply explicitly confirmed answers; unknown is retained without inventing a value. */
export function applyAnswers(scenarioInput: any, answers: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  if (!("fields" in scenario)) scenario.fields = {};
  const fields = scenario.fields;
  if (!isDict(fields)) return { scenario_input: scenario, errors: ["fields:object_required"], approvals: [] };
  const job = get(scenario, "job_id");
  const schema = buildSchema(job, rulePack);
  const byKey = new Map<string, Dict>(schema.fields.map((d: Dict) => [item(d, "field"), d]));
  const errors: string[] = [];
  const approvals: Dict[] = [];
  if (!isDict(answers)) return { scenario_input: scenario, errors: ["answers:object_required"], approvals: [] };
  const driverFields = new Set<any>();
  for (const definition of byKey.values()) {
    const condition = get(definition, "required_if", {});
    if (isDict(condition)) driverFields.add(get(condition, "field"));
  }
  const ordered = Object.entries(answers).sort((a, b) => (driverFields.has(a[0]) ? 0 : 1) - (driverFields.has(b[0]) ? 0 : 1));
  for (const [key, answer] of ordered) {
    const definition = byKey.get(key);
    if (definition === undefined) {
      errors.push(`${key}:unknown_field`);
      continue;
    }
    if (!isDict(answer)) {
      errors.push(`${key}:answer_object_required`);
      continue;
    }
    const value = get(answer, "value");
    const actor = get(answer, "actor");
    const source = get(answer, "source");
    const confirmedAt = get(answer, "confirmed_at");
    const provenanceOk = () =>
      get(answer, "confirmed") === true && isStr(actor) && actor.trim() && isStr(source) && source.trim() && validDate(confirmedAt);
    if (pyEq(value, "unknown") || get(answer, "status") === "unknown") {
      if (!provenanceOk()) {
        errors.push(`${key}:explicit_confirmation_actor_source_date_required`);
        continue;
      }
      const prior = get(fields, key);
      const oldValue = isDict(prior) ? get(prior, "value") : null;
      fields[key] = { value: null, status: "unknown", source, confirmed_at: confirmedAt };
      approvals.push({ field: key, actor, source, confirmed_at: confirmedAt, old_value: deepcopy(oldValue), new_value: null });
      continue;
    }
    if (!active(definition, fields)) {
      errors.push(`${key}:condition_not_active`);
      continue;
    }
    if (!validValue(definition, value)) {
      errors.push(`${key}:choice_or_value_invalid`);
      continue;
    }
    if (!provenanceOk()) {
      errors.push(`${key}:explicit_confirmation_actor_source_date_required`);
      continue;
    }
    const prior = get(fields, key);
    const oldValue = isDict(prior) ? get(prior, "value") : null;
    fields[key] = { value: deepcopy(value), status: "confirmed", source, confirmed_at: confirmedAt };
    approvals.push({ field: key, actor, source, confirmed_at: confirmedAt, old_value: deepcopy(oldValue), new_value: deepcopy(value) });
    if (key === "rotor_seizure_hours") {
      if (!("metadata" in scenario)) scenario.metadata = {};
      const metadata = scenario.metadata;
      if (!has(metadata, "approved_condition_widths")) metadata.approved_condition_widths = {};
      metadata.approved_condition_widths[key] = { actor, reason: get(answer, "reason", "人が条件幅を確認"), old_value: deepcopy(oldValue), new_value: deepcopy(value) };
    }
  }
  return { scenario_input: scenario, errors, approvals };
}

function stopped(unknowns: string[]): Dict {
  return { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(unknowns) };
}

/** Validate schema-required observations, then delegate calculation to E07. */
export function run(scenarioInput: any, rulePack: any = null): Dict {
  const original: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const schemaView = renderForm(original, rulePack);
  const questions = schemaView.questions;
  const errors: string[] = [];
  for (const definition of schemaView.schema.fields) {
    const isActive = active(definition, isDict(get(original, "fields")) ? original.fields : {});
    const isRequired = truthy(get(definition, "required", false)) || (get(definition, "required_if") !== null && isActive);
    if (isActive && isRequired) {
      const key = item(definition, "field");
      if (!hasValue(get(original, "fields", {}), key)) {
        const current = isDict(get(original, "fields")) ? get(original.fields, key) : null;
        const suffix = isDict(current) && get(current, "status") === "unknown" ? "unknown_confirmation_required" : "required_observation_missing";
        errors.push(`${key}:${suffix}`);
      }
    }
  }
  if (errors.length) {
    const trace = [{ stage: "schema_form", schema: schemaView.schema, questions, validation_errors: errors, provenance: deepcopy(get(original, "fields", {})) }];
    return { engine_id: ENGINE_ID, rule_version: RULE_VERSION, status: "missing-required", labor: stopped(errors), trace, operation_keys: [], approvals: [], simulator_notice: SIMULATOR_NOTICE };
  }
  const result = e07.run(deepcopy(original), rulePack);
  result.engine_id = ENGINE_ID;
  result.rule_version = RULE_VERSION;
  result.trace.push({ stage: "schema_form", schema: schemaView.schema, questions, validation_errors: [], provenance: deepcopy(get(original, "fields", {})) });
  result.approvals = isDict(get(original, "metadata")) ? deepcopy(get(original.metadata, "approved_condition_widths", {})) : [];
  result.simulator_notice = SIMULATOR_NOTICE;
  return result;
}
