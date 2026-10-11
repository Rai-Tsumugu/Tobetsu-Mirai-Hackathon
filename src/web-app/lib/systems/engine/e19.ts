/* eslint-disable @typescript-eslint/no-explicit-any */
// E19: side-by-side observation comparison without symmetry inference. 元: e19.py
import { type Dict, PyTypeError, codePointCompare, deepcopy, get, isDict, isList, isPyNum, isStr, pyRound, pySub } from "./py";
import { run as calculate } from "./e07";

export const ENGINE_ID = "e19_side_panels";
export const RULE_VERSION = "e19-side-panels-v1";

export function groupBySide(operations: any[]): { left: Dict[]; right: Dict[] } {
  const panels = { left: [] as Dict[], right: [] as Dict[] };
  for (const row of operations) {
    const side = get(row, "side");
    if (isList(side) || isDict(side)) throw new PyTypeError(`unhashable type: '${isList(side) ? "list" : "dict"}'`);
    if (side === "left" || side === "right") (panels as Record<string, Dict[]>)[side].push(deepcopy(row));
  }
  return panels;
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const snapshot = deepcopy(scenarioInput);
  const rows = isDict(snapshot) ? get(snapshot, "operations", []) : [];
  const panels = groupBySide(isList(rows) ? rows : []);
  const ids = new Set<any>();
  for (const row of [...panels.left, ...panels.right]) ids.add(get(row, "operation_id"));
  const comparison: Dict[] = [];
  for (const operationId of [...ids].filter((x) => isStr(x)).sort(codePointCompare)) {
    const left = panels.left.find((row) => get(row, "operation_id") === operationId) ?? null;
    const right = panels.right.find((row) => get(row, "operation_id") === operationId) ?? null;
    let difference: Dict;
    if (left === null || right === null) difference = { status: "opposite_unobserved", hours_delta: null };
    else if (isPyNum(get(left, "hours")) && isPyNum(get(right, "hours"))) difference = { status: "both_observed", hours_delta: pyRound(pySub(right.hours, left.hours), 10) };
    else difference = { status: "both_observed", hours_delta: null };
    comparison.push({ operation_id: operationId, left, right, difference });
  }
  const result = calculate(snapshot, rulePack);
  Object.assign(result, {
    engine_id: ENGINE_ID, rule_version: RULE_VERSION, side_panels: panels, side_comparison: comparison,
    trace: [{ event: "side_observations_grouped", left_count: panels.left.length, right_count: panels.right.length, unknown_opposite_autofilled: false }, ...result.trace],
  });
  return result;
}
