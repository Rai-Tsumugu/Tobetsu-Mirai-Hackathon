/* eslint-disable @typescript-eslint/no-explicit-any */
// E16: copy job context while expiring vehicle observations between visits. 元: e16.py
import { type Dict, PyTypeError, PyValueError, dedupe, deepcopy, get, isDict, isList, isNumber, isStr, keysOf, or, pyEq, pyIn, truthy } from "./py";
import { BANDS, referenceLabor } from "./contract";

export const ENGINE_ID = "e16_previous_visit_expiry_copy";
export const RULE_VERSION = "e16-previous-visit-expiry-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証は行いません。";
const nullRange = () => ({ low: null, typical: null, high: null });
const PRESERVED_FIELDS = ["work_scope", "included_operations"];
// 元の frozenset は反復順が実行ごとに変わる。ここでは宣言順に固定する。
const CONDITION_FIELDS = ["rotor_relevance", "rotor_seizure_hours", "subframe_relevance", "parts_wait_stock_checked", "rust_observation", "snow_observation"];
const TOKEN = /^(?:veh|vehicle)_[A-Za-z0-9_-]{4,120}$/;

/** `x in {a, b}`。unhashable なら Python と同じメッセージの TypeError。 */
function inSet(x: any, values: any[]): boolean {
  if (isList(x)) throw new PyTypeError("cannot use 'list' as a set element (unhashable type: 'list')");
  if (isDict(x)) throw new PyTypeError("cannot use 'dict' as a set element (unhashable type: 'dict')");
  return values.some((v) => pyEq(v, x));
}

const fieldValue = (it: any): any => (isDict(it) && "value" in it ? it.value : it);

/** Create a new immutable visit snapshot, marking every carried condition unknown. */
export function copyPreviousVisit(previousVisit: any, currentVisitId: any, observedAt: any): Dict {
  if (!isDict(previousVisit)) throw new PyValueError("previous_visit:object_required");
  const token = get(previousVisit, "vehicle_token");
  if (!isStr(token) || !TOKEN.test(token)) throw new PyValueError("previous_visit:anonymous_vehicle_token_required");
  const oldTime = get(previousVisit, "observed_at");
  const conditions = get(previousVisit, "conditions");
  if (!isStr(oldTime) || !oldTime.trim() || !isDict(conditions)) throw new PyValueError("previous_visit:observed_at_and_conditions_required");
  if (!isStr(currentVisitId) || !currentVisitId.trim()) throw new PyValueError("current_visit_id:required");
  if (!isStr(observedAt) || !observedAt.trim()) throw new PyValueError("observed_at:required");
  const expired = keysOf(conditions).filter((k) => CONDITION_FIELDS.includes(k)).sort();
  const carried: Dict = {};
  for (const [key, value] of Object.entries(conditions)) if (PRESERVED_FIELDS.includes(key)) carried[key] = deepcopy(value);
  for (const [key, value] of Object.entries(conditions)) {
    if (CONDITION_FIELDS.includes(key)) {
      carried[key] = { value: null, status: "unknown", source: "e16_expired_copy", copied_value: deepcopy(fieldValue(value)), copied_from: oldTime };
    }
  }
  return {
    visit_id: currentVisitId.trim(), vehicle_token: token.trim(), observed_at: observedAt.trim(), conditions: carried,
    copied_from: { visit_id: get(previousVisit, "visit_id"), observed_at: oldTime }, expired_fields: expired, observations: [],
  };
}

/** Return a new visit with one current observation appended and auditable. */
export function currentConfirm(visit: any, field: any, value: any, actor: any, reason: any, observedAt: any = null): Dict {
  const copied: Dict | null = isDict(visit) ? deepcopy(visit) : null;
  if (copied === null) return { visit: null, approval: null, error: "visit:object_required" };
  if (!(isStr(field) && CONDITION_FIELDS.includes(field)) || !pyIn(field, get(copied, "conditions", {}))) {
    return { visit: copied, approval: null, error: "field:not_expired_condition" };
  }
  if (["rotor_relevance", "subframe_relevance"].includes(field) && !inSet(value, ["relevant", "unrelated"])) return { visit: copied, approval: null, error: "confirmation:invalid_relevance" };
  if (field === "parts_wait_stock_checked" && typeof value !== "boolean") return { visit: copied, approval: null, error: "confirmation:boolean_required" };
  if (["rust_observation", "snow_observation"].includes(field) && !inSet(value, ["present", "absent"])) return { visit: copied, approval: null, error: "confirmation:invalid_condition" };
  if (field === "rotor_seizure_hours") {
    if (
      !isDict(value) || keysOf(value).length !== 3 || !BANDS.every((k) => k in value) ||
      BANDS.some((k) => !isNumber(value[k]) || value[k] < 0) || !(value.low <= value.typical && value.typical <= value.high)
    ) return { visit: copied, approval: null, error: "confirmation:invalid_condition_range" };
  }
  if (!isStr(actor) || !actor.trim() || !isStr(reason) || !reason.trim()) return { visit: copied, approval: null, error: "confirmation:actor_and_reason_required" };
  const stamp = or(observedAt, get(copied, "observed_at"));
  if (!isStr(stamp) || !stamp.trim()) return { visit: copied, approval: null, error: "confirmation:observed_at_required" };
  const prior = copied.conditions[field];
  const oldValue = isDict(prior) ? get(prior, "value") : prior;
  const observation = { field, value: deepcopy(value), status: "confirmed", source: "e16_current_visit", actor: actor.trim(), reason: reason.trim(), observed_at: or(observedAt, copied.observed_at).trim() };
  copied.conditions[field] = { value: deepcopy(value), status: "confirmed", source: "e16_current_visit", confirmed_at: observation.observed_at };
  if (!("observations" in copied)) copied.observations = [];
  copied.observations.push(observation);
  const approval = { field, old_value: oldValue, new_value: deepcopy(value), actor: actor.trim(), reason: reason.trim(), observed_at: observation.observed_at };
  return { visit: copied, approval, error: null };
}

function nullLabor(unknowns: string[]): Dict {
  return { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(unknowns) };
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const pack: Dict | null = isDict(rulePack) ? deepcopy(rulePack) : null;
  let version: any = or(get(scenario, "rule_version"), RULE_VERSION);
  const issues: string[] = [];
  const trace: Dict[] = [];
  const approvals: Dict[] = [];
  if (!isDict(scenarioInput)) issues.push("scenario_input:object_required");
  if (rulePack !== null) {
    if (pack === null) {
      issues.push("rule_pack:object_required");
    } else {
      if (keysOf(pack).some((k) => !["engine_id", "rule_version", "previous_visit", "current_confirm"].includes(k))) issues.push("rule_pack:unknown_key");
      if (!pyIn(get(pack, "engine_id"), [null, ENGINE_ID, "e16"])) issues.push("rule_pack:engine_id_mismatch");
      if ("rule_version" in pack && (!isStr(pack.rule_version) || !pack.rule_version.trim())) issues.push("rule_pack:rule_version_required");
      if (truthy(get(pack, "rule_version")) && truthy(get(scenario, "rule_version")) && !pyEq(pack.rule_version, scenario.rule_version)) issues.push("rule_pack:pinned_version_mismatch");
      version = or(get(pack, "rule_version"), version);
      if ("previous_visit" in pack) {
        const previous = pack.previous_visit;
        try {
          let copied = copyPreviousVisit(previous, get(scenario, "visit_id"), get(scenario, "observed_at"));
          if (get(previous, "job_id") !== null) {
            if (!pyIn(get(scenario, "job_id"), [null, get(previous, "job_id")])) issues.push("previous_visit:job_id_mismatch");
            else scenario.job_id = previous.job_id;
          }
          const scenarioFields = get(scenario, "fields", {});
          if (isDict(scenarioFields)) {
            for (const key of CONDITION_FIELDS) {
              if (key in scenarioFields) {
                const raw = scenarioFields[key];
                if (isDict(raw) && get(raw, "status") === "unknown" && get(raw, "value") === null) continue;
                if (!copied.expired_fields.includes(key)) copied.expired_fields.push(key);
                if (!(key in copied.conditions)) {
                  copied.conditions[key] = { value: null, status: "unknown", source: "e16_expired_copy", copied_value: deepcopy(fieldValue(scenarioFields[key])), copied_from: get(previous, "observed_at") };
                }
              }
            }
          }
          trace.push({ event: "previous_visit_copied", copied_from: deepcopy(copied.copied_from), expired_fields: [...copied.expired_fields], vehicle_token: copied.vehicle_token });
          const current = get(pack, "current_confirm", []);
          if (!isList(current)) {
            issues.push("current_confirm:list_required");
          } else {
            for (const confirmation of current) {
              if (!isDict(confirmation)) {
                issues.push("current_confirm:object_required");
                continue;
              }
              const result = currentConfirm(copied, get(confirmation, "field"), get(confirmation, "value"), get(confirmation, "actor"), get(confirmation, "reason"), get(confirmation, "observed_at"));
              if (result.error) {
                issues.push(result.error);
              } else {
                copied = result.visit;
                approvals.push(result.approval);
              }
            }
          }
          scenario.visit = copied;
          if (!("fields" in scenario)) scenario.fields = {};
          const fields = scenario.fields;
          if (!isDict(fields)) {
            issues.push("scenario_input:fields_must_be_object");
          } else {
            for (const key of CONDITION_FIELDS) if (key in copied.conditions) fields[key] = deepcopy(copied.conditions[key]);
            for (const key of CONDITION_FIELDS) if (key in fields && !(key in copied.conditions)) fields[key] = { value: null, status: "unknown", source: "e16_expired_copy" };
          }
          for (const approval of approvals) {
            if (approval.field === "rotor_seizure_hours") {
              if (!("metadata" in scenario)) scenario.metadata = {};
              if (!("approved_condition_widths" in scenario.metadata)) scenario.metadata.approved_condition_widths = {};
              scenario.metadata.approved_condition_widths.rotor_seizure_hours = { actor: approval.actor, reason: approval.reason, old_value: approval.old_value, new_value: approval.new_value };
            }
          }
          if (isDict(fields)) {
            const stock = get(fields, "parts_wait_stock_checked", {});
            for (const operation of get(scenario, "operations", [])) {
              if (get(operation, "operation_id") === "parts_wait") {
                operation.stock_checked = isDict(stock) ? get(stock, "value") === true && get(stock, "status") === "confirmed" : false;
              }
            }
            const snow = get(fields, "snow_observation", {});
            if (isDict(snow) && get(snow, "status") === "confirmed" && get(snow, "value") === "absent") {
              for (const operation of get(scenario, "operations", [])) {
                if (get(operation, "operation_id") === "snow_melt") {
                  operation.elapsed_hours = 0.0;
                  operation.hours = 0.0;
                  operation.source = "e16_current_snow_absent";
                }
              }
            }
          }
          const statusOf = (key: string) => get(get(copied.conditions, key, {}), "status");
          let missingConfirmations: string[] = copied.expired_fields.filter((key: string) => statusOf(key) !== "confirmed");
          const relevance = get(copied.conditions, "rotor_relevance", {});
          if (isDict(relevance) && get(relevance, "status") === "confirmed" && get(relevance, "value") === "unrelated") {
            missingConfirmations = missingConfirmations.filter((key) => key !== "rotor_seizure_hours");
          }
          if (missingConfirmations.length) issues.push("current_confirm:required_for_expired_fields:" + [...missingConfirmations].sort().join(","));
          trace.push({
            event: "current_visit_confirmations_applied", count: approvals.length,
            remaining_expired_fields: copied.expired_fields.filter((key: string) => statusOf(key) !== "confirmed"),
          });
        } catch (exc) {
          if (exc instanceof PyValueError || exc instanceof PyTypeError) issues.push(exc.message);
          else throw exc;
        }
      } else if ("current_confirm" in pack) {
        issues.push("previous_visit:required_for_current_confirm");
      }
    }
  }
  if (!isStr(version) || !version.trim()) issues.push("rule_version:required");
  if (isDict(scenarioInput)) {
    if (!isDict(get(scenario, "fields", {}))) issues.push("scenario_input:fields_must_be_object");
    if (!isList(get(scenario, "operations", []))) issues.push("scenario_input:operations_must_be_list");
    else if (get(scenario, "operations", []).some((o: any) => !isDict(o))) issues.push("scenario_input:operations_must_contain_objects");
  }
  let labor: Dict;
  let status: string;
  if (issues.length) {
    labor = nullLabor(issues);
    status = "missing-required";
  } else {
    labor = deepcopy(referenceLabor(scenario)[0]);
    const blocking = get(labor, "unknowns", []).filter((i: string) => !i.endsWith(":elapsed_duration_unknown"));
    status = blocking.length ? "missing-required" : truthy(get(labor, "unknowns")) ? "partial" : "proposed";
    trace.push({ event: "labor_calculated", rule_version: version, operation_keys: get(labor, "breakdown", []).filter((r: Dict) => truthy(get(r, "operation_id"))).map((r: Dict) => get(r, "operation_id")) });
  }
  return {
    engine_id: ENGINE_ID, rule_version: version, status, labor, trace,
    operation_keys: get(labor, "breakdown", []).filter((r: Dict) => truthy(get(r, "operation_id"))).map((r: Dict) => get(r, "operation_id")),
    approvals, simulator_notice: SIMULATOR_NOTICE,
  };
}
