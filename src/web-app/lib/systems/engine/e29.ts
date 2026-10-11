/* eslint-disable @typescript-eslint/no-explicit-any */
// E29: immutable offline snapshot queue with explicit conflict resolution. 元: e29.py
import { type Dict, PyValueError, deepcopy, get, isDict, isList, isStr, pyEq, pyJsonDumps, sha256Hex, truthy } from "./py";
import * as e07 from "./e07";

export const ENGINE_ID = "e29_offline_snapshot";
export const RULE_VERSION = "e29-offline-snapshot-v1";

const inputHash = (scenarioInput: any): string => sha256Hex(pyJsonDumps(scenarioInput, { sortKeys: true, ensureAscii: false, defaultStr: true }));

/** Append an immutable version-pinned snapshot; identical IDs are idempotent. */
export function queueSnapshot(queue: any, snapshotId: any, scenarioInput: any, ruleVersion: any): Dict[] {
  if (!isList(queue) || !isStr(snapshotId) || !snapshotId.trim()) throw new PyValueError("snapshot:id_and_queue_required");
  if (!isDict(scenarioInput) || !isStr(ruleVersion) || !ruleVersion.trim()) throw new PyValueError("snapshot:scenario_and_rule_version_required");
  const body = deepcopy(scenarioInput);
  const digest = inputHash(body);
  const existing = queue.find((it) => pyEq(get(it, "snapshot_id"), snapshotId));
  if (truthy(existing)) {
    if (!pyEq(get(existing, "input_sha256"), digest) || !pyEq(get(existing, "rule_version"), ruleVersion)) throw new PyValueError("snapshot:idempotency_conflict");
    return deepcopy(queue);
  }
  return [...deepcopy(queue), { snapshot_id: snapshotId, scenario_input: body, rule_version: ruleVersion, input_sha256: digest, status: "pending" }];
}

/** Version conflict remains pending until a person explicitly resolves it. */
export function syncSnapshot(snapshot: any, serverRuleVersion: any, opts: { resolution?: any; actor?: any; reason?: any } = {}): Dict {
  const { resolution = null, actor = null, reason = null } = opts;
  if (!isDict(snapshot)) throw new PyValueError("snapshot:object_required");
  const result = deepcopy(snapshot);
  const body = get(result, "scenario_input");
  if (!isDict(body) || !pyEq(get(result, "input_sha256"), inputHash(body))) {
    result.status = "snapshot_integrity_error";
    return result;
  }
  if (pyEq(get(result, "rule_version"), serverRuleVersion)) {
    result.status = "ready_to_recompute";
    return result;
  }
  if (resolution === null) {
    result.status = "version_conflict";
    result.server_rule_version = serverRuleVersion;
    return result;
  }
  if (resolution !== "keep_snapshot" && resolution !== "rebase_to_server") throw new PyValueError("resolution:unsupported");
  if (!isStr(actor) || !actor.trim() || !isStr(reason) || !reason.trim()) throw new PyValueError("resolution:actor_and_reason_required");
  result.status = resolution === "rebase_to_server" ? "ready_to_recompute" : "ready_with_pinned_version";
  result.resolution = { choice: resolution, actor: actor.trim(), reason: reason.trim(), old_version: result.rule_version, new_version: serverRuleVersion };
  if (resolution === "rebase_to_server") {
    result.rule_version = serverRuleVersion;
    if ("rule_version" in result.scenario_input) result.scenario_input.rule_version = serverRuleVersion;
    result.input_sha256 = inputHash(result.scenario_input);
  }
  return result;
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  void rulePack;
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const result = e07.run(scenario);
  result.engine_id = ENGINE_ID;
  result.trace.unshift({ stage: "offline_snapshot", rule_version_pinned: result.rule_version, sync_requires_explicit_conflict_resolution: true });
  return result;
}
