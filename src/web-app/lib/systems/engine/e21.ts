/* eslint-disable @typescript-eslint/no-explicit-any */
// E21: evidence-gated additions to a scenario estimate. 元: e21.py
import { type Dict, dedupe, deepcopy, get, isDict, isList, isNumber, isStr, item as itemOf, pyAdd, pyEq, pyRound, pySum, truthy } from "./py";
import { BANDS } from "./contract";
import { run as calculate } from "./e07";

export const ENGINE_ID = "e21_evidence_additions";
export const RULE_VERSION = "e21-evidence-additions-v1";

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const result = calculate(deepcopy(scenarioInput));
  let additions: any = deepcopy(isDict(rulePack) ? get(rulePack, "additions", []) : []);
  const issues: string[] = rulePack !== null && !isDict(rulePack) ? ["rule_pack:object_required"] : [];
  if (!isList(additions)) {
    additions = [];
    issues.push("additions:list_required");
  }
  const accepted: Dict[] = [];
  additions.forEach((it: any, i: number) => {
    if (!isDict(it)) {
      issues.push(`addition[${i}]:object_required`);
      return;
    }
    const value = get(it, "hours");
    const audit = get(it, "approval");
    if (!isStr(get(it, "operation_id")) || !it.operation_id) issues.push(`addition[${i}]:operation_id_required`);
    if (get(it, "unit") !== "person_hour") issues.push(`addition[${i}]:person_hour_unit_required`);
    if (!isStr(get(it, "source")) || !it.source.trim()) issues.push(`addition[${i}]:source_required`);
    if (typeof value === "boolean" || !isNumber(value) || !Number.isFinite(value) || value < 0) issues.push(`addition[${i}]:finite_nonnegative_hours_required`);
    const prior = isDict(scenarioInput) ? get(scenarioInput, "operations", []).find((row: Dict) => pyEq(get(row, "operation_id"), get(it, "operation_id"))) ?? null : null;
    const observedOld = truthy(prior) ? get(prior, "hours") : null;
    const declaredOld = get(it, "old_value");
    const expectedNew = { hours: value, unit: get(it, "unit"), source: get(it, "source") };
    if ((prior !== null && !pyEq(declaredOld, observedOld)) || (prior === null && declaredOld !== null)) issues.push(`addition[${i}]:old_value_does_not_match_observation`);
    if (
      !isDict(audit) || !isStr(get(audit, "actor")) || !audit.actor.trim() || !isStr(get(audit, "reason")) || !audit.reason.trim() ||
      !pyEq(get(audit, "old_value"), declaredOld) || !pyEq(get(audit, "new_value"), expectedNew) || get(audit, "rule_version") !== RULE_VERSION
    ) issues.push(`addition[${i}]:effective_approval_required`);
    if (!issues.length) accepted.push(it);
  });
  Object.assign(result, { engine_id: ENGINE_ID, rule_version: RULE_VERSION, evidence_additions: { accepted, issues } });
  if (issues.length) {
    const nulls = () => ({ low: null, typical: null, high: null });
    result.status = "missing-required";
    result.labor.person_hours = nulls();
    result.labor.elapsed_hours = nulls();
    for (const row of get(result.labor, "breakdown", [])) {
      row.hours = nulls();
      if ("elapsed_hours" in row) row.elapsed_hours = nulls();
      row.status = "missing-required";
    }
    result.labor.unknowns = dedupe([...get(result.labor, "unknowns", []), ...issues]);
  } else if (accepted.length) {
    const added = pySum(accepted.map((a) => itemOf(a, "hours")));
    for (const key of BANDS) result.labor.person_hours[key] = pyRound(pyAdd(result.labor.person_hours[key], added), 10);
    for (const a of accepted) {
      result.labor.breakdown.push({
        operation: a.operation_id, operation_id: a.operation_id, hours: Object.fromEntries(BANDS.map((k) => [k, a.hours])),
        reason: a.approval.reason, status: "conditional", source: a.source, approval: a.approval,
      });
    }
    result.operation_keys = dedupe([...result.operation_keys, ...accepted.map((a) => a.operation_id)]);
  }
  return result;
}
