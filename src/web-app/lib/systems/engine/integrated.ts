/* eslint-disable @typescript-eslint/no-explicit-any */
// 統合版: 検証済みの既存モジュールを合成した架空の見積ワークフロー。 元: integrated.py
import {
  type Dict, dedupe, deepcopy, get, isDict, isInt, isNumber, pyAdd, pyDiv, pyEq, pyFloat, pyIn, pyJsonDumps, pyRound, sha256Hex, truthy,
} from "./py";
import { BANDS } from "./contract";
import * as e02 from "./e02";
import * as e06 from "./e06";
import * as e07 from "./e07";
import * as e13 from "./e13";
import * as e18 from "./e18";
import * as e21 from "./e21";

export const ENGINE_ID = "integrated";
export const RULE_VERSION = "integrated-workflow-v1";
const NOTICE = "統合版も架空Simulatorです。実測工数・実価格・実車検証ではありません。";
const nullRange = () => ({ low: null, typical: null, high: null });
const WAIT_IDS = ["snow_melt", "penetrant_wait", "parts_wait"];

function stop(version: any, issues: string[], trace: Dict[]): Dict {
  return {
    engine_id: ENGINE_ID, rule_version: version, status: "missing-required",
    labor: { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(issues) },
    trace, operation_keys: [], approvals: [], simulator_notice: NOTICE,
  };
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const version = get(scenario, "rule_version", RULE_VERSION);
  const pack: Dict = isDict(rulePack) ? deepcopy(rulePack) : {};
  const trace: Dict[] = [];
  if (!isDict(scenarioInput)) return stop(version, ["scenario_input:object_required"], trace);
  if (rulePack !== null && !isDict(rulePack)) return stop(version, ["rule_pack:object_required"], trace);
  if (truthy(pack) && !pyIn(get(pack, "rule_version"), [null, version])) return stop(version, ["rule_pack:version_mismatch"], trace);
  const schema = e13.renderForm(scenario, get(pack, "form_rule_pack"));
  const validation = e07.validateStage(scenario);
  const unknownWaitIds: string[] = [];
  for (const op of get(scenario, "operations", [])) {
    if (isDict(op) && WAIT_IDS.includes(get(op, "operation_id"))) {
      const duration = get(op, "elapsed_hours", get(op, "duration_hours", get(op, "hours")));
      if (duration === null) unknownWaitIds.push(op.operation_id);
    }
  }
  const gaps: string[] = validation.issues.filter((issue) => !unknownWaitIds.some((id) => issue.startsWith(`${id}:`) && issue.includes("elapsed_hours_required")));
  const questions: Dict[] = get(schema, "questions", []);
  if (questions.length) gaps.push(...questions.map((q) => `${q.field}:schema_confirmation_required`));
  trace.push({ stage: "schema_and_pipeline_validation", schema: schema.schema, questions: deepcopy(questions), issues: dedupe(gaps), input_hash: validation.input_hash });
  if (gaps.length) return stop(version, gaps, trace);
  const approvedPack = get(pack, "approved_rule_pack");
  let result: Dict;
  if (approvedPack === null) {
    result = e06.run(scenario);
    trace.push({ stage: "approved_rules", engine_id: "e06_approval_rules", source: "fictional_approved_baseline", approval_trace: deepcopy(get(result, "trace", [])) });
  } else {
    result = e02.run(scenario, approvedPack);
    trace.push({ stage: "approved_rules", engine_id: "e02_versioned_json", source: "explicit_approved_rule_pack", approval_trace: deepcopy(get(result, "trace", [])) });
  }
  if (get(result, "status") === "missing-required") return stop(version, [...get(result.labor, "unknowns", [])], trace);
  const labor: Dict = deepcopy(result.labor);
  if (unknownWaitIds.length) {
    labor.elapsed_hours = nullRange();
    labor.unknowns = dedupe([...get(labor, "unknowns", []), ...unknownWaitIds.map((id) => `${id}:elapsed_duration_unknown`)]);
    for (const row of get(labor, "breakdown", [])) if (unknownWaitIds.includes(get(row, "operation_id"))) row.elapsed_hours = nullRange();
    result.status = "partial";
  }
  const additions = get(pack, "evidence_additions", []);
  const evidenceIds: string[] = [];
  const evidenceElapsedUnknowns: string[] = [];
  if (truthy(additions)) {
    const evidence = e21.run(scenario, { additions });
    trace.push({
      stage: "evidence_gate", engine_id: "e21_evidence_additions",
      accepted: deepcopy(get(get(evidence, "evidence_additions", {}), "accepted", [])), issues: deepcopy(get(get(evidence, "evidence_additions", {}), "issues", [])),
    });
    if (get(evidence, "status") === "missing-required") return stop(version, [...get(evidence.labor, "unknowns", [])], trace);
    const requestedById = new Map<any, Dict>();
    for (const it of additions) if (isDict(it)) requestedById.set(get(it, "operation_id"), it);
    for (const addition of evidence.evidence_additions.accepted) {
      evidenceIds.push(addition.operation_id);
      const requested = requestedById.get(addition.operation_id) ?? {};
      for (const band of BANDS) labor.person_hours[band] = pyRound(pyAdd(labor.person_hours[band], addition.hours), 10);
      const duration = get(requested, "duration_hours");
      const count = get(requested, "person_count");
      let additionElapsed: Dict;
      if (isNumber(duration) && duration >= 0 && isInt(count) && count > 0) {
        additionElapsed = Object.fromEntries(BANDS.map((k) => [k, pyFloat(duration)]));
        for (const band of BANDS) if (labor.elapsed_hours[band] !== null) labor.elapsed_hours[band] = pyRound(pyAdd(labor.elapsed_hours[band], pyFloat(duration)), 10);
      } else {
        additionElapsed = nullRange();
        evidenceElapsedUnknowns.push(`${addition.operation_id}:elapsed_duration_unknown`);
      }
      labor.breakdown.push({
        operation: addition.operation_id, operation_id: addition.operation_id, hours: Object.fromEntries(BANDS.map((k) => [k, addition.hours])),
        elapsed_hours: additionElapsed, person_count: count, reason: addition.approval.reason, status: "conditional", source: addition.source,
        approval: deepcopy(addition.approval),
      });
    }
  }
  const client = get(pack, "client_proposal");
  if (client !== null) {
    if (
      !isDict(client) || !isDict(get(client, "labor")) || !pyEq(get(client, "rule_version"), version) ||
      !pyEq(get(client.labor, "person_hours"), get(labor, "person_hours")) || !pyEq(get(client.labor, "elapsed_hours"), get(labor, "elapsed_hours"))
    ) return stop(version, ["client_proposal:server_recomputation_mismatch"], trace);
    trace.push({ stage: "server_recompute", client_proposal_checked: true, match: true });
  }
  if (evidenceElapsedUnknowns.length) {
    labor.elapsed_hours = nullRange();
    labor.unknowns = dedupe([...get(labor, "unknowns", []), ...evidenceElapsedUnknowns]);
  }
  const inputHash = sha256Hex(pyJsonDumps(scenario, { sortKeys: true, ensureAscii: false, defaultStr: true }));
  const operations: Dict[] = get(scenario, "operations", []);
  const leaves: Dict[] = [];
  const replacement = operations.find((op) => get(op, "operation_id") === "replacement_carry") ?? {};
  get(labor, "breakdown", []).forEach((row: Dict, index: number) => {
    let person: Dict = deepcopy(get(row, "hours", nullRange()));
    let elapsed: Dict;
    if (get(row, "status") === "wait") {
      elapsed = deepcopy(get(row, "elapsed_hours", nullRange()));
      person = { low: 0.0, typical: 0.0, high: 0.0 };
    } else if (get(row, "operation_id") === "replacement_carry") {
      const count = get(replacement, "person_count");
      elapsed = Object.fromEntries(BANDS.map((k) => [k, isInt(count) && count > 0 ? pyDiv(get(get(row, "hours", {}), k), count) : null]));
    } else if (get(row, "operation_id") === "wash") {
      const washOp = operations.find((op) => get(op, "operation_id") === "wash") ?? {};
      const count = get(washOp, "person_count", 1);
      elapsed = Object.fromEntries(BANDS.map((k) => [k, isInt(count) && count > 0 ? pyDiv(person[k], count) : null]));
    } else if (evidenceIds.includes(get(row, "operation_id"))) {
      elapsed = deepcopy(get(row, "elapsed_hours", nullRange()));
    } else {
      elapsed = deepcopy(or2(get(row, "elapsed_hours"), person));
    }
    leaves.push({
      node_id: `row-${index}`, rule: "operation_contribution", children: [], result: { person_hours: person, elapsed_hours: elapsed },
      operation_id: get(row, "operation_id"), source: get(row, "source"), status: get(row, "status"), reason: get(row, "reason"),
    });
  });
  const tree = { node_id: "integrated-root", rule: "sum_children", children: leaves };
  const evaluated = e18.evaluateTree(tree);
  const expected = { person_hours: deepcopy(labor.person_hours), elapsed_hours: deepcopy(labor.elapsed_hours) };
  trace.push({ stage: "e18_applied_row_trace_tree", engine_id: "e18_calculation_trace_tree", rule_version: version, input_sha256: inputHash, tree, evaluated });
  if (!pyEq(evaluated, expected)) return stop(version, ["trace_tree:applied_rows_do_not_reproduce_labor"], trace);
  trace.push({ stage: "offline_replay", engine_id: "e29_offline_snapshot", rule_version_pinned: version, conflict_policy: "explicit_human_resolution" });
  const finalStatus = unknownWaitIds.length || evidenceElapsedUnknowns.length ? "partial" : get(result, "status", "proposed");
  return {
    engine_id: ENGINE_ID, rule_version: version, status: finalStatus, labor, trace,
    operation_keys: dedupe(get(labor, "breakdown", []).map((row: Dict) => get(row, "operation_id", get(row, "operation", "")))),
    approvals: deepcopy(get(result, "approvals", [])), simulator_notice: NOTICE,
  };
}

/** `a or b`（Python の真偽値判定）。 */
function or2(a: any, b: any): any {
  return truthy(a) ? a : b;
}

