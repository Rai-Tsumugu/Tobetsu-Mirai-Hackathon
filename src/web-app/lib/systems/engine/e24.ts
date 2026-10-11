/* eslint-disable @typescript-eslint/no-explicit-any */
// E24: draft and human-approved immutable rule-pack updates. 元: e24.py
import { type Dict, PyValueError, PyTypeError, deepcopy, get, isDict, isList, isNumber, isStr, isoDate, item, keysAre, pyEq, pyJsonDumps, sha256Hex } from "./py";
import { BANDS } from "./contract";
import { run as pipeline } from "./e07";

export const ENGINE_ID = "e24_approval_version_update";

// 元の hashlib.sha256(json.dumps(x, sort_keys=True, default=str)) と同じ構造（既定の区切り・ensure_ascii）
const hashOf = (value: any) => sha256Hex(pyJsonDumps(value, { sortKeys: true, defaultStr: true }));

function finiteRange(value: any): boolean {
  return (
    isDict(value) && keysAre(value, [...BANDS]) &&
    BANDS.every((k) => typeof value[k] !== "boolean" && isNumber(value[k]) && Number.isFinite(value[k]) && value[k] >= 0) &&
    value.low <= value.typical && value.typical <= value.high
  );
}

/** Keep estimate envelope available while proposals remain outside applied rules. */
export function run(scenarioInput: any, rulePack: any = null): Dict {
  void rulePack;
  const result = pipeline(scenarioInput);
  result.engine_id = ENGINE_ID;
  result.trace.push({
    stage: "approval_version_update", status: "proposal_only", applied_rule_version: result.rule_version,
    note: "Call propose/approve to create a new immutable approved rule version.",
  });
  return result;
}

export function proposalHash(proposal: Dict): string {
  return hashOf(Object.fromEntries(Object.entries(proposal).filter(([k]) => k !== "proposal_sha256")));
}

/** Create a reviewable diff; proposals never alter or apply the old pack. */
export function propose(oldPack: any, operationKey: any, newHours: any, samples: any, reason: any): Dict {
  if (!isDict(oldPack) || !isList(samples) || !samples.length) throw new PyValueError("old pack and nonempty evidence samples are required");
  if (!isStr(reason) || !reason.trim()) throw new PyValueError("proposal reason is required");
  const before = get(oldPack, "rules", []).find((r: Dict) => get(r, "operation_key") === operationKey);
  if (before === undefined) throw new PyValueError("operation_key not found in old rule pack");
  if (!finiteRange(newHours)) throw new PyValueError("new_hours range is invalid");
  if (!finiteRange(get(before, "hours"))) throw new PyValueError("baseline pack range is invalid");
  const proposal: Dict = {
    engine_id: ENGINE_ID, status: "draft", old_rule_version: get(oldPack, "rule_version"), old_pack: deepcopy(oldPack), operation_key: operationKey,
    old_value: deepcopy(before.hours), new_value: deepcopy(newHours), samples: deepcopy(samples), reason: reason.trim(), old_pack_sha256: hashOf(oldPack),
  };
  proposal.proposal_sha256 = proposalHash(proposal);
  return proposal;
}

export function approve(proposal: any, actor: any, reason: any, newRuleVersion: any, effectiveFrom: any): Dict {
  if (get(proposal, "status") !== "draft" || get(proposal, "engine_id") !== ENGINE_ID) throw new PyValueError("a draft E24 proposal is required");
  if (!pyEq(get(proposal, "proposal_sha256"), proposalHash(proposal))) throw new PyValueError("proposal content or evidence was modified");
  if (![actor, reason, newRuleVersion, effectiveFrom].every((v) => isStr(v) && v.trim())) throw new PyValueError("actor, approval reason, new version, and effective date are required");
  if (newRuleVersion === get(proposal, "old_rule_version")) throw new PyValueError("approved changes require a new immutable rule_version");
  try {
    isoDate(effectiveFrom);
  } catch (e) {
    if (e instanceof PyValueError || e instanceof PyTypeError) throw new PyValueError("effective_from must be an ISO date");
    throw e;
  }
  const pack = deepcopy(item(proposal, "old_pack"));
  if (hashOf(pack) !== item(proposal, "old_pack_sha256")) throw new PyValueError("old pack snapshot hash mismatch");
  const matches = get(pack, "rules", []).filter((r: Dict) => get(r, "operation_key") === item(proposal, "operation_key"));
  if (matches.length !== 1 || !pyEq(get(matches[0], "hours"), item(proposal, "old_value"))) throw new PyValueError("proposal diff no longer matches the pinned old pack");
  matches[0].hours = deepcopy(proposal.new_value);
  Object.assign(pack, { rule_version: newRuleVersion, status: "approved", approved_by: actor, approval_reason: reason, effective_from: effectiveFrom });
  return {
    engine_id: ENGINE_ID, rule_version: newRuleVersion, status: "approved", rule_pack: pack,
    approval: {
      actor, reason, old_rule_version: proposal.old_rule_version, new_rule_version: newRuleVersion, operation_key: proposal.operation_key,
      old_value: deepcopy(proposal.old_value), new_value: deepcopy(proposal.new_value), samples: deepcopy(proposal.samples), effective_from: effectiveFrom,
    },
  };
}
