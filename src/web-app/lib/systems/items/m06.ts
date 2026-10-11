// M06: 価格イベント台帳（m06.py の移植）。価格版を上書きせず、変更理由・出所・担当者と一緒に追記する。
import { DEMO_DATE, ValidationError, approvedBy, dateValue, demoItem, textValue, validateItem, type Json, type Store, type Item } from "./core";
import { get, isDict, isoDate, isoDatetime, parseIsoDate, parseIsoDatetime, pyStrip } from "./py";

export const SPEC = {
  idea_id: "M06",
  title: "価格イベント台帳",
  description: "価格版を上書きせず、変更理由・出所・担当者とともに追記して履歴化します。",
  defaults: {
    action: "record_event",
    item: demoItem("demo-paint", "販売", "125"),
    event_type: "increase",
    reason: "架空デモの価格改定",
    source: "simulator:架空値",
    confirmed_by: "架空デモ担当",
    occurred_at: DEMO_DATE,
  },
};

const EVENT_TYPES = ["initial", "increase", "correction", "condition_change"];

function withoutRecordId(record: Json): Json {
  const copy = { ...record };
  delete copy.record_id;
  return copy;
}

/** 価格版とイベントを記録するか、品目のイベント履歴を返す。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "record_event");
  if (action === "record_event") return recordEvent(payload, store);
  if (action === "list_events") {
    const itemId = textValue(get(payload, "item_id"), "item_id");
    const events = await store.records("price_event", itemId);
    return { item_id: itemId, events: events.map(withoutRecordId), simulator: true };
  }
  throw new ValidationError("action: record_event または list_events を選択してください");
}

async function recordEvent(payload: Json, store: Store): Promise<Json> {
  const item: Item = validateItem(get(payload, "item"));
  const eventType = textValue(get(payload, "event_type"), "event_type");
  if (!EVENT_TYPES.includes(eventType)) {
    throw new ValidationError("event_type: initial / increase / correction / condition_change を選択してください");
  }
  const reason = textValue(get(payload, "reason"), "reason");
  const source = textValue(get(payload, "source", item.source), "source");
  const actor = approvedBy(payload);
  let supplierId = get(payload, "supplier_id", "");
  if (supplierId === null) {
    supplierId = "";
  } else if (typeof supplierId !== "string") {
    throw new ValidationError("supplier_id: 文字列を入力してください");
  }
  const supplier = pyStrip(supplierId as string);
  const status = get(payload, "status", "approved");
  if (status !== "approved" && status !== "pending") {
    throw new ValidationError("status: approved または pending を指定してください");
  }

  // 共通品目の出所をイベントの根拠と揃える。
  item.source = source;
  const occurredAt = toOccurredAt(get(payload, "occurred_at", item.updated_at));
  const previous = await store.priceVersions(item.item_id, item.price_type, supplier);
  const oldVersion = previous.length > 0 ? previous[previous.length - 1].price_version_id : null;
  if (oldVersion === null && eventType !== "initial") {
    throw new ValidationError("event_type: 初回登録は initial を選択してください");
  }
  if (oldVersion !== null && eventType === "initial") {
    throw new ValidationError("event_type: 既存価格の変更には別のイベント種別を選択してください");
  }

  const validFrom = dateValue(get(payload, "valid_from", item.updated_at), "valid_from");
  const validUntil = get(payload, "valid_until");
  return store.transaction(async () => {
    const version = await store.addPrice(item, actor, {
      supplier_id: supplier,
      valid_from: validFrom,
      valid_until: validUntil,
      status,
      reason,
    });
    const event = {
      item_id: item.item_id,
      old_version: oldVersion,
      new_version: version.price_version_id,
      event_type: eventType,
      reason,
      source,
      actor,
      occurred_at: occurredAt,
      status,
    };
    const savedEvent = await store.put("price_event", event, item.item_id);

    // 承認済みで有効な価格だけを返す。保留のイベントは記録しつつ、確認済みの価格を使い続ける。
    let currentItems: Item[] = [];
    try {
      const current = await store.getPrice(item.item_id, item.price_type, { as_of: version.valid_from, supplier_id: supplier });
      currentItems = [current.item];
    } catch (error) {
      if (!(error instanceof ValidationError) || status === "approved") throw error;
    }
    return {
      event: withoutRecordId(savedEvent),
      price_version: version,
      items: currentItems,
      simulator: true,
      notice: "価格は架空デモ値です。承認済みの価格だけを items に返しています。",
    };
  });
}

function toOccurredAt(value: unknown): string {
  const text = textValue(value, "occurred_at");
  if (!text.includes("T") && !text.includes(" ")) {
    const date = parseIsoDate(text);
    if (date) return isoDate(date);
  } else {
    const datetime = parseIsoDatetime(text.replace(/Z/g, "+00:00"));
    if (datetime) return isoDatetime(datetime);
  }
  throw new ValidationError("occurred_at: ISO形式の日付または日時が必要です");
}
