/* eslint-disable @typescript-eslint/no-explicit-any */
// E26: append-only actual revisions and rebuildable active views. 元: e26.py
import {
  type Dict, PyKeyError, PyTypeError, PyValueError, deepcopy, get, hashKey, isDict, isInt, isList, isNumber, isStr, item, or, pyFloat, pySum, truthy,
} from "./py";

export const ENGINE_ID = "e26_actual_revision";
const NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";

export function activeView(actuals: any, revisionsIn: any = null): Dict {
  const revisions: any = or(revisionsIn, []);
  if (!isList(actuals) || !isList(revisions)) throw new PyValueError("actuals and revisions must be lists");
  const base = new Map<string, Dict>();
  for (const it of actuals) {
    if (!isDict(it) || !isStr(get(it, "event_id")) || base.has(it.event_id)) throw new PyValueError("actual event IDs must be valid and unique");
    if (!isStr(get(it, "operation_id")) || typeof get(it, "hours") === "boolean" || !isNumber(get(it, "hours")) || !Number.isFinite(it.hours) || it.hours < 0) {
      throw new PyValueError("actual operation_id and nonnegative hours are required");
    }
    const count = get(it, "person_count", 1);
    if (typeof count === "boolean" || !isInt(count) || count <= 0) throw new PyValueError("actual person_count must be a positive integer");
    base.set(it.event_id, deepcopy(it));
  }
  const byId = new Map<string, Dict>();
  const children = new Map<string, string[]>();
  for (const revision of revisions) {
    const rid = get(revision, "revision_id");
    const parent = get(revision, "parent_id");
    if (!isStr(rid) || !rid || byId.has(rid) || base.has(rid)) throw new PyValueError("revision IDs must be valid and unique");
    const pk = hashKey(parent); // unhashable は TypeError
    if (!(typeof parent === "string" && (base.has(parent) || byId.has(parent)))) {
      void pk;
      throw new PyValueError("revision parent reference is missing");
    }
    if (!["reason", "actor", "rule_version"].every((k) => isStr(get(revision, k)) && revision[k].trim())) throw new PyValueError("revision reason, actor, and rule_version are required");
    const delta = get(revision, "delta_hours");
    if (typeof delta === "boolean" || !isNumber(delta) || !Number.isFinite(delta)) throw new PyValueError("delta_hours must be numeric");
    byId.set(rid, deepcopy(revision));
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent)!.push(rid);
  }
  if ([...children.values()].some((kids) => kids.length > 1)) throw new PyValueError("revision forks are invalid");
  for (const [rid, revision] of byId) {
    const seen = new Set<string>([rid]);
    let parent: string = revision.parent_id;
    while (byId.has(parent)) {
      if (seen.has(parent)) throw new PyValueError("revision cycle detected");
      seen.add(parent);
      parent = byId.get(parent)!.parent_id;
    }
  }
  const heads: string[] = [...base.keys()].filter((k) => !children.has(k));
  heads.push(...[...byId.keys()].filter((k) => !children.has(k)));
  const view: Dict[] = [];
  for (const head of heads) {
    let revisionId = head;
    if (byId.has(head)) {
      const chain: Dict[] = [];
      while (byId.has(revisionId)) {
        chain.push(byId.get(revisionId)!);
        revisionId = byId.get(revisionId)!.parent_id;
      }
      const original = base.get(revisionId)!;
      const active = chain[0];
      const hours = original.hours + pySum(chain.map((r) => r.delta_hours));
      if (hours < 0) throw new PyValueError("revision produces negative active hours");
      view.push({ ...deepcopy(original), hours, active_revision_id: active.revision_id, revision_rule_version: active.rule_version });
    } else {
      view.push(deepcopy(base.get(head)!));
    }
  }
  const totals: Dict = {};
  for (const it of view) {
    const key = it.operation_id;
    totals[key] = (Object.prototype.hasOwnProperty.call(totals, key) ? totals[key] : 0.0) + pyFloat(it.hours);
  }
  return { engine_id: ENGINE_ID, status: "proposed", active_view: view, bucket_hours: totals, revision_log: deepcopy(revisions) };
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  void rulePack;
  if (!isDict(scenarioInput) || !isList(get(scenarioInput, "actuals"))) {
    const nul = { low: null, typical: null, high: null };
    return {
      engine_id: ENGINE_ID, rule_version: get(or(scenarioInput, {}), "rule_version", "e26-1"), status: "missing-required",
      labor: { person_hours: nul, elapsed_hours: { ...nul }, breakdown: [], unknowns: ["actuals:list_required"] },
      trace: [], operation_keys: [], approvals: [], simulator_notice: NOTICE,
    };
  }
  const version = get(scenarioInput, "rule_version", "e26-1");
  let result: Dict;
  try {
    result = activeView(scenarioInput.actuals, get(scenarioInput, "revisions", []));
  } catch (exc) {
    if (exc instanceof PyValueError || exc instanceof PyTypeError || exc instanceof PyKeyError) {
      const nul = { low: null, typical: null, high: null };
      const text = exc instanceof PyKeyError ? `'${exc.message.replace(/^"|"$/g, "")}'` : exc.message;
      return {
        engine_id: ENGINE_ID, rule_version: version, status: "missing-required",
        labor: { person_hours: nul, elapsed_hours: { ...nul }, breakdown: [], unknowns: [`revision:${text}`] },
        trace: [], operation_keys: [], approvals: [], simulator_notice: NOTICE,
      };
    }
    throw exc;
  }
  const total = get(result.bucket_hours, "total", 0);
  return {
    engine_id: ENGINE_ID, rule_version: version, status: result.status,
    labor: {
      person_hours: { low: total, typical: total, high: total },
      elapsed_hours: { low: 0.0, typical: 0.0, high: 0.0 },
      breakdown: result.active_view.map((row: Dict) => ({
        operation_id: row.operation_id, operation: row.operation_id, hours: { low: row.hours, typical: row.hours, high: row.hours },
        reason: "append-only actual active view", status: "proposed",
      })),
      unknowns: [],
    },
    trace: [{ event: "active_view_rebuilt", revision_count: result.revision_log.length }],
    operation_keys: Object.keys(result.bucket_hours), approvals: [], simulator_notice: NOTICE,
    active_view: result.active_view, bucket_hours: result.bucket_hours, revision_log: result.revision_log,
  };
}

void item;
void truthy;
