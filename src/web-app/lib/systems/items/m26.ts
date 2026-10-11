// M26: 仕入・販売の旧新価格版から粗利の変化を試算する。価格は変えない（m26.py の移植）。
import { DEMO_DATE, ValidationError, approvedBy, decimalValue, demoItem, textValue, type Json, type PriceVersion, type Store } from "./core";
import { Decimal } from "./decimal";
import { get, isDict, pyEqual, truthy, uuidHex } from "./py";

export const SPEC = {
  idea_id: "M26",
  title: "材料粗利影響試算",
  description: "同一条件の旧・新仕入/販売価格版から、数量に応じた粗利差を試算します。",
  defaults: {
    action: "seed_demo",
    item_id: "demo-paint",
    unit: "ml",
    quantity: "10",
    transaction_conditions: {},
    confirmed_by: "架空デモ担当",
  },
};

export const NAMESPACE = "gross_margin_simulation";
const ROLE_TYPES: [string, string][] = [
  ["old_purchase", "仕入"],
  ["old_sales", "販売"],
  ["new_purchase", "仕入"],
  ["new_sales", "販売"],
];

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "simulate");
  if (action === "seed_demo") {
    checkKeys(payload, ["action", "item_id", "unit", "quantity", "transaction_conditions", "confirmed_by"]);
    const ids = await seedDemo(payload, store);
    return simulate({ ...payload, ...ids }, store, true);
  }
  if (action === "simulate") {
    checkKeys(payload, ["action", "item_id", "unit", "quantity", "transaction_conditions", ...ROLE_TYPES.map(([role]) => role), "confirmed_by"]);
    return simulate(payload, store, false);
  }
  if (action === "list") {
    checkKeys(payload, ["action"]);
    const rows = await store.records(NAMESPACE);
    return {
      simulations: rows,
      simulation_only: true,
      notice: notice(),
      simulator: rows.some((row) => truthy(get(row, "simulator"))),
    };
  }
  throw new ValidationError("action: simulate / seed_demo / list を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

function criteria(payload: Json): [string, string, Decimal, Json] {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const unit = textValue(get(payload, "unit"), "unit");
  const quantity = decimalValue(get(payload, "quantity"), "quantity", { positive: true });
  const conditions = get(payload, "transaction_conditions", {});
  if (!isDict(conditions)) {
    throw new ValidationError("transaction_conditions: 条件の集合を指定してください");
  }
  return [itemId, unit, quantity, conditions];
}

async function seedDemo(payload: Json, store: Store): Promise<Record<string, string | null>> {
  const [itemId, unit, , conditions] = criteria(payload);
  const confirmer = approvedBy(payload);
  if (!pyEqual([itemId, unit, conditions], ["demo-paint", "ml", {}])) {
    throw new ValidationError("seed_demo: 架空デモ条件を指定してください");
  }
  const versions = await store.priceVersions(itemId);
  const matching = versions.filter((v) => {
    const metadata = get(v as unknown as Json, "metadata", {}) as Json;
    return pyEqual(get(metadata, "transaction_conditions", {}), conditions) && get(v as unknown as Json, "supplier_id", "") === "";
  });
  const ids: Record<string, string | null> = {};
  // 共通 seed の架空価格だけを新価格の組として再利用する。
  if (matching.length > 0) {
    const demoPair: Record<string, string> = {};
    for (const [priceType, amount] of [
      ["仕入", "80"],
      ["販売", "120"],
    ]) {
      const candidates = matching.filter((v) => {
        const item = get(v as unknown as Json, "item", {}) as Json;
        return (
          get(item, "price_type") === priceType &&
          get(item, "unit") === unit &&
          get(item, "unit_price") === amount &&
          get(item, "source") === "simulator:架空値"
        );
      });
      if (candidates.length !== 1) {
        throw new ValidationError("seed_demo: 既存価格版があるため、指定の架空seedを確認できません");
      }
      demoPair[priceType] = candidates[0].price_version_id;
    }
    ids.new_purchase = demoPair["仕入"];
    ids.new_sales = demoPair["販売"];
  } else {
    ids.new_purchase = null;
    ids.new_sales = null;
  }
  for (const [role, priceType, amount, effective] of [
    ["old_purchase", "仕入", "70", "2026-08-01"],
    ["old_sales", "販売", "105", "2026-08-01"],
    ["new_purchase", "仕入", "80", DEMO_DATE],
    ["new_sales", "販売", "120", DEMO_DATE],
  ]) {
    if (role.startsWith("new_") && ids[role] !== null) continue;
    const item = demoItem(itemId, priceType, amount, unit);
    item.updated_at = effective;
    item.source = "simulator:架空M26価格";
    const version = await store.addPrice(item, confirmer, { valid_from: effective, transaction_conditions: conditions });
    ids[role] = version.price_version_id;
  }
  return ids;
}

async function simulate(payload: Json, store: Store, simulator: boolean): Promise<Json> {
  const [itemId, unit, quantity, conditions] = criteria(payload);
  const versionIds: Record<string, string> = {};
  for (const [role] of ROLE_TYPES) versionIds[role] = textValue(get(payload, role), role);
  const allVersions = await store.priceVersions(itemId);
  const byId = new Map<string, PriceVersion>();
  for (const v of allVersions) byId.set(v.price_version_id, v);
  const selected: Record<string, PriceVersion> = {};
  for (const [role, priceType] of ROLE_TYPES) {
    const version = byId.get(versionIds[role]);
    if (version === undefined) {
      throw new ValidationError(`${role}: 指定価格版が品目にありません`);
    }
    const v = version as unknown as Json;
    const item = get(v, "item", {}) as Json;
    const metadata = get(v, "metadata", {}) as Json;
    if (get(v, "status") !== "approved") {
      throw new ValidationError(`${role}: 承認済み価格版が必要です`);
    }
    if (get(item, "item_id") !== itemId || get(item, "unit") !== unit) {
      throw new ValidationError(`${role}: 品目IDまたは単位が一致しません`);
    }
    if (get(item, "price_type") !== priceType) {
      throw new ValidationError(`${role}: 価格区分が一致しません`);
    }
    if (!pyEqual(get(metadata, "transaction_conditions", {}), conditions)) {
      throw new ValidationError(`${role}: 取引条件が一致しません`);
    }
    if (!pyEqual(get(metadata, "currency", "JPY"), "JPY")) {
      throw new ValidationError(`${role}: 通貨条件が一致しません`);
    }
    selected[role] = version;
  }
  const suppliers = new Set(Object.values(selected).map((version) => get(version as unknown as Json, "supplier_id", "")));
  if (suppliers.size !== 1) {
    throw new ValidationError("supplier_id: 仕入先条件が一致しません");
  }
  const prices: Record<string, Decimal> = {};
  for (const [role, version] of Object.entries(selected)) prices[role] = decimalValue(version.item.unit_price, role);
  const oldUnitMargin = prices.old_sales.sub(prices.old_purchase);
  const newUnitMargin = prices.new_sales.sub(prices.new_purchase);
  const oldMargin = oldUnitMargin.mul(quantity);
  const newMargin = newUnitMargin.mul(quantity);
  const pricesOut: Json = {};
  for (const [role, price] of Object.entries(prices)) pricesOut[role] = price.toString();
  const saved = await store.put(
    NAMESPACE,
    {
      item_id: itemId,
      unit,
      quantity: quantity.toString(),
      transaction_conditions: conditions,
      price_version_ids: versionIds,
      prices: pricesOut,
      old_unit_gross_margin: oldUnitMargin.toString(),
      new_unit_gross_margin: newUnitMargin.toString(),
      old_gross_margin: oldMargin.toString(),
      new_gross_margin: newMargin.toString(),
      gross_margin_change: newMargin.sub(oldMargin).toString(),
      confirmed_by: approvedBy(payload),
      simulation_only: true,
      simulator,
      excluded_costs: ["人件費", "税", "廃棄"],
    },
    uuidHex(),
  );
  return {
    status: "simulated",
    simulation: saved,
    simulation_only: true,
    simulator: simulator || Object.values(selected).some((v) => String(get(v.item as unknown as Json, "source", "")).startsWith("simulator:")),
    notice: notice(),
  };
}

function notice(): string {
  return "粗利影響の試算のみです。価格は変更しません。人件費・税・廃棄を含みません。";
}
