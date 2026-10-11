// M04: 仕入先別価格レコード（m04.py の移植）。送料・税・納期・通貨が一致する場合だけ比較する。
import { Decimal } from "./decimal";
import {
  DEMO_DATE,
  ValidationError,
  approvedBy,
  dateValue,
  decimalValue,
  demoItem,
  textValue,
  validateItem,
  type Json,
  type PriceVersion,
  type Store,
} from "./core";
import { get, isDict, pyEqual, sortedBy } from "./py";

export const SPEC = {
  idea_id: "M04",
  title: "仕入先別価格レコード",
  description: "同一品目の仕入先別価格を送料・税・納期条件が一致する場合だけ比較し、選択を記録します。",
  defaults: {
    action: "save_offer",
    item: demoItem("demo-paint", "仕入", "80"),
    supplier_id: "demo-supplier-a",
    freight_basis: "送料込み",
    freight_amount: "0",
    tax_basis: "税別",
    delivery_days: 2,
    checked_at: DEMO_DATE,
    confirmed_by: "架空デモ担当",
  },
};

const COMPARISON_FIELDS = ["freight_basis", "freight_amount", "tax_basis", "delivery_days", "currency"];

/** 仕入先の価格を保存するか、比較して人の選択を記録する。条件が違えば順位付けしない。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "compare_and_select");
  if (action === "save_offer") return saveOffer(payload, store);
  if (action === "compare_and_select") return compareAndSelect(payload, store);
  throw new ValidationError("action: save_offer または compare_and_select を選択してください");
}

async function saveOffer(payload: Json, store: Store): Promise<Json> {
  const item = validateItem(get(payload, "item"));
  if (item.price_type !== "仕入") {
    throw new ValidationError("price_type: 仕入価格のみ登録できます");
  }
  const supplierId = textValue(get(payload, "supplier_id"), "supplier_id");
  const confirmer = approvedBy(payload);
  const freightBasis = textValue(get(payload, "freight_basis"), "freight_basis");
  const freightAmount = decimalValue(get(payload, "freight_amount"), "freight_amount");
  const taxBasis = textValue(get(payload, "tax_basis"), "tax_basis");
  const deliveryDays = toDeliveryDays(get(payload, "delivery_days"));
  const checkedAt = dateValue(get(payload, "checked_at", item.updated_at), "checked_at");
  const currency = toCurrency(get(payload, "currency", "JPY"));
  const validFrom = dateValue(get(payload, "valid_from", item.updated_at), "valid_from");
  let validUntil = get(payload, "valid_until");
  if (validUntil !== null) validUntil = dateValue(validUntil, "valid_until");

  const version = await store.addPrice(item, confirmer, {
    supplier_id: supplierId,
    valid_from: validFrom,
    valid_until: validUntil,
    status: get(payload, "status", "approved"),
    reason: textValue(get(payload, "reason", "仕入先価格の確認"), "reason"),
    freight_basis: freightBasis,
    freight_amount: freightAmount.toString(),
    tax_basis: taxBasis,
    delivery_days: deliveryDays,
    checked_at: checkedAt,
    currency,
  });
  return offerResult(version);
}

async function compareAndSelect(payload: Json, store: Store): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const unit = textValue(get(payload, "unit"), "unit");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const rawSupplierIds = get(payload, "supplier_ids");
  if (!Array.isArray(rawSupplierIds) || rawSupplierIds.length === 0) {
    throw new ValidationError("supplier_ids: 比較する仕入先を1件以上指定してください");
  }
  const supplierIds = rawSupplierIds.map((value) => textValue(value, "supplier_id"));
  if (new Set(supplierIds).size !== supplierIds.length) {
    throw new ValidationError("supplier_ids: 重複を除いてください");
  }
  const selectedSupplierId = textValue(get(payload, "selected_supplier_id"), "selected_supplier_id");
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason", "仕入先を選択"), "reason");
  if (!supplierIds.includes(selectedSupplierId)) {
    throw new ValidationError("selected_supplier_id: 比較候補から選択してください");
  }

  const versions: PriceVersion[] = [];
  for (const supplierId of supplierIds) {
    versions.push(await store.getPrice(itemId, "仕入", { as_of: asOf, supplier_id: supplierId, unit }));
  }
  const offers = versions.map(offerResult);
  const reference = offers[0];
  for (const offer of offers.slice(1)) {
    if (COMPARISON_FIELDS.some((field) => !pyEqual(offer[field], reference[field]))) {
      throw new ValidationError("比較条件不一致: 送料・税・納期・通貨を揃えてください");
    }
  }

  const rankedOffers = sortedBy(offers, (offer) => [
    Decimal.parse((offer.item as Json).unit_price as string),
    offer.supplier_id as string,
  ]);
  const selected = offers.find((offer) => offer.supplier_id === selectedSupplierId)!;
  const conditions: Json = {};
  for (const field of COMPARISON_FIELDS) conditions[field] = selected[field];
  const selection = await store.put("supplier_price_selection", {
    item_id: itemId,
    unit,
    price_type: "仕入",
    as_of: asOf,
    supplier_id: selectedSupplierId,
    price_version_id: selected.price_version_id,
    selected_by: confirmer,
    reason,
    conditions,
  });
  return {
    item_id: itemId,
    unit,
    price_type: "仕入",
    as_of: asOf,
    offers,
    ranked_supplier_ids: rankedOffers.map((offer) => offer.supplier_id),
    selected,
    selection_record_id: selection.record_id,
    selected_by: confirmer,
    reason,
  };
}

function offerResult(version: PriceVersion): Json {
  const item = version.item;
  if (item.price_type !== "仕入") {
    throw new ValidationError("price_type: 仕入価格のみ比較できます");
  }
  const metadata = (get(version as unknown as Json, "metadata", {}) ?? {}) as Json;
  return {
    item: { ...item, unit_price: decimalValue(item.unit_price, "unit_price").toString() },
    supplier_id: textValue(get(version as unknown as Json, "supplier_id"), "supplier_id"),
    price_version_id: textValue(get(version as unknown as Json, "price_version_id"), "price_version_id"),
    freight_basis: textValue(get(metadata, "freight_basis"), "freight_basis"),
    freight_amount: decimalValue(get(metadata, "freight_amount"), "freight_amount").toString(),
    tax_basis: textValue(get(metadata, "tax_basis"), "tax_basis"),
    delivery_days: toDeliveryDays(get(metadata, "delivery_days")),
    currency: toCurrency(get(metadata, "currency", "JPY")),
    checked_at: dateValue(get(metadata, "checked_at"), "checked_at"),
    source: item.source,
    valid_from: version.valid_from,
    valid_until: version.valid_until,
    status: version.status,
  };
}

function toDeliveryDays(value: unknown): number {
  const days = decimalValue(value, "delivery_days");
  if (!days.eq(days.toIntegralValue())) {
    throw new ValidationError("delivery_days: 0以上の整数を入力してください");
  }
  return Number(days.toBigInt());
}

function toCurrency(value: unknown): string {
  const currency = textValue(value, "currency").toUpperCase();
  if ([...currency].length !== 3 || !/^[A-Za-z]+$/.test(currency)) {
    throw new ValidationError("currency: 3文字の通貨コードを入力してください");
  }
  return currency;
}
