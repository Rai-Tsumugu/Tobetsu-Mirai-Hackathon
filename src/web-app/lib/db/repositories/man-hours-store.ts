// 工数エンジン（lib/systems/man-hours）へ渡すデータの取り出しと、計算結果・補正表の承認の保存。
//
// DB に置く（作業のたびに増える・工場や整備士の承認で変わる・履歴を残す）:
//   工場パラメータの現行版 / 作業実績・工程ログ / 同一車両の観察 / 他工場の参照値 / 採用中の補正表 / 今回の入力 / 計算結果
// JSON に置く（アプリと一緒に版管理する。lib/systems/man-hours/json-data.ts）:
//   基準工数（job_catalog.json。DB の jobs には工程名などの全項目がない）
//   DB が使えないときの全データ（デモ・ローカル確認・テストの入力。元の Python 版の data/ と同じ架空値）
//
// サーバー側専用。画面やクライアントコンポーネントから import しない。

import { DataValidationError } from "../errors";
import { withDatabase } from "../client";
import { queryOne, queryRows, transaction, type Database, type Queryable } from "../queryable";
import * as C from "../../systems/man-hours/constants";
import { buildRateTables, estimateSafely } from "../../systems/man-hours/estimator";
import {
  loadCatalog,
  loadJsonData,
  REFERENCE_CASE,
  REFERENCE_PARAMS,
  REFERENCE_RECORDS,
} from "../../systems/man-hours/json-data";
import { restoreKeyOrder } from "../../systems/man-hours/key-order";
import type { Obj } from "../../systems/man-hours/python-compat";
import * as manHours from "./man-hours";

export type EngineData = { case: Obj; params: Obj; catalog: Obj; records: Obj };
export type DataSource = "database" | "json";
export type Reference = { params: Obj; records: Obj; catalog: Obj; source: DataSource; fallbackReason?: string };

type ProcessLogRow = { recordCode: string; step: string; persons: number; hours: string; isWait: boolean };
type ObservationRow = { vehicleKey: string; recordCode: string; observedMonth: string; odometerKm: number; observed: Obj };

/** DB の作業実績・工程ログ・観察・他工場の値を、エンジンの records の形に組み立てる。 */
export async function loadRecordsFromDatabase(db: Queryable): Promise<Obj> {
  const workRecords = await manHours.listWorkRecords(db);
  const logs = await queryRows<ProcessLogRow>(
    db,
    `SELECT record_code AS "recordCode", step, persons, hours::text AS hours, is_wait AS "isWait"
       FROM process_logs ORDER BY record_code, seq`,
  );
  const observations = await queryRows<ObservationRow>(
    db,
    `SELECT vehicle_key AS "vehicleKey", record_code AS "recordCode", to_char(observed_month, 'YYYY-MM') AS "observedMonth",
            odometer_km AS "odometerKm", observed
       FROM vehicle_observations ORDER BY observed_month, observation_id`,
  );
  const peers = await manHours.listPeerBenchmarks(db);

  const tapLogs: Obj = {};
  for (const log of logs) {
    const steps: Obj[] = tapLogs[log.recordCode] ?? [];
    steps.push({ step: log.step, persons: log.persons, hours: Number(log.hours), ...(log.isWait ? { wait: true } : {}) });
    tapLogs[log.recordCode] = steps;
  }
  const otherShops: Obj = {};
  const otherShopTagToOp: Record<string, string> = {};
  for (const peer of peers) {
    otherShops[peer.shopCode] = {
      ...(otherShops[peer.shopCode] ?? {}),
      [peer.metric]: { median: Number(peer.medianHours), n: peer.sampleCount },
    };
    if (peer.operationCode) {
      otherShopTagToOp[peer.metric] = peer.operationCode;
    }
  }
  const built: Obj = {
    historical_records: workRecords.map((record) => ({
      id: record.recordCode,
      date: record.performedMonth,
      body: record.bodyClass,
      drive: record.drive,
      age_years: record.ageYears,
      km: record.odometerKm,
      brake_rust: record.brakeRustGrade,
      jobs: record.jobCodes,
      estimate: Number(record.estimatedHours),
      actual: Number(record.actualHours),
      same_vehicle: record.isSameVehicle,
      tags: Object.fromEntries(
        Object.entries(record.tags).map(([tag, value]) => [
          tag,
          { hours: Number(value.hours), ...(value.count === null ? {} : { count: value.count }) },
        ]),
      ),
    })),
    tap_logs: tapLogs,
    vehicle_history: observations.map((o) => ({
      vehicle_key: o.vehicleKey,
      record_id: o.recordCode,
      date: o.observedMonth,
      odometer_km: o.odometerKm,
      observed: o.observed,
    })),
    other_shops: otherShops,
    other_shop_tag_to_op: otherShopTagToOp,
  };
  return restoreKeyOrder(built, REFERENCE_RECORDS);
}

/**
 * DB の現行パラメータ・採用中の補正表・実績を読む。
 * 現行のパラメータがなければエラー（黙って JSON に切り替えない。切り替えは loadReference が行う）。
 */
export async function loadReferenceFromDatabase(db: Queryable): Promise<Reference> {
  const current = await manHours.getCurrentShopParameters(db);
  if (!current) {
    throw new DataValidationError("shop_parameter_sets: 現行の工場パラメータがありません");
  }
  const params: Obj = restoreKeyOrder(structuredClone(current.params), REFERENCE_PARAMS);
  // 補正表の採用は整備士の承認（labor_rate_tables）で決まる。エンジンが知っている版のときだけ反映する
  const adopted = await manHours.getRateTable(db);
  if (adopted && C.RATE_TABLES.includes(adopted.rateTableCode)) {
    params.adopted_rate_table = adopted.rateTableCode;
  }
  return { params, records: await loadRecordsFromDatabase(db), catalog: loadCatalog(), source: "database" };
}

/** 保存済みの今回の入力（estimate_cases）に、DB の参照データを組み合わせて読む。 */
export async function loadFromDatabase(db: Queryable, caseId: string): Promise<EngineData> {
  const saved = await manHours.getEstimateCase(db, caseId);
  if (!saved) {
    throw new DataValidationError(`case_id: 見積もり入力 ${caseId} がありません`);
  }
  const reference = await loadReferenceFromDatabase(db);
  return { case: restoreKeyOrder(structuredClone(saved.inputs) as Obj, REFERENCE_CASE), ...reference };
}

/**
 * 計算に使う参照データ。DB が設定され、現行パラメータが読めればそれを使い、
 * 設定がない・接続できない・まだ投入されていないときは同梱の JSON で計算する（理由を fallbackReason に残す）。
 */
export async function loadReference(): Promise<Reference> {
  const json = (reason: string): Reference => {
    const data = loadJsonData();
    return { params: data.params, records: data.records, catalog: data.catalog, source: "json", fallbackReason: reason };
  };
  if (!process.env.DATABASE_URL) {
    return json("DATABASE_URL が設定されていないため、同梱のデータで計算しました");
  }
  try {
    return await withDatabase((db) => loadReferenceFromDatabase(db));
  } catch (error) {
    const detail = error instanceof DataValidationError ? error.message : "DB に接続できません";
    return json(`${detail}。同梱のデータで計算しました`);
  }
}

/** DB の参照データで計算する。DB が使えなければエラー（保存・承認はこちらを使う）。 */
async function requireDatabaseReference(db: Queryable): Promise<Reference> {
  try {
    return await loadReferenceFromDatabase(db);
  } catch (error) {
    if (error instanceof DataValidationError) {
      throw new DataValidationError(`${error.message}。先に npm run db:migrate と npm run db:seed を実行してください`);
    }
    throw error;
  }
}

// ---- 入力と計算結果の保存 ----

/** 入力の保存（同じ case_id は上書き）。作業は DB の jobs に登録されているものだけ。 */
async function saveCase(db: Database, caseData: Obj, createdBy: string | null): Promise<string> {
  const caseId = caseData.case_id;
  if (typeof caseId !== "string" || caseId.trim() === "") {
    throw new DataValidationError("case_id: 入力が必要です");
  }
  await transaction(db, async (tx) => {
    await tx.query(
      `INSERT INTO estimate_cases (case_id, intake_date, inputs, created_by) VALUES ($1, $2, $3, $4)
       ON CONFLICT (case_id) DO UPDATE SET intake_date = EXCLUDED.intake_date, inputs = EXCLUDED.inputs`,
      [caseId, caseData.intake.date, caseData, createdBy],
    );
    await tx.query("DELETE FROM case_jobs WHERE case_id = $1", [caseId]);
    for (const jobCode of caseData.jobs as string[]) {
      await tx.query("INSERT INTO case_jobs (case_id, job_code) VALUES ($1, $2)", [caseId, jobCode]);
    }
  });
  return caseId;
}

/**
 * 入力を保存し、DB の参照データで計算して、結果を man_hour_estimates に追記する。
 * 結果は提案で、確定は整備士・見積もり担当者が行う。
 */
export async function estimateAndSave(
  db: Database,
  caseData: Obj,
  options: { createdBy?: string | null } = {},
): Promise<{ estimateId: string; result: Obj }> {
  const reference = await requireDatabaseReference(db);
  const result = estimateSafely(caseData, reference.params, reference.catalog, reference.records);
  return transaction(db, async (tx) => {
    const caseId = await saveCase(tx, caseData, options.createdBy ?? null);
    const estimateId = await manHours.saveManHourEstimate(tx, {
      caseId,
      parameterVersion: reference.params.version,
      rateTableCode: result.estimate.rate_table,
      catalogVersion: reference.catalog.version,
      personHours: result.estimate.labor_hours,
      elapsedHours: result.estimate.elapsed_hours,
      result,
      createdBy: options.createdBy ?? null,
    });
    return { estimateId, result };
  });
}

/** 保存済みの最新の計算結果。なければ undefined。 */
export async function getSavedEstimate(db: Queryable, caseId: string) {
  return manHours.getLatestManHourEstimate(db, caseId);
}

// ---- 補正表の承認 ----

export type RateTableRow = { rateTableCode: string; label: string | null; status: string; approvedBy: string | null };

export async function listRateTables(db: Queryable): Promise<RateTableRow[]> {
  return queryRows<RateTableRow>(
    db,
    `SELECT rate_table_code AS "rateTableCode", label, status, approved_by AS "approvedBy"
       FROM labor_rate_tables ORDER BY rate_table_code`,
  );
}

/**
 * 補正表の版を採用する（整備士の承認）。
 * DB にまだない版（実績から作った v2 の候補など）は、現在の参照データから候補として作ってから採用する。
 * すでにある版は作り直さない（版は変えずに残す。計算結果がどの版で出たかを辿れるように）。
 */
export async function approveRateTable(
  db: Database,
  rateTableCode: string,
  approvedBy: string,
): Promise<{ adopted: string; created: boolean }> {
  if (!C.RATE_TABLES.includes(rateTableCode)) {
    throw new DataValidationError(`rate_table: 採用できる版は ${C.RATE_TABLES.join("・")} です（${rateTableCode}）`);
  }
  if (typeof approvedBy !== "string" || approvedBy.trim() === "") {
    throw new DataValidationError("approved_by: 承認者を入力してください");
  }
  const approver = approvedBy.trim();
  const staff = await queryOne(db, "SELECT 1 FROM staff WHERE staff_code = $1", [approver]);
  if (!staff) {
    throw new DataValidationError(`approved_by: 承認者 ${approver} が登録されていません`);
  }
  const reference = await requireDatabaseReference(db);
  return transaction(db, async (tx) => {
    const existing = await queryOne(tx, "SELECT 1 FROM labor_rate_tables WHERE rate_table_code = $1", [rateTableCode]);
    let created = false;
    if (!existing) {
      const tables = buildRateTables(reference.params, reference.records);
      const rates: Obj = rateTableCode === C.RATE_TABLE_V1 ? tables.v1 : tables.v2;
      await manHours.createRateTable(tx, {
        rateTableCode,
        label:
          rateTableCode === C.RATE_TABLE_V1
            ? "整備士の暫定値"
            : `実績から作った候補（実績 ${reference.records.historical_records.length} 件）`,
        derivedFrom: `shop_params ${reference.params.version}`,
        entries: Object.entries<Obj>(rates).map(([operationCode, rate]) => ({
          operationCode,
          perUnit: rate.per ?? null,
          hours: { low: rate.low, typical: rate.typical, high: rate.high },
        })),
      });
      created = true;
    }
    await manHours.adoptRateTable(tx, rateTableCode, approver);
    return { adopted: rateTableCode, created };
  });
}
