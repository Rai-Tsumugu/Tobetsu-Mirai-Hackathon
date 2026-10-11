// 工数見積もり: 工場パラメータ・補正表・作業実績・今回の入力・計算結果。
import { DataValidationError, requireDecimal, requireText } from "../errors";
import { queryOne, queryRows, transaction, type Database, type Queryable } from "../queryable";
import type { BandRange, DecimalInput, DecimalString, JsonObject } from "../types";
import { monthToDate } from "./masters";

// ---- 工場パラメータ ----

export type ShopParameterSet = { version: string; params: JsonObject; isCurrent: boolean; adoptedBy: string | null };

/** 工場パラメータの版を保存する。makeCurrent なら、それまでの現行版を外してこの版を現行にする。 */
export async function saveShopParameters(
  db: Database,
  input: { version: string; params: JsonObject; makeCurrent?: boolean; adoptedBy?: string | null; isSimulator?: boolean },
): Promise<void> {
  const version = requireText(input.version, "version");
  await transaction(db, async (tx) => {
    if (input.makeCurrent) {
      await tx.query("UPDATE shop_parameter_sets SET is_current = false WHERE is_current");
    }
    await tx.query(
      `INSERT INTO shop_parameter_sets (version, params, is_current, adopted_by, is_simulator) VALUES ($1, $2, $3, $4, $5)`,
      [version, input.params, input.makeCurrent ?? false, input.adoptedBy ?? null, input.isSimulator ?? false],
    );
  });
}

export async function getCurrentShopParameters(db: Queryable): Promise<ShopParameterSet | undefined> {
  return queryOne<ShopParameterSet>(
    db,
    `SELECT version, params, is_current AS "isCurrent", adopted_by AS "adoptedBy"
       FROM shop_parameter_sets WHERE is_current`,
  );
}

// ---- 補正表 ----

export type RateEntry = {
  operationCode: string;
  perUnit: string | null;
  hours: BandRange;
  sampleCount: number | null;
};
export type RateEntryInput = {
  operationCode: string;
  perUnit?: string | null;
  hours: BandRange<DecimalInput>;
  sampleCount?: number | null;
};
export type RateTable = {
  rateTableCode: string;
  label: string | null;
  status: "candidate" | "adopted" | "retired";
  derivedFrom: string | null;
  approvedBy: string | null;
  entries: RateEntry[];
};

/** 補正表を候補として作る。実績から作った候補は自動では使わず、adoptRateTable で承認する。 */
export async function createRateTable(
  db: Database,
  input: { rateTableCode: string; label?: string | null; derivedFrom?: string | null; entries: RateEntryInput[]; isSimulator?: boolean },
): Promise<void> {
  const code = requireText(input.rateTableCode, "rate_table_code");
  if (input.entries.length === 0) {
    throw new DataValidationError("entries: 工程の補正値を1件以上指定してください");
  }
  await transaction(db, async (tx) => {
    await tx.query(
      `INSERT INTO labor_rate_tables (rate_table_code, label, status, derived_from, is_simulator) VALUES ($1, $2, 'candidate', $3, $4)`,
      [code, input.label ?? null, input.derivedFrom ?? null, input.isSimulator ?? false],
    );
    for (const entry of input.entries) {
      await tx.query(
        `INSERT INTO labor_rate_entries (rate_table_code, operation_code, per_unit, hours_low, hours_typical, hours_high, sample_count)
         VALUES ($1, $2, $3, $4, $5, $6, $7)`,
        [
          code,
          requireText(entry.operationCode, "operation_code"),
          entry.perUnit ?? null,
          requireDecimal(entry.hours.low, "hours.low"),
          requireDecimal(entry.hours.typical, "hours.typical"),
          requireDecimal(entry.hours.high, "hours.high"),
          entry.sampleCount ?? null,
        ],
      );
    }
  });
}

/** 整備士の承認で補正表を採用する。それまでの採用版は retired になる（同時に採用できるのは1つ）。 */
export async function adoptRateTable(db: Database, rateTableCode: string, approvedBy: string): Promise<void> {
  const code = requireText(rateTableCode, "rate_table_code");
  const approver = requireText(approvedBy, "approved_by");
  await transaction(db, async (tx) => {
    const target = await queryOne<{ status: string }>(
      tx,
      "SELECT status FROM labor_rate_tables WHERE rate_table_code = $1 FOR UPDATE",
      [code],
    );
    if (!target) {
      throw new DataValidationError(`rate_table_code: 補正表 ${code} がありません`);
    }
    if (target.status === "adopted") {
      return;
    }
    await tx.query("UPDATE labor_rate_tables SET status = 'retired' WHERE status = 'adopted'");
    await tx.query(
      "UPDATE labor_rate_tables SET status = 'adopted', approved_by = $2, approved_at = now() WHERE rate_table_code = $1",
      [code, approver],
    );
  });
}

/** 補正表を返す。コードを省くと採用中の版。 */
export async function getRateTable(db: Queryable, rateTableCode?: string): Promise<RateTable | undefined> {
  return queryOne<RateTable>(
    db,
    `SELECT t.rate_table_code AS "rateTableCode", t.label, t.status, t.derived_from AS "derivedFrom",
            t.approved_by AS "approvedBy",
            COALESCE(
              (SELECT json_agg(json_build_object(
                        'operationCode', e.operation_code, 'perUnit', e.per_unit, 'sampleCount', e.sample_count,
                        'hours', json_build_object('low', e.hours_low::text, 'typical', e.hours_typical::text, 'high', e.hours_high::text))
                      ORDER BY e.operation_code)
                 FROM labor_rate_entries e WHERE e.rate_table_code = t.rate_table_code),
              '[]'
            ) AS entries
       FROM labor_rate_tables t
      WHERE ($1::text IS NULL AND t.status = 'adopted') OR t.rate_table_code = $1`,
    [rateTableCode ?? null],
  );
}

// ---- 作業実績 ----

export type WorkRecordInput = {
  recordCode: string;
  /** 作業月 "YYYY-MM" */
  performedMonth: string;
  vehicleRef?: string | null;
  bodyClass?: string | null;
  drive?: string | null;
  ageYears?: number | null;
  odometerKm?: number | null;
  brakeRustGrade?: number | null;
  estimatedHours: DecimalInput;
  actualHours: DecimalInput;
  isSameVehicle?: boolean;
  jobCodes: string[];
  /** 原因タグ → 人時と本数（入庫1回単位のタグは count を省く） */
  tags?: Record<string, { hours: DecimalInput; count?: number | null }>;
  /** wait=true は作業者を拘束しない待機（0人で記録する） */
  processLogs?: { step: string; persons: number; hours: DecimalInput; wait?: boolean }[];
  isSimulator?: boolean;
};

export async function recordWorkRecord(db: Database, record: WorkRecordInput): Promise<void> {
  const code = requireText(record.recordCode, "record_code");
  await transaction(db, async (tx) => {
    await tx.query(
      `INSERT INTO work_records (record_code, vehicle_ref, performed_month, body_class, drive, age_years, odometer_km,
                                 brake_rust_grade, estimated_hours, actual_hours, is_same_vehicle, is_simulator)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
      [
        code,
        record.vehicleRef ?? null,
        monthToDate(record.performedMonth, "performed_month"),
        record.bodyClass ?? null,
        record.drive ?? null,
        record.ageYears ?? null,
        record.odometerKm ?? null,
        record.brakeRustGrade ?? null,
        requireDecimal(record.estimatedHours, "estimated_hours"),
        requireDecimal(record.actualHours, "actual_hours"),
        record.isSameVehicle ?? false,
        record.isSimulator ?? false,
      ],
    );
    for (const jobCode of record.jobCodes) {
      await tx.query("INSERT INTO work_record_jobs (record_code, job_code) VALUES ($1, $2)", [code, jobCode]);
    }
    for (const [tag, value] of Object.entries(record.tags ?? {})) {
      await tx.query("INSERT INTO work_record_tags (record_code, tag, hours, count) VALUES ($1, $2, $3, $4)", [
        code,
        tag,
        requireDecimal(value.hours, `tags.${tag}.hours`),
        value.count ?? null,
      ]);
    }
    for (const [index, log] of (record.processLogs ?? []).entries()) {
      await tx.query(
        "INSERT INTO process_logs (record_code, seq, step, persons, hours, is_wait) VALUES ($1, $2, $3, $4, $5, $6)",
        [code, index + 1, requireText(log.step, "step"), log.persons, requireDecimal(log.hours, "hours"), log.wait ?? false],
      );
    }
  });
}

export type WorkRecord = {
  recordCode: string;
  performedMonth: string;
  vehicleRef: string | null;
  bodyClass: string | null;
  drive: string | null;
  ageYears: number | null;
  odometerKm: number | null;
  brakeRustGrade: number | null;
  estimatedHours: DecimalString;
  actualHours: DecimalString;
  isSameVehicle: boolean;
  jobCodes: string[];
  tags: Record<string, { hours: DecimalString; count: number | null }>;
};

export async function listWorkRecords(db: Queryable): Promise<WorkRecord[]> {
  return queryRows<WorkRecord>(
    db,
    `SELECT r.record_code AS "recordCode", to_char(r.performed_month, 'YYYY-MM') AS "performedMonth",
            r.vehicle_ref AS "vehicleRef", r.body_class AS "bodyClass", r.drive, r.age_years AS "ageYears",
            r.odometer_km AS "odometerKm", r.brake_rust_grade AS "brakeRustGrade",
            r.estimated_hours::text AS "estimatedHours", r.actual_hours::text AS "actualHours",
            r.is_same_vehicle AS "isSameVehicle",
            COALESCE((SELECT array_agg(j.job_code ORDER BY j.job_code) FROM work_record_jobs j WHERE j.record_code = r.record_code), '{}') AS "jobCodes",
            COALESCE((SELECT json_object_agg(t.tag, json_build_object('hours', t.hours::text, 'count', t.count))
                        FROM work_record_tags t WHERE t.record_code = r.record_code), '{}') AS tags
       FROM work_records r
      ORDER BY r.performed_month, r.record_code`,
  );
}

export type TagSampleSummary = {
  tag: string;
  sampleCount: number;
  perUnitHours: BandRange<DecimalString> & { values: DecimalString[] };
};

/**
 * 原因タグごとに「1単位あたりの人時」を集める（count があれば count で割る）。
 * 件数が minRecords 以上のタグだけ、最小・中央値・最大を返す。補正表の候補（v2）づくりに使う。
 * 同一車両の実績も含める（工程の単価として使う値で、車全体の状態の代表ではないため）。
 */
export async function summarizeTagSamples(db: Queryable, minRecords: number): Promise<TagSampleSummary[]> {
  const rows = await queryRows<{ tag: string; values: string[] }>(
    db,
    `SELECT tag, array_agg(trim_scale(per_unit)::text ORDER BY per_unit) AS values
       FROM (SELECT tag, CASE WHEN count IS NULL THEN hours ELSE hours / count END AS per_unit FROM work_record_tags) samples
      GROUP BY tag HAVING count(*) >= $1 ORDER BY tag`,
    [minRecords],
  );
  return rows.map(({ tag, values }) => ({
    tag,
    sampleCount: values.length,
    perUnitHours: { low: values[0], typical: median(values), high: values[values.length - 1], values },
  }));
}

/** 昇順の10進数文字列の中央値。偶数件は中央2つの平均を、浮動小数点を通さずに出す。 */
function median(sortedValues: string[]): string {
  const middle = Math.floor(sortedValues.length / 2);
  if (sortedValues.length % 2 === 1) {
    return sortedValues[middle];
  }
  return averageDecimals(sortedValues[middle - 1], sortedValues[middle]);
}

function averageDecimals(a: string, b: string): string {
  const scale = Math.max(fractionDigits(a), fractionDigits(b)) + 1;
  const total = toScaled(a, scale) + toScaled(b, scale);
  const halved = total / BigInt(2); // scale を1桁増やしてあるので 2 で割り切れる
  const digits = halved.toString().padStart(scale + 1, "0");
  const integer = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale).replace(/0+$/, "");
  return fraction ? `${integer}.${fraction}` : integer;
}

function fractionDigits(value: string): number {
  return value.includes(".") ? value.split(".")[1].length : 0;
}

function toScaled(value: string, scale: number): bigint {
  const [integer, fraction = ""] = value.split(".");
  return BigInt(integer + fraction.padEnd(scale, "0"));
}

// ---- 同一車両の観察・他工場の実績 ----

export async function addVehicleObservation(
  db: Queryable,
  input: { vehicleKey: string; vehicleRef?: string | null; recordCode?: string | null; observedMonth: string; odometerKm?: number | null; observed: JsonObject },
): Promise<void> {
  await db.query(
    `INSERT INTO vehicle_observations (vehicle_key, vehicle_ref, record_code, observed_month, odometer_km, observed)
     VALUES ($1, $2, $3, $4, $5, $6)`,
    [
      requireText(input.vehicleKey, "vehicle_key"),
      input.vehicleRef ?? null,
      input.recordCode ?? null,
      monthToDate(input.observedMonth, "observed_month"),
      input.odometerKm ?? null,
      input.observed,
    ],
  );
}

export type VehicleObservation = {
  vehicleKey: string;
  recordCode: string | null;
  observedMonth: string;
  odometerKm: number | null;
  observed: JsonObject;
};

export async function listVehicleObservations(db: Queryable, vehicleKey: string): Promise<VehicleObservation[]> {
  return queryRows<VehicleObservation>(
    db,
    `SELECT vehicle_key AS "vehicleKey", record_code AS "recordCode", to_char(observed_month, 'YYYY-MM') AS "observedMonth",
            odometer_km AS "odometerKm", observed
       FROM vehicle_observations WHERE vehicle_key = $1 ORDER BY observed_month, observation_id`,
    [vehicleKey],
  );
}

export type PeerBenchmark = {
  shopCode: string;
  metric: string;
  operationCode: string | null;
  medianHours: DecimalString;
  sampleCount: number;
};

export async function upsertPeerBenchmark(
  db: Queryable,
  input: Omit<PeerBenchmark, "medianHours"> & { medianHours: DecimalInput; isSimulator?: boolean },
): Promise<void> {
  await db.query(
    `INSERT INTO peer_benchmarks (shop_code, metric, operation_code, median_hours, sample_count, is_simulator)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (shop_code, metric) DO UPDATE SET
       operation_code = EXCLUDED.operation_code, median_hours = EXCLUDED.median_hours, sample_count = EXCLUDED.sample_count`,
    [
      requireText(input.shopCode, "shop_code"),
      requireText(input.metric, "metric"),
      input.operationCode,
      requireDecimal(input.medianHours, "median_hours"),
      input.sampleCount,
      input.isSimulator ?? false,
    ],
  );
}

export async function listPeerBenchmarks(db: Queryable): Promise<PeerBenchmark[]> {
  return queryRows<PeerBenchmark>(
    db,
    `SELECT shop_code AS "shopCode", metric, operation_code AS "operationCode", median_hours::text AS "medianHours",
            sample_count AS "sampleCount"
       FROM peer_benchmarks ORDER BY shop_code, metric`,
  );
}

// ---- 今回の見積もり入力と計算結果 ----

export type EstimateCaseInput = {
  caseId: string;
  vehicleRef?: string | null;
  intakeDate: string;
  inputs: JsonObject;
  jobCodes: string[];
  createdBy?: string | null;
  isSimulator?: boolean;
};

export async function saveEstimateCase(db: Database, input: EstimateCaseInput): Promise<void> {
  const caseId = requireText(input.caseId, "case_id");
  if (input.jobCodes.length === 0) {
    throw new DataValidationError("jobs: 今回の作業を1件以上選択してください");
  }
  await transaction(db, async (tx) => {
    await tx.query(
      `INSERT INTO estimate_cases (case_id, vehicle_ref, intake_date, inputs, created_by, is_simulator)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [caseId, input.vehicleRef ?? null, requireText(input.intakeDate, "intake_date"), input.inputs, input.createdBy ?? null, input.isSimulator ?? false],
    );
    for (const jobCode of input.jobCodes) {
      await tx.query("INSERT INTO case_jobs (case_id, job_code) VALUES ($1, $2)", [caseId, jobCode]);
    }
  });
}

export type EstimateCase = {
  caseId: string;
  vehicleRef: string | null;
  intakeDate: string;
  inputs: JsonObject;
  jobCodes: string[];
};

export async function getEstimateCase(db: Queryable, caseId: string): Promise<EstimateCase | undefined> {
  return queryOne<EstimateCase>(
    db,
    `SELECT c.case_id AS "caseId", c.vehicle_ref AS "vehicleRef", c.intake_date::text AS "intakeDate", c.inputs,
            COALESCE((SELECT array_agg(j.job_code ORDER BY j.job_code) FROM case_jobs j WHERE j.case_id = c.case_id), '{}') AS "jobCodes"
       FROM estimate_cases c WHERE c.case_id = $1`,
    [caseId],
  );
}

export type ManHourEstimateInput = {
  caseId: string;
  parameterVersion: string;
  rateTableCode: string;
  catalogVersion?: string | null;
  personHours: BandRange<DecimalInput>;
  /** 待機を含む経過時間。表示用で、請求には使わない。 */
  elapsedHours?: BandRange<DecimalInput> | null;
  result: JsonObject;
  createdBy?: string | null;
};

export type ManHourEstimate = {
  estimateId: string;
  caseId: string;
  parameterVersion: string;
  rateTableCode: string;
  catalogVersion: string | null;
  personHours: BandRange;
  elapsedHours: BandRange | null;
  result: JsonObject;
  createdAt: string;
};

/** 計算結果を追記する。結果は変えず、計算し直したら新しい行になる。 */
export async function saveManHourEstimate(db: Queryable, input: ManHourEstimateInput): Promise<string> {
  const elapsed = input.elapsedHours;
  const row = await queryOne<{ estimateId: string }>(
    db,
    `INSERT INTO man_hour_estimates (case_id, parameter_version, rate_table_code, catalog_version,
                                     person_hours_low, person_hours_typical, person_hours_high,
                                     elapsed_hours_low, elapsed_hours_typical, elapsed_hours_high, result, created_by)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
     RETURNING estimate_id AS "estimateId"`,
    [
      requireText(input.caseId, "case_id"),
      requireText(input.parameterVersion, "parameter_version"),
      requireText(input.rateTableCode, "rate_table_code"),
      input.catalogVersion ?? null,
      requireDecimal(input.personHours.low, "person_hours.low"),
      requireDecimal(input.personHours.typical, "person_hours.typical"),
      requireDecimal(input.personHours.high, "person_hours.high"),
      elapsed ? requireDecimal(elapsed.low, "elapsed_hours.low") : null,
      elapsed ? requireDecimal(elapsed.typical, "elapsed_hours.typical") : null,
      elapsed ? requireDecimal(elapsed.high, "elapsed_hours.high") : null,
      input.result,
      input.createdBy ?? null,
    ],
  );
  return row!.estimateId;
}

export async function getLatestManHourEstimate(db: Queryable, caseId: string): Promise<ManHourEstimate | undefined> {
  return queryOne<ManHourEstimate>(
    db,
    `SELECT estimate_id AS "estimateId", case_id AS "caseId", parameter_version AS "parameterVersion",
            rate_table_code AS "rateTableCode", catalog_version AS "catalogVersion",
            json_build_object('low', person_hours_low::text, 'typical', person_hours_typical::text, 'high', person_hours_high::text) AS "personHours",
            CASE WHEN elapsed_hours_low IS NULL THEN NULL ELSE
              json_build_object('low', elapsed_hours_low::text, 'typical', elapsed_hours_typical::text, 'high', elapsed_hours_high::text) END AS "elapsedHours",
            result, created_at::text AS "createdAt"
       FROM man_hour_estimates WHERE case_id = $1
      ORDER BY created_at DESC, estimate_id DESC LIMIT 1`,
    [caseId],
  );
}
