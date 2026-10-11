/* eslint-disable @typescript-eslint/no-explicit-any */
// E25: deterministic replay of pinned scenario snapshots across rule versions. 元: e25.py
import { type Dict, deepcopy, get, isDict, isPyNum, isStr, pyEq, pyJsonDumps, pyRound, pySub, sha256Hex } from "./py";
import { BANDS } from "./contract";
import { run as calculate } from "./e02";

export const ENGINE_ID = "e25_version_replay";
const nullRange = () => ({ low: null, typical: null, high: null });

function stopped(version: any, unknown: string): Dict {
  return {
    engine_id: ENGINE_ID, rule_version: version, status: "missing-required",
    labor: { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: [unknown] },
    trace: [], operation_keys: [], approvals: [], simulator_notice: "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。", unknowns: [unknown],
  };
}

export function replay(scenarioInput: any, oldPack: any, newPack: any, opts: { actor: any; reason: any; diff_acknowledged: any }): Dict {
  const { actor, reason, diff_acknowledged: diffAcknowledged } = opts;
  if (!isDict(scenarioInput) || !isDict(oldPack) || !isDict(newPack)) return stopped("replay", "snapshot_and_two_rule_packs_required");
  if (!isStr(actor) || !actor.trim() || !isStr(reason) || !reason.trim() || diffAcknowledged !== true) {
    return stopped(get(scenarioInput, "rule_version", "replay"), "human_actor_reason_and_diff_ack_required");
  }
  if (pyEq(get(oldPack, "rule_version"), get(newPack, "rule_version"))) return stopped(get(scenarioInput, "rule_version", "replay"), "distinct_rule_versions_required");
  const pinned = deepcopy(scenarioInput);
  const outputs: Dict[] = [];
  for (const pack of [oldPack, newPack]) {
    const versioned = deepcopy(pinned);
    versioned.rule_version = get(pack, "rule_version");
    outputs.push(calculate(versioned, deepcopy(pack)));
  }
  const [a, b] = outputs;
  const delta = (key: string) =>
    Object.fromEntries(BANDS.map((k) => {
      const x = get(a.labor[key], k);
      const y = get(b.labor[key], k);
      return [k, isPyNum(x) && isPyNum(y) ? pyRound(pySub(y, x), 10) : null];
    }));
  const diff = {
    person_hours: delta("person_hours"), elapsed_hours: delta("elapsed_hours"),
    old_unknowns: deepcopy(get(a.labor, "unknowns", [])), new_unknowns: deepcopy(get(b.labor, "unknowns", [])),
    unknowns_changed: !pyEq(get(a.labor, "unknowns", []), get(b.labor, "unknowns", [])),
  };
  const snapshotHash = sha256Hex(pyJsonDumps(pinned, { sortKeys: true, defaultStr: true }));
  return {
    engine_id: ENGINE_ID, rule_version: b.rule_version, status: outputs.every((x) => x.status !== "missing-required") ? "replayed" : "partial",
    labor: deepcopy(b.labor), trace: [{ stage: "pinned_replay", snapshot_sha256: snapshotHash }], operation_keys: deepcopy(get(b, "operation_keys", [])), approvals: [],
    simulator_notice: get(b, "simulator_notice", "Fictional simulator data."), snapshot_sha256: snapshotHash,
    batches: outputs.map((output) => ({ rule_version: output.rule_version, engine_result: output })),
    diff, release_gate: { actor, reason, diff_acknowledged: diffAcknowledged }, unknowns: [],
  };
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  if (!isDict(rulePack) || !["old_pack", "new_pack", "actor", "reason", "diff_acknowledged"].every((k) => k in rulePack)) {
    const version = isDict(scenarioInput) ? get(scenarioInput, "rule_version", "replay") : "replay";
    return stopped(version, "old_new_packs_and_human_ack_required");
  }
  return replay(scenarioInput, rulePack.old_pack, rulePack.new_pack, { actor: rulePack.actor, reason: rulePack.reason, diff_acknowledged: rulePack.diff_acknowledged });
}
