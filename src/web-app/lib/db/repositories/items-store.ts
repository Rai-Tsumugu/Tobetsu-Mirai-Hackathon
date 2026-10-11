// 部品・材料単価（auto_repair_items）の30案が使う保存先。
// 元の Store の records(namespace, payload) と単価の版の全体を 0008_items の表に追記し、
// 見積スナップショット・実使用量・単位換算は 0004 / 0005 の既存の表にも写す。
import { DataValidationError } from "../errors";
import { queryOne, queryRows, type Queryable } from "../queryable";
import { addUnitConversion } from "./items";

/** 確認者・承認者の名前を担当者として登録する（元の実装は自由入力の名前を受け付けるため）。 */
export async function ensureStaff(db: Queryable, staffCode: string): Promise<void> {
  await db.query(
    `INSERT INTO staff (staff_code, display_name, is_simulator) VALUES ($1, $1, true) ON CONFLICT (staff_code) DO NOTHING`,
    [staffCode],
  );
}

export async function ensureSupplier(db: Queryable, supplierCode: string): Promise<void> {
  await db.query(
    `INSERT INTO suppliers (supplier_code, name, is_simulator) VALUES ($1, $1, true) ON CONFLICT (supplier_code) DO NOTHING`,
    [supplierCode],
  );
}

// ---- 追記記録（records） ----

export async function insertRecord(db: Queryable, namespace: string, recordId: string, payloadJson: string): Promise<void> {
  await db.query(`INSERT INTO items_records (namespace, record_id, payload) VALUES ($1, $2, $3::json)`, [
    namespace,
    recordId,
    payloadJson,
  ]);
}

export async function selectRecords(
  db: Queryable,
  namespace: string,
  recordId: string | null,
): Promise<{ record_id: string; payload: Record<string, unknown> }[]> {
  return queryRows(
    db,
    `SELECT record_id, payload FROM items_records
      WHERE namespace = $1 AND ($2::text IS NULL OR record_id = $2) ORDER BY seq`,
    [namespace, recordId],
  );
}

// ---- 単価の版 ----

export async function insertPricePayload(db: Queryable, priceVersionId: string, payloadJson: string): Promise<void> {
  await db.query(`INSERT INTO items_price_payloads (price_version_id, payload) VALUES ($1, $2::json)`, [priceVersionId, payloadJson]);
}

export type PriceRow = {
  priceVersionId: string;
  itemCode: string;
  name: string;
  category: string;
  unit: string;
  priceType: string;
  supplierCode: string | null;
  unitPrice: string;
  currency: string;
  validFrom: string;
  validUntil: string | null;
  status: string;
  source: string;
  reason: string;
  updatedOn: string;
  checkedOn: string | null;
  conditions: Record<string, unknown>;
  confirmedBy: string;
  /** 30案から保存した版の全体。ほかのシステムが登録した版では null。 */
  payload: Record<string, unknown> | null;
};

/** 単価の版を追記順に返す。supplierCode の '' は仕入先なし。 */
export async function selectPriceRows(
  db: Queryable,
  filter: { itemCode: string | null; priceType: string | null; supplierCode: string | null },
): Promise<PriceRow[]> {
  return queryRows<PriceRow>(
    db,
    `SELECT p.price_version_id::text AS "priceVersionId", p.item_code AS "itemCode", i.name, i.category, p.unit,
            p.price_type AS "priceType", p.supplier_code AS "supplierCode", p.unit_price::text AS "unitPrice",
            p.currency, p.valid_from::text AS "validFrom", p.valid_until::text AS "validUntil", p.status, p.source,
            p.reason, p.updated_on::text AS "updatedOn", p.checked_on::text AS "checkedOn", p.conditions,
            p.confirmed_by AS "confirmedBy", d.payload
       FROM item_prices p
       JOIN items i USING (item_code)
       LEFT JOIN items_price_payloads d USING (price_version_id)
      WHERE ($1::text IS NULL OR p.item_code = $1)
        AND ($2::text IS NULL OR p.price_type = $2)
        AND ($3::text IS NULL OR coalesce(p.supplier_code, '') = $3)
      ORDER BY p.seq`,
    [filter.itemCode, filter.priceType, filter.supplierCode],
  );
}

// ---- 見積スナップショット → quotes / quote_versions / quote_lines ----

export type QuoteProjectionLine = {
  lineId: string;
  kind: "parts" | "materials";
  category: string | null;
  description: string;
  unit: string;
  quantity: string;
  unitPrice: string;
  amount: string;
  itemCode: string | null;
  priceVersionId: string | null;
  snapshotJson: string;
};

export type QuoteProjection = {
  quoteId: string;
  isSimulator: boolean;
  confirmedBy: string | null;
  asOf: string | null;
  subtotal: string;
  tax: string;
  total: string;
  snapshotJson: string;
  lines: QuoteProjectionLine[];
};

const UUID_PATTERN = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

/**
 * 30案の見積スナップショットを origin=items の見積の新しい版として写す（同じ見積IDの再保存は次の版）。
 * 品目・単価の版が DB にない行（架空デモの行など）は、その参照を空にして写す。
 */
export async function projectQuote(db: Queryable, input: QuoteProjection): Promise<number> {
  const existing = await queryOne<{ origin: string }>(db, "SELECT origin FROM quotes WHERE quote_id = $1", [input.quoteId]);
  if (existing && existing.origin !== "items") {
    throw new DataValidationError("quote_id: 整備見積で使われている見積IDです。別の見積IDを指定してください");
  }
  if (!existing) {
    await db.query("INSERT INTO quotes (quote_id, origin, is_simulator) VALUES ($1, 'items', $2)", [input.quoteId, input.isSimulator]);
  }
  if (input.confirmedBy) await ensureStaff(db, input.confirmedBy);
  const { next } = (await queryOne<{ next: number }>(
    db,
    "SELECT COALESCE(max(version_no), 0) + 1 AS next FROM quote_versions WHERE quote_id = $1",
    [input.quoteId],
  ))!;
  await db.query(
    `INSERT INTO quote_versions (quote_id, version_no, status, subtotal_low, subtotal_typical, subtotal_high,
       tax_low, tax_typical, tax_high, total_low, total_typical, total_high, confirmed_by, as_of, snapshot)
     VALUES ($1, $2, 'proposed', $3, $3, $3, $4, $4, $4, $5, $5, $5, $6, $7, $8::jsonb)`,
    [input.quoteId, next, input.subtotal, input.tax, input.total, input.confirmedBy, input.asOf, input.snapshotJson],
  );
  for (const [index, line] of input.lines.entries()) {
    const itemCode =
      line.itemCode && (await queryOne(db, "SELECT 1 FROM items WHERE item_code = $1", [line.itemCode])) ? line.itemCode : null;
    let priceVersionId: string | null = null;
    if (line.priceVersionId && UUID_PATTERN.test(line.priceVersionId)) {
      const price = await queryOne<{ itemCode: string }>(
        db,
        `SELECT item_code AS "itemCode" FROM item_prices WHERE price_version_id = $1::uuid`,
        [line.priceVersionId],
      );
      if (price && (itemCode === null || price.itemCode === itemCode)) priceVersionId = line.priceVersionId;
    }
    await db.query(
      `INSERT INTO quote_lines (quote_id, version_no, line_id, position, kind, category, description, unit,
         quantity_low, quantity_typical, quantity_high, unit_price_low, unit_price_typical, unit_price_high,
         amount_low, amount_typical, amount_high, source_system, item_code, price_version_id, status, snapshot)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9, $9, $10, $10, $10, $11, $11, $11, 'items', $12, $13::uuid, 'snapshot', $14::jsonb)`,
      [
        input.quoteId,
        next,
        line.lineId,
        index + 1,
        line.kind,
        line.category,
        line.description,
        line.unit,
        line.quantity,
        line.unitPrice,
        line.amount,
        itemCode,
        priceVersionId,
        line.snapshotJson,
      ],
    );
  }
  return next;
}

// ---- 実使用量 → material_usages ----

/** 見積行の実使用量を material_usages に写す。行を写していない見積（不備のある行）では何もしない。 */
export async function projectMaterialUsage(
  db: Queryable,
  input: {
    usageId: string | null;
    quoteId: string;
    lineId: string;
    estimated: string;
    actual: string;
    unit: string;
    reason: string;
    confirmedBy: string;
    isSimulator: boolean;
  },
): Promise<boolean> {
  const line = await queryOne<{ versionNo: number }>(
    db,
    `SELECT l.version_no AS "versionNo" FROM quote_lines l JOIN quotes q USING (quote_id)
      WHERE q.origin = 'items' AND l.quote_id = $1 AND l.line_id = $2 ORDER BY l.version_no DESC LIMIT 1`,
    [input.quoteId, input.lineId],
  );
  if (!line) return false;
  await ensureStaff(db, input.confirmedBy);
  await db.query(
    `INSERT INTO material_usages (usage_id, quote_id, version_no, line_id, estimated_quantity, actual_quantity, unit,
       reason, confirmed_by, is_simulator)
     VALUES (COALESCE($1::uuid, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
    [
      input.usageId && UUID_PATTERN.test(input.usageId) ? input.usageId : null,
      input.quoteId,
      line.versionNo,
      input.lineId,
      input.estimated,
      input.actual,
      input.unit,
      input.reason,
      input.confirmedBy,
      input.isSimulator,
    ],
  );
  return true;
}

// ---- 単位換算 → unit_conversions ----

/** 品目固有の換算を写す。同一単位（係数1の確認）と、品目が DB にない・登録済みの換算は写さない。 */
export async function projectUnitConversion(
  db: Queryable,
  input: { itemCode: string; fromUnit: string; toUnit: string; factor: string; confirmedBy: string },
): Promise<boolean> {
  if (input.fromUnit === input.toUnit) return false;
  if (!(await queryOne(db, "SELECT 1 FROM items WHERE item_code = $1", [input.itemCode]))) return false;
  const duplicate = await queryOne(
    db,
    "SELECT 1 FROM unit_conversions WHERE item_code = $1 AND from_unit = $2 AND to_unit = $3",
    [input.itemCode, input.fromUnit, input.toUnit],
  );
  if (duplicate) return false;
  await ensureStaff(db, input.confirmedBy);
  await addUnitConversion(db, input);
  return true;
}
