// m20.py の移植: 承認済みの面積帯ごとの使用量幅と、同じ単位の承認済み価格から金額の幅を示す。
import { Decimal } from "./decimal";
import { DEMO_DATE, ValidationError, dateValue, decimalValue, textValue, type Json, type PriceVersion, type Store, type StoredRecord } from "./core";
import { get, isDict, sortedBy, truthy } from "./py";

export const SPEC = {
  idea_id: "M20",
  title: "面積帯の使用量目安",
  description: "工場承認済みの面積帯ごとの使用量幅と、同単位の承認済み価格から候補幅を表示します。",
  defaults: {
    action: "record",
    item_id: "demo-m20-paint",
    area_band: "架空の小面積",
    low_qty: "10",
    typical_qty: "15",
    high_qty: "20",
    unit: "ml",
    evidence: "simulator:架空デモ用の仮定値",
    approved_by: "架空デモ担当",
    reason: "架空デモデータ",
  } as Json,
};

export const NAMESPACE = "usage_band";

/** 承認済みの使用量帯の記録・一覧・金額幅の候補。読取・試算では品目や価格を作らない。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "estimate");
  if (action === "record") {
    checkKeys(payload, ["action", "item_id", "area_band", "low_qty", "typical_qty", "high_qty", "unit", "evidence", "approved_by", "reason"]);
    return record(payload, store);
  }
  if (action === "list") {
    checkKeys(payload, ["action", "item_id", "area_band"]);
    return list(payload, store);
  }
  if (action === "estimate") {
    checkKeys(payload, ["action", "item_id", "area_band", "price_type", "as_of"]);
    return estimate(payload, store);
  }
  throw new ValidationError("action: record / list / estimate を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

async function record(payload: Json, store: Store): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const areaBand = textValue(get(payload, "area_band"), "area_band");
  const unit = textValue(get(payload, "unit"), "unit");
  const lowQty = decimalValue(get(payload, "low_qty"), "low_qty");
  const typicalQty = decimalValue(get(payload, "typical_qty"), "typical_qty");
  const highQty = decimalValue(get(payload, "high_qty"), "high_qty");
  if (!(lowQty.lte(typicalQty) && typicalQty.lte(highQty))) {
    throw new ValidationError("数量帯: low_qty <= typical_qty <= high_qty の順にしてください");
  }
  const evidence = textValue(get(payload, "evidence"), "evidence");
  const confirmer = textValue(get(payload, "approved_by"), "approved_by");
  const reason = textValue(get(payload, "reason"), "reason");
  const row = {
    item_id: itemId,
    area_band: areaBand,
    low_qty: lowQty.toString(),
    typical_qty: typicalQty.toString(),
    high_qty: highQty.toString(),
    unit,
    evidence,
    approved_by: confirmer,
    status: "approved",
    reason,
  };
  const saved = await store.put(NAMESPACE, row, `${itemId}:${areaBand}`);
  return { status: "saved", usage_band: saved, simulator: evidence.startsWith("simulator:") };
}

async function list(payload: Json, store: Store): Promise<Json> {
  let itemId = get(payload, "item_id") as string | null;
  let areaBand = get(payload, "area_band") as string | null;
  if (itemId !== null) itemId = textValue(itemId, "item_id");
  if (areaBand !== null) areaBand = textValue(areaBand, "area_band");
  const bands = new Map<string, StoredRecord>();
  for (const row of await store.records(NAMESPACE)) {
    if (itemId !== null && row.item_id !== itemId) continue;
    if (areaBand !== null && row.area_band !== areaBand) continue;
    bands.set(JSON.stringify([row.item_id, row.area_band]), row);
  }
  const rows = sortedBy([...bands.values()], (row) => [row.item_id as string, row.area_band as string]);
  return { usage_bands: rows, simulator: rows.some((row) => (row.evidence as string).startsWith("simulator:")) };
}

async function estimate(payload: Json, store: Store): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const areaBand = textValue(get(payload, "area_band"), "area_band");
  const priceType = get(payload, "price_type", "販売");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const candidates = (await store.records(NAMESPACE)).filter((row) => row.item_id === itemId && row.area_band === areaBand);
  const band = candidates.length > 0 ? candidates[candidates.length - 1] : null;
  if (band === null || get(band, "status") !== "approved" || !truthy(get(band, "approved_by"))) {
    return unknown(itemId, areaBand, "承認済みの使用量目安がありません");
  }

  // 保存済みのデータも検査し直す（古い記録や手で入れた記録で検査を抜けない）。
  let quantities: Decimal[];
  let unit: string;
  let evidence: string;
  try {
    quantities = (["low_qty", "typical_qty", "high_qty"] as const).map((field) => decimalValue(get(band, field), field));
    if (!(quantities[0].lte(quantities[1]) && quantities[1].lte(quantities[2]))) {
      throw new ValidationError("数量帯の順序が不正です");
    }
    unit = textValue(get(band, "unit"), "unit");
    evidence = textValue(get(band, "evidence"), "evidence");
  } catch (error) {
    if (!(error instanceof ValidationError)) throw error;
    return unknown(itemId, areaBand, "使用量の単位・数量・根拠を確認してください");
  }

  let version: PriceVersion;
  try {
    version = await store.getPrice(itemId, priceType, { as_of: asOf, unit });
  } catch (error) {
    if (!(error instanceof ValidationError)) throw error;
    return unknown(itemId, areaBand, "同じ単位の承認済み価格がありません", unit);
  }
  const unitPrice = Decimal.parse(version.item.unit_price);
  const amounts = quantities.map((qty) => qty.mul(unitPrice, { prec: 60 }));
  return {
    status: "needs_human_confirmation",
    item_id: itemId,
    area_band: areaBand,
    quantity: {
      low: quantities[0].toString(),
      typical: quantities[1].toString(),
      high: quantities[2].toString(),
      unit,
      evidence,
      approved_by: band.approved_by,
    },
    price: { unit_price: version.item.unit_price, unit, price_type: priceType, price_version_id: version.price_version_id },
    candidate_amount: { low: amounts[0].toString(), typical: amounts[1].toString(), high: amounts[2].toString(), currency: "JPY" },
    unknowns: [],
    simulator: evidence.startsWith("simulator:") || version.item.source.startsWith("simulator:"),
  };
}

function unknown(itemId: string, areaBand: string, reason: string, unit: string | null = null): Json {
  return {
    status: "needs_human_input",
    item_id: itemId,
    area_band: areaBand,
    quantity: null,
    unit,
    candidate_amount: null,
    unknowns: [reason],
    simulator: false,
  };
}
