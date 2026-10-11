// Neon（PostgreSQL）上の Store。サーバー側でだけ使う。
// 単価の版は items / item_prices（既存）に入れ、元の版の全体を items_price_payloads に添える。
// 記録は items_records に追記し、見積スナップショット・実使用量・単位換算は既存の表にも写す。
import * as itemsRepo from "../../db/repositories/items";
import * as storeRepo from "../../db/repositories/items-store";
import type { Transaction } from "../../db/queryable";
import { Decimal } from "./decimal";
import { CATEGORIES, PRICE_TYPES, priceConditions, Store, type Item, type Json, type PriceVersion } from "./core";
import { dumps, get, isDict, parseIsoDate, parseIsoDatetime, isoDate, pyStr, uuidHex } from "./py";

const QUOTE_NAMESPACE = "quote_snapshot";
const USAGE_NAMESPACE = "item_usage";
const UNIT_CONVERSION_NAMESPACE = "unit_conversion";

/** 非負の有限な十進数なら指数表記を使わない文字列、そうでなければ null。 */
function plainDecimal(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number" && !(value instanceof Decimal)) return null;
  try {
    const decimal = value instanceof Decimal ? value : Decimal.parse(String(value));
    if (!decimal.isFinite() || decimal.lt(0)) return null;
    return decimal.toPlainString();
  } catch {
    return null;
  }
}

function dateOrNull(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const date = parseIsoDate(value.trim()) ?? parseIsoDatetime(value.trim().replace(/Z/g, "+00:00"));
  return date ? isoDate(date) : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

export class PgStore extends Store {
  constructor(private readonly tx: Transaction) {
    super();
  }

  transaction<T>(fn: () => Promise<T>): Promise<T> {
    return this.tx.savepoint(() => fn());
  }

  protected newId(): string {
    return uuidHex();
  }

  protected async insertRecord(namespace: string, recordId: string, payload: string, record: Json): Promise<void> {
    await storeRepo.insertRecord(this.tx, namespace, recordId, payload);
    if (namespace === QUOTE_NAMESPACE) await this.projectQuote(recordId, record);
    if (namespace === USAGE_NAMESPACE) await this.projectUsage(recordId, record);
    if (namespace === UNIT_CONVERSION_NAMESPACE) await this.projectUnitConversion(record);
  }

  protected async selectRecords(namespace: string, recordId: string | null): Promise<{ record_id: string; payload: Json }[]> {
    return storeRepo.selectRecords(this.tx, namespace, recordId);
  }

  protected async insertPrice(version: PriceVersion): Promise<string> {
    const item = version.item;
    const metadata = version.metadata ?? {};
    await storeRepo.ensureStaff(this.tx, version.confirmed_by);
    const supplierCode = typeof version.supplier_id === "string" && version.supplier_id.trim() !== "" ? version.supplier_id : null;
    if (supplierCode) await storeRepo.ensureSupplier(this.tx, supplierCode);
    const currency = pyStr(get(metadata, "currency", "JPY"));
    let conditions: Json = {};
    try {
      conditions = JSON.parse(dumps(priceConditions(version as unknown as Json))) as Json;
    } catch {
      conditions = {};
    }
    const saved = await itemsRepo.registerItemPrice(this.tx, {
      item: {
        itemCode: item.item_id,
        name: item.name,
        category: item.category as (typeof CATEGORIES)[number],
        unit: item.unit,
      },
      unitPrice: plainDecimal(item.unit_price) ?? item.unit_price,
      priceType: item.price_type as (typeof PRICE_TYPES)[number],
      source: item.source,
      updatedOn: dateOrNull(item.updated_at) ?? version.valid_from,
      supplierCode,
      validFrom: version.valid_from,
      validUntil: version.valid_until,
      status: version.status as "approved" | "pending",
      // 列の制約（3文字の大文字）に合わない通貨は XXX（通貨なし）として持ち、版の全体には原表記を残す。
      currency: /^[A-Z]{3}$/.test(currency) ? currency : "XXX",
      checkedOn: dateOrNull(get(metadata, "checked_at")),
      conditions,
      confirmedBy: version.confirmed_by,
      reason: version.reason,
    });
    await storeRepo.insertPricePayload(this.tx, saved.priceVersionId, dumps({ ...version, price_version_id: saved.priceVersionId }));
    return saved.priceVersionId;
  }

  protected async selectPrices(itemId: string | null, priceType: string | null, supplierId: string | null): Promise<PriceVersion[]> {
    const rows = await storeRepo.selectPriceRows(this.tx, { itemCode: itemId, priceType, supplierCode: supplierId });
    return rows.map((row) => {
      if (row.payload) return row.payload as unknown as PriceVersion;
      // ほかのシステム（lib/db/seed.ts など）が登録した版は列から元の形を組み立てる。
      const metadata: Json = { ...row.conditions };
      if (row.checkedOn) metadata.checked_at = row.checkedOn;
      if (row.currency !== "JPY") metadata.currency = row.currency;
      const item: Item = {
        item_id: row.itemCode,
        name: row.name,
        category: row.category,
        unit: row.unit,
        unit_price: row.unitPrice,
        price_type: row.priceType,
        source: row.source,
        updated_at: row.updatedOn,
      };
      return {
        price_version_id: row.priceVersionId,
        item,
        confirmed_by: row.confirmedBy,
        supplier_id: row.supplierCode ?? "",
        valid_from: row.validFrom,
        valid_until: row.validUntil,
        status: row.status,
        reason: row.reason,
        metadata,
      };
    });
  }

  // ---- 既存の表への写し ----

  private async projectQuote(quoteId: string, record: Json): Promise<void> {
    const rawLines = Array.isArray(record.lines) ? record.lines : [];
    const seen = new Set<string>();
    const lines: storeRepo.QuoteProjectionLine[] = [];
    for (const raw of rawLines) {
      if (!isDict(raw)) continue;
      const lineId = text(raw.quote_line_id);
      const quantity = plainDecimal(raw.quantity);
      const unitPrice = plainDecimal(get(raw, "unit_price_snapshot", get(raw, "unit_price")));
      const amount = plainDecimal(raw.line_total);
      // 列の制約に合わない行（数値の不備・行IDの重複）は写さず、items_records の記録だけに残す。
      if (!lineId || seen.has(lineId) || quantity === null || unitPrice === null || amount === null) continue;
      seen.add(lineId);
      lines.push({
        lineId,
        kind: raw.category === "部品" ? "parts" : "materials",
        category: text(raw.category),
        description: text(raw.name) ?? lineId,
        unit: typeof raw.unit === "string" ? raw.unit : "",
        quantity,
        unitPrice,
        amount,
        itemCode: text(raw.item_id),
        priceVersionId: text(raw.price_version_id),
        snapshotJson: dumps(raw),
      });
    }
    let subtotal = plainDecimal(record.subtotal);
    if (subtotal === null) {
      subtotal = lines.reduce((sum, line) => sum.add(Decimal.parse(line.amount)), Decimal.parse("0")).toPlainString();
    }
    const tax = plainDecimal(record.tax) ?? "0";
    const total = plainDecimal(record.total) ?? Decimal.parse(subtotal).add(Decimal.parse(tax)).toPlainString();
    await storeRepo.projectQuote(this.tx, {
      quoteId,
      isSimulator: record.simulator === true,
      confirmedBy: text(record.confirmed_by),
      asOf: dateOrNull(record.as_of),
      subtotal,
      tax,
      total,
      snapshotJson: dumps(record),
      lines,
    });
  }

  private async projectUsage(recordId: string, record: Json): Promise<void> {
    const quoteId = text(record.quote_id);
    const lineId = text(record.quote_line_id);
    const estimated = plainDecimal(record.estimated_qty);
    const actual = plainDecimal(record.actual_qty);
    const reason = text(record.reason);
    const confirmedBy = text(record.confirmed_by);
    if (!quoteId || !lineId || estimated === null || actual === null || !reason || !confirmedBy) return;
    await storeRepo.projectMaterialUsage(this.tx, {
      usageId: recordId,
      quoteId,
      lineId,
      estimated,
      actual,
      unit: typeof record.unit === "string" ? record.unit : "",
      reason,
      confirmedBy,
      isSimulator: record.simulator === true,
    });
  }

  private async projectUnitConversion(record: Json): Promise<void> {
    const itemCode = text(record.item_id);
    const fromUnit = text(record.source_unit);
    const toUnit = text(record.base_unit);
    const factor = plainDecimal(record.factor);
    const confirmedBy = text(record.confirmed_by);
    if (!itemCode || !fromUnit || !toUnit || factor === null || factor.replace(/[0.]/g, "") === "" || !confirmedBy) return;
    await storeRepo.projectUnitConversion(this.tx, { itemCode, fromUnit, toUnit, factor, confirmedBy });
  }
}
