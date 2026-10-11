// M27: 前回見積のスナップショットと現行価格の差を示す。見積も価格も変えない（m27.py の移植）。
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, demoItem, textValue, type Json, type PriceVersion, type Store } from "./core";
import { get, isDict, pyEqual, truthy } from "./py";

export const SPEC = {
  idea_id: "M27",
  title: "見積バスケット差分通知",
  description: "見積バスケットの現行価格と前回見積の同一条件価格を比較します。",
  defaults: {
    action: "compare_demo",
    quote_id: "demo-m27-quote",
    basket: [
      {
        item_id: "demo-m27-paint",
        unit: "ml",
        price_type: "販売",
        supplier_id: "supplier-demo",
        conditions: { freight_basis: "included", currency: "JPY" },
      },
    ],
    as_of: DEMO_DATE,
    confirmed_by: "架空デモ担当",
  },
};

export const QUOTE_NAMESPACE = "quote_snapshot";

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "compare");
  if (action === "compare_demo") {
    await seedDemo(payload, store);
    return compare(payload, store, true);
  }
  if (action === "compare") {
    return compare(payload, store, false);
  }
  throw new ValidationError("action: compare / compare_demo を選択してください");
}

async function seedDemo(payload: Json, store: Store): Promise<void> {
  if (get(payload, "quote_id") !== "demo-m27-quote") {
    throw new ValidationError("compare_demo: 架空デモの quote_id を指定してください");
  }
  const quote = await store.records(QUOTE_NAMESPACE, "demo-m27-quote");
  if (quote.length === 0) {
    const old = demoItem("demo-m27-paint", "販売", "100", "ml");
    old.updated_at = "2026-08-01";
    old.source = "simulator:架空M27前回価格";
    const oldVersion = await store.addPrice(old, "架空デモ担当", {
      supplier_id: "supplier-demo",
      valid_from: "2026-08-01",
      transaction_conditions: { freight_basis: "included", currency: "JPY" },
    });
    const current = demoItem("demo-m27-paint", "販売", "120", "ml");
    current.source = "simulator:架空M27現行価格";
    await store.addPrice(current, "架空デモ担当", {
      supplier_id: "supplier-demo",
      transaction_conditions: { freight_basis: "included", currency: "JPY" },
    });
    await store.put(
      QUOTE_NAMESPACE,
      {
        quote_id: "demo-m27-quote",
        confirmed_by: "架空デモ担当",
        created_at: "2026-08-01T00:00:00+09:00",
        simulator: true,
        lines: [
          {
            quote_line_id: "demo-m27-line",
            item_id: "demo-m27-paint",
            name: old.name,
            category: old.category,
            quantity: "1",
            unit: "ml",
            unit_price_snapshot: "100",
            price_type: "販売",
            price_version_id: oldVersion.price_version_id,
            source_snapshot: old.source,
            updated_at: "2026-08-01",
            supplier_id: "supplier-demo",
            conditions: { freight_basis: "included", currency: "JPY" },
            line_total: "100",
          },
        ],
      },
      "demo-m27-quote",
    );
  }
}

async function compare(payload: Json, store: Store, simulator: boolean): Promise<Json> {
  const quoteId = textValue(get(payload, "quote_id"), "quote_id");
  const basket = get(payload, "basket");
  if (!Array.isArray(basket) || basket.length === 0) {
    throw new ValidationError("basket: 比較する品目を1件以上指定してください");
  }
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  // 人の確認は比較依頼の記録であり、価格の承認ではない。
  const confirmer = approvedBy(payload);
  const snapshot = await store.latest(QUOTE_NAMESPACE, quoteId);
  const previousLines = get(snapshot, "lines");
  if (!Array.isArray(previousLines)) {
    throw new ValidationError("quote_snapshot.lines: 見積行を確認してください");
  }
  const results: Json[] = [];
  for (const [index, selection] of basket.entries()) {
    if (!isDict(selection)) {
      throw new ValidationError(`basket[${index}]: 品目条件を確認してください`);
    }
    const itemId = textValue(get(selection, "item_id"), "item_id");
    const unit = textValue(get(selection, "unit"), "unit");
    const priceType = textValue(get(selection, "price_type"), "price_type");
    const supplierId = truthy(get(selection, "supplier_id", "")) ? textValue(get(selection, "supplier_id", ""), "supplier_id") : "";
    const conditions = get(selection, "conditions", {});
    if (!isDict(conditions)) {
      throw new ValidationError("conditions: 取引条件を確認してください");
    }
    const matches = previousLines.filter((line) => isDict(line) && get(line, "item_id") === itemId) as Json[];
    let result: Json = { item_id: itemId, status: "comparison_unavailable" };
    if (matches.length === 1) {
      const previous = matches[0];
      // 単位・条件などが違う・欠けているものを差額として示さない。
      if (
        get(previous, "unit") === unit &&
        get(previous, "price_type") === priceType &&
        pyEqual(get(previous, "supplier_id", ""), supplierId) &&
        pyEqual(get(previous, "conditions", {}), conditions)
      ) {
        let current: PriceVersion | null;
        try {
          current = await store.getPrice(itemId, priceType, { as_of: asOf, supplier_id: supplierId, unit });
        } catch (error) {
          if (!(error instanceof ValidationError)) throw error;
          current = null;
        }
        if (current && pyEqual(get(get(current as unknown as Json, "metadata", {}) as Json, "transaction_conditions", {}), conditions)) {
          const previousPrice = decimalValue(get(previous, "unit_price_snapshot"), "unit_price_snapshot");
          const currentPrice = decimalValue(get(current.item as unknown as Json, "unit_price"), "current.unit_price");
          result = {
            item_id: itemId,
            status: "comparable",
            previous_unit_price: previousPrice.toString(),
            current_unit_price: currentPrice.toString(),
            difference: currentPrice.sub(previousPrice).toString(),
            previous_price_version_id: textValue(get(previous, "price_version_id"), "price_version_id"),
            current_price_version_id: current.price_version_id,
            unit,
            price_type: priceType,
            supplier_id: supplierId,
            conditions,
          };
        } else {
          result.reason = "現行価格がないか取引条件が一致しません";
        }
      } else {
        result.reason = "単位・価格区分・仕入先・取引条件が一致しません";
      }
    } else {
      result.reason = "前回見積に同一品目がないか、複数あります";
    }
    results.push(result);
  }
  return {
    status: "compared",
    quote_id: quoteId,
    comparisons: results,
    confirmed_by: confirmer,
    simulator: simulator || truthy(get(snapshot, "simulator")),
    price_finalized: false,
    notice: "差額は参考表示です。採用価格は人が確認するまで確定しません。",
  };
}
