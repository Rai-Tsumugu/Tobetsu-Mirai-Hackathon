/* eslint-disable @typescript-eslint/no-explicit-any */
// E22: join scoped estimates to actual person-time observations. 元: e22.py
import { type Dict, codePointCompare, deepcopy, get, isDict, isInt, isList, isNumber, isStr, pyEq, pyRound, truthy } from "./py";
import { run as calculate } from "./e07";

export const ENGINE_ID = "e22_actual_join";
export const RULE_VERSION = "e22-actual-join-v1";

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const result = calculate(deepcopy(scenarioInput));
  const pack: Dict = isDict(rulePack) ? rulePack : {};
  let steps: any = deepcopy(get(pack, "actual_steps", []));
  const issues: string[] = [];
  const expectedScope = isDict(scenarioInput) ? get(scenarioInput, "job_id") : null;
  if (!pyEq(get(pack, "scope_id"), expectedScope)) issues.push("scope_id:estimate_actual_mismatch");
  if (!pyEq(get(pack, "rule_version"), get(result, "rule_version"))) issues.push("rule_version:estimate_actual_mismatch");
  if (!isList(steps)) {
    steps = [];
    issues.push("actual_steps:list_required");
  }
  let total = 0.0;
  const matched = new Set<string>();
  const actualRows: Dict[] = [];
  steps.forEach((step: any, i: number) => {
    if (!isDict(step)) {
      issues.push(`actual_steps[${i}]:object_required`);
      return;
    }
    if (get(step, "is_wait") === true || get(step, "unit") === "elapsed_hours") {
      actualRows.push({ index: i, excluded: "waiting_time" });
      return;
    }
    const count = get(step, "person_count");
    const duration = get(step, "duration_hours");
    if (get(step, "unit") !== "person_hour" || !isStr(get(step, "operation_id")) || !step.operation_id) {
      issues.push(`actual_steps[${i}]:operation_and_person_hour_required`);
      return;
    }
    if (typeof count === "boolean" || !isInt(count) || count <= 0 || typeof duration === "boolean" || !isNumber(duration) || !Number.isFinite(duration) || duration < 0) {
      issues.push(`actual_steps[${i}]:person_count_and_duration_required`);
      return;
    }
    const hours = count * duration;
    total += hours;
    matched.add(step.operation_id);
    actualRows.push({ operation_id: step.operation_id, person_count: count, duration_hours: duration, person_hours: hours });
  });
  const estimateKeys = new Set<any>();
  for (const row of get(result.labor, "breakdown", [])) if (truthy(get(row, "operation_id")) && get(row, "status") !== "wait") estimateKeys.add(row.operation_id);
  for (const operationId of [...matched].filter((m) => !estimateKeys.has(m)).sort(codePointCompare)) issues.push("actual_step:unknown_operation_id:" + operationId);
  const complete = !issues.length && [...estimateKeys].every((k) => matched.has(k));
  const estimate = get(result.labor.person_hours, "typical");
  Object.assign(result, {
    engine_id: ENGINE_ID, rule_version: RULE_VERSION,
    actual_comparison: {
      complete, incomplete: !complete, actual_person_hours: complete ? total : null,
      estimate_typical_person_hours: complete ? estimate : null,
      delta_actual_minus_estimate: complete && estimate !== null ? pyRound(total - estimate, 10) : null,
      issues, unknowns: [...issues], actual_steps: actualRows,
    },
  });
  return result;
}
