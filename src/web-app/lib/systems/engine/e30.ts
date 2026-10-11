/* eslint-disable @typescript-eslint/no-explicit-any */
// E30: manual labor-basis bridge with source permission checks. 元: e30.py
import { type Dict, deepcopy, get, isDict, isNumber, isStr, pyEq, pyFloat, pyIn } from "./py";
import * as e07 from "./e07";

export const ENGINE_ID = "e30_manual_basis_bridge";
export const RULE_VERSION = "e30-manual-bridge-v1";
const NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const nullRange = () => ({ low: null, typical: null, high: null });

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const version = get(scenario, "rule_version", RULE_VERSION);
  const pack: Dict = isDict(rulePack) ? deepcopy(rulePack) : {};
  const basis = rulePack !== null && isDict(pack) ? get(pack, "manual_basis") : null;
  const fallback = rulePack === null;
  const packIssues: string[] = [];
  if (rulePack !== null && !isDict(rulePack)) {
    packIssues.push("rule_pack:object_required");
  } else if (rulePack !== null) {
    if (!pyIn(get(pack, "engine_id"), [null, ENGINE_ID])) packIssues.push("rule_pack:engine_id_mismatch");
    if (!pyEq(get(pack, "rule_version"), version)) packIssues.push("rule_pack:version_mismatch");
  }
  if (fallback) {
    const result = e07.run(scenario);
    result.engine_id = ENGINE_ID;
    result.trace.unshift({ stage: "manual_basis", mode: "approved_process_fallback", note: "No manual basis supplied; retain the approved fictional process baseline." });
    return result;
  }
  const issues = [...packIssues];
  if (!isDict(basis)) {
    issues.push("manual_basis:object_required");
  } else {
    if (get(basis, "unit") !== "person_hour") issues.push("manual_basis:person_hour_unit_required");
    if (!isStr(get(basis, "definition")) || !basis.definition.trim()) issues.push("manual_basis:definition_required");
    if (!isStr(get(basis, "source")) || !basis.source.trim()) issues.push("manual_basis:source_required");
    if (get(basis, "permission_status") !== "fictional_only") issues.push("manual_basis:permission_unconfirmed");
    const value = get(basis, "value");
    if (typeof value === "boolean" || !isNumber(value) || !Number.isFinite(value) || value < 0) issues.push("manual_basis:value_invalid");
  }
  if (issues.length) {
    return {
      engine_id: ENGINE_ID, rule_version: version, status: "missing-required",
      labor: { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: issues },
      trace: [{ stage: "manual_basis", validated: false }], operation_keys: [], approvals: [], simulator_notice: NOTICE,
    };
  }
  const base = get(scenario, "operations", []).find((op: any) => isDict(op) && get(op, "operation_id") === "base_service");
  if (base === undefined) {
    return {
      engine_id: ENGINE_ID, rule_version: version, status: "missing-required",
      labor: { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: ["base_service:required"] },
      trace: [], operation_keys: [], approvals: [], simulator_notice: NOTICE,
    };
  }
  base.hours = pyFloat(basis!.value);
  base.deduplicated = true;
  const result = e07.run(scenario);
  result.engine_id = ENGINE_ID;
  result.trace.unshift({
    stage: "manual_basis", mode: "manual", unit: basis!.unit, definition: basis!.definition, source: basis!.source,
    permission_status: basis!.permission_status, value: basis!.value,
  });
  return result;
}
