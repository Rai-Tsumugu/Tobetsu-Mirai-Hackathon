/* eslint-disable @typescript-eslint/no-explicit-any */
// テスト用の入力（golden/generate.py の同名の入力と同じ内容）
import { readFileSync } from "node:fs";
import path from "node:path";

export const golden = (name: string): any => JSON.parse(readFileSync(path.join(__dirname, "golden", name), "utf8"));

export const E05_CSV = `job_id,operation_key,condition_field,match_value,low,typical,high,unit,source,reason
front_brake_service,base_service,work_scope,front_brake_service,1.7,1.7,1.7,person_hours,fixture:base,base work
front_brake_service,replacement_carry,included_operations,remove_install,0.2,0.2,0.2,person_hours,fixture:carry,replacement handling
front_brake_service,snow_melt,included_operations,snow_removal,0.5,0.5,0.5,elapsed_hours,fixture:snow,wait only
front_brake_service,penetrant_wait,work_scope,front_brake_service,0.25,0.25,0.25,elapsed_hours,fixture:penetrant,wait only
front_brake_service,parts_wait,parts_wait_stock_checked,true,0,0,0,elapsed_hours,fixture:parts,stock checked wait
front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fixture:wash,performed wash
front_brake_service,rotor_seizure,rotor_relevance,relevant,0,0.25,0.5,person_hours,fixture:rotor,condition range
`;

export function e04Pack(version = "fictional-rule-v1", washHours = 0.1): any {
  const defs: [string, string, string, string, any, number][] = [
    ["base_service", "承認済み基準作業", "work", "person_hours", 1.7, 1],
    ["included_carry", "含有運搬", "work", "person_hours", 0.12, 1],
    ["replacement_carry", "二人作業の運搬", "work", "person_hours", 0.2, 2],
    ["rotor_seizure", "ローター固着", "work", "person_hours", { low: 0, typical: 0.25, high: 0.5 }, 1],
    ["snow_melt", "雪の融解待ち", "wait", "elapsed_hours", 0.5, 0],
    ["penetrant_wait", "浸透待ち", "wait", "elapsed_hours", 0.25, 0],
    ["parts_wait", "部品待ち", "wait", "elapsed_hours", 0.0, 0],
    ["wash", "洗浄", "work", "person_hours", washHours, 1],
  ];
  const entries = defs.map(([operationId, name, kind, unit, hours, personCount]) => ({
    operation_id: operationId, operation_key: operationId, operation: name, kind, unit,
    hours: typeof hours === "number" ? { low: hours, typical: hours, high: hours } : hours,
    person_count: personCount,
    evidence: [{ source: "fictional_simulator_fixture", note: `架空 evidence: ${operationId}` }],
  }));
  return {
    id: "fictional_labor_rules", rule_version: version, status: "approved", approved_by: "fictional_shop_owner",
    effective_from: "2026-10-11", source: "fictional_simulator_fixture", rules: entries,
  };
}

export function e06FixturePackPayload(scenario: any): any {
  const r = (key: string, condition: any, h: number, unit: string) => ({
    job_id: "front_brake_service", operation_key: key, condition, hours: { low: h, typical: h, high: h }, unit, source: "fixture:" + key,
  });
  return {
    engine_id: "e06_approval_rules", rule_version: "fictional-e06-test-v1", source: "fixture",
    basis_unit: scenario.basis_unit, basis_definition: scenario.basis_definition,
    rules: [
      r("base_service", { field: "work_scope", equals: "front_brake_service" }, 1.7, "person_hours"),
      r("replacement_carry", { field: "included_operations", contains: "remove_install" }, 0.2, "person_hours"),
      r("snow_melt", { field: "included_operations", contains: "snow_removal" }, 0.5, "elapsed_hours"),
      r("penetrant_wait", { field: "work_scope", equals: "front_brake_service" }, 0.25, "elapsed_hours"),
      r("parts_wait", { field: "parts_wait_stock_checked", equals: true }, 0, "elapsed_hours"),
      r("wash", { field: "work_scope", equals: "front_brake_service" }, 0.1, "person_hours"),
      { ...r("rotor_seizure", { field: "rotor_relevance", equals: "relevant" }, 0, "person_hours"), hours: { low: 0, typical: 0.25, high: 0.5 } },
    ],
  };
}
