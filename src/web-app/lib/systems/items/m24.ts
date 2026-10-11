// M24: 品目の承認済み価格版を、条件が一致するものだけ時系列で示す（m24.py の移植）。
import { DEMO_DATE, ValidationError, approvedBy, demoItem, textValue, type Json, type PriceVersion, type Store } from "./core";
import { dumps, get, isDict, pyEqual, sortedBy } from "./py";

export const SPEC = {
  idea_id: "M24",
  title: "価格履歴タイムライン",
  description: "同一品目・単位・価格区分・仕入先・取引条件の価格版を時系列で確認します。",
  defaults: {
    action: "timeline",
    item_id: "demo-paint",
    unit: "ml",
    price_type: "販売",
    supplier_id: "",
    transaction_conditions: {},
  },
};

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "timeline");
  if (action === "seed_demo") {
    checkKeys(payload, ["action", "item_id", "unit", "price_type", "supplier_id", "transaction_conditions", "confirmed_by"]);
    await seedDemo(payload, store);
    return timeline(payload, store);
  }
  if (action === "timeline") {
    checkKeys(payload, ["action", "item_id", "unit", "price_type", "supplier_id", "transaction_conditions"]);
    return timeline(payload, store);
  }
  throw new ValidationError("action: timeline / seed_demo を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

function criteria(payload: Json): [string, string, string, string, Json] {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const unit = textValue(get(payload, "unit"), "unit");
  const priceType = textValue(get(payload, "price_type"), "price_type");
  if (priceType !== "仕入" && priceType !== "販売") {
    throw new ValidationError("price_type: 仕入 / 販売を選択してください");
  }
  const supplierId = get(payload, "supplier_id", "");
  if (typeof supplierId !== "string") {
    throw new ValidationError("supplier_id: 文字列を指定してください");
  }
  const conditions = get(payload, "transaction_conditions", {});
  if (!isDict(conditions)) {
    throw new ValidationError("transaction_conditions: 条件の集合を指定してください");
  }
  return [itemId, unit, priceType, supplierId, conditions];
}

async function seedDemo(payload: Json, store: Store): Promise<void> {
  const [itemId, unit, priceType, supplierId, conditions] = criteria(payload);
  const confirmer = approvedBy(payload);
  if (!pyEqual([itemId, unit, priceType, supplierId, conditions], ["demo-paint", "ml", "販売", "", {}])) {
    throw new ValidationError("seed_demo: 架空デモ条件を指定してください");
  }
  if ((await store.priceVersions(itemId, priceType, supplierId)).length > 0) return;
  for (const [effectiveDate, amount, checkedAt] of [
    ["2026-08-01", "110", "2026-08-02"],
    [DEMO_DATE, "120", DEMO_DATE],
  ]) {
    const item = demoItem(itemId, priceType, amount, unit);
    item.updated_at = effectiveDate;
    item.source = "simulator:架空価格履歴";
    await store.addPrice(item, confirmer, {
      supplier_id: supplierId,
      valid_from: effectiveDate,
      checked_at: checkedAt,
      transaction_conditions: conditions,
    });
  }
}

async function timeline(payload: Json, store: Store): Promise<Json> {
  const [itemId, unit, priceType, supplierId, conditions] = criteria(payload);
  const allVersions = await store.priceVersions(itemId);
  const matching: [number, PriceVersion][] = [];
  const otherGroups = new Map<string, { key: [unknown, unknown, unknown, string]; rows: PriceVersion[] }>();
  for (const [index, version] of allVersions.entries()) {
    const v = version as unknown as Json;
    const item = get(v, "item", {}) as Json;
    const metadata = get(v, "metadata", {}) as Json;
    const versionConditions = get(metadata, "transaction_conditions", {});
    const groupKey: [unknown, unknown, unknown, string] = [
      get(item, "unit"),
      get(item, "price_type"),
      get(v, "supplier_id", ""),
      dumps(versionConditions),
    ];
    if (pyEqual(groupKey.slice(0, 3), [unit, priceType, supplierId]) && groupKey[3] === dumps(conditions)) {
      if (get(v, "status") === "approved") matching.push([index, version]);
    } else {
      const mapKey = JSON.stringify(groupKey);
      if (!otherGroups.has(mapKey)) otherGroups.set(mapKey, { key: groupKey, rows: [] });
      otherGroups.get(mapKey)!.rows.push(version);
    }
  }
  const sorted = sortedBy(matching, (pair) => [pair[1].valid_from, pair[0]]);
  const versions = sorted.map(([, version]) => versionRow(version));
  const result: Json = {
    item_id: itemId,
    unit,
    price_type: priceType,
    supplier_id: supplierId,
    transaction_conditions: conditions,
    versions,
    comparison: "同一条件の履歴表示。相場を代表する値ではありません。",
    simulator: versions.some((row) => (row.source as string).startsWith("simulator:")),
  };
  if (versions.length === 0) {
    result.unknowns = ["指定条件に一致する承認済み価格履歴がありません"];
  }
  if (otherGroups.size > 0) {
    result.incomparable_groups = [...otherGroups.values()].map(({ key, rows }) => ({
      unit: key[0] ?? null,
      price_type: key[1] ?? null,
      supplier_id: key[2],
      transaction_conditions: JSON.parse(key[3]),
      reason: "単位・価格区分・仕入先・取引条件の不一致により比較対象外",
      versions: rows.filter((version) => get(version as unknown as Json, "status") === "approved").map(versionRow),
    }));
  }
  return result;
}

function versionRow(version: PriceVersion): Json {
  const v = version as unknown as Json;
  const item = version.item;
  const metadata = get(v, "metadata", {}) as Json;
  return {
    price_version_id: version.price_version_id,
    item_id: item.item_id,
    unit: item.unit,
    price_type: item.price_type,
    amount: item.unit_price,
    supplier_id: get(v, "supplier_id", ""),
    transaction_conditions: get(metadata, "transaction_conditions", {}),
    source: item.source,
    confirmed_by: version.confirmed_by,
    checked_at: get(metadata, "checked_at", item.updated_at),
    valid_from: version.valid_from,
    valid_until: get(v, "valid_until"),
    status: version.status,
  };
}
