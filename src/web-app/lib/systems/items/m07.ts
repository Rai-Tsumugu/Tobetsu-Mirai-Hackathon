// M07: 単品価格入力フォーム（m07.py の移植）。1品目ずつ確認者付きで登録し、承認済みの品目を検索する。
import { CATEGORIES, DEMO_DATE, ITEM_FIELDS, PRICE_TYPES, ValidationError, approvedBy, dateValue, textValue, validateItem, type Item, type Json, type Store } from "./core";
import { casefold, get, isDict, pyStrip, sortedBy, compareKeys } from "./py";

export const SPEC = {
  idea_id: "M07",
  title: "単品価格入力フォーム",
  description: "品目と価格を一件ずつ確認者付きで登録し、承認済みの有効な品目価格を検索・一覧表示します。",
  defaults: {
    action: "register",
    item_id: "demo-m07-brake-pad",
    name: "架空サンプルブレーキパッド",
    category: "部品",
    unit: "個",
    unit_price: "2400",
    price_type: "販売",
    source: "simulator:架空値",
    updated_at: DEMO_DATE,
    confirmed_by: "架空デモ担当",
    reason: "単品価格の初回確認",
    as_of: DEMO_DATE,
    query: "",
    category_filter: "",
    price_type_filter: "",
  },
};

function pickItem(item: Item): Item {
  const out: Record<string, string> = {};
  for (const field of ITEM_FIELDS) out[field] = item[field];
  return out as Item;
}

/** 確認済みの価格を1件登録するか、有効な承認済みカタログを検索する。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "register");
  if (action === "register") return register(payload, store);
  if (action === "search" || action === "list") return search(payload, store);
  throw new ValidationError("action: register、search、list のいずれかを指定してください");
}

async function register(payload: Json, store: Store): Promise<Json> {
  // SPEC の平らな形と、共通品目のオブジェクトの両方を受け付ける。
  const itemInput = get(payload, "item", payload);
  const item = validateItem(itemInput);
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason", "単品価格の登録"), "reason");
  const validFrom = dateValue(get(payload, "valid_from", item.updated_at), "valid_from");
  let validUntil: unknown = get(payload, "valid_until");
  if (validUntil !== null && validUntil !== "") {
    validUntil = dateValue(validUntil, "valid_until");
  } else {
    validUntil = null;
  }

  const version = await store.addPrice(item, confirmer, {
    valid_from: validFrom,
    valid_until: validUntil,
    reason,
    currency: "JPY",
  });
  const registeredItem = pickItem(version.item);
  return {
    status: version.status,
    item: registeredItem,
    items: [registeredItem],
    price_version_id: version.price_version_id,
    confirmed_by: version.confirmed_by,
    reason: version.reason,
    valid_from: version.valid_from,
    valid_until: version.valid_until,
    currency: version.metadata.currency,
  };
}

async function search(payload: Json, store: Store): Promise<Json> {
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const query = casefold(optionalText(get(payload, "query", ""), "query"));
  const category = optionalText(get(payload, "category_filter", ""), "category_filter");
  const priceType = optionalText(get(payload, "price_type_filter", ""), "price_type_filter");
  if (category && !(CATEGORIES as readonly string[]).includes(category)) {
    throw new ValidationError("category_filter: 選択値を確認してください");
  }
  if (priceType && !(PRICE_TYPES as readonly string[]).includes(priceType)) {
    throw new ValidationError("price_type_filter: 選択値を確認してください");
  }

  // 品目×価格区分ごとに、有効な承認済みの最新版を残す。
  // 共通品目の項目に仕入先はないため、仕入先別の行は区別できる一覧にしない。
  const activeByKey = new Map<string, { rank: [string, number]; item: Item }>();
  const versions = await store.priceVersions();
  for (const [sequence, version] of versions.entries()) {
    if (version.status !== "approved" || version.valid_from > asOf) continue;
    if (version.valid_until !== null && asOf > version.valid_until) continue;
    const item = version.item;
    const key = JSON.stringify([item.item_id, item.price_type]);
    const prior = activeByKey.get(key);
    const rank: [string, number] = [version.valid_from, sequence];
    if (prior === undefined || compareKeys(rank, prior.rank) > 0) {
      activeByKey.set(key, { rank, item });
    }
  }

  const items: Item[] = [];
  for (const { item } of activeByKey.values()) {
    if (category && item.category !== category) continue;
    if (priceType && item.price_type !== priceType) continue;
    const searchable = casefold([item.item_id, item.name, item.source].join(" "));
    if (query && !searchable.includes(query)) continue;
    items.push(pickItem(item));
  }
  const sorted = sortedBy(items, (item) => [casefold(item.name), item.item_id, item.price_type]);
  return { as_of: asOf, count: sorted.length, items: sorted };
}

function optionalText(value: unknown, field: string): string {
  if (value === null || value === undefined) return "";
  if (typeof value !== "string") {
    throw new ValidationError(`${field}: 文字列を入力してください`);
  }
  return pyStrip(value);
}
