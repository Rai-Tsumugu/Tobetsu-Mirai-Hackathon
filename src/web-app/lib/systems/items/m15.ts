// M15: 品目別有効期限（m15.py の移植）。価格版ごとの有効期間を追記し、期限なし・未確認・期限切れを区別する。
import { DEMO_DATE, PRICE_TYPES, ValidationError, approvedBy, dateValue, demoItem, textValue, type Json, type Store } from "./core";
import { get, isDict, maxBy, truthy } from "./py";

export const SPEC = {
  idea_id: "M15",
  title: "品目別有効期限",
  description: "価格版ごとの有効期間を追記し、期限なし・未確認・期限切れを区別します。",
  defaults: {
    action: "list",
    item_id: "demo-m15-paint",
    price_type: "仕入",
    as_of: DEMO_DATE,
  },
};

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "list");
  if (action === "list") {
    checkKeys(payload, ["action", "item_id", "price_type", "as_of"]);
    return listValidity(payload, store);
  }
  if (action === "set_validity") {
    checkKeys(payload, ["action", "item_id", "price_type", "supplier_id", "valid_from", "valid_until", "reason", "confirmed_by"]);
    return setValidity(payload, store);
  }
  throw new ValidationError("action: list / set_validity を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

function target(payload: Json): [string, string, string | null] {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const priceType = get(payload, "price_type", "仕入");
  if (!(PRICE_TYPES as readonly unknown[]).includes(priceType)) {
    throw new ValidationError("price_type: 仕入または販売を選択してください");
  }
  let supplierId = get(payload, "supplier_id");
  if (supplierId !== null && supplierId !== "") {
    supplierId = textValue(supplierId, "supplier_id");
  }
  return [itemId, priceType as string, supplierId as string | null];
}

async function listValidity(payload: Json, store: Store): Promise<Json> {
  const [itemId, priceType, supplierId] = target(payload);
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  let versions = await store.priceVersions(itemId, priceType, supplierId);
  if (versions.length === 0 && itemId === SPEC.defaults.item_id && supplierId === null) {
    await store.addPrice(demoItem(itemId, priceType, "80"), "架空デモ担当", {
      valid_from: DEMO_DATE,
      reason: "架空デモ初回登録",
      simulator: true,
    });
    versions = await store.priceVersions(itemId, priceType);
  }
  if (versions.length === 0) {
    throw new ValidationError("価格未確認: 対象価格がありません");
  }

  const rows = versions.map((version) => {
    let status: string;
    if (version.status !== "approved") status = "未確認";
    else if (version.valid_from > asOf) status = "未開始";
    else if (version.valid_until !== null && asOf > version.valid_until) status = "期限切れ";
    else if (version.valid_until === null) status = "期限なし";
    else status = "有効";
    return {
      price_version_id: version.price_version_id,
      item_id: itemId,
      price_type: priceType,
      supplier_id: version.supplier_id,
      unit_price: version.item.unit_price,
      valid_from: version.valid_from,
      valid_until: version.valid_until,
      status,
      confirmed_by: version.confirmed_by,
      reason: version.reason,
    };
  });
  return {
    item_id: itemId,
    price_type: priceType,
    as_of: asOf,
    price_versions: rows,
    simulator: versions.some((version) => truthy(get((get(version, "metadata") as Json | null) || {}, "simulator"))),
  };
}

async function setValidity(payload: Json, store: Store): Promise<Json> {
  const [itemId, priceType, supplierId] = target(payload);
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason"), "reason");
  const versions = await store.priceVersions(itemId, priceType, supplierId);
  const approved = versions.map((version, index) => ({ index, version })).filter((pair) => pair.version.status === "approved");
  if (approved.length === 0) {
    throw new ValidationError("価格未確認: 承認済みの価格版がありません");
  }
  const current = maxBy(approved, (pair) => [pair.version.valid_from, pair.index]).version;
  const validFrom = dateValue(get(payload, "valid_from", current.valid_from), "valid_from");
  const rawUntil = get(payload, "valid_until");
  const validUntil = rawUntil !== null ? dateValue(rawUntil, "valid_until") : null;
  if (validUntil !== null && validUntil < validFrom) {
    throw new ValidationError("valid_until: 開始日より前です");
  }
  const item = { ...current.item };
  const metadata: Json = { ...((get(current, "metadata") as Json | null) || {}) };
  // 価格と品目は同じまま新しい版を追記し、旧版は残す。
  const version = await store.transaction(() =>
    store.addPrice(item, confirmer, {
      supplier_id: current.supplier_id,
      valid_from: validFrom,
      valid_until: validUntil,
      status: "approved",
      reason,
      ...metadata,
    }),
  );
  return {
    status: "saved",
    item_id: itemId,
    price_type: priceType,
    price_version_id: version.price_version_id,
    previous_price_version_id: current.price_version_id,
    valid_from: version.valid_from,
    valid_until: version.valid_until,
    price_status: validUntil === null ? "期限なし" : "有効",
    confirmed_by: version.confirmed_by,
    reason: version.reason,
    item: version.item,
    simulator: truthy(get(metadata, "simulator", false)),
  };
}
