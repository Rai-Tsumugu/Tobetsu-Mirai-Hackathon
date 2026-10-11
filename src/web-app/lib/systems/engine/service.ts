/* eslint-disable @typescript-eslint/no-explicit-any */
// API の処理本体（フレームワーク非依存）。元: src/auto_repair_engine/api.py の各エンドポイント。
// Route Handler はここを呼び、HttpError を HTTP のステータスと { detail } に変える。
import { randomUUID } from "node:crypto";
import {
  type Dict, PyKeyError, PyTypeError, PyValueError, deepcopy, get, isDict, isList, isStr, pyFloat, pyIn, pyEq, truthy,
} from "./py";
import { approvedCommonScenarioFixture, commonScenarioFixture } from "./contract";
import * as e13 from "./e13";
import { ENGINE_IDS, EngineNotInstalled, compareEngines, runEngine } from "./runner";
import type { EngineStore } from "../../db/repositories/engine-store";

/** FastAPI の HTTPException(status_code, detail) に当たる。 */
export class HttpError extends Error {
  constructor(readonly status: number, readonly detail: any) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

export interface ApiResponse {
  status: number;
  body: any;
}

const ok = (body: any, status = 200): ApiResponse => ({ status, body });

/** 元の fictional_e02_pack: 共通フィクスチャ用の架空 E02 パック（製品側 API が作る）。 */
export function fictionalE02Pack(scenario: Dict): Dict {
  const rule = (operationKey: string, condition: Dict, hours: number[], unit: string, source: string) => ({
    job_id: "front_brake_service", operation_key: operationKey, condition,
    hours: { low: hours[0], typical: hours[1], high: hours[2] }, unit, source,
  });
  return {
    engine_id: "e02_versioned_json", rule_version: get(scenario, "rule_version", "fictional-rule-v1"), status: "approved",
    approved_by: "fictional_shop_owner", effective_from: "2026-10-11", source: "fictional_fixture_only",
    basis_unit: get(scenario, "basis_unit"), basis_definition: get(scenario, "basis_definition"),
    rules: [
      rule("base_service", { field: "work_scope", equals: "front_brake_service" }, [1.7, 1.7, 1.7], "person_hours", "fictional_json:base"),
      rule("replacement_carry", { field: "included_operations", contains: "remove_install" }, [0.2, 0.2, 0.2], "person_hours", "fictional_json:carry"),
      rule("snow_melt", { field: "included_operations", contains: "snow_removal" }, [0.5, 0.5, 0.5], "elapsed_hours", "fictional_json:snow"),
      rule("penetrant_wait", { field: "work_scope", equals: "front_brake_service" }, [0.25, 0.25, 0.25], "elapsed_hours", "fictional_json:penetrant"),
      rule("parts_wait", { field: "parts_wait_stock_checked", equals: true }, [0.0, 0.0, 0.0], "elapsed_hours", "fictional_json:parts"),
      rule("wash", { field: "work_scope", equals: "front_brake_service" }, [0.1, 0.1, 0.1], "person_hours", "fictional_json:wash"),
      rule("rotor_seizure", { field: "rotor_relevance", equals: "relevant" }, [0.0, 0.25, 0.5], "person_hours", "fictional_json:rotor"),
    ],
  };
}

function scenarioFrom(payload: Dict, allowInline = false): Dict {
  let scenario = get(payload, "scenario_input");
  if (scenario === null && allowInline && "job_id" in payload) scenario = payload;
  if (!isDict(scenario) || !truthy(scenario)) throw new HttpError(422, "scenario_input object is required");
  return scenario;
}

/** 元の `except (TypeError, ValueError, KeyError)` / `except ModuleNotFoundError` に当たる変換。 */
function engineErrorToHttp(error: unknown, notInstalled: string): never {
  if (error instanceof HttpError) throw error;
  if (error instanceof PyKeyError) throw new HttpError(422, `'${error.message.replace(/^"|"$/g, "")}'`);
  if (error instanceof PyTypeError || error instanceof PyValueError) throw new HttpError(422, error.message);
  if (error instanceof EngineNotInstalled) throw new HttpError(503, notInstalled);
  throw error;
}

export const health = (): ApiResponse => ok({ status: "ok", mode: "simulator", fictional_data: true });

export const engines = (): ApiResponse => ok({ engine_ids: [...ENGINE_IDS], integrated_engine_id: "integrated", count: ENGINE_IDS.length });

export const integratedSchema = (jobId = "front_brake_service"): ApiResponse => ok(e13.buildSchema(jobId));

export function integratedEvaluate(payload: Dict): ApiResponse {
  const scenario = scenarioFrom(payload);
  const applied = "answers" in payload ? e13.applyAnswers(scenario, get(payload, "answers", {})) : { scenario_input: scenario, errors: [], approvals: [] };
  return ok({
    scenario_input: applied.scenario_input, errors: applied.errors,
    questions: e13.renderForm(applied.scenario_input).questions, approvals: applied.approvals,
  });
}

export function fixture(approvedRotor = false): ApiResponse {
  return ok({ scenario_input: approvedRotor ? approvedCommonScenarioFixture() : commonScenarioFixture(), fictional_data: true });
}

export function exampleRulePack(engineId: string, approvedRotor = true): ApiResponse {
  const scenario = approvedRotor ? approvedCommonScenarioFixture() : commonScenarioFixture();
  if (engineId === "e02") return ok({ scenario_input: scenario, rule_pack: fictionalE02Pack(scenario), fictional_data: true });
  throw new HttpError(404, "no approved example pack for this engine");
}

export function calculate(engineId: string, payload: Dict): ApiResponse {
  try {
    if (engineId === "integrated") {
      const scenario = scenarioFrom(payload, true);
      let rulePack = get(payload, "rule_pack");
      if (get(payload, "client_proposal") !== null) {
        rulePack = { ...(truthy(rulePack) ? rulePack : {}), rule_version: get(scenario, "rule_version", "fictional-rule-v1"), client_proposal: payload.client_proposal };
      }
      return ok(runEngine(engineId, scenario, rulePack));
    }
    const scenario = scenarioFrom(payload, true);
    let rulePack = get(payload, "rule_pack");
    if (engineId === "e02" && rulePack === null) rulePack = fictionalE02Pack(scenario);
    return ok(runEngine(engineId, scenario, rulePack));
  } catch (e) {
    return engineErrorToHttp(e, `${engineId} implementation is not installed yet`);
  }
}

export function compare(payload: Dict): ApiResponse {
  const scenario = scenarioFrom(payload);
  const rawEngineIds = get(payload, "engine_ids", [...ENGINE_IDS]);
  if (!isList(rawEngineIds) || !rawEngineIds.length) throw new HttpError(422, "engine_ids must be a non-empty array");
  if (rawEngineIds.some((id) => !ENGINE_IDS.includes(id))) throw new HttpError(422, "unknown engine_id");
  try {
    const customPacks = get(payload, "rule_packs", {});
    if (!isDict(customPacks)) throw new HttpError(422, "rule_packs must be an object keyed by engine id");
    const results = rawEngineIds.map((selected: string) => {
      let pack = get(customPacks, selected, get(payload, "rule_pack"));
      if (selected === "e02" && pack === null) pack = fictionalE02Pack(scenario);
      const result = runEngine(selected, scenario, pack);
      return { engine_id: selected, labor: get(result, "labor"), status: get(result, "status"), rule_version: get(result, "rule_version"), trace: get(result, "trace", []) };
    });
    return ok({ scenario_id: get(scenario, "scenario_id"), results, fictional_data: true });
  } catch (e) {
    return engineErrorToHttp(e, "one or more engine implementations are not installed yet");
  }
}

export async function createEstimate(store: EngineStore, payload: Dict): Promise<ApiResponse> {
  const scenario = deepcopy(scenarioFrom(payload));
  const engineId = get(payload, "engine_id", get(scenario, "engine_id", "e07"));
  let result: Dict;
  try {
    let rulePack = get(payload, "rule_pack");
    if (engineId === "e02" && rulePack === null) rulePack = fictionalE02Pack(scenario);
    if (["e27", "e28", "integrated"].includes(engineId) && get(payload, "client_proposal") !== null) {
      rulePack = { ...(truthy(rulePack) ? rulePack : {}), rule_version: get(scenario, "rule_version", "fictional-rule-v1"), client_proposal: payload.client_proposal };
    }
    result = runEngine(engineId, scenario, rulePack);
  } catch (e) {
    return engineErrorToHttp(e, `${engineId} implementation is not installed yet`);
  }
  if (pyIn(get(result, "status"), ["missing-required", "blocked"])) {
    throw new HttpError(409, { message: "required observations or approvals are missing", engine_result: result });
  }
  const rateRaw = get(scenario, "labor_rate");
  const rate = isDict(rateRaw) ? get(rateRaw, "value") : rateRaw;
  const hours = get(get(result, "labor", {}), "person_hours", {});
  let rateValue: number;
  try {
    rateValue = pyFloat(rate);
  } catch (e) {
    if (e instanceof PyTypeError || e instanceof PyValueError) rateValue = NaN;
    else throw e;
  }
  if (rate === null) throw new HttpError(409, "labor_rate is required to calculate money");
  if (typeof rate === "boolean" || !Number.isFinite(rateValue) || rateValue < 0) throw new HttpError(422, "labor_rate must be a finite, non-negative number");
  if (["low", "typical", "high"].some((key) => get(hours, key) === null)) throw new HttpError(409, "a complete person_hours range is required to calculate money");
  const hourValues: Dict = {};
  try {
    for (const key of ["low", "typical", "high"]) hourValues[key] = pyFloat(hours[key]);
  } catch (e) {
    if (e instanceof PyTypeError || e instanceof PyValueError) throw new HttpError(422, "person_hours range must contain finite numbers");
    throw e;
  }
  if (Object.values(hourValues).some((v: any) => !Number.isFinite(v) || v < 0) || !(hourValues.low <= hourValues.typical && hourValues.typical <= hourValues.high)) {
    throw new HttpError(422, "person_hours range must be finite, non-negative, and ordered low <= typical <= high");
  }
  const amountRange: Dict = {};
  for (const key of ["low", "typical", "high"]) amountRange[key] = Math.floor(hourValues[key] * rateValue);
  result.labor_result = {
    labor_hours: hourValues, labor_rate: rateValue, calculated_amount_range: amountRange,
    final_labor_amount: null, parts_amount: null, tax_amount: null, status: "proposed",
  };
  const approvals: Dict[] = [...get(result, "approvals", [])];
  if (get(payload, "final_labor_amount") !== null) {
    const actor = get(payload, "actor");
    const reason = get(payload, "adjustment_reason");
    const finalAmount = payload.final_labor_amount;
    if (typeof finalAmount === "boolean" || typeof finalAmount !== "number" || !Number.isFinite(finalAmount) || finalAmount < 0 || !Number.isInteger(finalAmount)) {
      throw new HttpError(422, "final_labor_amount must be a non-negative whole number");
    }
    if (!isStr(actor) || !actor.trim() || !isStr(reason) || !reason.trim()) throw new HttpError(422, "manual adjustment requires actor and adjustment_reason");
    approvals.push({ type: "labor_amount_adjustment", actor, reason, old_value: amountRange.typical, new_value: Math.trunc(finalAmount) });
    result.approvals = approvals;
    result.labor_result.final_labor_amount = Math.trunc(finalAmount);
    result.labor_result.status = "confirmed";
  }
  let estimateId: string = randomUUID();
  const idempotencyKey = get(payload, "idempotency_key");
  if (idempotencyKey !== null && (!isStr(idempotencyKey) || !idempotencyKey.trim())) throw new HttpError(422, "idempotency_key must be a non-empty string");
  try {
    estimateId = await store.saveEstimate(estimateId, result, idempotencyKey);
  } catch (e) {
    if (e instanceof PyValueError) throw new HttpError(409, e.message);
    throw e;
  }
  return ok({ estimate_id: estimateId, ...((await store.getEstimate(estimateId)) ?? result) }, 201);
}

export async function listEstimates(store: EngineStore, limit = 100): Promise<ApiResponse> {
  return ok(await store.listEstimates(limit));
}

export async function getEstimate(store: EngineStore, estimateId: string): Promise<ApiResponse> {
  const result = await store.getEstimate(estimateId);
  if (result === null) throw new HttpError(404, "estimate not found");
  return ok({ estimate_id: estimateId, ...result });
}

export async function addObservationEvent(store: EngineStore, scenarioId: string, payload: Dict): Promise<ApiResponse> {
  const eventId = randomUUID();
  await store.recordEvent(eventId, scenarioId, get(payload, "event_type", "observation"), payload, get(payload, "operation_id"));
  return ok({ event_id: eventId, scenario_id: scenarioId, status: "recorded" }, 201);
}

void pyEq;
void compareEngines;
