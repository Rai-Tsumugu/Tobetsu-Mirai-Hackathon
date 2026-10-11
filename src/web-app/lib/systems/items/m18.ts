// m18.py の移植: 条件付き価格を別に保存し、すべての条件が一致したときだけ見積候補にする。
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, textValue, type Json, type Store } from "./core";
import { get, isDict } from "./py";

export const SPEC = {
  idea_id: "M18",
  title: "期限条件付き価格",
  description: "数量・期間・単位が一致した場合だけ条件付き価格を見積候補として返します。",
  defaults: {
    action: "apply",
    item_id: "demo-m18-paint",
    quantity: "5",
    unit: "缶",
    price_type: "仕入",
    as_of: DEMO_DATE,
  } as Json,
};

export const NAMESPACE = "conditional_price";

/** 条件の記録、一覧、または検証して見積候補を返す。通常の価格表には入れない。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "apply");
  if (action === "record") {
    checkKeys(payload, ["action", "item_id", "unit_price", "min_qty", "unit", "valid_from", "valid_until", "price_type", "source", "confirmed_by"]);
    return record(payload, store);
  }
  if (action === "list" || action === "apply") {
    checkKeys(payload, ["action", "item_id", "quantity", "unit", "price_type", "as_of"]);
    return evaluate(payload, store, action === "apply");
  }
  throw new ValidationError("action: record / list / apply を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

async function record(payload: Json, store: Store): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const unit = textValue(get(payload, "unit"), "unit");
  const priceType = get(payload, "price_type");
  if (priceType !== "仕入") {
    throw new ValidationError("price_type: 条件付き特価は仕入価格のみ登録できます");
  }
  const unitPrice = decimalValue(get(payload, "unit_price"), "unit_price", { positive: true });
  const minQty = decimalValue(get(payload, "min_qty"), "min_qty", { positive: true });
  const validFrom = dateValue(get(payload, "valid_from"), "valid_from");
  const validUntil = dateValue(get(payload, "valid_until"), "valid_until");
  if (validUntil < validFrom) {
    throw new ValidationError("valid_until: 開始日より前です");
  }
  const source = textValue(get(payload, "source"), "source");
  const confirmer = approvedBy(payload);
  const row = {
    item_id: itemId,
    unit_price: unitPrice.toString(),
    min_qty: minQty.toString(),
    unit,
    valid_from: validFrom,
    valid_until: validUntil,
    price_type: priceType,
    source,
    confirmed_by: confirmer,
  };
  const saved = await store.put(NAMESPACE, row);
  return { status: "saved", conditional_price_id: saved.record_id, conditional_price: row, simulator: false };
}

async function evaluate(payload: Json, store: Store, apply: boolean): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const quantity = decimalValue(get(payload, "quantity"), "quantity", { positive: true });
  const unit = textValue(get(payload, "unit"), "unit");
  const priceType = get(payload, "price_type", "仕入");
  if (priceType !== "仕入") {
    throw new ValidationError("price_type: 条件付き特価は仕入価格のみ対象です");
  }
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  let rows = await store.records(NAMESPACE);
  if (rows.length === 0 && itemId === SPEC.defaults.item_id) {
    await record(
      {
        item_id: itemId,
        unit_price: "6800",
        min_qty: "5",
        unit: "缶",
        valid_from: "2026-10-01",
        valid_until: "2026-10-31",
        price_type: "仕入",
        source: "simulator:架空仕入条件",
        confirmed_by: "架空デモ担当",
      },
      store,
    );
    rows = await store.records(NAMESPACE);
  }
  const matching = rows.filter((row) => row.item_id === itemId);
  if (matching.length === 0) {
    throw new ValidationError("条件付き価格未確認: 対象価格がありません");
  }
  const results: Json[] = [];
  const eligible: Json[] = [];
  for (const row of matching) {
    const terms =
      (row.valid_from as string) <= asOf &&
      asOf <= (row.valid_until as string) &&
      quantity.gte(decimalValue(row.min_qty)) &&
      unit === row.unit &&
      priceType === row.price_type;
    const status = terms ? "条件一致" : "条件不一致";
    const result = {
      conditional_price_id: row.record_id,
      item_id: itemId,
      unit_price: row.unit_price,
      min_qty: row.min_qty,
      unit: row.unit,
      valid_from: row.valid_from,
      valid_until: row.valid_until,
      price_type: row.price_type,
      source: row.source,
      confirmed_by: row.confirmed_by,
      as_of: asOf,
      requested_quantity: quantity.toString(),
      requested_unit: unit,
      status,
    };
    results.push(result);
    if (terms) eligible.push(result);
  }
  if (apply && eligible.length === 0) {
    throw new ValidationError("条件不一致: 数量・期間・単位を確認してください。通常価格を確認してください");
  }
  const response: Json = {
    item_id: itemId,
    price_type: priceType,
    as_of: asOf,
    conditional_prices: results,
    simulator: matching.some((row) => (row.source as string).startsWith("simulator:")),
  };
  if (apply) {
    response.quote_candidate = { ...eligible[eligible.length - 1] };
  }
  return response;
}
