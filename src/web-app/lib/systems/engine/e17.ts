/* eslint-disable @typescript-eslint/no-explicit-any */
// E17: append-only observation events with a deterministic current-state reducer. 元: e17.py
import {
  type Dict, PyTypeError, PyValueError, dedupe, deepcopy, get, hashKey, isDict, isList, isNumber, isStr, isoDatetime, item, keysAre, keysOf, or, pyIter, setHas, truthy,
} from "./py";
import { BANDS, referenceLabor } from "./contract";

export const ENGINE_ID = "e17_observation_events";
export const RULE_VERSION = "e17-observation-events-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const FIELDS = ["rotor_relevance", "rotor_seizure_hours", "subframe_relevance", "parts_wait_stock_checked", "snow_observation"];
const nullRange = () => ({ low: null, typical: null, high: null });

function validDate(value: any): boolean {
  if (!isStr(value) || !value.trim()) return false;
  try {
    isoDatetime(value.replace(/Z/g, "+00:00"));
    return true;
  } catch (e) {
    if (e instanceof PyValueError) return false;
    throw e;
  }
}

function validValue(target: any, value: any): boolean {
  if (target === "rotor_relevance" || target === "subframe_relevance") return setHas(value, ["relevant", "unrelated"]);
  if (target === "parts_wait_stock_checked") return typeof value === "boolean";
  if (target === "snow_observation") return setHas(value, ["present", "absent"]);
  if (target === "rotor_seizure_hours") {
    if (!isDict(value) || !keysAre(value, [...BANDS])) return false;
    const values = BANDS.map((k) => value[k]);
    return values.every((n) => isNumber(n) && n >= 0) && values[0] <= values[1] && values[1] <= values[2];
  }
  return false;
}

/** Return a new event list with one validated, auditable observation. */
export function appendObservationEvent(
  events: any, target: any, value: any, actor: any, reason: any, observedAt: any, eventId: any,
  supersedes: any = null, status: any = "confirmed", source: any = "direct_observation",
): Dict[] {
  if (!isList(events) || events.some((e) => !isDict(e))) throw new PyValueError("events:list_of_objects_required");
  if (!setHas(target, FIELDS)) throw new PyValueError("event:unknown_target");
  if (!isStr(eventId) || !eventId.trim()) throw new PyValueError("event:id_required");
  if (events.some((e) => get(e, "id") === eventId)) throw new PyValueError("event:duplicate_id");
  if (supersedes !== null) {
    const prior = events.find((e) => get(e, "id") === supersedes);
    if (prior === undefined) throw new PyValueError("event:unknown_supersedes");
    if (get(prior, "target") !== target) throw new PyValueError("event:supersedes_target_mismatch");
  }
  if (!setHas(status, ["confirmed", "pending"])) throw new PyValueError("event:invalid_status");
  if (status === "confirmed") {
    if (!isStr(actor) || !actor.trim() || !isStr(reason) || !reason.trim()) throw new PyValueError("event:confirmed_actor_reason_required");
    if (!validDate(observedAt)) throw new PyValueError("event:confirmed_date_required");
    if (!isStr(source) || !source.trim()) throw new PyValueError("event:confirmed_source_required");
    if (!validValue(target, value)) throw new PyValueError("event:invalid_confirmed_value");
  }
  const event = {
    id: eventId.trim(), target, value: deepcopy(value), supersedes, actor: isStr(actor) ? actor.trim() : null,
    reason: isStr(reason) ? reason.trim() : null, observed_at: observedAt, source, status,
  };
  return [...deepcopy(events), event];
}

/** Validate event references and return the latest confirmed event per target. */
export function reduceObservations(events: any): Record<string, Dict> {
  if (!isList(events) || events.some((e) => !isDict(e))) throw new PyValueError("events:list_of_objects_required");
  const byId = new Map<string, Dict>();
  for (const event of events) {
    const eventId = get(event, "id");
    if (!isStr(eventId) || !eventId.trim() || byId.has(eventId)) throw new PyValueError("event:duplicate_or_missing_id");
    const target = get(event, "target");
    if (!setHas(target, FIELDS)) throw new PyValueError("event:unknown_target");
    if (!setHas(get(event, "status"), ["pending", "confirmed"])) throw new PyValueError("event:invalid_status");
    if (event.status === "confirmed") {
      if (
        !isStr(get(event, "actor")) || !event.actor.trim() || !isStr(get(event, "reason")) || !event.reason.trim() ||
        !isStr(get(event, "source")) || !event.source.trim() || !validDate(get(event, "observed_at"))
      ) throw new PyValueError("event:confirmed_audit_required");
      if (!validValue(target, get(event, "value"))) throw new PyValueError("event:invalid_confirmed_value");
    }
    byId.set(eventId, event);
  }
  const superseded = new Set<string>();
  for (const event of events) {
    const priorId = get(event, "supersedes");
    if (priorId === null) continue;
    hashKey(priorId); // list / dict は unhashable で TypeError
    const found = typeof priorId === "string" ? byId.get(priorId) : undefined;
    if (found === undefined) throw new PyValueError("event:unknown_supersedes");
    if (get(found, "target") !== get(event, "target")) throw new PyValueError("event:supersedes_target_mismatch");
    if (superseded.has(priorId)) throw new PyValueError("event:sequence_ambiguity");
    superseded.add(priorId);
  }
  for (const eventId of byId.keys()) {
    const seen = new Set<string>();
    let cursor: any = eventId;
    while (byId.has(cursor) && get(byId.get(cursor)!, "supersedes") !== null) {
      if (seen.has(cursor)) throw new PyValueError("event:revision_cycle");
      seen.add(cursor);
      cursor = byId.get(cursor)!.supersedes;
    }
  }
  const latest: Record<string, Dict> = {};
  for (const event of events) {
    if (!setHas(get(event, "status"), ["pending", "confirmed"])) throw new PyValueError("event:invalid_status");
    if (superseded.has(item(event, "id")) || get(event, "status") !== "confirmed") continue;
    if (!validValue(item(event, "target"), get(event, "value"))) throw new PyValueError("event:invalid_confirmed_value");
    if (Object.prototype.hasOwnProperty.call(latest, event.target)) throw new PyValueError("event:sequence_ambiguity");
    latest[event.target] = deepcopy(event);
  }
  return latest;
}

function nullLabor(unknowns: string[]): Dict {
  return { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(unknowns) };
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const pack: Dict | null = isDict(rulePack) ? deepcopy(rulePack) : null;
  let version: any = or(get(scenario, "rule_version"), RULE_VERSION);
  const events: any = pack !== null ? get(pack, "events") : [];
  const issues: string[] = [];
  if (!isDict(scenarioInput)) issues.push("scenario_input:object_required");
  if (rulePack !== null && pack === null) issues.push("rule_pack:object_required");
  if (pack !== null) {
    if (keysOf(pack).some((k) => !["engine_id", "rule_version", "events"].includes(k))) issues.push("rule_pack:unknown_key");
    if (![null, ENGINE_ID, "e17"].includes(get(pack, "engine_id"))) issues.push("rule_pack:engine_id_mismatch");
    if (truthy(get(pack, "rule_version")) && truthy(get(scenario, "rule_version")) && pack.rule_version !== scenario.rule_version) issues.push("rule_pack:pinned_version_mismatch");
    version = or(get(pack, "rule_version"), version);
  }
  let reduced: Record<string, Dict>;
  try {
    reduced = reduceObservations(events);
  } catch (exc) {
    if (exc instanceof PyValueError || exc instanceof PyTypeError) {
      reduced = {};
      issues.push(exc.message);
    } else {
      throw exc;
    }
  }
  if (!("fields" in scenario)) scenario.fields = {};
  let fields = scenario.fields;
  if (!isDict(fields)) {
    issues.push("scenario_input:fields_must_be_object");
    fields = {};
  }
  for (const target of FIELDS) {
    const event = reduced[target];
    if (event !== undefined) fields[target] = { value: deepcopy(event.value), status: "confirmed", source: event.source, confirmed_at: event.observed_at };
  }
  for (const operation of pyIter(get(scenario, "operations", []))) {
    if (get(operation, "operation_id") === "parts_wait") {
      const stock = get(fields, "parts_wait_stock_checked", {});
      operation.stock_checked = isDict(stock) && get(stock, "value") === true && get(stock, "status") === "confirmed";
    }
    if (get(operation, "operation_id") === "snow_melt") {
      const snow = get(fields, "snow_observation", {});
      if (isDict(snow) && get(snow, "status") === "confirmed" && get(snow, "value") === "absent") {
        operation.hours = 0.0;
        operation.elapsed_hours = 0.0;
        operation.source = "e17_confirmed_snow_absent";
      }
    }
  }
  const approvals: Dict[] = Object.values(reduced).map((event) => ({
    type: "observation_event", id: event.id, target: event.target, actor: event.actor, reason: event.reason, old_value: null,
    new_value: deepcopy(event.value), observed_at: event.observed_at, source: event.source,
  }));
  const byId = new Map<any, Dict>();
  if (isList(events)) for (const e of events) if (isDict(e)) byId.set(get(e, "id"), e);
  for (const approval of approvals) {
    const current = byId.get(approval.id) ?? {};
    const priorKey = get(current, "supersedes");
    const prior = typeof priorKey === "string" || priorKey === null ? byId.get(priorKey) : undefined;
    if (truthy(prior)) approval.old_value = deepcopy(get(prior, "value"));
  }
  let labor: Dict;
  let status: string;
  if (issues.length) {
    labor = nullLabor(issues);
    status = "missing-required";
  } else {
    labor = referenceLabor(scenario)[0];
    const blocking = get(labor, "unknowns", []).filter((i: string) => !i.endsWith(":elapsed_duration_unknown"));
    status = blocking.length ? "missing-required" : truthy(get(labor, "unknowns")) ? "partial" : "proposed";
    if (blocking.length) {
      for (const key of ["person_hours", "elapsed_hours"]) labor[key] = nullRange();
      for (const row of get(labor, "breakdown", [])) {
        row.hours = nullRange();
        row.status = "missing-required";
      }
    }
  }
  return {
    engine_id: ENGINE_ID, rule_version: version, status, labor,
    trace: [{ event: "observation_events_reduced", event_ids: pyIter(events).map((e: any) => get(e, "id")), confirmed_targets: Object.keys(reduced).sort() }],
    operation_keys: get(labor, "breakdown", []).filter((r: Dict) => truthy(get(r, "operation_id"))).map((r: Dict) => get(r, "operation_id")),
    approvals, simulator_notice: SIMULATOR_NOTICE,
  };
}
