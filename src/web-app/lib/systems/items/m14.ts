// M14: 最終確認からの経過表示（m14.py の移植）。人の確認日と出所の更新日を分けて表示する。価格は変えない。
import { DEMO_DATE, ValidationError, dateValue, demoItem, textValue, type Json, type Store } from "./core";
import { daysBetween, get, isDict, truthy } from "./py";

export const SPEC = {
  idea_id: "M14",
  title: "最終確認からの経過表示",
  description: "価格を最後に人が確認した日と経過日数を、出所の更新日と分けて表示します。",
  defaults: {
    item_id: "demo-m14-paint",
    price_type: "仕入",
    as_of: DEMO_DATE,
  },
};

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  if (Object.keys(payload).some((key) => !["item_id", "price_type", "as_of"].includes(key))) {
    throw new ValidationError("payload: item_id、price_type、as_ofだけ指定できます");
  }

  const itemId = textValue(get(payload, "item_id"), "item_id");
  const priceType = get(payload, "price_type", "仕入");
  if (priceType !== "仕入" && priceType !== "販売") {
    throw new ValidationError("price_type: 選択値を確認してください");
  }
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  let versions = await store.priceVersions(itemId, priceType);
  if (versions.length === 0) {
    if (itemId !== SPEC.defaults.item_id) {
      throw new ValidationError("価格未確認: 対象価格がありません");
    }
    // 架空の初期データは人の確認日を明示する。item.updated_at は別の出所の日付。
    const item = demoItem(itemId, priceType, "80");
    await store.addPrice(item, "架空デモ担当", { checked_at: DEMO_DATE, source_updated_at: DEMO_DATE, simulator: true });
    versions = await store.priceVersions(itemId, priceType);
  }

  const version = versions[versions.length - 1];
  const metadata = (get(version, "metadata") as Json | null) || {};
  const checkedAt = get(metadata, "checked_at");
  const sourceUpdatedAt = truthy(get(metadata, "source_updated_at")) ? get(metadata, "source_updated_at") : get(version.item, "updated_at");
  const checkedDate = optionalDate(checkedAt, "checked_at");
  const sourceDate = optionalDate(sourceUpdatedAt, "source_updated_at");
  for (const [field, parsed] of [
    ["checked_at", checkedDate],
    ["source_updated_at", sourceDate],
  ] as const) {
    if (parsed !== null && parsed > asOf) {
      throw new ValidationError(`${field}: 基準日より未来の日付です`);
    }
  }

  const elapsedDays = checkedDate !== null ? daysBetween(asOf, checkedDate) : null;
  return {
    status: checkedDate !== null ? "確認済み" : "未確認",
    item_id: itemId,
    price_type: priceType,
    human_checked_at: checkedDate,
    elapsed_days: elapsedDays,
    source_updated_at: sourceDate,
    as_of: asOf,
    message: elapsedDays !== null ? `最終人確認から${elapsedDays}日経過` : "最終人確認日は未確認です",
    simulator: truthy(get(metadata, "simulator", false)),
  };
}

function optionalDate(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  return dateValue(value, field);
}
