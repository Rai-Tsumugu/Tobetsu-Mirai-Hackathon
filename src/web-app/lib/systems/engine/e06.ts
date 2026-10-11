/* eslint-disable @typescript-eslint/no-explicit-any */
// E06: immutable, approval-audited JSON rule pack lifecycle. 元: e06.py
import {
  type Dict, PyTypeError, PyValueError, deepcopy, get, hashKey, isDict, isList, isStr, isoDate, keysOf, or, pyEq, pyJsonDumps, pySorted, sha256Hex, truthy,
} from "./py";
import * as e02 from "./e02";

export const ENGINE_ID = "e06_approval_rules";
const PUBLISHED = new Map<string, Dict>();

/** テスト用: 公開済みスナップショットの登録を空にする。 */
export function resetPublished(): void {
  PUBLISHED.clear();
}

/** _PUBLISHED.get(version)（unhashable なら TypeError）。 */
function published(version: any): Dict | undefined {
  return PUBLISHED.get(hashKey(version));
}

const canonical = (value: any): string => pyJsonDumps(value, { sortKeys: true, ensureAscii: false, compact: true, allowNan: false });

export function payloadHash(pack: Dict): string {
  const payload = deepcopy(pack);
  delete payload.payload_hash;
  return sha256Hex(canonical(payload));
}

export function defaultPack(scenario: Dict): Dict {
  const rule = (operationKey: string, condition: Dict, hours: number[], unit: string, source: string) => ({
    job_id: "front_brake_service", operation_key: operationKey, condition,
    hours: { low: hours[0], typical: hours[1], high: hours[2] }, unit, source,
  });
  const base: Dict = {
    engine_id: ENGINE_ID, rule_version: get(scenario, "rule_version", "fictional-rule-v1"),
    status: "approved", approver: "fictional_shop_owner",
    approval_reason: "fictional fixture approval", effective_from: "2026-10-11",
    source: "fictional_fixture", basis_unit: get(scenario, "basis_unit"),
    basis_definition: get(scenario, "basis_definition"),
    rules: [
      rule("base_service", { field: "work_scope", equals: "front_brake_service" }, [1.7, 1.7, 1.7], "person_hours", "fictional_fixture:base"),
      rule("replacement_carry", { field: "included_operations", contains: "remove_install" }, [0.2, 0.2, 0.2], "person_hours", "fictional_fixture:carry"),
      rule("snow_melt", { field: "included_operations", contains: "snow_removal" }, [0.5, 0.5, 0.5], "elapsed_hours", "fictional_fixture:snow"),
      rule("penetrant_wait", { field: "work_scope", equals: "front_brake_service" }, [0.25, 0.25, 0.25], "elapsed_hours", "fictional_fixture:penetrant"),
      rule("parts_wait", { field: "parts_wait_stock_checked", equals: true }, [0.0, 0.0, 0.0], "elapsed_hours", "fictional_fixture:parts"),
      rule("wash", { field: "work_scope", equals: "front_brake_service" }, [0.1, 0.1, 0.1], "person_hours", "fictional_fixture:wash"),
      rule("rotor_seizure", { field: "rotor_relevance", equals: "relevant" }, [0.0, 0.25, 0.5], "person_hours", "fictional_fixture:rotor"),
    ],
  };
  base.approval_audit = base.rules.map((r: Dict) => ({
    actor: base.approver, reason: base.approval_reason, operation_key: r.operation_key, old_value: null, new_value: deepcopy(r),
  }));
  base.payload_hash = payloadHash(base);
  return base;
}

const PACK_ATTR_EXCLUDED = new Set(["engine_id", "rule_version", "status", "approver", "approval_reason", "approval_audit", "payload_hash", "rules"]);

function indexRules(rules: any[]): Map<string, [any, Dict]> {
  const out = new Map<string, [any, Dict]>();
  for (const r of rules) if (isDict(r)) out.set(hashKey(get(r, "operation_key")), [get(r, "operation_key"), r]);
  return out;
}

export function publishRulePack(payload: any, actor: any, reason: any, effectiveFrom: any, previous: Dict | null = null): Dict {
  if (!isStr(actor) || !actor.trim()) throw new PyValueError("approval:actor_required");
  if (!isStr(reason) || !reason.trim()) throw new PyValueError("approval:reason_required");
  try {
    isoDate(effectiveFrom);
  } catch (e) {
    if (e instanceof PyTypeError || e instanceof PyValueError) throw new PyValueError("approval:effective_from_invalid");
    throw e;
  }
  if (!isDict(payload)) throw new PyValueError("publish:payload_required");
  const pack = deepcopy(payload);
  delete pack.payload_hash;
  const version = get(pack, "rule_version");
  if (!isStr(version) || !version.trim()) throw new PyValueError("publish:rule_version_required");
  if (!isList(get(pack, "rules")) || !pack.rules.length) throw new PyValueError("publish:nonempty_rules_required");
  const oldRules = indexRules(truthy(previous) ? get(previous, "rules", []) : []);
  const newRules = indexRules(get(pack, "rules", []));
  const audit: Dict[] = [];
  const allKeys = new Map<string, any>();
  for (const [k, [orig]] of [...oldRules, ...newRules]) allKeys.set(k, orig);
  const sortedKeys = pySorted([...allKeys.values()]);
  for (const key of sortedKeys) {
    const hk = hashKey(key);
    const prior = oldRules.get(hk)?.[1];
    const rule = newRules.get(hk)?.[1];
    const oldValue = truthy(prior) ? deepcopy(prior) : null;
    const newValue = truthy(rule) ? deepcopy(rule) : null;
    if (!pyEq(oldValue, newValue)) {
      audit.push({ actor: actor.trim(), reason: reason.trim(), operation_key: key, scope: "rule", old_value: oldValue, new_value: newValue });
    }
  }
  const oldAttrs: Dict = {};
  if (truthy(previous)) for (const k of keysOf(previous!)) if (!PACK_ATTR_EXCLUDED.has(k)) oldAttrs[k] = previous![k];
  const newAttrs: Dict = {};
  for (const k of keysOf(pack)) if (!PACK_ATTR_EXCLUDED.has(k)) newAttrs[k] = pack[k];
  newAttrs.effective_from = effectiveFrom;
  const attrKeys = [...new Set([...keysOf(oldAttrs), ...keysOf(newAttrs)])];
  for (const key of pySorted(attrKeys)) {
    const prior = get(oldAttrs, key);
    const neu = get(newAttrs, key);
    if (!pyEq(prior, neu)) {
      audit.push({ actor: actor.trim(), reason: reason.trim(), operation_key: "@pack:" + key, scope: "pack", old_value: deepcopy(prior), new_value: deepcopy(neu) });
    }
  }
  Object.assign(pack, { engine_id: ENGINE_ID, status: "approved", approver: actor.trim(), approval_reason: reason.trim(), effective_from: effectiveFrom, approval_audit: audit });
  pack.payload_hash = payloadHash(pack);
  const prior = published(version);
  if (prior !== undefined) {
    if (prior.payload_hash !== pack.payload_hash) throw new PyValueError("publish:published_version_is_immutable");
    return deepcopy(prior);
  }
  PUBLISHED.set(hashKey(version), deepcopy(pack));
  return deepcopy(pack);
}

function invalidPack(pack: any, scenario: Dict, reason: string): Dict {
  const result = e02.run(scenario, null);
  result.engine_id = ENGINE_ID;
  result.trace.unshift({ event: "approval_pack_rejected", reason });
  if (isDict(pack) && truthy(get(pack, "rule_version"))) result.rule_version = or(get(scenario, "rule_version"), pack.rule_version);
  return result;
}

export function run(scenarioInput: Dict, rulePack: any = null): Dict {
  const scenario = deepcopy(scenarioInput);
  const pack: any = rulePack === null ? defaultPack(scenario) : deepcopy(rulePack);
  if (!isDict(pack)) return invalidPack(null, scenario, "rule_pack_required");
  if (rulePack === null) {
    const version = get(pack, "rule_version");
    const seeded = published(version);
    if (seeded === undefined) PUBLISHED.set(hashKey(version), deepcopy(pack));
    else if (canonical(seeded) !== canonical(pack)) return invalidPack(pack, scenario, "published_snapshot_mismatch");
  }
  if (get(pack, "status") !== "approved") return invalidPack(pack, scenario, "approved_status_required");
  let actualHash: string;
  try {
    actualHash = payloadHash(pack);
  } catch (e) {
    if (e instanceof PyTypeError || e instanceof PyValueError) return invalidPack(pack, scenario, "payload_not_canonical_json");
    throw e;
  }
  if (!truthy(get(pack, "payload_hash")) || !pyEq(actualHash, get(pack, "payload_hash"))) return invalidPack(pack, scenario, "payload_tampered_or_hash_missing");
  const registered = published(get(pack, "rule_version"));
  if (registered === undefined || canonical(registered) !== canonical(pack)) return invalidPack(pack, scenario, "published_snapshot_unregistered_or_mismatch");
  if (!isList(get(pack, "rules")) || !pack.rules.length) return invalidPack(pack, scenario, "rules_nonempty_list_required");
  const rules = new Map<string, Dict>();
  for (const r of pack.rules) if (isDict(r)) rules.set(hashKey(get(r, "operation_key")), r);
  if (rules.size !== pack.rules.length) return invalidPack(pack, scenario, "rule_rows_invalid_or_duplicate");
  const auditRows = get(pack, "approval_audit");
  if (!isList(auditRows)) return invalidPack(pack, scenario, "approval_audit_invalid");
  const seenAudit = new Set<string>();
  for (const row of auditRows) {
    if (!isDict(row) || !isStr(get(row, "actor")) || !row.actor.trim() || !isStr(get(row, "reason")) || !row.reason.trim() || !isStr(get(row, "operation_key")) || seenAudit.has(row.operation_key)) {
      return invalidPack(pack, scenario, "approval_audit_invalid");
    }
    const scope = get(row, "scope", "rule");
    const key: string = row.operation_key;
    if (scope === "rule") {
      if (!pyEq(get(row, "new_value"), rules.get(hashKey(key)) ?? null)) return invalidPack(pack, scenario, "approval_audit_invalid");
    } else if (scope === "pack" && key.startsWith("@pack:")) {
      const attr = key.slice("@pack:".length);
      if (!attr || !pyEq(get(row, "new_value"), get(pack, attr))) return invalidPack(pack, scenario, "approval_audit_invalid");
    } else {
      return invalidPack(pack, scenario, "approval_audit_invalid");
    }
    seenAudit.add(row.operation_key);
  }
  let effective: number;
  try {
    effective = isoDate(get(pack, "effective_from", ""));
  } catch (e) {
    if (e instanceof PyTypeError || e instanceof PyValueError) return invalidPack(pack, scenario, "effective_from_invalid");
    throw e;
  }
  let current: number;
  try {
    current = isoDate(get(scenario, "as_of", "2026-10-11"));
  } catch (e) {
    if (e instanceof PyTypeError || e instanceof PyValueError) return invalidPack(pack, scenario, "scenario_as_of_invalid");
    throw e;
  }
  if (effective > current) return invalidPack(pack, scenario, "not_yet_effective");
  const pinned = get(scenario, "rule_version");
  if (truthy(pinned) && !pyEq(pinned, get(pack, "rule_version"))) return invalidPack(pack, scenario, "pinned_version_mismatch");
  if (get(pack, "engine_id") !== ENGINE_ID) return invalidPack(pack, scenario, "engine_id_mismatch");
  const adapted = deepcopy(pack);
  adapted.engine_id = e02.ENGINE_ID;
  delete adapted.payload_hash;
  delete adapted.approval_reason;
  delete adapted.approval_audit;
  const underlying = e02.run(scenario, adapted);
  underlying.engine_id = ENGINE_ID;
  underlying.trace.unshift({ event: "approval_pack_verified", rule_version: pack.rule_version, payload_hash: pack.payload_hash, effective_from: pack.effective_from });
  underlying.approvals.unshift({
    type: "json_pack_publish", actor: get(pack, "approver"), reason: get(pack, "approval_reason"), rule_version: pack.rule_version,
    effective_from: pack.effective_from, payload_hash: pack.payload_hash, changes: deepcopy(get(pack, "approval_audit", [])),
  });
  return underlying;
}

