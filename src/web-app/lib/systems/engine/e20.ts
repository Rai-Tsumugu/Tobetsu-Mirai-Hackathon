/* eslint-disable @typescript-eslint/no-explicit-any */
// E20: isolated what-if calculation over a cloned scenario snapshot. 元: e20.py
import { type Dict, deepcopy, get, isDict, isList, isStr, pyEq, pyJsonDumps, sha256Hex, truthy } from "./py";
import { run as calculate } from "./e07";

export const ENGINE_ID = "e20_what_if";
export const RULE_VERSION = "e20-what-if-v1";

// 元の _hash は json.dumps(sort_keys=True, default=str)（既定の区切り・ensure_ascii）。
const hashOf = (value: any) => sha256Hex(pyJsonDumps(value, { sortKeys: true, defaultStr: true }));

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const original = deepcopy(scenarioInput);
  const hypothesis: Dict = deepcopy(isDict(rulePack) ? get(rulePack, "hypothesis", {}) : {});
  const sandbox = deepcopy(original);
  let changes: any = get(hypothesis, "operations", []);
  if (!isList(changes)) changes = null;
  const issues: string[] = rulePack !== null && !isDict(rulePack) ? ["rule_pack:object_required"] : [];
  if (changes === null) issues.push("hypothesis:operations_list_required");
  else if (changes.length && (!truthy(get(hypothesis, "actor")) || !truthy(get(hypothesis, "reason")))) issues.push("hypothesis:actor_and_reason_required");
  const applied: Dict[] = [];
  if (!issues.length) {
    for (const change of changes) {
      if (!isDict(change) || !isStr(get(change, "operation_id"))) {
        issues.push("hypothesis:operation_id_required");
        break;
      }
      const target = get(sandbox, "operations", []).find((row: Dict) => pyEq(get(row, "operation_id"), change.operation_id));
      if (target === undefined) {
        issues.push("hypothesis:unknown_operation:" + change.operation_id);
        break;
      }
      const before = deepcopy(target);
      for (const [key, value] of Object.entries(change)) if (key !== "operation_id") target[key] = deepcopy(value);
      applied.push({ operation_id: change.operation_id, old_value: before, new_value: deepcopy(target), actor: get(hypothesis, "actor"), reason: get(hypothesis, "reason") });
    }
  }
  if (issues.length) {
    const result = calculate(original);
    Object.assign(result, { engine_id: ENGINE_ID, rule_version: RULE_VERSION, hypothesis: { status: "rejected", issues, changes: [] } });
    return result;
  }
  const result = calculate(sandbox);
  Object.assign(result, {
    engine_id: ENGINE_ID, rule_version: RULE_VERSION,
    hypothesis: { status: "sandbox-proposed", parent_hash: hashOf(original), hypothesis_hash: hashOf(sandbox), changes: applied, approved: false, overwrote_original: false },
    trace: [{ event: "what_if_snapshot_cloned", parent_hash: hashOf(original) }, ...result.trace],
  });
  return result;
}
