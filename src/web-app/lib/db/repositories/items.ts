// 部品・材料単価: 品目・単価の版・換算・配合・取込。
import { DataValidationError, requireDecimal, requireText } from "../errors";
import { queryOne, queryRows, transaction, type Database, type Queryable } from "../queryable";
import {
  ITEM_CATEGORIES,
  PRICE_TYPES,
  type DecimalInput,
  type DecimalString,
  type ItemCategory,
  type JsonObject,
  type PriceType,
} from "../types";

export type ItemInput = {
  itemCode: string;
  name: string;
  category: ItemCategory;
  unit: string;
};

export type PriceInput = {
  item: ItemInput;
  unitPrice: DecimalInput;
  priceType: PriceType;
  source: string;
  /** 価格情報の更新日（YYYY-MM-DD）。valid_from を省いたときの適用開始日にもなる。 */
  updatedOn: string;
  supplierCode?: string | null;
  validFrom?: string;
  validUntil?: string | null;
  status?: "approved" | "pending";
  currency?: string;
  checkedOn?: string | null;
  conditions?: JsonObject;
};

export type PriceVersion = {
  priceVersionId: string;
  itemCode: string;
  name: string;
  category: ItemCategory;
  unit: string;
  priceType: PriceType;
  supplierCode: string | null;
  unitPrice: DecimalString;
  currency: string;
  validFrom: string;
  validUntil: string | null;
  status: "approved" | "pending";
  source: string;
  reason: string;
  updatedOn: string;
  checkedOn: string | null;
  conditions: JsonObject;
  confirmedBy: string;
  seq: string;
};

const PRICE_COLUMNS = `
  p.price_version_id AS "priceVersionId", p.item_code AS "itemCode", i.name, i.category, p.unit,
  p.price_type AS "priceType", p.supplier_code AS "supplierCode", p.unit_price::text AS "unitPrice",
  p.currency, p.valid_from::text AS "validFrom", p.valid_until::text AS "validUntil", p.status,
  p.source, p.reason, p.updated_on::text AS "updatedOn", p.checked_on::text AS "checkedOn",
  p.conditions, p.confirmed_by AS "confirmedBy", p.seq::text AS seq`;

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function requireDate(value: unknown, field: string): string {
  const text = requireText(value, field);
  if (!DATE_PATTERN.test(text) || Number.isNaN(Date.parse(`${text}T00:00:00Z`))) {
    throw new DataValidationError(`${field}: ISO形式の日付が必要です`);
  }
  return text;
}

/**
 * 単価の版を追記する。品目が未登録なら作る。
 * 登録済みの品目の名称・分類・基準単位は単価の更新では変えられない。
 */
export async function registerItemPrice(
  db: Database,
  input: PriceInput & { confirmedBy: string; reason: string },
): Promise<PriceVersion> {
  const itemCode = requireText(input.item.itemCode, "item_code");
  const name = requireText(input.item.name, "name");
  const unit = requireText(input.item.unit, "unit");
  if (!ITEM_CATEGORIES.includes(input.item.category) || !PRICE_TYPES.includes(input.priceType)) {
    throw new DataValidationError("category / price_type: 選択値を確認してください");
  }
  const updatedOn = requireDate(input.updatedOn, "updated_on");
  const validFrom = input.validFrom ? requireDate(input.validFrom, "valid_from") : updatedOn;
  const validUntil = input.validUntil ? requireDate(input.validUntil, "valid_until") : null;
  if (validUntil !== null && validUntil < validFrom) {
    throw new DataValidationError("valid_until: 開始日より前です");
  }

  return transaction(db, async (tx) => {
    const existing = await queryOne<ItemInput>(
      tx,
      `SELECT item_code AS "itemCode", name, category, base_unit AS unit FROM items WHERE item_code = $1 FOR UPDATE`,
      [itemCode],
    );
    if (!existing) {
      await tx.query("INSERT INTO items (item_code, name, category, base_unit, is_simulator) VALUES ($1, $2, $3, $4, $5)", [
        itemCode,
        name,
        input.item.category,
        unit,
        input.source.startsWith("simulator"),
      ]);
    } else if (existing.name !== name || existing.category !== input.item.category || existing.unit !== unit) {
      throw new DataValidationError("品目の名称・分類・基準単位は価格更新で変更できません");
    }
    const row = await queryOne<{ priceVersionId: string }>(
      tx,
      `INSERT INTO item_prices (item_code, unit, price_type, supplier_code, unit_price, currency, valid_from, valid_until,
                                status, source, reason, updated_on, checked_on, conditions, confirmed_by)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
       RETURNING price_version_id AS "priceVersionId"`,
      [
        itemCode,
        unit,
        input.priceType,
        input.supplierCode || null,
        requireDecimal(input.unitPrice, "unit_price"),
        input.currency ?? "JPY",
        validFrom,
        validUntil,
        input.status ?? "approved",
        requireText(input.source, "source"),
        requireText(input.reason, "reason"),
        updatedOn,
        input.checkedOn ? requireDate(input.checkedOn, "checked_on") : null,
        input.conditions ?? {},
        requireText(input.confirmedBy, "confirmed_by"),
      ],
    );
    return (await getPriceVersion(tx, row!.priceVersionId))!;
  });
}

export async function getPriceVersion(db: Queryable, priceVersionId: string): Promise<PriceVersion | undefined> {
  return queryOne<PriceVersion>(
    db,
    `SELECT ${PRICE_COLUMNS} FROM item_prices p JOIN items i USING (item_code) WHERE p.price_version_id = $1`,
    [priceVersionId],
  );
}

export async function listPriceVersions(
  db: Queryable,
  filter: { itemCode?: string; priceType?: PriceType } = {},
): Promise<PriceVersion[]> {
  return queryRows<PriceVersion>(
    db,
    `SELECT ${PRICE_COLUMNS} FROM item_prices p JOIN items i USING (item_code)
      WHERE ($1::text IS NULL OR p.item_code = $1) AND ($2::text IS NULL OR p.price_type = $2)
      ORDER BY p.seq`,
    [filter.itemCode ?? null, filter.priceType ?? null],
  );
}

/**
 * 基準日に適用する承認済みの単価を返す。
 * supplierCode を省くと仕入先を問わないが、複数の仕入先に価格があれば選択を求める（null は仕入先なし）。
 */
export async function getEffectivePrice(
  db: Queryable,
  itemCode: string,
  priceType: PriceType,
  options: { asOf: string; supplierCode?: string | null; unit?: string },
): Promise<PriceVersion> {
  if (!PRICE_TYPES.includes(priceType)) {
    throw new DataValidationError("price_type: 選択値を確認してください");
  }
  const asOf = requireDate(options.asOf, "as_of");
  const anySupplier = options.supplierCode === undefined;
  const candidates = await queryRows<PriceVersion>(
    db,
    `SELECT ${PRICE_COLUMNS} FROM item_prices p JOIN items i USING (item_code)
      WHERE p.item_code = $1 AND p.price_type = $2 AND p.status = 'approved' AND p.valid_from <= $3
        AND ($4 OR p.supplier_code IS NOT DISTINCT FROM $5)
      ORDER BY p.valid_from DESC, p.seq DESC`,
    [itemCode, priceType, asOf, anySupplier, options.supplierCode || null],
  );
  if (anySupplier && new Set(candidates.map((row) => row.supplierCode)).size > 1) {
    throw new DataValidationError("supplier_id: 仕入先の選択が必要です");
  }
  const version = candidates[0];
  if (!version) {
    throw new DataValidationError("価格未確認: 承認済みの対象価格がありません");
  }
  if (version.validUntil !== null && asOf > version.validUntil) {
    throw new DataValidationError("価格期限切れ: 再確認してください");
  }
  if (version.currency !== "JPY") {
    throw new DataValidationError("比較条件不一致: 通貨が異なるため円価格へ自動換算できません");
  }
  if (options.unit !== undefined && version.unit !== options.unit) {
    throw new DataValidationError("単位不一致: 換算根拠を確認してください");
  }
  return version;
}

export type InventoryRow = PriceVersion & {
  ageDays: number | null;
  freshness: "current" | "stale" | "未確認";
  issues: string[];
};

/**
 * 品目×仕入／販売×仕入先ごとに、基準日の現行単価と確認状況を返す（統合ワークスペースの一覧）。
 * 適用できる承認済みの版がない組み合わせは、最後に追記した版を課題付きで示す。
 */
export async function priceInventory(db: Queryable, asOf: string): Promise<InventoryRow[]> {
  const date = requireDate(asOf, "as_of");
  const rows = await queryRows<PriceVersion & { ageDays: number | null }>(
    db,
    `SELECT DISTINCT ON (p.item_code, p.price_type, p.supplier_code) ${PRICE_COLUMNS},
            ($1::date - p.checked_on) AS "ageDays"
       FROM item_prices p JOIN items i USING (item_code)
      ORDER BY p.item_code, p.price_type, p.supplier_code,
               (p.status = 'approved' AND p.valid_from <= $1::date) DESC, p.valid_from DESC, p.seq DESC`,
    [date],
  );
  return rows.map((row) => {
    const issues: string[] = [];
    if (row.checkedOn !== null && row.checkedOn > date) issues.push("確認日が適用日より未来");
    if (row.status !== "approved") issues.push("未承認");
    if (row.validFrom > date || (row.validUntil !== null && row.validUntil < date)) issues.push("有効期間外");
    if (issues.length === 0 && row.checkedOn === null) issues.push("価格確認日不明");
    const freshness = issues.includes("価格確認日不明") ? "未確認" : issues.length === 0 ? "current" : "stale";
    return { ...row, ageDays: row.checkedOn === null ? null : row.ageDays, freshness, issues };
  });
}

// ---- 単位換算・塗料コード・配合 ----

export async function addUnitConversion(
  db: Queryable,
  input: { itemCode?: string | null; fromUnit: string; toUnit: string; factor: DecimalInput; confirmedBy: string },
): Promise<void> {
  await db.query(
    `INSERT INTO unit_conversions (item_code, from_unit, to_unit, factor, confirmed_by) VALUES ($1, $2, $3, $4, $5)`,
    [
      input.itemCode ?? null,
      requireText(input.fromUnit, "from_unit"),
      requireText(input.toUnit, "to_unit"),
      requireDecimal(input.factor, "factor", { positive: true }),
      requireText(input.confirmedBy, "confirmed_by"),
    ],
  );
}

/** 品目固有の換算を優先し、なければ共通の換算を返す。 */
export async function findUnitConversion(
  db: Queryable,
  itemCode: string | null,
  fromUnit: string,
  toUnit: string,
): Promise<DecimalString | undefined> {
  const row = await queryOne<{ factor: string }>(
    db,
    `SELECT factor::text AS factor FROM unit_conversions
      WHERE (item_code = $1 OR item_code IS NULL) AND from_unit = $2 AND to_unit = $3
      ORDER BY item_code NULLS LAST LIMIT 1`,
    [itemCode, fromUnit, toUnit],
  );
  return row?.factor;
}

export async function upsertPaintCode(
  db: Queryable,
  input: { maker?: string; rawCode: string; normalizedCode: string; itemCode?: string | null },
): Promise<void> {
  await db.query(
    `INSERT INTO paint_codes (maker, raw_code, normalized_code, item_code) VALUES ($1, $2, $3, $4)
     ON CONFLICT (maker, raw_code) DO UPDATE SET normalized_code = EXCLUDED.normalized_code, item_code = EXCLUDED.item_code`,
    [input.maker ?? "", requireText(input.rawCode, "raw_code"), requireText(input.normalizedCode, "normalized_code"), input.itemCode ?? null],
  );
}

export type Formula = {
  formulaCode: string;
  version: number;
  itemCode: string | null;
  baseQuantity: DecimalString;
  baseUnit: string;
  components: { itemCode: string; quantity: DecimalString; unit: string }[];
};

/** 配合を新しい版として保存し、その版番号を返す。 */
export async function saveFormula(
  db: Database,
  input: {
    formulaCode: string;
    itemCode?: string | null;
    baseQuantity: DecimalInput;
    baseUnit: string;
    components: { itemCode: string; quantity: DecimalInput; unit: string }[];
    confirmedBy: string;
  },
): Promise<number> {
  const code = requireText(input.formulaCode, "formula_code");
  if (input.components.length === 0) {
    throw new DataValidationError("components: 配合の構成を1件以上指定してください");
  }
  return transaction(db, async (tx) => {
    await tx.query("SELECT pg_advisory_xact_lock(hashtext('formulas:' || $1))", [code]);
    const { next } = (await queryOne<{ next: number }>(
      tx,
      "SELECT COALESCE(max(version), 0) + 1 AS next FROM formulas WHERE formula_code = $1",
      [code],
    ))!;
    await tx.query(
      `INSERT INTO formulas (formula_code, version, item_code, base_quantity, base_unit, confirmed_by) VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        code,
        next,
        input.itemCode ?? null,
        requireDecimal(input.baseQuantity, "base_quantity", { positive: true }),
        requireText(input.baseUnit, "base_unit"),
        requireText(input.confirmedBy, "confirmed_by"),
      ],
    );
    for (const component of input.components) {
      await tx.query(
        `INSERT INTO formula_components (formula_code, version, component_item_code, quantity, unit) VALUES ($1, $2, $3, $4, $5)`,
        [code, next, component.itemCode, requireDecimal(component.quantity, "quantity", { positive: true }), requireText(component.unit, "unit")],
      );
    }
    return next;
  });
}

export async function getFormula(db: Queryable, formulaCode: string, version?: number): Promise<Formula | undefined> {
  return queryOne<Formula>(
    db,
    `SELECT f.formula_code AS "formulaCode", f.version, f.item_code AS "itemCode", f.base_quantity::text AS "baseQuantity",
            f.base_unit AS "baseUnit",
            (SELECT json_agg(json_build_object('itemCode', c.component_item_code, 'quantity', c.quantity::text, 'unit', c.unit)
                             ORDER BY c.component_item_code)
               FROM formula_components c WHERE c.formula_code = f.formula_code AND c.version = f.version) AS components
       FROM formulas f
      WHERE f.formula_code = $1 AND ($2::int IS NULL OR f.version = $2)
      ORDER BY f.version DESC LIMIT 1`,
    [formulaCode, version ?? null],
  );
}

// ---- 取込（CSV・Excel・PDF → 候補 → 人の承認） ----

/** 取込候補の parsed に入れる形。承認すると、この内容で単価の版を作る。 */
export type ImportedPrice = PriceInput;

export async function saveImportMapping(
  db: Database,
  input: { sourceKey: string; fieldMap: JsonObject; createdBy?: string | null },
): Promise<{ mappingId: string; version: number }> {
  const sourceKey = requireText(input.sourceKey, "source_key");
  return transaction(db, async (tx) => {
    await tx.query("SELECT pg_advisory_xact_lock(hashtext('import_mappings:' || $1))", [sourceKey]);
    return (await queryOne<{ mappingId: string; version: number }>(
      tx,
      `INSERT INTO import_mappings (source_key, version, field_map, created_by)
       SELECT $1, COALESCE(max(version), 0) + 1, $2, $3 FROM import_mappings WHERE source_key = $1
       RETURNING mapping_id AS "mappingId", version`,
      [sourceKey, input.fieldMap, input.createdBy ?? null],
    ))!;
  });
}

export type ImportCandidate = {
  candidateId: string;
  rowNumber: number;
  raw: unknown;
  parsed: ImportedPrice | null;
  issues: string[];
  status: "pending" | "approved" | "rejected";
  priceVersionId: string | null;
};

/** 取込バッチと候補行を保存する。この時点では単価にしない。 */
export async function stageImportBatch(
  db: Database,
  input: {
    batchId: string;
    source: string;
    sourceKey?: string | null;
    mappingId?: string | null;
    createdBy?: string | null;
    rows: { raw: unknown; parsed: ImportedPrice | null; issues?: string[] }[];
  },
): Promise<ImportCandidate[]> {
  const batchId = requireText(input.batchId, "import_batch_id");
  return transaction(db, async (tx) => {
    const duplicate = await queryOne(tx, "SELECT 1 FROM import_batches WHERE batch_id = $1", [batchId]);
    if (duplicate) {
      throw new DataValidationError("import_batch_id: 既存バッチIDです");
    }
    await tx.query(
      `INSERT INTO import_batches (batch_id, source, source_key, mapping_id, created_by) VALUES ($1, $2, $3, $4, $5)`,
      [batchId, requireText(input.source, "source"), input.sourceKey ?? null, input.mappingId ?? null, input.createdBy ?? null],
    );
    for (const [index, row] of input.rows.entries()) {
      await tx.query(
        `INSERT INTO import_candidates (batch_id, row_number, raw, parsed, issues) VALUES ($1, $2, $3, $4, $5)`,
        [batchId, index + 1, JSON.stringify(row.raw), row.parsed, JSON.stringify(row.issues ?? [])],
      );
    }
    return listImportCandidates(tx, batchId);
  });
}

export async function listImportCandidates(db: Queryable, batchId: string): Promise<ImportCandidate[]> {
  return queryRows<ImportCandidate>(
    db,
    `SELECT candidate_id AS "candidateId", row_number AS "rowNumber", raw, parsed, issues, status,
            price_version_id AS "priceVersionId"
       FROM import_candidates WHERE batch_id = $1 ORDER BY row_number`,
    [batchId],
  );
}

/**
 * 選んだ候補を承認し、単価の版を作る。全件を1つのトランザクションで行い、1件でも失敗したら何も承認しない。
 * 課題の残る候補・解析できなかった候補・別バッチの候補・判断済みの候補は承認できない。
 */
export async function approveImportCandidates(
  db: Database,
  input: { batchId: string; candidateIds: string[]; confirmedBy: string; reason?: string },
): Promise<PriceVersion[]> {
  const batchId = requireText(input.batchId, "import_batch_id");
  const confirmedBy = requireText(input.confirmedBy, "confirmed_by");
  if (input.candidateIds.length === 0) {
    throw new DataValidationError("candidate_ids: 候補IDを選択してください");
  }
  return transaction(db, async (tx) => {
    const candidates = await queryRows<ImportCandidate & { batchId: string }>(
      tx,
      `SELECT candidate_id AS "candidateId", batch_id AS "batchId", row_number AS "rowNumber", parsed, issues, status
         FROM import_candidates WHERE candidate_id = ANY($1::uuid[]) ORDER BY row_number FOR UPDATE`,
      [input.candidateIds],
    );
    if (candidates.length !== new Set(input.candidateIds).size || candidates.some((row) => row.batchId !== batchId)) {
      throw new DataValidationError("candidate_ids: 指定バッチに属する候補を選択してください");
    }
    const versions: PriceVersion[] = [];
    for (const candidate of candidates) {
      if (candidate.status !== "pending") {
        throw new DataValidationError(`candidate_ids: ${candidate.rowNumber}行目は判断済みです`);
      }
      if (!candidate.parsed || candidate.issues.length > 0) {
        throw new DataValidationError(`candidate_ids: ${candidate.rowNumber}行目は確認が必要な項目が残っています`);
      }
      const version = await registerItemPrice(tx, {
        ...candidate.parsed,
        confirmedBy,
        reason: input.reason ?? `取込 ${batchId} の${candidate.rowNumber}行目を承認`,
      });
      await tx.query(
        `UPDATE import_candidates SET status = 'approved', decided_by = $2, decided_at = now(), price_version_id = $3
          WHERE candidate_id = $1`,
        [candidate.candidateId, confirmedBy, version.priceVersionId],
      );
      versions.push(version);
    }
    return versions;
  });
}

export async function rejectImportCandidates(
  db: Queryable,
  input: { batchId: string; candidateIds: string[]; confirmedBy: string },
): Promise<number> {
  const result = await db.query(
    `UPDATE import_candidates SET status = 'rejected', decided_by = $3, decided_at = now()
      WHERE batch_id = $1 AND candidate_id = ANY($2::uuid[]) AND status = 'pending'`,
    [requireText(input.batchId, "import_batch_id"), input.candidateIds, requireText(input.confirmedBy, "confirmed_by")],
  );
  return result.rowCount ?? 0;
}
