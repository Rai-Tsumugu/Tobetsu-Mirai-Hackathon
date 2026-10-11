// 架空のデモデータを入れる。数値・ID・価格はすべて3システムの Simulator と同じ架空値。
// 何度実行しても同じ状態になる（登録済みのものは足さない）。
import { readFile } from "node:fs/promises";
import path from "node:path";
import { queryOne, transaction, type PoolLike, type Transaction } from "./queryable";
import * as items from "./repositories/items";
import * as manHours from "./repositories/man-hours";
import * as masters from "./repositories/masters";
import * as quotes from "./repositories/quotes";
import type { JsonObject } from "./types";

const DEMO_DATE = "2026-10-11";

type RateOp = { name: string; per: string; low: number; typical: number; high: number };
type CatalogJob = {
  name: string;
  base_labor_hours: number;
  basis_unit: string;
  basis_source: string;
  included_operations: { op: string; name: string; hours: number; shared?: boolean }[];
  tire_carry?: { op: string } & JsonObject;
  sides?: JsonObject;
  work_areas: string[];
};
type HistoricalRecord = {
  id: string;
  date: string;
  body: string;
  drive: string;
  age_years: number;
  km: number;
  brake_rust: number;
  jobs: string[];
  estimate: number;
  actual: number;
  same_vehicle?: boolean;
  tags: Record<string, { hours: number; count?: number }>;
};

async function readJson<T>(directory: string, file: string): Promise<T> {
  return JSON.parse(await readFile(path.join(directory, file), "utf8")) as T;
}

/** 和暦の「平成26年1月」を "2014-01" にする。 */
function warekiToMonth(text: string): string {
  const eras: Record<string, number> = { 令和: 2019, 平成: 1989, 昭和: 1926 };
  const match = /^(令和|平成|昭和)(\d+|元)年(\d+)月$/.exec(text);
  if (!match) {
    throw new Error(`初度登録年月を読めません: ${text}`);
  }
  const year = eras[match[1]] + (match[2] === "元" ? 1 : Number(match[2])) - 1;
  return `${year}-${match[3].padStart(2, "0")}`;
}

/**
 * @param manHoursDataDir src/30-algorithm/integrated/data（工数エンジンの架空データ）
 */
export async function seedDemoData(db: PoolLike, manHoursDataDir: string): Promise<void> {
  const shopParams = await readJson<JsonObject & { version: string; provisional_rates_v1: { ops: Record<string, RateOp> } }>(
    manHoursDataDir,
    "shop_params.json",
  );
  const catalog = await readJson<{ version: string; jobs: Record<string, CatalogJob> }>(manHoursDataDir, "job_catalog.json");
  const records = await readJson<{
    historical_records: HistoricalRecord[];
    tap_logs: Record<string, { step: string; persons: number; hours: number; wait?: boolean }[]>;
    vehicle_history: { vehicle_key: string; record_id: string; date: string; odometer_km: number; observed: JsonObject }[];
    other_shops: Record<string, Record<string, { median: number; n: number }>>;
    other_shop_tag_to_op: Record<string, string>;
  }>(manHoursDataDir, "records.json");
  const caseExample = await readJson<JsonObject & {
    case_id: string;
    e_shakensho: Record<string, string>;
    vehicle: JsonObject & { model: string; drive: string; body_class: string };
    intake: { date: string };
    jobs: string[];
  }>(manHoursDataDir, "case_example.json");

  await transaction(db, async (tx) => {
    for (const staff of [
      { staffCode: "架空デモ担当", displayName: "架空デモ担当" },
      { staffCode: "operator-demo-01", displayName: "架空: 見積担当" },
      { staffCode: "mechanic-demo-01", displayName: "架空: 整備士" },
    ]) {
      await masters.upsertStaff(tx, { ...staff, isSimulator: true });
    }

    await seedManHours(tx, shopParams, catalog, records, caseExample);
    await seedItems(tx);
    await seedQuotes(tx);
  });
}

async function seedManHours(
  tx: Transaction,
  shopParams: JsonObject & { version: string; provisional_rates_v1: { ops: Record<string, RateOp> } },
  catalog: { version: string; jobs: Record<string, CatalogJob> },
  records: {
    historical_records: HistoricalRecord[];
    tap_logs: Record<string, { step: string; persons: number; hours: number; wait?: boolean }[]>;
    vehicle_history: { vehicle_key: string; record_id: string; date: string; odometer_km: number; observed: JsonObject }[];
    other_shops: Record<string, Record<string, { median: number; n: number }>>;
    other_shop_tag_to_op: Record<string, string>;
  },
  caseExample: JsonObject & {
    case_id: string;
    e_shakensho: Record<string, string>;
    vehicle: JsonObject & { model: string; drive: string; body_class: string };
    intake: { date: string };
    jobs: string[];
  },
): Promise<void> {
  const rateOps = shopParams.provisional_rates_v1.ops;
  for (const [code, op] of Object.entries(rateOps)) {
    await masters.upsertOperation(tx, { operationCode: code, name: op.name, perUnit: op.per });
  }
  for (const job of Object.values(catalog.jobs)) {
    for (const op of job.included_operations) {
      await masters.upsertOperation(tx, { operationCode: op.op, name: op.name, perUnit: null });
    }
    if (job.tire_carry) {
      await masters.upsertOperation(tx, { operationCode: job.tire_carry.op, name: "タイヤ運搬", perUnit: null });
    }
  }
  for (const [jobCode, job] of Object.entries(catalog.jobs)) {
    const attributes: JsonObject = {};
    if (job.tire_carry) attributes.tire_carry = job.tire_carry;
    if (job.sides) attributes.sides = job.sides;
    await masters.upsertJob(tx, {
      jobCode,
      name: job.name,
      baseLaborHours: job.base_labor_hours,
      basisUnit: job.basis_unit,
      basisSource: job.basis_source,
      catalogVersion: catalog.version,
      workAreas: job.work_areas,
      attributes,
      operations: job.included_operations.map((op) => ({ operationCode: op.op, hours: op.hours, shared: op.shared ?? false })),
      isSimulator: true,
    });
  }

  if (!(await queryOne(tx, "SELECT 1 FROM shop_parameter_sets WHERE version = $1", [shopParams.version]))) {
    await manHours.saveShopParameters(tx, {
      version: shopParams.version,
      params: shopParams,
      makeCurrent: true,
      adoptedBy: "mechanic-demo-01",
      isSimulator: true,
    });
  }
  if (!(await queryOne(tx, "SELECT 1 FROM labor_rate_tables WHERE rate_table_code = 'v1'"))) {
    await manHours.createRateTable(tx, {
      rateTableCode: "v1",
      label: "整備士の暫定値",
      derivedFrom: `shop_params ${shopParams.version} provisional_rates_v1`,
      entries: Object.entries(rateOps).map(([code, op]) => ({
        operationCode: code,
        perUnit: op.per,
        hours: { low: op.low, typical: op.typical, high: op.high },
      })),
      isSimulator: true,
    });
    await manHours.adoptRateTable(tx, "v1", "mechanic-demo-01");
  }

  // 今回の見積もり対象の車両（電子車検証の型式と初度登録年月から vehicle_key を作る）
  const vehicleRef = `V-${caseExample.case_id}`;
  await masters.upsertVehicle(tx, {
    vehicleRef,
    modelCode: caseExample.e_shakensho["型式"],
    firstRegisteredMonth: warekiToMonth(caseExample.e_shakensho["初度登録年月"]),
    modelName: caseExample.vehicle.model,
    drive: caseExample.vehicle.drive,
    bodyClass: caseExample.vehicle.body_class,
    isSimulator: true,
  });

  for (const record of records.historical_records) {
    if (await queryOne(tx, "SELECT 1 FROM work_records WHERE record_code = $1", [record.id])) continue;
    await manHours.recordWorkRecord(tx, {
      recordCode: record.id,
      performedMonth: record.date,
      bodyClass: record.body,
      drive: record.drive,
      ageYears: record.age_years,
      odometerKm: record.km,
      brakeRustGrade: record.brake_rust,
      estimatedHours: record.estimate,
      actualHours: record.actual,
      isSameVehicle: record.same_vehicle ?? false,
      jobCodes: record.jobs,
      tags: record.tags,
      processLogs: records.tap_logs[record.id] ?? [],
      isSimulator: true,
    });
  }

  if (!(await queryOne(tx, "SELECT 1 FROM vehicle_observations LIMIT 1"))) {
    for (const history of records.vehicle_history) {
      await manHours.addVehicleObservation(tx, {
        vehicleKey: history.vehicle_key,
        recordCode: history.record_id,
        observedMonth: history.date,
        odometerKm: history.odometer_km,
        observed: history.observed,
      });
    }
  }

  for (const [shopCode, metrics] of Object.entries(records.other_shops)) {
    for (const [metric, value] of Object.entries(metrics)) {
      await manHours.upsertPeerBenchmark(tx, {
        shopCode,
        metric,
        operationCode: records.other_shop_tag_to_op[metric] ?? null,
        medianHours: value.median,
        sampleCount: value.n,
        isSimulator: true,
      });
    }
  }

  if (!(await queryOne(tx, "SELECT 1 FROM estimate_cases WHERE case_id = $1", [caseExample.case_id]))) {
    await manHours.saveEstimateCase(tx, {
      caseId: caseExample.case_id,
      vehicleRef,
      intakeDate: caseExample.intake.date,
      inputs: caseExample,
      jobCodes: caseExample.jobs,
      createdBy: "mechanic-demo-01",
      isSimulator: true,
    });
  }
}

async function seedItems(tx: Transaction): Promise<void> {
  // auto_repair_items の seed_demo と同じ架空塗料（仕入80円・販売120円 / ml）
  if ((await items.listPriceVersions(tx, { itemCode: "demo-paint" })).length > 0) return;
  for (const [priceType, unitPrice] of [
    ["仕入", "80"],
    ["販売", "120"],
  ] as const) {
    await items.registerItemPrice(tx, {
      item: { itemCode: "demo-paint", name: "架空サンプル塗料", category: "塗料", unit: "ml" },
      unitPrice,
      priceType,
      source: "simulator:架空値",
      updatedOn: DEMO_DATE,
      confirmedBy: "架空デモ担当",
      reason: "初回登録",
    });
  }
}

async function seedQuotes(tx: Transaction): Promise<void> {
  // auto_repair_quote の fixtures（demo_inputs / demo_presets）と同じ架空値
  await masters.ensureCustomer(tx, "C-DEMO-01", true);
  await masters.upsertVehicle(tx, { vehicleRef: "V-DEMO-01", isSimulator: true });
  if (!(await masters.getJob(tx, "JOB-DEMO-01"))) {
    await masters.upsertJob(tx, { jobCode: "JOB-DEMO-01", name: "架空: ブレーキ整備", isSimulator: true });
  }
  if ((await items.listPriceVersions(tx, { itemCode: "SIM-PART-001" })).length === 0) {
    await items.registerItemPrice(tx, {
      item: { itemCode: "SIM-PART-001", name: "架空: 販売部品", category: "部品", unit: "個" },
      unitPrice: 1000,
      priceType: "販売",
      source: "simulator",
      updatedOn: DEMO_DATE,
      confirmedBy: "operator-demo-01",
      reason: "初回登録",
    });
  }
  if ((await quotes.searchJobPresets(tx)).some((preset) => preset.presetId === "PRESET-DEMO-01")) return;
  await quotes.saveJobPreset(tx, {
    presetId: "PRESET-DEMO-01",
    version: 1,
    jobCode: "JOB-DEMO-01",
    name: "架空: ブレーキ整備",
    aliases: [
      { alias: "ブレーキ", approved_by: "operator-demo-01" },
      { alias: "パッド", approved_by: "operator-demo-01" },
    ],
    requiredConditions: [],
    inputs: {
      customer_ref: "C-DEMO-01",
      vehicle_ref: "V-DEMO-01",
      job_ref: "JOB-DEMO-01",
      labor: {
        person_hours: { low: 1, typical: 1.5, high: 2.5 },
        elapsed_hours: { low: 1, typical: 3, high: 5 },
        breakdown: [
          {
            operation: "架空: デモ作業",
            hours: { low: 1, typical: 1.5, high: 2.5 },
            reason: "架空: 現車確認前のデモ条件",
            status: "proposed",
          },
        ],
        unknowns: [],
      },
      labor_rate: {
        yen_per_person_hour: 8000,
        rate_ref: "RATE-DEMO-01",
        effective_from: "2026-10-01",
        basis: [{ label: "架空: デモ設定", value: 8000, unit: "円/人時" }],
      },
      items: [
        {
          item_id: "SIM-PART-001",
          name: "架空: 販売部品",
          category: "部品",
          unit: "個",
          unit_price: 1000,
          price_type: "販売",
          source: "simulator",
          updated_at: DEMO_DATE,
          quantity_range: { low: 1, typical: 1, high: 1 },
          quantity_unit: "個",
        },
      ],
      tax_policy: { source: "simulator", rate: 0.1, rounding: "floor" },
    },
    defaultQuantity: 1,
    rateRef: "RATE-DEMO-01",
    itemCodes: ["SIM-PART-001"],
    source: "simulator",
    approvedBy: "operator-demo-01",
    updatedOn: DEMO_DATE,
  });
}
