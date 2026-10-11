// auto_repair_items/core.py の移植: 共通の名前・入力検査・追記保存の Store。
// 金額・数量は Decimal で計算し、保存と JSON は丸めない十進文字列にする。
import { Decimal, InvalidOperation } from "./decimal";
import { dumps, get, has, isDict, maxBy, parseIsoDate, parseIsoDatetime, pyEqual, pyStrip, roundTrip, isoDate, truthy } from "./py";

export const ITEM_FIELDS = ["item_id", "name", "category", "unit", "unit_price", "price_type", "source", "updated_at"] as const;
export const CATEGORIES = ["部品", "塗料", "溶剤", "消耗品"] as const;
export const PRICE_TYPES = ["仕入", "販売"] as const;
export const DEMO_DATE = "2026-10-11";

export type Item = {
  item_id: string;
  name: string;
  category: string;
  unit: string;
  unit_price: string;
  price_type: string;
  source: string;
  updated_at: string;
};

export type Json = Record<string, unknown>;

export type PriceVersion = {
  price_version_id: string;
  item: Item;
  confirmed_by: string;
  supplier_id: string;
  valid_from: string;
  valid_until: string | null;
  status: string;
  reason: string;
  metadata: Json;
};

export type StoredRecord = Json & { record_id: string };

/** 人が入力を直す必要があるときのエラー。0 で置き換えない。 */
export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

export function textValue(value: unknown, field: string): string {
  if (typeof value !== "string" || !pyStrip(value)) {
    throw new ValidationError(`${field}: 入力が必要です`);
  }
  return pyStrip(value);
}

/** Decimal(str(value)) と同じ解釈。None / bool / 非有限 / 負数は止める。 */
export function decimalValue(value: unknown, field = "value", options: { positive?: boolean } = {}): Decimal {
  if (value === null || value === undefined || typeof value === "boolean") {
    throw new ValidationError(`${field}: 数値を確認してください`);
  }
  let result: Decimal;
  try {
    if (value instanceof Decimal) result = value;
    else if (typeof value === "number" || typeof value === "bigint") result = Decimal.parse(String(value));
    else if (typeof value === "string") result = Decimal.parse(value);
    else throw new InvalidOperation("unsupported");
  } catch (error) {
    if (error instanceof InvalidOperation) throw new ValidationError(`${field}: 数値を確認してください`);
    throw error;
  }
  if (!result.isFinite() || result.lt(0) || (options.positive && result.isZero())) {
    throw new ValidationError(`${field}: 有限の正数/非負数を入力してください`);
  }
  if (result.digitCount() > 28 || Math.abs(result.exponent) > 12) {
    throw new ValidationError(`${field}: 数値の桁数が大きすぎます`);
  }
  return result;
}

/** date_value(): ISO の日付（または日時の日付部分）を 'YYYY-MM-DD' で返す。 */
export function dateValue(value: unknown, field = "date"): string {
  const text = textValue(value, field);
  const date = parseIsoDate(text);
  if (date) return isoDate(date);
  const datetime = parseIsoDatetime(text.replace(/Z/g, "+00:00"));
  if (datetime) return isoDate(datetime);
  throw new ValidationError(`${field}: ISO形式の日付が必要です`);
}

export function approvedBy(payload: Json): string {
  return textValue(get(payload, "confirmed_by"), "confirmed_by");
}

export function validateItem(item: unknown): Item {
  if (!isDict(item)) {
    throw new ValidationError("item: 品目が必要です");
  }
  const result: Record<string, string> = {};
  for (const field of ITEM_FIELDS) {
    if (field !== "unit_price") result[field] = textValue(get(item, field), field);
  }
  if (!(CATEGORIES as readonly string[]).includes(result.category) || !(PRICE_TYPES as readonly string[]).includes(result.price_type)) {
    throw new ValidationError("category / price_type: 選択値を確認してください");
  }
  result.unit_price = decimalValue(get(item, "unit_price"), "unit_price").toString();
  dateValue(result.updated_at, "updated_at");
  const ordered: Record<string, string> = {};
  for (const field of ITEM_FIELDS) ordered[field] = result[field];
  return ordered as Item;
}

export function demoItem(itemId = "demo-paint", priceType = "販売", unitPrice: unknown = "120", unit = "ml"): Item {
  return {
    item_id: itemId,
    name: "架空サンプル塗料",
    category: "塗料",
    unit,
    unit_price: unitPrice as string,
    price_type: priceType,
    source: "simulator:架空値",
    updated_at: DEMO_DATE,
  };
}

const CONDITION_KEYS = ["freight_basis", "freight_amount", "tax_basis", "delivery_days", "currency", "transaction_conditions"];

/** 仕入先・履歴・スナップショットで取引条件の表記を揃える（price_conditions）。 */
export function priceConditions(version: Json): Json {
  const metadata = (get(version, "metadata") as Json | null) || {};
  const nested = has(metadata, "conditions") ? metadata.conditions : {};
  if (!isDict(nested)) {
    throw new ValidationError("conditions: 取引条件の形式を確認してください");
  }
  const result: Json = {};
  for (const key of CONDITION_KEYS) if (has(nested, key)) result[key] = nested[key];
  for (const key of CONDITION_KEYS) {
    if (has(metadata, key)) {
      if (has(result, key) && !pyEqual(result[key], metadata[key])) {
        throw new ValidationError("conditions: 取引条件の二重定義が一致しません");
      }
      result[key] = metadata[key];
    }
  }
  if (!has(result, "currency")) result.currency = "JPY";
  return result;
}

/** add_price のキーワード引数。ここにない名前はすべて metadata になる。 */
export type AddPriceKwargs = Json & {
  supplier_id?: unknown;
  valid_from?: unknown;
  valid_until?: unknown;
  status?: unknown;
  reason?: unknown;
};

export type GetPriceOptions = { as_of?: unknown; supplier_id?: string | null; unit?: string | null };

/**
 * 追記だけの保存先（core.Store）。価格の版と内部記録を持ち、更新・削除はしない。
 * 実体は MemoryStore（テスト）と PgStore（Neon）。
 */
export abstract class Store {
  /** with store.transaction(): 失敗したら中の保存をすべて取り消す。 */
  abstract transaction<T>(fn: () => Promise<T>): Promise<T>;

  protected abstract insertRecord(namespace: string, recordId: string, payload: string, record: Json): Promise<void>;
  protected abstract selectRecords(namespace: string, recordId: string | null): Promise<{ record_id: string; payload: Json }[]>;
  /** 版を保存し、決めた price_version_id を返す。 */
  protected abstract insertPrice(version: PriceVersion): Promise<string>;
  protected abstract selectPrices(itemId: string | null, priceType: string | null, supplierId: string | null): Promise<PriceVersion[]>;
  protected abstract newId(): string;

  async put(namespace: unknown, record: unknown, recordId: unknown = null): Promise<StoredRecord> {
    const ns = textValue(namespace, "namespace");
    if (!isDict(record)) {
      throw new ValidationError("record: 記録項目の集合が必要です");
    }
    const id = recordId !== null && recordId !== undefined ? textValue(recordId, "record_id") : this.newId();
    const payload = dumps(record);
    await this.transaction(() => this.insertRecord(ns, id, payload, record));
    return { ...record, record_id: id };
  }

  async records(namespace: string, recordId: string | null = null): Promise<StoredRecord[]> {
    const rows = await this.selectRecords(namespace, recordId);
    return rows.map((row) => ({ ...row.payload, record_id: row.record_id }));
  }

  async latest(namespace: string, recordId: string): Promise<StoredRecord> {
    const rows = await this.records(namespace, recordId);
    if (rows.length === 0) {
      throw new ValidationError(`${namespace}: 指定した記録がありません`);
    }
    return rows[rows.length - 1];
  }

  async addPrice(itemInput: unknown, confirmedByInput: unknown, kwargs: AddPriceKwargs = {}): Promise<PriceVersion> {
    const { supplier_id: supplierInput, valid_from: validFromInput, valid_until: validUntilInput, status: statusInput, reason: reasonInput, ...metadata } = kwargs;
    const item = validateItem(itemInput);
    const confirmedBy = textValue(confirmedByInput, "confirmed_by");
    const reason = textValue(has(kwargs, "reason") ? reasonInput : "初回登録", "reason");
    const status = has(kwargs, "status") ? statusInput : "approved";
    if (status !== "approved" && status !== "pending") {
      throw new ValidationError("status: 承認状態を確認してください");
    }
    const supplierId = (has(kwargs, "supplier_id") ? supplierInput : "") as string;
    const validFrom = dateValue(truthy(validFromInput) ? validFromInput : item.updated_at, "valid_from");
    let validUntil: string | null = null;
    if (validUntilInput !== null && validUntilInput !== undefined) {
      validUntil = dateValue(validUntilInput, "valid_until");
      if (validUntil < validFrom) {
        throw new ValidationError("valid_until: 開始日より前です");
      }
    }
    // 品目の名称・分類・基準単位は、仕入／販売・仕入先をまたいで変えない。
    const prior = await this.priceVersions(item.item_id);
    if (prior.length > 0) {
      const last = prior[prior.length - 1].item;
      if (last.name !== item.name || last.category !== item.category || last.unit !== item.unit) {
        throw new ValidationError("品目の名称・分類・基準単位は価格更新で変更できません");
      }
    }
    const version: PriceVersion = {
      price_version_id: "",
      item,
      confirmed_by: confirmedBy,
      supplier_id: supplierId,
      valid_from: validFrom,
      valid_until: validUntil,
      status,
      reason,
      metadata,
    };
    version.price_version_id = await this.transaction(() => this.insertPrice(version));
    return version;
  }

  async priceVersions(itemId: string | null = null, priceType: string | null = null, supplierId: string | null = null): Promise<PriceVersion[]> {
    return this.selectPrices(itemId, priceType, supplierId);
  }

  async getPrice(itemId: string, priceType: unknown = "販売", options: GetPriceOptions = {}): Promise<PriceVersion> {
    if (!(PRICE_TYPES as readonly unknown[]).includes(priceType)) {
      throw new ValidationError("price_type: 選択値を確認してください");
    }
    const asOf = dateValue(options.as_of === undefined ? DEMO_DATE : options.as_of, "as_of");
    const supplierId = options.supplier_id ?? null;
    const versions = (await this.priceVersions(itemId, priceType as string, supplierId)).filter(
      (version) => version.status === "approved" && version.valid_from <= asOf,
    );
    const suppliers = new Set(versions.map((version) => version.supplier_id));
    if (supplierId === null && suppliers.size > 1) {
      throw new ValidationError("supplier_id: 仕入先の選択が必要です");
    }
    if (versions.length === 0) {
      throw new ValidationError("価格未確認: 承認済みの対象価格がありません");
    }
    // 有効開始日、同日なら後に追記した版。
    const version = maxBy(
      versions.map((entry, index) => ({ entry, index })),
      (pair) => [pair.entry.valid_from, pair.index],
    ).entry;
    if (version.valid_until !== null && asOf > version.valid_until) {
      throw new ValidationError("価格期限切れ: 再確認してください");
    }
    if (!pyEqual(get(version.metadata, "currency", "JPY"), "JPY")) {
      throw new ValidationError("比較条件不一致: 通貨が異なるため円価格へ自動換算できません");
    }
    const unit = options.unit ?? null;
    if (unit !== null && version.item.unit !== unit) {
      throw new ValidationError("単位不一致: 換算根拠を確認してください");
    }
    return version;
  }
}

/** 明示的な Simulator の初期データ（seed_demo）。 */
export async function seedDemo(store: Store): Promise<void> {
  if ((await store.priceVersions("demo-paint")).length > 0) return;
  for (const [priceType, unitPrice] of [
    ["仕入", "80"],
    ["販売", "120"],
  ]) {
    await store.addPrice(demoItem("demo-paint", priceType, unitPrice), "架空デモ担当");
  }
}

/** 記録は JSON で保存されるので、読み戻した値で返す。 */
export function storedCopy<T>(value: T): T {
  return roundTrip<T>(value);
}
