// src/app-demo/backend/app.py の API の処理。保存先は SQLite ではなく Neon（0006_demo.sql の demo_* テーブル）。
// サーバー側専用。Route Handler（app/api/demo/）から接続を渡して呼ぶ。
import { createHash } from "node:crypto";
import { transaction, type Database, type Queryable } from "@/lib/db/queryable";
import * as gemini from "./gemini";
import { HttpError, pyCasefold, pyDumps, pySlice, pyStrip, pyUtcNow, uuidHex } from "./py";
import { JOBS, ensureRepairJobs, simulatorSources } from "./seed";
import type { EstimateCase, EstimateItem, ResearchRecord, ResearchTarget, SavedEstimate, Source, Vehicle } from "./types";
import { CaseInput, Estimate, ManualVehicle, Research, dump, validateBody, type Infer } from "./validation";

const TAX_RATE = 0.1;

async function rows<T>(db: Queryable, text: string, values?: unknown[]): Promise<T[]> {
  const result = await db.query(text, values);
  return (result.rows as { data: T }[]).map((row) => row.data);
}

// ---- 案件 ----

type CaseFields = Partial<EstimateCase>;

function newCase(fields: CaseFields, createdAt?: string): EstimateCase {
  const now = pyUtcNow();
  return {
    id: "CASE-" + uuidHex(),
    created_at: createdAt || now,
    updated_at: now,
    ...{ latest_estimate_id: null, recipient_name: "", phone_memo: "", vehicle_id: null, ...fields },
  } as EstimateCase;
}

function vehicleLabel(estimate: { vehicle: Vehicle }): string {
  const vehicle = estimate.vehicle;
  return `${vehicle.maker} ${vehicle.model} / ${vehicle.model_code}`;
}

function estimateTitle(estimate: { items: { name: string }[] }): string {
  return pySlice(estimate.items.map((item) => item.name).join("・"), 120);
}

async function caseById(db: Queryable, caseId: string): Promise<EstimateCase> {
  const [found] = await rows<EstimateCase>(db, "SELECT data FROM demo_cases WHERE id = $1", [caseId]);
  if (!found) throw new HttpError(404, "案件が見つかりません");
  return found;
}

async function caseFields(db: Queryable, input: Infer<typeof CaseInput>) {
  const fields = dump(input);
  fields.title = pyStrip(fields.title);
  if (!fields.title) throw new HttpError(422, "案件名を入力してください");
  fields.recipient_name = pyStrip(fields.recipient_name);
  fields.vehicle_label = pyStrip(fields.vehicle_label);
  if (input.vehicle_id !== null) {
    const selected = await vehicleById(db, input.vehicle_id);
    fields.vehicle_label = `${selected.maker} ${selected.model} / ${selected.model_code}`;
  }
  return fields as CaseFields & Record<string, unknown>;
}

async function writeCase(db: Queryable, data: EstimateCase, insert: boolean) {
  if (insert) {
    await db.query("INSERT INTO demo_cases (id, created_at, data) VALUES ($1, $2, $3)", [data.id, data.created_at, JSON.stringify(data)]);
  } else {
    await db.query("UPDATE demo_cases SET data = $2 WHERE id = $1", [data.id, JSON.stringify(data)]);
  }
}

export function listCases(db: Queryable): Promise<EstimateCase[]> {
  return rows(db, 'SELECT data FROM demo_cases ORDER BY created_at DESC, id COLLATE "C" DESC');
}

export async function createCase(db: Queryable, body: unknown): Promise<EstimateCase> {
  const input = validateBody(CaseInput, body);
  const created = newCase(await caseFields(db, input));
  await writeCase(db, created, true);
  return created;
}

export async function updateCase(db: Database, caseId: string, body: unknown): Promise<EstimateCase> {
  const input = validateBody(CaseInput, body);
  return transaction(db, async (tx) => {
    const current = await caseById(tx, caseId);
    const fields = await caseFields(tx, input);
    for (const name of ["recipient_name", "phone_memo", "vehicle_id"] as const) {
      if (!input.fieldsSet.has(name)) delete fields[name];
    }
    Object.assign(current, fields, { updated_at: pyUtcNow() });
    await writeCase(tx, current, false);
    return current;
  });
}

// ---- 車両・作業 ----

export async function vehicleById(db: Queryable, vehicleId: string): Promise<Vehicle> {
  const [found] = await rows<Vehicle>(db, "SELECT data FROM demo_vehicles WHERE id = $1", [vehicleId]);
  if (!found) throw new HttpError(404, "車両が見つかりません");
  return found;
}

export async function listVehicles(db: Queryable, query = "", origin = "all"): Promise<Vehicle[]> {
  const all = await rows<Vehicle>(db, "SELECT data FROM demo_vehicles ORDER BY position");
  const needle = pyStrip(pyCasefold(query));
  return all.filter(
    (v) => pyCasefold(v.maker + v.model + v.model_code).includes(needle) && (origin !== "live" || v.source_name !== "simulator"),
  );
}

export async function createManualVehicle(db: Queryable, body: unknown): Promise<Vehicle> {
  const input = validateBody(ManualVehicle, body);
  if (![input.maker, input.model, input.model_code, input.grade].every((s) => pyStrip(s))) {
    throw new HttpError(422, "車両情報を入力してください");
  }
  const data: Vehicle = {
    id: "manual-" + uuidHex().slice(0, 12),
    maker: pyStrip(input.maker),
    model: pyStrip(input.model),
    model_code: pyStrip(input.model_code),
    years: [input.year],
    grades: [pyStrip(input.grade)],
    length_mm: null,
    width_mm: null,
    height_mm: null,
    powertrain: "未確認",
    source_name: "manual",
    source_url: null,
    verified_at: null,
    note: "手入力の暫定登録。適合・諸元は未確認です。",
  };
  await db.query("INSERT INTO demo_vehicles (id, data) VALUES ($1, $2)", [data.id, JSON.stringify(data)]);
  return data;
}

export function repairJobs() {
  return JOBS;
}

export function config() {
  return { gemini_configured: gemini.configured(), gemini_model: gemini.MODEL };
}

async function validateContext(db: Queryable, vehicleId: string, year: number, grade: string, jobIds: string[]): Promise<Vehicle> {
  const vehicle = await vehicleById(db, vehicleId);
  if (!vehicle.years.includes(year) || !vehicle.grades.includes(grade)) throw new HttpError(422, "年式・仕様を選択してください");
  if (new Set(jobIds).size !== jobIds.length || jobIds.some((j) => !JOBS.some((job) => job.id === j))) {
    throw new HttpError(422, "作業が重複しているか、未登録の作業です");
  }
  return vehicle;
}

// ---- 参考価格 ----

/** 同じ条件の Gemini 調査は24時間 DB に保存して再利用する。 */
async function cachedInvestigation(
  db: Queryable,
  kind: string,
  target: ResearchTarget,
  schema: unknown,
  extract: (result: gemini.Investigation) => Record<string, Source[]>,
): Promise<ResearchRecord> {
  const cacheKey = createHash("sha256")
    .update(pyDumps({ kind, target, model: gemini.MODEL }, { sortKeys: true }))
    .digest("hex");
  const [cached] = await rows<ResearchRecord>(
    db,
    `SELECT data FROM demo_research_cache WHERE cache_key = $1 AND created_at > now() - interval '86400 seconds'
     ORDER BY created_at DESC LIMIT 1`,
    [cacheKey],
  );
  if (cached) return { ...cached, cached: true };
  const result = (await gemini.investigate(db, target, schema)) as gemini.Investigation & Partial<ResearchRecord>;
  const values = extract(result);
  delete (result as { data?: unknown }).data;
  Object.assign(result, { values, context: target, kind, research_id: uuidHex(), cached: false });
  result.warnings = [...new Set(result.warnings)];
  await db.query("INSERT INTO demo_research_cache (id, cache_key, data) VALUES ($1, $2, $3)", [
    result.research_id,
    cacheKey,
    JSON.stringify(result),
  ]);
  return result as unknown as ResearchRecord;
}

export async function priceResearch(db: Queryable, body: unknown) {
  const input = validateBody(Research, body);
  const vehicle = await validateContext(db, input.vehicle_id, input.year, input.grade, input.job_ids);
  const jobs = JOBS.filter((job) => input.job_ids.includes(job.id));
  if (input.mode === "simulator") return Object.fromEntries(jobs.map((job) => [job.id, simulatorSources(job)]));
  const target: ResearchTarget = {
    vehicle_id: vehicle.id,
    maker: vehicle.maker,
    model: vehicle.model,
    model_code: vehicle.model_code,
    year: input.year,
    grade: input.grade,
    jobs: jobs.map(({ id, name, description }) => ({ id, name, description })),
  };
  const result = await cachedInvestigation(db, "prices", target, gemini.PRICES_SCHEMA, (r) =>
    gemini.extractPrices(r, input.job_ids),
  );
  return { ...result, sources: result.values };
}

// ---- 見積もり ----

/** statistics.median の結果を int() にしたもの（偶数件は中央2件の平均の切り捨て）。 */
export function medianInt(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : Math.trunc((sorted[mid - 1] + sorted[mid]) / 2);
}

export async function saveEstimate(db: Database, body: unknown): Promise<SavedEstimate> {
  const input = validateBody(Estimate, body);
  const vehicle = await validateContext(db, input.vehicle_id, input.year, input.grade, input.items.map((i) => i.job_id));
  let research: Partial<ResearchRecord> = {};
  let liveSources: Record<string, Source[]> | null = null;
  if (input.mode === "live") {
    const [row] =
      input.research_id === null
        ? []
        : await rows<ResearchRecord>(db, "SELECT data FROM demo_research_cache WHERE id = $1", [input.research_id]);
    if (!row) throw new HttpError(422, "参照したWeb調査が見つかりません。再検索してください。");
    research = row;
    const context = row.context;
    const sameSet = (a: string[], b: string[]) => new Set(a).size === new Set(b).size && a.every((x) => b.includes(x));
    if (
      row.kind !== "prices" ||
      context.vehicle_id !== input.vehicle_id ||
      context.year !== input.year ||
      context.grade !== input.grade ||
      !sameSet(context.jobs.map((j) => j.id), input.items.map((i) => i.job_id)) ||
      !sameSet(context.winter_conditions ?? [], input.winter_conditions)
    ) {
      throw new HttpError(422, "Web調査時と車両・年式・仕様・作業・雪国条件が異なります。再検索してください。");
    }
    liveSources = row.values;
  } else if (input.research_id !== null) {
    throw new HttpError(422, "SimulatorにWeb調査を混ぜることはできません。");
  }
  const records: EstimateItem[] = [];
  for (const validated of input.items) {
    const item = dump(validated);
    const job = JOBS.find((j) => j.id === item.job_id)!;
    const sources = liveSources !== null ? liveSources[item.job_id] : simulatorSources(job);
    const ids = item.selected_source_ids;
    if (new Set(ids).size !== ids.length || ids.some((s) => !sources.some((p) => p.id === s))) {
      throw new HttpError(422, "参照候補を確認してください");
    }
    const labor = sources
      .filter((s) => ids.includes(s.id) && s.normalized_labor !== null)
      .map((s) => s.normalized_labor as number);
    const calculated = labor.length ? medianInt(labor) : null;
    if ((calculated === null || calculated !== item.labor_price) && !pyStrip(item.adjustment_reason)) {
      throw new HttpError(422, "工賃の手入力・調整理由を入力してください");
    }
    records.push({ ...item, name: job.name, category: job.category, calculated_labor_price: calculated, sources });
  }
  const subtotal = records.reduce((sum, i) => sum + i.labor_price + i.parts_price, 0);
  const tax = Math.floor(subtotal / 10);
  const result = {
    id: uuidHex().slice(0, 12),
    created_at: pyUtcNow(),
    status: "confirmed",
    mode: input.mode,
    winter_conditions: [...new Set(input.winter_conditions)].sort(),
    research_id: input.research_id,
    search_suggestions: research.search_suggestions ?? "",
    vehicle,
    year: input.year,
    grade: input.grade,
    items: records,
    notes: input.notes,
    labor_total: records.reduce((sum, i) => sum + i.labor_price, 0),
    parts_total: records.reduce((sum, i) => sum + i.parts_price, 0),
    tax_rate: TAX_RATE,
    subtotal,
    tax_amount: tax,
    total_amount: subtotal + tax,
  } as SavedEstimate;
  return transaction(db, async (tx) => {
    let linked: EstimateCase;
    if (input.case_id) {
      linked = await caseById(tx, input.case_id);
    } else {
      // 旧クライアント向けの互換: ID なしで保存しても必ず案件を作る。
      linked = newCase({
        title: estimateTitle(result),
        vehicle_label: vehicleLabel(result),
        status: "unestimated",
        amount: null,
        due_date: null,
        notes: "",
      });
      await writeCase(tx, linked, true);
    }
    result.case_id = linked.id;
    Object.assign(linked, {
      status: "completed",
      amount: result.total_amount,
      vehicle_id: input.vehicle_id,
      vehicle_label: vehicleLabel(result),
      latest_estimate_id: result.id,
      updated_at: result.created_at,
    });
    await writeCase(tx, linked, false);
    await ensureRepairJobs(tx);
    const searchText = [vehicle.maker, vehicle.model, vehicle.model_code, String(input.year), input.grade, ...records.map((i) => i.name)].join(" ");
    await tx.query("INSERT INTO demo_estimates (id, created_at, search_text, data) VALUES ($1, $2, $3, $4)", [
      result.id,
      result.created_at,
      searchText,
      JSON.stringify(result),
    ]);
    const items: { id: string; estimate_id: string; repair_job_id: string; data: EstimateItem }[] = [];
    const sources: { id: string; item_id: string; data: Source }[] = [];
    const selected: { item_id: string; source_id: string }[] = [];
    for (const record of records) {
      const itemId = uuidHex();
      items.push({ id: itemId, estimate_id: result.id, repair_job_id: record.job_id, data: record });
      for (const source of record.sources) {
        const sourceId = itemId + "-" + source.id;
        sources.push({ id: sourceId, item_id: itemId, data: source });
        if (record.selected_source_ids.includes(source.id)) selected.push({ item_id: itemId, source_id: sourceId });
      }
    }
    await tx.query(
      `INSERT INTO demo_estimate_items (id, estimate_id, repair_job_id, data)
       SELECT id, estimate_id, repair_job_id, data FROM json_to_recordset($1::json) AS x(id text, estimate_id text, repair_job_id text, data json)`,
      [JSON.stringify(items)],
    );
    if (sources.length) {
      await tx.query(
        `INSERT INTO demo_price_sources (id, item_id, data)
         SELECT id, item_id, data FROM json_to_recordset($1::json) AS x(id text, item_id text, data json)`,
        [JSON.stringify(sources)],
      );
    }
    if (selected.length) {
      await tx.query(
        `INSERT INTO demo_selected_sources (item_id, source_id)
         SELECT item_id, source_id FROM json_to_recordset($1::json) AS x(item_id text, source_id text)`,
        [JSON.stringify(selected)],
      );
    }
    return result;
  });
}

const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const LOWER = "abcdefghijklmnopqrstuvwxyz";

/** 保存した見積もりの部分一致検索。元の SQLite の LIKE と同じく、英字の大文字・小文字は ASCII だけ区別しない。 */
export function listEstimates(db: Queryable, query = ""): Promise<SavedEstimate[]> {
  const escaped = pyStrip(query).replaceAll("\\", "\\\\").replaceAll("%", "\\%").replaceAll("_", "\\_");
  return rows(
    db,
    `SELECT data FROM demo_estimates
     WHERE translate(search_text, '${UPPER}', '${LOWER}') LIKE translate($1, '${UPPER}', '${LOWER}') ESCAPE '\\'
     ORDER BY created_at DESC`,
    ["%" + escaped + "%"],
  );
}

export async function estimateDetail(db: Queryable, estimateId: string): Promise<SavedEstimate> {
  const [found] = await rows<SavedEstimate>(db, "SELECT data FROM demo_estimates WHERE id = $1", [estimateId]);
  if (!found) throw new HttpError(404, "見積もりが見つかりません");
  return found;
}
