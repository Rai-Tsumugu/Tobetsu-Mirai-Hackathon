// M30: 見積時点の価格スナップショットを保存し、後から変えずに再表示する（m30.py の移植）。
import {
  DEMO_DATE,
  ValidationError,
  approvedBy,
  dateValue,
  decimalValue,
  demoItem,
  priceConditions,
  textValue,
  type Item,
  type Json,
  type Store,
} from "./core";
import { Decimal, InvalidOperation, decimalSum } from "./decimal";
import { casefold, get, isDict, pyEqual, truthy, utcNowIso, uuidHex } from "./py";

export const SPEC = {
  idea_id: "M30",
  title: "見積時価格スナップショット",
  description: "人が選択した承認済み単価と数量を見積時点で固定し、後から再表示します。",
  defaults: {
    action: "save_demo",
    quote_id: "demo-m30-quote",
    as_of: DEMO_DATE,
    confirmed_by: "架空デモ担当",
    lines: [
      {
        item_id: "demo-m30-paint",
        quantity: "2.5",
        unit: "ml",
        price_type: "販売",
        supplier_id: "",
        conditions: { freight_basis: "included", currency: "JPY", transaction_conditions: "simulator:架空条件" },
      },
    ],
  },
};

export const QUOTE_NAMESPACE = "quote_snapshot";

/** 見積の保存・ID での取得・一覧。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "save");
  if (action === "save_demo") {
    await seedDemoPrice(store);
    return save(payload, store, true);
  }
  if (action === "save") {
    return save(payload, store, false);
  }
  if (action === "get") {
    const quoteId = textValue(get(payload, "quote_id"), "quote_id");
    const quote = await store.latest(QUOTE_NAMESPACE, quoteId);
    return { status: "found", quote, simulator: truthy(get(quote, "simulator")) };
  }
  if (action === "list") {
    let quotes = await store.records(QUOTE_NAMESPACE);
    let query = get(payload, "query");
    if (query !== null) {
      query = casefold(textValue(query, "query"));
      quotes = quotes.filter((quote) => casefold(quote.quote_id as string).includes(query as string));
    }
    return { status: "listed", quotes, simulator: quotes.some((quote) => truthy(get(quote, "simulator"))) };
  }
  throw new ValidationError("action: save / save_demo / get / list を選択してください");
}

/** 架空の価格は save_demo を選んだときだけ作る。 */
async function seedDemoPrice(store: Store): Promise<void> {
  const itemId = "demo-m30-paint";
  if ((await store.priceVersions(itemId)).length > 0) return;
  const item = demoItem(itemId, "販売", "120", "ml");
  await store.addPrice(item, "架空デモ担当", {
    transaction_conditions: "simulator:架空条件",
    freight_basis: "included",
    currency: "JPY",
  });
}

async function save(payload: Json, store: Store, simulator: boolean): Promise<Json> {
  const quoteId = textValue(get(payload, "quote_id"), "quote_id");
  if ((await store.records(QUOTE_NAMESPACE, quoteId)).length > 0) {
    throw new ValidationError("quote_id: 保存済みです。別の見積IDを指定してください");
  }
  const confirmer = approvedBy(payload);
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const selections = get(payload, "lines");
  if (!Array.isArray(selections) || selections.length === 0) {
    throw new ValidationError("lines: 見積品目を1件以上指定してください");
  }

  const lines: Json[] = [];
  const commonItems: Item[] = [];
  const seenLineIds = new Set<string>();
  for (const [index, selection] of selections.entries()) {
    if (!isDict(selection)) {
      throw new ValidationError(`lines[${index}]: 見積品目を確認してください`);
    }
    const itemId = textValue(get(selection, "item_id"), `lines[${index}].item_id`);
    const quantity = decimalValue(get(selection, "quantity"), `lines[${index}].quantity`, { positive: true });
    const unit = textValue(get(selection, "unit"), `lines[${index}].unit`);
    const priceType = textValue(get(selection, "price_type"), `lines[${index}].price_type`);
    let supplierId = get(selection, "supplier_id", "");
    if (truthy(supplierId)) {
      supplierId = textValue(supplierId, `lines[${index}].supplier_id`);
    }
    const version = await store.getPrice(itemId, priceType, {
      as_of: asOf,
      supplier_id: truthy(supplierId) ? (supplierId as string) : null,
      unit,
    });
    const item = version.item;
    const conditions = priceConditions(version as unknown as Json);
    const requestedConditions = get(selection, "conditions");
    if (requestedConditions !== null) {
      if (!isDict(requestedConditions)) {
        throw new ValidationError(`lines[${index}].conditions: 取引条件を確認してください`);
      }
      // M27 と同じ正規化（通貨は明示の JPY）で比べる。
      const supplied: Json = { ...requestedConditions };
      if (!Object.prototype.hasOwnProperty.call(supplied, "currency")) supplied.currency = "JPY";
      if (!pyEqual(supplied, conditions)) {
        throw new ValidationError(`lines[${index}].conditions: 価格版の取引条件と一致しません`);
      }
    }
    let lineTotal: Decimal;
    try {
      lineTotal = quantity.mul(decimalValue(item.unit_price, "unit_price"));
    } catch (error) {
      if (error instanceof InvalidOperation) throw new ValidationError(`lines[${index}]: 金額の桁数を確認してください`);
      throw error;
    }
    if (lineTotal.digitCount() > 28 || Math.abs(lineTotal.exponent) > 12) {
      throw new ValidationError(`lines[${index}]: 金額の桁数を確認してください`);
    }
    const lineId = textValue(get(selection, "quote_line_id", uuidHex()), `lines[${index}].quote_line_id`);
    if (seenLineIds.has(lineId)) {
      throw new ValidationError("quote_line_id: 重複しています");
    }
    seenLineIds.add(lineId);
    lines.push({
      quote_line_id: lineId,
      item_id: item.item_id,
      name: item.name,
      category: item.category,
      quantity: quantity.toString(),
      unit: item.unit,
      unit_price_snapshot: item.unit_price,
      price_type: item.price_type,
      price_version_id: version.price_version_id,
      source_snapshot: item.source,
      updated_at: item.updated_at,
      supplier_id: version.supplier_id,
      conditions,
      line_total: lineTotal.toString(),
    });
    commonItems.push(item);
  }

  const createdAt = utcNowIso();
  const quote: Json = {
    quote_id: quoteId,
    lines,
    confirmed_by: confirmer,
    created_at: createdAt,
    as_of: asOf,
    subtotal: decimalSum(lines.map((line) => Decimal.parse(line.line_total as string))).toString(),
    simulator,
  };
  await store.transaction(async () => {
    // 同じ依頼の繰り返しで版を追記しないよう、トランザクションの中で確かめ直す。
    if ((await store.records(QUOTE_NAMESPACE, quoteId)).length > 0) {
      throw new ValidationError("quote_id: 保存済みです。別の見積IDを指定してください");
    }
    await store.put(QUOTE_NAMESPACE, quote, quoteId);
  });
  return { status: "saved", quote: { ...quote, record_id: quoteId }, items: commonItems, simulator };
}
