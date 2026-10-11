// m23.py の移植: 見積スナップショットの数量と実使用量を比べ、理由付きで別に記録する。
import { ValidationError, approvedBy, decimalValue, textValue, type Json, type Store } from "./core";
import { get, isDict, pyEqual, pyStr, truthy, utcNowIso, uuidHex } from "./py";

export const SPEC = {
  idea_id: "M23",
  title: "見積量と実使用量の比較",
  description: "見積スナップショットの数量と実使用量を比較し、理由付きで別記録します。",
  defaults: {
    action: "record_demo",
    quote_id: "demo-m23-quote",
    quote_line_id: "demo-m23-line",
    actual_qty: "12.5",
    reason: "simulator:架空デモ作業で一部を使い切らなかった",
    confirmed_by: "架空デモ担当",
  } as Json,
};

export const QUOTE_NAMESPACE = "quote_snapshot";
export const USAGE_NAMESPACE = "item_usage";

/** 保存済みの見積行に実使用量を記録する、または記録を一覧する。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "record");
  if (action === "record_demo") {
    await ensureDemoQuote(store);
    return record(payload, store, true);
  }
  if (action === "record") return record(payload, store, false);
  if (action === "list") return list(payload, store);
  throw new ValidationError("action: record_demo / record / list を選択してください");
}

/** 明示的なデモ操作のときだけ、架空の見積を作る。 */
async function ensureDemoQuote(store: Store): Promise<void> {
  if ((await store.records(QUOTE_NAMESPACE, "demo-m23-quote")).length > 0) return;
  const snapshot = {
    quote_id: "demo-m23-quote",
    lines: [
      {
        quote_line_id: "demo-m23-line",
        item_id: "demo-m23-material",
        name: "架空デモ材料",
        category: "消耗品",
        quantity: "15",
        unit: "ml",
        unit_price_snapshot: "0",
        price_type: "販売",
        price_version_id: "simulator:no-price-seeded",
        source_snapshot: "simulator:架空見積スナップショット",
        updated_at: "2026-10-11T00:00:00+09:00",
        supplier_id: "",
        conditions: {},
        line_total: "0",
      },
    ],
    confirmed_by: "架空デモ担当",
    created_at: "2026-10-11T00:00:00+09:00",
    simulator: true,
  };
  await store.put(QUOTE_NAMESPACE, snapshot, "demo-m23-quote");
}

async function record(payload: Json, store: Store, simulator: boolean): Promise<Json> {
  const quoteId = textValue(get(payload, "quote_id"), "quote_id");
  const quoteLineId = textValue(get(payload, "quote_line_id"), "quote_line_id");
  const actualQty = decimalValue(get(payload, "actual_qty"), "actual_qty");
  const reason = textValue(get(payload, "reason"), "reason");
  const confirmer = approvedBy(payload);

  const snapshot = await store.latest(QUOTE_NAMESPACE, quoteId);
  const lines = get(snapshot, "lines");
  if (!Array.isArray(lines)) {
    throw new ValidationError("quote_snapshot.lines: 見積行を確認してください");
  }
  const matches = lines.filter((line) => isDict(line) && pyEqual(get(line, "quote_line_id"), quoteLineId)) as Json[];
  if (matches.length !== 1) {
    throw new ValidationError("quote_line_id: 見積スナップショット内の一意な行を指定してください");
  }
  const line = matches[0];
  const estimatedQty = decimalValue(get(line, "quantity"), "quote_snapshot.quantity");
  const unit = textValue(get(line, "unit"), "quote_snapshot.unit");
  const difference = actualQty.sub(estimatedQty);
  const recordedAt = utcNowIso();
  const usage = {
    quote_id: quoteId,
    quote_line_id: quoteLineId,
    item_id: textValue(get(line, "item_id"), "quote_snapshot.item_id"),
    estimated_qty: estimatedQty.toString(),
    actual_qty: actualQty.toString(),
    difference: difference.toString(),
    unit,
    reason,
    confirmed_by: confirmer,
    recorded_at: recordedAt,
    simulator: simulator || truthy(get(snapshot, "simulator")) || pyStr(get(snapshot, "source", "")).startsWith("simulator:"),
  };
  const saved = await store.put(USAGE_NAMESPACE, usage, uuidHex());
  return {
    status: "saved",
    item_usage: saved,
    comparison: {
      estimated_qty: estimatedQty.toString(),
      actual_qty: actualQty.toString(),
      difference: difference.toString(),
      unit,
    },
    simulator: usage.simulator,
    notice: "実使用量を別記録しました。見積数量・標準量・価格は変更していません。",
  };
}

async function list(payload: Json, store: Store): Promise<Json> {
  let quoteId = get(payload, "quote_id") as string | null;
  let quoteLineId = get(payload, "quote_line_id") as string | null;
  if (quoteId !== null) quoteId = textValue(quoteId, "quote_id");
  if (quoteLineId !== null) quoteLineId = textValue(quoteLineId, "quote_line_id");
  const rows = (await store.records(USAGE_NAMESPACE)).filter(
    (row) =>
      (quoteId === null || pyEqual(get(row, "quote_id"), quoteId)) &&
      (quoteLineId === null || pyEqual(get(row, "quote_line_id"), quoteLineId)),
  );
  return { item_usages: rows, simulator: rows.some((row) => truthy(get(row, "simulator"))) };
}
