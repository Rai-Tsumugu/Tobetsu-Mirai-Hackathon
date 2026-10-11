// M16: 更新待ち隊列（m16.py の移植）。期限切れ・未確認・差分を優先順に並べ、人の確認状態を記録する。
import { DEMO_DATE, PRICE_TYPES, ValidationError, approvedBy, dateValue, textValue, type Json, type PriceVersion, type Store, type StoredRecord } from "./core";
import { compareKeys, get, isDict, pyEqual, pyStr, sortedBy, truthy } from "./py";

export const SPEC = {
  idea_id: "M16",
  title: "更新待ち隊列",
  description: "期限切れ・未確認・価格差分を明示した優先順位で並べ、人の確認状態を記録します。",
  defaults: {
    action: "list",
    as_of: DEMO_DATE,
  },
};

const PRIORITY: Record<string, number> = { 期限切れ: 0, 未確認: 1, 差分あり: 2 };
const STATES = ["確認済み", "要調査"];

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "list");
  if (action === "list") {
    checkKeys(payload, ["action", "as_of"]);
    return listQueue(payload, store);
  }
  if (action === "update_status") {
    checkKeys(payload, ["action", "item_id", "price_type", "supplier_id", "status", "confirmed_by", "reason", "checked_at", "as_of"]);
    return updateStatus(payload, store);
  }
  throw new ValidationError("action: list / update_status を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

const keyOf = (parts: unknown[]) => JSON.stringify(parts);

async function listQueue(payload: Json, store: Store): Promise<Json> {
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");

  const latestStates = new Map<string, StoredRecord>();
  for (const record of await store.records("freshness_queue")) {
    latestStates.set(keyOf([record.item_id, record.price_type, get(record, "supplier_id", "")]), record);
  }

  type Indexed = PriceVersion & { _index: number };
  const latestVersions = new Map<string, { key: [string, string, string]; version: Indexed }>();
  const histories = new Map<string, PriceVersion[]>();
  for (const version of await store.priceVersions()) {
    const item = version.item;
    const parts: [string, string, string] = [item.item_id, item.price_type, version.supplier_id];
    const key = keyOf(parts);
    if (!histories.has(key)) histories.set(key, []);
    histories.get(key)!.push(version);
    const prior = latestVersions.get(key);
    const index = histories.get(key)!.length - 1;
    if (prior === undefined || compareKeys([version.valid_from, index], [prior.version.valid_from, prior.version._index]) >= 0) {
      latestVersions.set(key, { key: parts, version: { ...version, _index: index } });
    }
  }

  const rows: Json[] = [];
  for (const [key, { key: parts, version }] of latestVersions) {
    const [itemId, priceType, supplierId] = parts;
    let checked: StoredRecord | null = latestStates.get(key) ?? null;
    if (checked && !pyEqual(get(checked, "price_version_id"), version.price_version_id)) {
      checked = null;
    }
    if (checked && checked.status === "確認済み" && pyEqual(get(checked, "price_version_id"), version.price_version_id)) {
      continue;
    }
    const metadata = (get(version, "metadata") as Json | null) || {};
    const checkedAt = get(metadata, "checked_at");
    const validUntil = get(version, "valid_until") as string | null;
    let reason: string;
    if (validUntil !== null && validUntil < asOf) {
      reason = "期限切れ";
    } else if (version.status !== "approved" || !truthy(checkedAt)) {
      reason = "未確認";
    } else {
      const versions = histories.get(key)!;
      const position = version._index;
      if (position > 0 && versions[position - 1].item.unit_price !== version.item.unit_price) {
        reason = "差分あり";
      } else if (truthy(get(metadata, "has_diff"))) {
        reason = "差分あり";
      } else {
        continue;
      }
    }
    rows.push({
      item_id: itemId,
      name: version.item.name,
      price_type: priceType,
      supplier_id: supplierId,
      price_version_id: version.price_version_id,
      unit_price: version.item.unit_price,
      unit: version.item.unit,
      source: version.item.source,
      updated_at: version.item.updated_at,
      valid_until: validUntil,
      reason,
      priority: PRIORITY[reason],
      status: checked ? checked.status : "未対応",
      confirmed_by: checked ? get(checked, "confirmed_by") : null,
      review_reason: checked ? get(checked, "reason") : null,
      checked_at: checkedAt,
      simulator: truthy(get(metadata, "simulator", false)) || version.item.source.startsWith("simulator:"),
    });
  }

  const sorted = sortedBy(rows, (row) => [
    row.priority as number,
    (truthy(row.valid_until) ? row.valid_until : "9999-12-31") as string,
    row.item_id as string,
    row.price_type as string,
    row.supplier_id as string,
  ]);
  return { as_of: asOf, queue: sorted, priority_order: Object.keys(PRIORITY), simulator: sorted.some((row) => truthy(row.simulator)) };
}

async function updateStatus(payload: Json, store: Store): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const priceType = get(payload, "price_type", "仕入");
  if (!(PRICE_TYPES as readonly unknown[]).includes(priceType)) {
    throw new ValidationError("price_type: 仕入または販売を選択してください");
  }
  let supplierId = get(payload, "supplier_id", "");
  if (truthy(supplierId)) {
    supplierId = textValue(supplierId, "supplier_id");
  }
  const status = get(payload, "status");
  if (!STATES.includes(status as string)) {
    throw new ValidationError("status: 確認済みまたは要調査を選択してください");
  }
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason"), "reason");
  const checkedAt = dateValue(get(payload, "checked_at", get(payload, "as_of", DEMO_DATE)), "checked_at");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  if (checkedAt > asOf) {
    throw new ValidationError("checked_at: 基準日より未来の日付です");
  }

  const versions = await store.priceVersions(itemId, priceType as string, supplierId as string | null);
  if (versions.length === 0) {
    throw new ValidationError("価格未確認: 対象価格がありません");
  }
  const current = versions[versions.length - 1];
  let revised: PriceVersion;
  if (status === "確認済み") {
    const item = { ...current.item };
    const metadata: Json = { ...((get(current, "metadata") as Json | null) || {}) };
    metadata.checked_at = checkedAt;
    revised = await store.transaction(() =>
      store.addPrice(item, confirmer, {
        supplier_id: supplierId,
        valid_from: current.valid_from,
        valid_until: current.valid_until,
        status: current.status,
        reason,
        ...metadata,
      }),
    );
  } else {
    revised = current;
  }

  const saved = await store.put(
    "freshness_queue",
    {
      item_id: itemId,
      price_type: priceType,
      supplier_id: supplierId,
      status,
      confirmed_by: confirmer,
      reason,
      checked_at: status === "確認済み" ? checkedAt : null,
      price_version_id: revised.price_version_id,
    },
    `${itemId}:${pyStr(priceType)}:${pyStr(supplierId)}`,
  );
  return {
    status,
    item_id: itemId,
    price_type: priceType,
    supplier_id: supplierId,
    confirmed_by: confirmer,
    reason,
    checked_at: status === "確認済み" ? checkedAt : null,
    price_version_id: revised.price_version_id,
    unit_price: revised.item.unit_price,
    record_id: saved.record_id,
    simulator: truthy(get((get(revised, "metadata") as Json | null) || {}, "simulator", false)),
  };
}
