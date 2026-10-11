// 見積: 版・行・顧客への説明・変更の記録・下書き・実使用量・作業プリセット。
import { DataValidationError, requireDecimal, requireText } from "../errors";
import { queryOne, queryRows, transaction, type Database, type Queryable } from "../queryable";
import {
  BANDS,
  QUOTE_LINE_KINDS,
  QUOTE_STATUSES,
  type Band,
  type BandRange,
  type DecimalInput,
  type DecimalString,
  type JsonObject,
  type QuoteLineKind,
  type QuoteStatus,
} from "../types";

export type QuoteLineInput = {
  lineId: string;
  kind: QuoteLineKind;
  category?: string | null;
  description: string;
  unit: string;
  /** 単一値の行（材料の見積時価格など）は数値1つで渡すと3帯に同じ値が入る。 */
  quantity: BandRange<DecimalInput> | DecimalInput;
  unitPrice: BandRange<DecimalInput> | DecimalInput;
  amount: BandRange<DecimalInput> | DecimalInput;
  sourceSystem: string;
  sourceRef?: string | null;
  itemCode?: string | null;
  priceVersionId?: string | null;
  reason?: string;
  status: string;
  snapshot?: JsonObject;
};

export type QuoteVersionInput = {
  quoteId: string;
  origin: "quote" | "items";
  customerRef?: string | null;
  vehicleRef?: string | null;
  jobCode?: string | null;
  caseId?: string | null;
  isSimulator?: boolean;
  /** 省くと次の版番号を振る。指定した版がすでにあれば止める。 */
  versionNo?: number;
  parentVersionNo?: number | null;
  status: QuoteStatus;
  selectedBand?: Band | null;
  subtotal: BandRange<DecimalInput>;
  tax: BandRange<DecimalInput>;
  total: BandRange<DecimalInput>;
  finalAmount?: DecimalInput | null;
  overrideReason?: string | null;
  confirmedBy?: string | null;
  manHourEstimateId?: string | null;
  asOf?: string | null;
  inputs?: JsonObject;
  /** 保存時点の見積全体。再表示はこれを使い、価格を再計算しない。 */
  snapshot: JsonObject;
  lines: QuoteLineInput[];
};

export type QuoteLine = {
  lineId: string;
  position: number;
  kind: QuoteLineKind;
  category: string | null;
  description: string;
  unit: string;
  quantity: BandRange;
  unitPrice: BandRange;
  amount: BandRange;
  sourceSystem: string;
  sourceRef: string | null;
  itemCode: string | null;
  priceVersionId: string | null;
  reason: string;
  status: string;
  snapshot: JsonObject;
};

export type QuoteVersion = {
  quoteId: string;
  origin: "quote" | "items";
  customerRef: string | null;
  vehicleRef: string | null;
  jobCode: string | null;
  caseId: string | null;
  isSimulator: boolean;
  versionNo: number;
  parentVersionNo: number | null;
  status: QuoteStatus;
  selectedBand: Band | null;
  subtotal: BandRange;
  tax: BandRange;
  total: BandRange;
  finalAmount: DecimalString | null;
  overrideReason: string | null;
  confirmedBy: string | null;
  manHourEstimateId: string | null;
  asOf: string | null;
  inputs: JsonObject;
  snapshot: JsonObject;
  createdAt: string;
  lines: QuoteLine[];
};

function bandValues(value: BandRange<DecimalInput> | DecimalInput, field: string): string[] {
  const range = typeof value === "object" ? value : { low: value, typical: value, high: value };
  return BANDS.map((band) => requireDecimal(range[band], `${field}.${band}`));
}

/** 見積の新しい版を、行と一緒に1つのトランザクションで保存する。保存した版は変えない。 */
export async function saveQuoteVersion(db: Database, input: QuoteVersionInput): Promise<QuoteVersion> {
  const quoteId = requireText(input.quoteId, "quote_id");
  if (!QUOTE_STATUSES.includes(input.status)) {
    throw new DataValidationError("status: 見積の状態を確認してください");
  }
  if (input.selectedBand != null && !BANDS.includes(input.selectedBand)) {
    throw new DataValidationError("selected_band: low / typical / high から選んでください");
  }
  if (input.status === "confirmed" && (!input.confirmedBy || !input.selectedBand)) {
    throw new DataValidationError("確定には担当者と帯の選択が必要です");
  }
  const lineIds = new Set<string>();
  for (const line of input.lines) {
    if (!QUOTE_LINE_KINDS.includes(line.kind)) {
      throw new DataValidationError(`lines.kind: ${line.kind} は使えません`);
    }
    const lineId = requireText(line.lineId, "line_id");
    if (lineIds.has(lineId)) {
      throw new DataValidationError("line_id: 重複しています");
    }
    lineIds.add(lineId);
  }

  return transaction(db, async (tx) => {
    await tx.query("SELECT pg_advisory_xact_lock(hashtext('quotes:' || $1))", [quoteId]);
    await tx.query(
      `INSERT INTO quotes (quote_id, origin, customer_ref, vehicle_ref, job_code, case_id, is_simulator)
       VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (quote_id) DO NOTHING`,
      [
        quoteId,
        input.origin,
        input.customerRef ?? null,
        input.vehicleRef ?? null,
        input.jobCode ?? null,
        input.caseId ?? null,
        input.isSimulator ?? false,
      ],
    );
    const { latest } = (await queryOne<{ latest: number }>(
      tx,
      "SELECT COALESCE(max(version_no), 0) AS latest FROM quote_versions WHERE quote_id = $1",
      [quoteId],
    ))!;
    const versionNo = input.versionNo ?? latest + 1;
    if (versionNo <= latest) {
      throw new DataValidationError(`quote_version: 版 ${versionNo} は保存済みです。新しい版を作ってください`);
    }

    await tx.query(
      `INSERT INTO quote_versions (
         quote_id, version_no, parent_version_no, status, selected_band,
         subtotal_low, subtotal_typical, subtotal_high, tax_low, tax_typical, tax_high,
         total_low, total_typical, total_high, final_amount, override_reason, confirmed_by,
         man_hour_estimate_id, as_of, inputs, snapshot)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)`,
      [
        quoteId,
        versionNo,
        input.parentVersionNo ?? null,
        input.status,
        input.selectedBand ?? null,
        ...bandValues(input.subtotal, "subtotal"),
        ...bandValues(input.tax, "tax"),
        ...bandValues(input.total, "total"),
        input.finalAmount == null ? null : requireDecimal(input.finalAmount, "final_amount"),
        input.overrideReason ?? null,
        input.confirmedBy ?? null,
        input.manHourEstimateId ?? null,
        input.asOf ?? null,
        input.inputs ?? {},
        input.snapshot,
      ],
    );

    for (const [index, line] of input.lines.entries()) {
      let itemCode = line.itemCode ?? null;
      if (line.priceVersionId) {
        const price = await queryOne<{ itemCode: string }>(
          tx,
          `SELECT item_code AS "itemCode" FROM item_prices WHERE price_version_id = $1`,
          [line.priceVersionId],
        );
        if (!price) {
          throw new DataValidationError(`lines[${index}].price_version_id: 単価の版がありません`);
        }
        if (itemCode !== null && itemCode !== price.itemCode) {
          throw new DataValidationError(`lines[${index}]: 品目と単価の版が一致しません`);
        }
        itemCode = price.itemCode;
      }
      await tx.query(
        `INSERT INTO quote_lines (
           quote_id, version_no, line_id, position, kind, category, description, unit,
           quantity_low, quantity_typical, quantity_high, unit_price_low, unit_price_typical, unit_price_high,
           amount_low, amount_typical, amount_high, source_system, source_ref, item_code, price_version_id,
           reason, status, snapshot)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24)`,
        [
          quoteId,
          versionNo,
          line.lineId.trim(),
          index + 1,
          line.kind,
          line.category ?? null,
          requireText(line.description, `lines[${index}].description`),
          requireText(line.unit, `lines[${index}].unit`),
          ...bandValues(line.quantity, `lines[${index}].quantity`),
          ...bandValues(line.unitPrice, `lines[${index}].unit_price`),
          ...bandValues(line.amount, `lines[${index}].amount`),
          requireText(line.sourceSystem, `lines[${index}].source_system`),
          line.sourceRef ?? null,
          itemCode,
          line.priceVersionId ?? null,
          line.reason ?? "",
          requireText(line.status, `lines[${index}].status`),
          line.snapshot ?? {},
        ],
      );
    }
    return (await getQuoteVersion(tx, quoteId, versionNo))!;
  });
}

function range(prefix: string, alias = ""): string {
  return `json_build_object('low', ${alias}${prefix}_low::text, 'typical', ${alias}${prefix}_typical::text, 'high', ${alias}${prefix}_high::text)`;
}

const VERSION_SELECT = `
  SELECT q.quote_id AS "quoteId", q.origin, q.customer_ref AS "customerRef", q.vehicle_ref AS "vehicleRef",
         q.job_code AS "jobCode", q.case_id AS "caseId", q.is_simulator AS "isSimulator",
         v.version_no AS "versionNo", v.parent_version_no AS "parentVersionNo", v.status, v.selected_band AS "selectedBand",
         ${range("subtotal", "v.")} AS subtotal, ${range("tax", "v.")} AS tax, ${range("total", "v.")} AS total,
         v.final_amount::text AS "finalAmount", v.override_reason AS "overrideReason", v.confirmed_by AS "confirmedBy",
         v.man_hour_estimate_id AS "manHourEstimateId", v.as_of::text AS "asOf", v.inputs, v.snapshot,
         v.created_at::text AS "createdAt",
         COALESCE(
           (SELECT json_agg(json_build_object(
                     'lineId', l.line_id, 'position', l.position, 'kind', l.kind, 'category', l.category,
                     'description', l.description, 'unit', l.unit,
                     'quantity', ${range("quantity", "l.")}, 'unitPrice', ${range("unit_price", "l.")},
                     'amount', ${range("amount", "l.")}, 'sourceSystem', l.source_system, 'sourceRef', l.source_ref,
                     'itemCode', l.item_code, 'priceVersionId', l.price_version_id, 'reason', l.reason,
                     'status', l.status, 'snapshot', l.snapshot) ORDER BY l.position)
              FROM quote_lines l WHERE l.quote_id = v.quote_id AND l.version_no = v.version_no),
           '[]'
         ) AS lines
    FROM quote_versions v JOIN quotes q USING (quote_id)`;

/** 保存した版をそのまま返す（価格を再計算しない）。版を省くと最新版。 */
export async function getQuoteVersion(db: Queryable, quoteId: string, versionNo?: number): Promise<QuoteVersion | undefined> {
  return queryOne<QuoteVersion>(
    db,
    `${VERSION_SELECT} WHERE v.quote_id = $1 AND ($2::int IS NULL OR v.version_no = $2)
      ORDER BY v.version_no DESC LIMIT 1`,
    [quoteId, versionNo ?? null],
  );
}

export type QuoteSummary = Omit<QuoteVersion, "lines" | "inputs" | "snapshot">;

/** 見積ごとの最新版を、顧客・車両・作業で絞り込んで返す。 */
export async function listQuotes(
  db: Queryable,
  filter: { customerRef?: string; vehicleRef?: string; jobCode?: string; origin?: "quote" | "items" } = {},
): Promise<QuoteSummary[]> {
  return queryRows<QuoteSummary>(
    db,
    `SELECT DISTINCT ON (q.quote_id)
            q.quote_id AS "quoteId", q.origin, q.customer_ref AS "customerRef", q.vehicle_ref AS "vehicleRef",
            q.job_code AS "jobCode", q.case_id AS "caseId", q.is_simulator AS "isSimulator",
            v.version_no AS "versionNo", v.parent_version_no AS "parentVersionNo", v.status, v.selected_band AS "selectedBand",
            ${range("subtotal", "v.")} AS subtotal, ${range("tax", "v.")} AS tax, ${range("total", "v.")} AS total,
            v.final_amount::text AS "finalAmount", v.override_reason AS "overrideReason", v.confirmed_by AS "confirmedBy",
            v.man_hour_estimate_id AS "manHourEstimateId", v.as_of::text AS "asOf", v.created_at::text AS "createdAt"
       FROM quote_versions v JOIN quotes q USING (quote_id)
      WHERE ($1::text IS NULL OR q.customer_ref = $1) AND ($2::text IS NULL OR q.vehicle_ref = $2)
        AND ($3::text IS NULL OR q.job_code = $3) AND ($4::text IS NULL OR q.origin = $4)
      ORDER BY q.quote_id, v.version_no DESC`,
    [filter.customerRef ?? null, filter.vehicleRef ?? null, filter.jobCode ?? null, filter.origin ?? null],
  );
}

// ---- 顧客への説明・変更の記録 ----

export type QuoteCommunication = {
  communicationId: string;
  quoteId: string;
  versionNo: number;
  payload: JsonObject;
  recordedBy: string | null;
  createdAt: string;
};

export async function appendCommunication(
  db: Queryable,
  input: { communicationId: string; quoteId: string; versionNo: number; payload: JsonObject; recordedBy?: string | null },
): Promise<void> {
  await db.query(
    `INSERT INTO quote_communications (communication_id, quote_id, version_no, payload, recorded_by) VALUES ($1, $2, $3, $4, $5)`,
    [
      requireText(input.communicationId, "communication_id"),
      requireText(input.quoteId, "quote_id"),
      input.versionNo,
      input.payload,
      input.recordedBy ?? null,
    ],
  );
}

/** 版を指定すると、その版の記録だけを返す（版ごとに説明を分ける）。 */
export async function listCommunications(db: Queryable, quoteId: string, versionNo?: number): Promise<QuoteCommunication[]> {
  return queryRows<QuoteCommunication>(
    db,
    `SELECT communication_id AS "communicationId", quote_id AS "quoteId", version_no AS "versionNo", payload,
            recorded_by AS "recordedBy", created_at::text AS "createdAt"
       FROM quote_communications WHERE quote_id = $1 AND ($2::int IS NULL OR version_no = $2)
      ORDER BY created_at, communication_id`,
    [quoteId, versionNo ?? null],
  );
}

export type QuoteChangeEvent = {
  eventId: string;
  quoteId: string;
  fromVersion: number | null;
  toVersion: number;
  payload: JsonObject;
  createdAt: string;
};

export async function appendChangeEvent(
  db: Queryable,
  input: { eventId: string; quoteId: string; fromVersion?: number | null; toVersion: number; payload: JsonObject },
): Promise<void> {
  await db.query(
    `INSERT INTO quote_change_events (event_id, quote_id, from_version, to_version, payload) VALUES ($1, $2, $3, $4, $5)`,
    [requireText(input.eventId, "event_id"), requireText(input.quoteId, "quote_id"), input.fromVersion ?? null, input.toVersion, input.payload],
  );
}

export async function listChangeEvents(db: Queryable, quoteId: string, toVersion?: number): Promise<QuoteChangeEvent[]> {
  return queryRows<QuoteChangeEvent>(
    db,
    `SELECT event_id AS "eventId", quote_id AS "quoteId", from_version AS "fromVersion", to_version AS "toVersion",
            payload, created_at::text AS "createdAt"
       FROM quote_change_events WHERE quote_id = $1 AND ($2::int IS NULL OR to_version = $2)
      ORDER BY created_at, event_id`,
    [quoteId, toVersion ?? null],
  );
}

// ---- 下書き ----

export type QuoteDraft = { draftId: string; quoteId: string | null; step: number; payload: JsonObject; updatedAt: string };

export async function saveDraft(
  db: Queryable,
  input: { draftId: string; quoteId?: string | null; step?: number; payload: JsonObject },
): Promise<void> {
  await db.query(
    `INSERT INTO quote_drafts (draft_id, quote_id, step, payload) VALUES ($1, $2, $3, $4)
     ON CONFLICT (draft_id) DO UPDATE SET
       quote_id = EXCLUDED.quote_id, step = EXCLUDED.step, payload = EXCLUDED.payload, updated_at = now()`,
    [requireText(input.draftId, "draft_id"), input.quoteId ?? null, input.step ?? 0, input.payload],
  );
}

const DRAFT_COLUMNS = `draft_id AS "draftId", quote_id AS "quoteId", step, payload, updated_at::text AS "updatedAt"`;

export async function getDraft(db: Queryable, draftId: string): Promise<QuoteDraft | undefined> {
  return queryOne<QuoteDraft>(db, `SELECT ${DRAFT_COLUMNS} FROM quote_drafts WHERE draft_id = $1`, [draftId]);
}

export async function listDrafts(db: Queryable): Promise<QuoteDraft[]> {
  return queryRows<QuoteDraft>(db, `SELECT ${DRAFT_COLUMNS} FROM quote_drafts ORDER BY updated_at DESC, draft_id`);
}

// ---- 実使用量 ----

export type MaterialUsage = {
  usageId: string;
  quoteId: string;
  versionNo: number;
  lineId: string;
  itemCode: string | null;
  estimatedQuantity: DecimalString;
  actualQuantity: DecimalString;
  difference: DecimalString;
  unit: string;
  reason: string;
  confirmedBy: string;
  recordedAt: string;
};

/**
 * 見積行に対する実使用量を理由付きで記録する。見積の数量・単価は変えない。
 * 見積量は、版で選んだ帯の数量。帯を選んでいない版では、3帯の数量が同じ行だけ記録できる。
 */
export async function recordMaterialUsage(
  db: Queryable,
  input: {
    quoteId: string;
    versionNo?: number;
    lineId: string;
    actualQuantity: DecimalInput;
    reason: string;
    confirmedBy: string;
    isSimulator?: boolean;
  },
): Promise<MaterialUsage> {
  const quoteId = requireText(input.quoteId, "quote_id");
  const lineId = requireText(input.lineId, "quote_line_id");
  const line = await queryOne<{
    versionNo: number;
    selectedBand: Band | null;
    low: string;
    typical: string;
    high: string;
    unit: string;
  }>(
    db,
    `SELECT l.version_no AS "versionNo", v.selected_band AS "selectedBand", l.unit,
            l.quantity_low::text AS low, l.quantity_typical::text AS typical, l.quantity_high::text AS high
       FROM quote_lines l JOIN quote_versions v USING (quote_id, version_no)
      WHERE l.quote_id = $1 AND l.line_id = $2 AND ($3::int IS NULL OR l.version_no = $3)
      ORDER BY l.version_no DESC LIMIT 1`,
    [quoteId, lineId, input.versionNo ?? null],
  );
  if (!line) {
    throw new DataValidationError("quote_line_id: 見積の行が見つかりません");
  }
  let estimated: string;
  if (line.selectedBand) {
    estimated = line[line.selectedBand];
  } else if (Number(line.low) === Number(line.typical) && Number(line.typical) === Number(line.high)) {
    estimated = line.typical;
  } else {
    throw new DataValidationError("quote_line_id: 数量に幅がある行は、帯を選んだ版で記録してください");
  }
  const row = await queryOne<{ usageId: string }>(
    db,
    `INSERT INTO material_usages (quote_id, version_no, line_id, estimated_quantity, actual_quantity, unit, reason, confirmed_by, is_simulator)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING usage_id AS "usageId"`,
    [
      quoteId,
      line.versionNo,
      lineId,
      estimated,
      requireDecimal(input.actualQuantity, "actual_qty"),
      line.unit,
      requireText(input.reason, "reason"),
      requireText(input.confirmedBy, "confirmed_by"),
      input.isSimulator ?? false,
    ],
  );
  return (await listMaterialUsages(db, { usageId: row!.usageId }))[0];
}

export async function listMaterialUsages(
  db: Queryable,
  filter: { quoteId?: string; lineId?: string; usageId?: string } = {},
): Promise<MaterialUsage[]> {
  return queryRows<MaterialUsage>(
    db,
    `SELECT u.usage_id AS "usageId", u.quote_id AS "quoteId", u.version_no AS "versionNo", u.line_id AS "lineId",
            l.item_code AS "itemCode", u.estimated_quantity::text AS "estimatedQuantity",
            u.actual_quantity::text AS "actualQuantity", u.difference::text AS difference, u.unit, u.reason,
            u.confirmed_by AS "confirmedBy", u.recorded_at::text AS "recordedAt"
       FROM material_usages u JOIN quote_lines l USING (quote_id, version_no, line_id)
      WHERE ($1::text IS NULL OR u.quote_id = $1) AND ($2::text IS NULL OR u.line_id = $2)
        AND ($3::uuid IS NULL OR u.usage_id = $3)
      ORDER BY u.recorded_at, u.usage_id`,
    [filter.quoteId ?? null, filter.lineId ?? null, filter.usageId ?? null],
  );
}

// ---- 作業プリセット ----

export type JobPreset = {
  presetId: string;
  version: number;
  jobCode: string;
  name: string;
  aliases: { alias: string; approved_by: string }[];
  requiredConditions: unknown[];
  inputs: JsonObject;
  defaultQuantity: DecimalString;
  rateRef: string | null;
  itemCodes: string[];
  source: string;
  approvedBy: string;
  updatedOn: string;
};

export async function saveJobPreset(
  db: Queryable,
  input: Omit<JobPreset, "defaultQuantity"> & { defaultQuantity?: DecimalInput },
): Promise<void> {
  await db.query(
    `INSERT INTO job_presets (preset_id, version, job_code, name, aliases, required_conditions, inputs, default_quantity,
                              rate_ref, item_codes, source, approved_by, updated_on)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`,
    [
      requireText(input.presetId, "preset_id"),
      input.version,
      requireText(input.jobCode, "job_code"),
      requireText(input.name, "name"),
      JSON.stringify(input.aliases),
      JSON.stringify(input.requiredConditions),
      input.inputs,
      requireDecimal(input.defaultQuantity ?? 1, "default_quantity", { positive: true }),
      input.rateRef,
      input.itemCodes,
      requireText(input.source, "source"),
      requireText(input.approvedBy, "approved_by"),
      requireText(input.updatedOn, "updated_on"),
    ],
  );
}

/** 各プリセットの最新版を、名前・別名で検索する。 */
export async function searchJobPresets(db: Queryable, query = ""): Promise<JobPreset[]> {
  return queryRows<JobPreset>(
    db,
    `SELECT DISTINCT ON (p.preset_id)
            p.preset_id AS "presetId", p.version, p.job_code AS "jobCode", p.name, p.aliases,
            p.required_conditions AS "requiredConditions", p.inputs, p.default_quantity::text AS "defaultQuantity",
            p.rate_ref AS "rateRef", p.item_codes AS "itemCodes", p.source, p.approved_by AS "approvedBy",
            p.updated_on::text AS "updatedOn"
       FROM job_presets p
      WHERE $1 = ''
         OR strpos(lower(p.name), lower($1)) > 0
         OR EXISTS (SELECT 1 FROM jsonb_array_elements(p.aliases) a WHERE strpos(lower(a ->> 'alias'), lower($1)) > 0)
      ORDER BY p.preset_id, p.version DESC`,
    [query.trim()],
  );
}
