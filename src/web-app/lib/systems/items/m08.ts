// M08: クイック価格変更（m08.py の移植）。差分を確認してから、人が確定した新しい価格版を追記する。
import { DEMO_DATE, PRICE_TYPES, ValidationError, approvedBy, dateValue, decimalValue, textValue, type Item, type Json, type PriceVersion, type Store } from "./core";
import { casefold, get, isDict, maxBy, sortedBy } from "./py";

export const SPEC = {
  idea_id: "M08",
  title: "クイック価格変更",
  description: "品目と価格区分を検索し、差分を確認してから新しい価格版を追記します。",
  defaults: {
    action: "preview_change",
    item_id: "demo-paint",
    price_type: "販売",
    new_price: "130",
    reason: "架空デモ価格の見直し",
    source: "simulator:架空値、架空価格票で確認",
    checked_at: DEMO_DATE,
    confirmed_by: "架空デモ担当",
  },
};

type Values = { item: Item; supplier_id: string; checked_at: string; reason: string; confirmed_by: string };
type Preview = Json & { current_price_version_id: string; _values: Values };

function withoutValues(preview: Preview): Json {
  const copy: Json = { ...preview };
  delete copy._values;
  return copy;
}

/**
 * 検索・プレビュー・確定。プレビューは読むだけ。confirm_change は検査をやり直し、
 * プレビューで見た版を要求して、その間に別の人が変えた価格を上書きしない。
 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "preview_change");
  if (action === "search_items") return searchItems(payload, store);
  if (action === "preview_change" || action === "confirm_change") {
    const preview = await previewChange(payload, store);
    if (action === "preview_change") return withoutValues(preview);
    const expectedVersionId = textValue(get(payload, "expected_price_version_id"), "expected_price_version_id");
    if (expectedVersionId !== preview.current_price_version_id) {
      throw new ValidationError("価格がプレビュー後に変更されています: 再確認してください");
    }
    const values = preview._values;
    return store.transaction(async () => {
      // 人が見た版に対して追記するよう、トランザクションの中でもう一度確かめる。
      const latestPreview = await previewChange(payload, store);
      if (latestPreview.current_price_version_id !== expectedVersionId) {
        throw new ValidationError("価格がプレビュー後に変更されています: 再確認してください");
      }
      const version = await store.addPrice(values.item, values.confirmed_by, {
        supplier_id: values.supplier_id,
        valid_from: values.checked_at,
        reason: values.reason,
        checked_at: values.checked_at,
      });
      return savedResult(latestPreview, version);
    });
  }
  throw new ValidationError("action: search_items / preview_change / confirm_change を選択してください");
}

async function searchItems(payload: Json, store: Store): Promise<Json> {
  const query = casefold(textValue(get(payload, "query"), "query"));
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const priceType = get(payload, "price_type");
  if (priceType !== null && !(PRICE_TYPES as readonly unknown[]).includes(priceType)) {
    throw new ValidationError("price_type: 仕入または販売を選択してください");
  }

  // 品目×価格区分×仕入先ごとに、承認済みの最新の版を1件返す。
  const latestByKey = new Map<string, PriceVersion>();
  for (const version of await store.priceVersions()) {
    const item = version.item;
    if (version.status !== "approved" || version.valid_from > asOf) continue;
    if (priceType !== null && item.price_type !== priceType) continue;
    if (!casefold(item.item_id).includes(query) && !casefold(item.name).includes(query)) continue;
    const key = JSON.stringify([item.item_id, item.price_type, version.supplier_id]);
    const previous = latestByKey.get(key);
    if (previous === undefined || version.valid_from >= previous.valid_from) {
      latestByKey.set(key, version);
    }
  }

  const candidates = sortedBy(
    [...latestByKey.values()].map((version) => ({
      item: version.item,
      price_type: version.item.price_type,
      supplier_id: version.supplier_id,
      price_version_id: version.price_version_id,
      valid_from: version.valid_from,
      valid_until: version.valid_until,
    })),
    (candidate) => [candidate.item.name, candidate.item.item_id, candidate.price_type, candidate.supplier_id],
  );
  return {
    query: textValue(get(payload, "query"), "query"),
    as_of: asOf,
    candidates,
    items: candidates.map((candidate) => candidate.item),
    simulator: true,
  };
}

async function previewChange(payload: Json, store: Store): Promise<Preview> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const priceType = textValue(get(payload, "price_type"), "price_type");
  if (!(PRICE_TYPES as readonly string[]).includes(priceType)) {
    throw new ValidationError("price_type: 仕入または販売を選択してください");
  }
  let supplierId = get(payload, "supplier_id") as string | null;
  if (supplierId !== null && supplierId !== "") {
    supplierId = textValue(supplierId, "supplier_id");
  }
  const reason = textValue(get(payload, "reason"), "reason");
  const source = textValue(get(payload, "source"), "source");
  const checkedAt = dateValue(get(payload, "checked_at"), "checked_at");
  const confirmer = approvedBy(payload);
  const newPrice = decimalValue(get(payload, "new_price"), "new_price", { positive: true });

  const allVersions = (await store.priceVersions(itemId, priceType, supplierId)).filter((version) => version.status === "approved");
  const suppliers = new Set(allVersions.map((version) => version.supplier_id));
  if (supplierId === null && suppliers.size > 1) {
    throw new ValidationError("supplier_id: 仕入先の選択が必要です");
  }
  const latestOf = (versions: PriceVersion[]) =>
    maxBy(
      versions.map((entry, index) => ({ entry, index })),
      (pair) => [pair.entry.valid_from, pair.index],
    ).entry;
  if (allVersions.length > 0) {
    const latestVersion = latestOf(allVersions);
    if (checkedAt < latestVersion.valid_from) {
      throw new ValidationError("checked_at: 現行価格の開始日以降を指定してください");
    }
  }
  const versions = allVersions.filter((version) => version.valid_from <= checkedAt);
  if (versions.length === 0) {
    throw new ValidationError("価格未確認: 変更対象の承認済み価格がありません");
  }
  const current = latestOf(versions);

  const oldPrice = decimalValue(current.item.unit_price, "unit_price");
  const difference = newPrice.sub(oldPrice, { prec: 80 });
  const newItem: Item = { ...current.item, unit_price: newPrice.toString(), source, updated_at: checkedAt };
  return {
    status: "preview",
    item: newItem,
    items: [newItem],
    item_id: itemId,
    price_type: priceType,
    supplier_id: current.supplier_id,
    unit: current.item.unit,
    current_price: oldPrice.toString(),
    new_price: newPrice.toString(),
    difference: difference.toString(),
    direction: difference.gt(0) ? "increase" : difference.lt(0) ? "decrease" : "unchanged",
    reason,
    source,
    checked_at: checkedAt,
    confirmed_by: confirmer,
    current_price_version_id: current.price_version_id,
    requires_confirmation: true,
    simulator: current.item.source.startsWith("simulator:") || source.startsWith("simulator:"),
    _values: {
      item: newItem,
      supplier_id: current.supplier_id,
      checked_at: checkedAt,
      reason,
      confirmed_by: confirmer,
    },
  };
}

function savedResult(preview: Preview, version: PriceVersion): Json {
  const item = version.item;
  return {
    ...withoutValues(preview),
    status: "saved",
    item,
    items: [item],
    price_version_id: version.price_version_id,
    previous_price_version_id: preview.current_price_version_id,
    requires_confirmation: false,
    confirmed_by: version.confirmed_by,
  };
}
