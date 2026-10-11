// M03: 仕入・販売の二列価格（m03.py の移植）。仕入価格から販売価格を自動計算しない。
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, textValue, validateItem, type Json, type Store } from "./core";
import { get, isDict, pyStrip } from "./py";

export const SPEC = {
  idea_id: "M03",
  title: "仕入・販売の二列価格",
  description:
    "同一品目の仕入価格と販売価格を独立して保存・参照します。販売価格が未登録なら見積利用を停止し、仕入価格から販売価格を自動計算しません。",
  defaults: {
    action: "get_price",
    item_id: "demo-paint",
    price_type: "販売",
    as_of: DEMO_DATE,
  },
};

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "get_price");
  if (action === "save_price") return savePrice(payload, store);
  if (action === "get_price") return getPrice(payload, store);
  throw new ValidationError("action: save_price または get_price を選択してください");
}

function currencyCode(value: unknown): string {
  const currency = textValue(value, "currency").toUpperCase();
  if ([...currency].length !== 3 || !/^[A-Za-z]+$/.test(currency)) {
    throw new ValidationError("currency: 3文字の通貨コードを入力してください");
  }
  return currency;
}

async function savePrice(payload: Json, store: Store): Promise<Json> {
  const item = validateItem(get(payload, "item"));
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason", "価格登録"), "reason");
  const supplierId = get(payload, "supplier_id", "");
  if (typeof supplierId !== "string") {
    throw new ValidationError("supplier_id: 文字列を入力してください");
  }
  const validFrom = dateValue(get(payload, "valid_from", item.updated_at), "valid_from");
  let validUntil = get(payload, "valid_until");
  if (validUntil !== null) validUntil = dateValue(validUntil, "valid_until");
  const currency = currencyCode(get(payload, "currency", "JPY"));

  const version = await store.addPrice(item, confirmer, {
    supplier_id: pyStrip(supplierId),
    valid_from: validFrom,
    valid_until: validUntil,
    status: get(payload, "status", "approved"),
    reason,
    currency,
  });
  return {
    item: version.item,
    price_version_id: version.price_version_id,
    confirmed_by: version.confirmed_by,
    valid_from: version.valid_from,
    valid_until: version.valid_until,
    status: version.status,
    reason: version.reason,
    currency: version.metadata.currency,
  };
}

async function getPrice(payload: Json, store: Store): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const priceType = get(payload, "price_type", "販売");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  let supplierId = get(payload, "supplier_id") as string | null;
  let unit = get(payload, "unit") as string | null;
  if (supplierId !== null) supplierId = textValue(supplierId, "supplier_id");
  if (unit !== null) unit = textValue(unit, "unit");

  const version = await store.getPrice(itemId, priceType, { as_of: asOf, supplier_id: supplierId, unit });
  // 返すのは保存済みの承認価格そのもの。掛率は適用しない。
  const item = { ...version.item, unit_price: decimalValue(version.item.unit_price, "unit_price").toString() };
  return {
    item,
    price_version_id: version.price_version_id,
    confirmed_by: version.confirmed_by,
    valid_from: version.valid_from,
    valid_until: version.valid_until,
    status: version.status,
    reason: version.reason,
    currency: get(version.metadata, "currency", "JPY"),
  };
}
