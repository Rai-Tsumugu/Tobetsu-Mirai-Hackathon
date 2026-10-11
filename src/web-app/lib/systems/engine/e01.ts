/* eslint-disable @typescript-eslint/no-explicit-any */
// E01: fictional typed static-table labor estimator. 元: e01.py
import { type Dict, dedupe, get, isDict, isList, or, pyEq, pyIn } from "./py";
import { referenceLabor } from "./contract";

interface RuleRow {
  job_id: string;
  operation_key: string;
  field_key: string | null;
  match_value: any;
  source: string;
  reason: string;
}

const row = (operation_key: string, field_key: string, match_value: any, source: string, reason: string): RuleRow => ({
  job_id: "front_brake_service", operation_key, field_key, match_value, source, reason,
});

const STATIC_TABLE: RuleRow[] = [
  row("base_service", "work_scope", "front_brake_service", "fictional_static_table:E01/base", "Deduplicated base labor from the fictional scenario."),
  row("replacement_carry", "included_operations", "remove_install", "fictional_static_table:E01/carry", "Replaces included carry with two-person handling."),
  row("rust_observation", "included_operations", "rust_observation", "fictional_static_table:E01/rust", "Rust observation is an explicitly included scope key."),
  row("snow_melt", "included_operations", "snow_removal", "fictional_static_table:E01/wait", "Confirmed waiting contributes elapsed time only."),
  row("penetrant_wait", "work_scope", "front_brake_service", "fictional_static_table:E01/wait", "Confirmed waiting contributes elapsed time only."),
  row("parts_wait", "parts_wait_stock_checked", true, "fictional_static_table:E01/wait", "Stock-checked wait is zero in this fictional fixture."),
  row("wash", "work_scope", "front_brake_service", "fictional_static_table:E01/wash", "Performed wash remains work and is marked nonbillable."),
  row("rotor_seizure", "rotor_relevance", "relevant", "fictional_static_table:E01/condition", "Rotor condition width requires human approval."),
  row("rotor_unrelated", "rotor_relevance", "unrelated", "fictional_static_table:E01/condition", "Human-confirmed unrelated condition is excluded from this scope."),
];
const TABLE_VERSION = "e01-static-table-v1";
const REQUIRED_INCLUDED_OPERATIONS = ["remove_install", "rust_observation", "snow_removal"];

function obs(scenario: Dict, key: string): Dict {
  const raw = get(or(get(scenario, "fields"), {}), key);
  if (isDict(raw) && "status" in raw) return raw;
  return { value: raw, status: raw !== null ? "declared" : "unknown", source: null };
}

const NULL = () => ({ low: null, typical: null, high: null });
const badStatus = (s: any) => s === null || s === "unknown" || s === "assumed";

export function run(scenario: Dict, rulePack: Dict | null = null): Dict {
  const engineId = "e01_static_table";
  const ruleVersion = get(scenario, "rule_version", "fictional-rule-v1");
  const jobId = get(scenario, "job_id");
  const selected: RuleRow[] = [];
  const trace: Dict[] = [{ event: "table_loaded", table: "STATIC_TABLE", table_version: TABLE_VERSION, source: "fictional_static_table:E01", row_count: STATIC_TABLE.length }];
  const gateUnknowns: string[] = [];
  if (rulePack !== null) {
    if (get(rulePack, "table_version") !== TABLE_VERSION) gateUnknowns.push("rule_pack:unbound_to_static_table_version");
    if (get(rulePack, "rules")) gateUnknowns.push("rule_pack:dynamic_rules_unsupported");
  }
  for (const r of STATIC_TABLE) {
    if (r.job_id !== jobId) continue;
    if (r.field_key === null) {
      selected.push(r);
      continue;
    }
    const observed = obs(scenario, r.field_key);
    const val = get(observed, "value");
    const validStatus = !badStatus(get(observed, "status"));
    const matched = validStatus && (pyEq(val, r.match_value) || (r.field_key === "included_operations" && isList(val) && pyIn(r.match_value, val)));
    if (matched) {
      selected.push(r);
      trace.push({ event: "row_applied", table: "STATIC_TABLE", table_version: TABLE_VERSION, operation_key: r.operation_key, job_id: r.job_id, field_key: r.field_key, matched_value: val, static_table_source: r.source, observation_source: get(observed, "source"), observation_status: get(observed, "status"), confirmed_at: get(observed, "confirmed_at") });
    } else if (r.field_key === "work_scope" || r.field_key === "included_operations") {
      gateUnknowns.push(`${r.field_key}:static_table_eligibility_failed`);
    }
  }
  const scopeObs = obs(scenario, "work_scope");
  if (get(scopeObs, "value") !== "front_brake_service" || badStatus(get(scopeObs, "status"))) gateUnknowns.push("work_scope:confirmed_exact_match_required");
  const includedObs = obs(scenario, "included_operations");
  const includedValue = get(includedObs, "value");
  if (badStatus(get(includedObs, "status")) || !isList(includedValue) || !REQUIRED_INCLUDED_OPERATIONS.every((k) => includedValue.includes(k))) {
    gateUnknowns.push("included_operations:confirmed_required_set_required");
  } else {
    const tableOps = new Set(STATIC_TABLE.filter((r) => r.field_key === "included_operations").map((r) => r.match_value));
    if ([...new Set(includedValue)].some((v) => !tableOps.has(v))) gateUnknowns.push("included_operations:declared_operation_missing_static_table_row");
  }
  const rotorObs = obs(scenario, "rotor_relevance");
  if ((get(rotorObs, "value") === "relevant" || get(rotorObs, "value") === "unrelated") && badStatus(get(rotorObs, "status"))) {
    gateUnknowns.push("rotor_relevance:confirmed_status_required");
  }
  const operations: any[] = or(get(scenario, "operations"), []);
  if (operations.some((op) => get(op, "operation_id") === "parts_wait")) {
    const stockObs = obs(scenario, "parts_wait_stock_checked");
    if (get(stockObs, "value") !== true || get(stockObs, "status") !== "confirmed") gateUnknowns.push("parts_wait_stock_checked:confirmed_true_required");
  }
  trace.push({ event: "lookup_complete", job_id: jobId, matched_operation_keys: selected.map((r) => r.operation_key) });

  const operationToKey: Record<string, string> = {
    base_service: "base_service", included_carry: "replacement_carry",
    replacement_carry: "replacement_carry", snow_melt: "snow_melt",
    penetrant_wait: "penetrant_wait", parts_wait: "parts_wait", wash: "wash",
  };
  const selectedKeysSet = new Set(selected.map((r) => r.operation_key));
  const filteredScenario: Dict = { ...scenario };
  filteredScenario.operations = [];
  for (const operation of operations) {
    const operationId = get(operation, "operation_id");
    const operationKey = typeof operationId === "string" && Object.prototype.hasOwnProperty.call(operationToKey, operationId) ? operationToKey[operationId] : undefined;
    if (operationKey === undefined) {
      gateUnknowns.push(`${or(operationId, "operation")}:static_table_row_missing`);
    } else if (!selectedKeysSet.has(operationKey)) {
      gateUnknowns.push(`${operationId}:static_table_row_not_matched`);
    } else {
      filteredScenario.operations.push(operation);
    }
  }
  const [labor, , refUnknowns] = referenceLabor(filteredScenario);
  let unknowns = dedupe([...refUnknowns, ...gateUnknowns]);
  let blockingUnknowns = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));
  if (blockingUnknowns.length) {
    labor.person_hours = NULL();
    labor.elapsed_hours = NULL();
    labor.unknowns = unknowns;
    for (const r of labor.breakdown) {
      r.hours = NULL();
      if ("elapsed_hours" in r) r.elapsed_hours = NULL();
      r.status = "missing-required";
    }
  }
  trace.push({ event: "table_version_pinned", table: "STATIC_TABLE", table_version: TABLE_VERSION });
  if (!selected.length) {
    unknowns = dedupe([...unknowns, "job_id:unsupported_by_static_table"]);
    blockingUnknowns = dedupe([...blockingUnknowns, "job_id:unsupported_by_static_table"]);
    labor.unknowns = unknowns;
    labor.person_hours = NULL();
    labor.elapsed_hours = NULL();
    for (const r of labor.breakdown) {
      r.hours = NULL();
      if ("elapsed_hours" in r) r.elapsed_hours = NULL();
      r.status = "missing-required";
    }
  }
  for (const r of labor.breakdown) {
    const opId = get(r, "operation_id");
    if (opId === "rotor_seizure" && get(rotorObs, "value") === "unrelated") r.operation_key = "rotor_unrelated";
    else if (opId === "included_carry") r.operation_key = "replacement_carry";
    else r.operation_key = opId ? opId : r.operation;
    if (!("reason" in r)) r.reason = "Fictional shared contract calculation.";
    if (!("status" in r)) r.status = "proposed";
  }
  const selectedKeys = selected.map((r) => r.operation_key);
  const approvals = labor.breakdown.filter((r: Dict) => get(r, "approval")).map((r: Dict) => ({ operation_key: get(r, "operation_id"), ...r.approval }));
  const resultStatus = blockingUnknowns.length ? "missing-required" : unknowns.length ? "partial" : "proposed";
  return { engine_id: engineId, rule_version: ruleVersion, table_version: TABLE_VERSION, status: resultStatus, labor, trace, operation_keys: dedupe(selectedKeys), approvals, simulator_notice: "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。" };
}
