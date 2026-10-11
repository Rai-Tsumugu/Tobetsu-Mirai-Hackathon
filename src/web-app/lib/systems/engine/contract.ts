/* eslint-disable @typescript-eslint/no-explicit-any */
// 元: src/auto_repair_engine/contract.py（共有契約・共通フィクスチャ・正準の工数計算）
import {
  type Dict,
  dedupe,
  deepcopy,
  get,
  isDict,
  isList,
  isNumber,
  isStr,
  item,
  pyEq,
  pyFloat,
  pyInt,
  pyRound,
  pySum,
  truthy,
} from "./py";

export const KNOWN_SCOPE_KEYS = new Set(["remove_install", "rust_observation", "snow_removal"]);
export const BANDS = ["low", "typical", "high"] as const;

export const nullRange = (): Dict => ({ low: null, typical: null, high: null });

export function commonScenarioFixture(): Dict {
  return {
    scenario_id: "fictional-common-scenario-01",
    job_id: "front_brake_service",
    engine_id: "e07_pipeline",
    rule_version: "fictional-rule-v1",
    basis_unit: "person_hour",
    basis_definition: "架空の整備作業範囲。含有運搬を除き、承認済み作業行を人時で集計する",
    base_hours: { value: 1.0, status: "declared", source: "fictional_fixture", confirmed_at: null },
    labor_rate: { value: 9000, status: "assumed", source: "fictional_fixture_only", confirmed_at: null },
    fields: {
      work_scope: { value: "front_brake_service", status: "confirmed", source: "fictional_fixture", confirmed_at: "2026-10-11T00:00:00+00:00" },
      included_operations: { value: ["remove_install", "rust_observation", "snow_removal"], status: "confirmed", source: "fictional_fixture", confirmed_at: "2026-10-11T00:00:00+00:00" },
      rotor_seizure: { value: null, status: "unknown", source: null, confirmed_at: null },
      subframe_relevance: { value: "unrelated", status: "confirmed", source: "fictional_fixture", confirmed_at: "2026-10-11T00:00:00+00:00" },
      parts_wait_stock_checked: { value: true, status: "confirmed", source: "fictional_fixture", confirmed_at: "2026-10-11T00:00:00+00:00" },
    },
    operations: [
      { operation_id: "base_service", operation: "approved_deduplicated_base", gross_hours: 2.0, hours: 1.7, person_count: 1, duration_hours: 1.7, status: "confirmed-observation", source: "fictional_fixture", deduplicated: true, reason: "E10's 0.3 shared overlap is already removed outside E10" },
      { operation_id: "included_carry", operation: "included_transport", hours: 0.12, person_count: 1, status: "confirmed-observation", included_in_base: true, billable: false, source: "fictional_fixture" },
      { operation_id: "replacement_carry", operation: "two_person_handling", hours_per_person: 0.10, person_count: 2, status: "confirmed-observation", replaces_operation_id: "included_carry", source: "fictional_fixture" },
      { operation_id: "snow_melt", operation: "snow_melting", hours: 0.5, person_count: 0, elapsed_hours: 0.5, status: "wait", source: "fictional_fixture" },
      { operation_id: "penetrant_wait", operation: "penetrant_wait", hours: 0.25, person_count: 0, elapsed_hours: 0.25, status: "wait", source: "fictional_fixture" },
      { operation_id: "parts_wait", operation: "parts_wait", hours: 0.0, person_count: 0, elapsed_hours: 0.0, status: "wait", source: "fictional_fixture", stock_checked: true },
      { operation_id: "wash", operation: "wash", hours: 0.1, person_count: 1, status: "nonbillable-work", source: "fictional_fixture" },
    ],
    person_count: 1,
    duration_hours: null,
    waiting_hours: 0.75,
    metadata: { fictional_values: true },
  };
}

export function approvedCommonScenarioFixture(): Dict {
  const scenario = deepcopy(commonScenarioFixture());
  scenario.fields.rotor_relevance = {
    value: "relevant", status: "confirmed", source: "fictional_fixture", confirmed_at: "2026-10-11T00:00:00+00:00",
  };
  scenario.fields.rotor_seizure_hours = {
    value: { low: 0.0, typical: 0.25, high: 0.5 }, status: "confirmed",
    source: "fictional_human_approved_condition_width", confirmed_at: "2026-10-11T00:00:00+00:00",
  };
  scenario.metadata.approved_condition_widths = {
    rotor_seizure_hours: {
      actor: "fictional_shop_owner", reason: "fictional fixture approval",
      old_value: null, new_value: { low: 0.0, typical: 0.25, high: 0.5 },
    },
  };
  return scenario;
}

export function validateCoreContract(labor: Dict): string[] {
  const issues: string[] = [];

  const validRange = (value: any): boolean => {
    if (!isDict(value) || BANDS.some((k) => !(k in value))) return false;
    const numbers = BANDS.map((k) => value[k]);
    if (numbers.some((n) => n !== null && n !== undefined && (typeof n === "boolean" || !isNumber(n) || !Number.isFinite(n) || n < 0))) return false;
    const present = numbers.filter((n) => n !== null && n !== undefined);
    return present.length === 0 || (present.length === 3 && present[0] <= present[1] && present[1] <= present[2]);
  };

  for (const key of ["person_hours", "elapsed_hours"]) {
    const value = get(labor, key, {});
    if (!validRange(value)) issues.push(`${key}:invalid_range`);
  }
  let rows = get(labor, "breakdown", []);
  if (!isList(rows)) {
    issues.push("breakdown:not_list");
    rows = [];
  }
  rows.forEach((row: any, index: number) => {
    if (!isDict(row)) {
      issues.push(`breakdown[${index}]:not_object`);
      return;
    }
    if (!["operation", "hours", "reason", "status"].every((k) => k in row)) issues.push(`breakdown[${index}]:shape`);
    if (!validRange(get(row, "hours"))) issues.push(`breakdown[${index}]:invalid_range`);
    if (get(row, "status") === "missing-required") {
      const h = truthy(get(row, "hours")) ? get(row, "hours") : {};
      if (Object.values(h).some((v) => v !== null && v !== undefined)) issues.push(`breakdown[${index}]:missing_must_be_null`);
    }
  });
  const unknowns = get(labor, "unknowns");
  if (!isList(unknowns) || get(labor, "unknowns", []).some((u: any) => !isStr(u))) issues.push("unknowns:must_be_string_list");
  return issues;
}

function obsValue(fields: Dict, key: string): [any, string] {
  const it = get(fields, key, {});
  if (isDict(it) && "value" in it) return [it.value ?? null, get(it, "status", "unknown")];
  return [it, it !== null ? "declared" : "unknown"];
}

const zeroRange = () => ({ low: 0.0, typical: 0.0, high: 0.0 });

/** 共通の工数計算。 [labor, rows, unknowns] を返す。 */
export function referenceLabor(scenarioInput: Dict): [Dict, Dict[], string[]] {
  const scenario = deepcopy(scenarioInput);
  const operations: any[] = get(scenario, "operations", []);
  const fields: Dict = get(scenario, "fields", {});
  const unknowns: string[] = [];
  const elapsedUnknowns: string[] = [];
  const rows: Dict[] = [];
  const findOp = (id: string) => operations.find((op) => get(op, "operation_id") === id);

  const [workScope, scopeStatus] = obsValue(fields, "work_scope");
  if (!pyEq(workScope, get(scenario, "job_id")) || !["confirmed", "declared"].includes(scopeStatus)) unknowns.push("work_scope:required_match_and_status");
  const [includedOperations, includedStatus] = obsValue(fields, "included_operations");
  if (!isList(includedOperations) || !["confirmed", "declared"].includes(includedStatus)) {
    unknowns.push("included_operations:required_and_status");
  } else if (includedOperations.length === 0 || includedOperations.some((key) => !isStr(key) || !KNOWN_SCOPE_KEYS.has(key))) {
    unknowns.push("included_operations:unknown_or_empty_scope");
  }
  const basisDefinition = get(scenario, "basis_definition");
  if (get(scenario, "basis_unit") !== "person_hour" || !isStr(basisDefinition) || !basisDefinition.trim()) unknowns.push("basis_unit_or_definition:required");

  const base = findOp("base_service");
  if (!base || get(base, "hours") === null || !truthy(get(base, "deduplicated"))) unknowns.push("approved_deduplicated_base");
  const baseHours = base && truthy(get(base, "deduplicated")) && get(base, "hours") !== null ? pyFloat(item(base, "hours")) : 0.0;
  const included = findOp("included_carry");
  const replacement = findOp("replacement_carry");
  if (truthy(included) && truthy(replacement) && get(replacement, "replaces_operation_id") === "included_carry") {
    const includedHours = truthy(get(included, "included_in_base")) ? pyFloat(get(included, "hours", 0)) : 0.0;
    const netBaseHours = baseHours - includedHours;
    if (netBaseHours < 0) unknowns.push("included_transport:exceeds_base");
    if (netBaseHours && truthy(base)) {
      rows.push({ operation: "approved_deduplicated_base_after_included_removal", hours: { low: netBaseHours, typical: netBaseHours, high: netBaseHours }, reason: "E10共有工程0.3控除済みの基準から含有運搬0.12を控除。二重控除しない", status: "confirmed-observation", operation_id: "base_service", source: get(base, "source") });
    }
    rows.push({ operation: "included_transport_removed", hours: zeroRange(), reason: "含有運搬0.12は含有済みのため追加計上しない", status: "confirmed-observation", operation_id: "included_carry", source: get(included, "source") });
    const handling = pyFloat(get(replacement, "hours_per_person", 0)) * pyInt(get(replacement, "person_count", 0));
    rows.push({ operation: "two_person_handling", hours: { low: handling, typical: handling, high: handling }, reason: "2人×0.10人時。含有運搬を追加計上しない", status: "confirmed-observation", operation_id: "replacement_carry", person_count: get(replacement, "person_count"), source: get(replacement, "source") });
  } else {
    unknowns.push("included_transport_replacement");
  }

  const [rotorRelevance, relevanceStatus] = obsValue(fields, "rotor_relevance");
  const [rotorHours, rotorStatus] = obsValue(fields, "rotor_seizure_hours");
  if (rotorRelevance === "relevant") {
    const approval = get(get(get(scenario, "metadata", {}), "approved_condition_widths", {}), "rotor_seizure_hours");
    if (!["confirmed", "declared"].includes(relevanceStatus)) {
      unknowns.push("rotor_relevance:human_confirmation_required");
    } else if (!truthy(approval) || !isDict(rotorHours) || rotorStatus !== "confirmed") {
      unknowns.push("rotor_seizure_hours:human_approval_required");
    } else {
      const rotor: Dict = {};
      for (const k of BANDS) rotor[k] = get(rotorHours, k);
      const expectedApproval = { low: rotor.low, typical: rotor.typical, high: rotor.high };
      if (
        !isDict(approval) || !isStr(get(approval, "actor")) || !get(approval, "actor").trim() ||
        !isStr(get(approval, "reason")) || !get(approval, "reason").trim() ||
        get(approval, "old_value") !== null || !pyEq(get(approval, "new_value"), expectedApproval)
      ) {
        unknowns.push("rotor_seizure_hours:approval_audit_mismatch");
      } else {
        rows.push({ operation: "rotor_seizure", hours: rotor, reason: "人が承認した条件幅。条件付き提案", status: "conditional", operation_id: "rotor_seizure", approval, source: get(item(fields, "rotor_seizure_hours"), "source") });
      }
    }
  } else if (rotorRelevance === "unrelated" && relevanceStatus === "confirmed") {
    rows.push({ operation: "rotor_seizure", hours: zeroRange(), reason: "このscenarioの作業関連性なしとして人が確認。0は条件不適用を示す", status: "confirmed-observation", operation_id: "rotor_seizure" });
  } else {
    unknowns.push("rotor_relevance:confirm_whether_required");
  }

  for (const operationId of ["snow_melt", "penetrant_wait", "parts_wait"]) {
    const operation = findOp(operationId);
    if (!operation) {
      unknowns.push(`${operationId}:missing`);
      continue;
    }
    if (operationId === "parts_wait" && !truthy(get(operation, "stock_checked"))) {
      unknowns.push("parts_wait:stock_confirmation_required");
      continue;
    }
    const rawElapsed = get(operation, "elapsed_hours", get(operation, "hours", 0));
    let elapsedRange: Dict;
    if (rawElapsed === null) {
      elapsedRange = nullRange();
      elapsedUnknowns.push(`${operationId}:elapsed_duration_unknown`);
    } else {
      const elapsed = pyFloat(rawElapsed);
      elapsedRange = { low: elapsed, typical: elapsed, high: elapsed };
    }
    rows.push({ operation: item(operation, "operation"), hours: zeroRange(), reason: "非拘束の待機。人時0、確認できた経過時間にのみ加算", status: "wait", operation_id: operationId, elapsed_hours: elapsedRange, source: get(operation, "source") });
  }

  const wash = findOp("wash");
  const washHours = wash ? pyFloat(get(wash, "hours", 0)) : 0.0;
  if (wash) {
    rows.push({ operation: "wash", hours: { low: washHours, typical: washHours, high: washHours }, reason: "実作業人時は保持し、請求控除は別承認", status: "nonbillable-work", operation_id: "wash", source: get(wash, "source") });
  }

  if (unknowns.length) {
    const allUnknowns = dedupe([...unknowns, ...elapsedUnknowns]);
    const labor = {
      person_hours: nullRange(),
      elapsed_hours: nullRange(),
      breakdown: rows.map((row) => ({ ...row, hours: nullRange(), status: "missing-required" })),
      unknowns: allUnknowns,
    };
    return [labor, rows, allUnknowns];
  }

  const rotorRow = rows.find((row) => item(row, "operation_id") === "rotor_seizure");
  const rotor = rotorRow ? rotorRow.hours : zeroRange();
  const includedHours = included && truthy(get(included, "included_in_base")) ? pyFloat(get(included, "hours", 0)) : 0.0;
  const netBaseHours = baseHours - includedHours;
  const person: Dict = {};
  for (const key of BANDS) {
    person[key] = pyRound(netBaseHours + pyFloat(item(replacement, "hours_per_person")) * pyInt(item(replacement, "person_count")) + pyFloat(rotor[key]) + washHours, 10);
  }
  const workElapsed = netBaseHours + pyFloat(item(replacement, "hours_per_person")) + washHours + pyFloat(rotor.typical);
  let elapsed: Dict;
  if (elapsedUnknowns.length) {
    elapsed = nullRange();
  } else {
    const waitElapsed = pySum(rows.filter((row) => get(row, "status") === "wait").map((row) => pyFloat(item(item(row, "elapsed_hours"), "typical"))));
    elapsed = {
      low: pyRound(Math.max(0.0, workElapsed - pyFloat(rotor.typical) + pyFloat(rotor.low)) + waitElapsed, 10),
      typical: pyRound(workElapsed + waitElapsed, 10),
      high: pyRound(Math.max(0.0, workElapsed - pyFloat(rotor.typical) + pyFloat(rotor.high)) + waitElapsed, 10),
    };
  }
  const labor = { person_hours: person, elapsed_hours: elapsed, breakdown: rows, unknowns: [...elapsedUnknowns] };
  return [labor, rows, [...elapsedUnknowns]];
}
