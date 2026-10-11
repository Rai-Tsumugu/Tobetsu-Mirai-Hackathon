// m17.py の移植: 取込候補と現行版の差分を比べ、人の採否を追記する。
import { Decimal } from "./decimal";
import {
  DEMO_DATE,
  ValidationError,
  approvedBy,
  dateValue,
  decimalValue,
  demoItem,
  textValue,
  validateItem,
  type Json,
  type PriceVersion,
  type Store,
  type StoredRecord,
} from "./core";
import { get, isDict, pyEqual, truthy } from "./py";

export const SPEC = {
  idea_id: "M17",
  title: "更新差分確認画面",
  description: "品目・単位・価格区分・仕入先・取引条件が一致する候補だけ価格差を比較し、人の採否を追記します。",
  defaults: {
    action: "review",
    item_id: "demo-m17-paint",
    candidate: {
      item: demoItem("demo-m17-paint", "仕入", "88", "ml"),
      supplier_id: "demo-supplier",
      transaction_conditions: "月末締め翌月末払い",
      valid_from: DEMO_DATE,
      simulator: true,
    },
  } as Json,
};

const NAMESPACE = "m17_update_reviews";

/** 候補を1件確認し、指定があれば人の採否も記録する。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  if (get(payload, "action", "review") !== "review") {
    throw new ValidationError("action: reviewを選択してください");
  }
  const allowed = new Set(["action", "item_id", "candidate", "decision", "confirmed_by", "reason"]);
  if (Object.keys(payload).some((key) => !allowed.has(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }

  const itemId = textValue(get(payload, "item_id"), "item_id");
  let candidate = get(payload, "candidate");
  if ((candidate === null || candidate === undefined) && itemId === SPEC.defaults.item_id) {
    candidate = SPEC.defaults.candidate;
  }
  const comparison = await compare(itemId, candidate, store);
  const decision = get(payload, "decision");
  if (decision === null || decision === undefined) {
    const review = { item_id: itemId, decision: "保留中", reviewer: null, reason: null, comparison, candidate };
    const saved = await store.put(NAMESPACE, review);
    return response(saved, comparison);
  }
  if (decision !== "採用" && decision !== "保留") {
    throw new ValidationError("decision: 採用または保留を選択してください");
  }
  const reviewer = approvedBy(payload);
  const reason = textValue(get(payload, "reason"), "reason");
  if (decision === "採用" && !comparison.comparable) {
    throw new ValidationError("比較不可: 条件不一致の候補は採用できません");
  }

  const record = { item_id: itemId, decision, reviewer, reason, comparison, candidate };
  let saved!: StoredRecord;
  let adoptedVersion: PriceVersion | null = null;
  await store.transaction(async () => {
    saved = await store.put(NAMESPACE, record);
    adoptedVersion = decision === "採用" ? await adopt(candidate as Json, reviewer, reason, store) : null;
  });
  const result = response(saved, comparison);
  const adopted = adoptedVersion as PriceVersion | null;
  if (adopted) {
    result.price_version_id = adopted.price_version_id;
    result.item = adopted.item;
  }
  return result;
}

async function compare(itemId: string, candidate: unknown, store: Store): Promise<Json> {
  if (!isDict(candidate)) {
    throw new ValidationError("candidate: 取込候補が必要です");
  }
  const rawItem = get(candidate, "item");
  if (!isDict(rawItem) || !pyEqual(get(rawItem, "item_id"), itemId)) {
    throw new ValidationError("item_id: 現行品目と候補品目を一致させてください");
  }
  const item = validateItem(rawItem);
  const unitPrice = decimalValue(item.unit_price, "candidate.unit_price");
  const supplierId = textValue(get(candidate, "supplier_id"), "candidate.supplier_id");
  const conditions = textValue(get(candidate, "transaction_conditions"), "candidate.transaction_conditions");
  const priceType = item.price_type;
  if (priceType !== "仕入" && priceType !== "販売") {
    throw new ValidationError("candidate.price_type: 選択値を確認してください");
  }

  const versions = await store.priceVersions(itemId);
  let oldVersion: PriceVersion | null = versions.length > 0 ? versions[versions.length - 1] : null;
  if (oldVersion === null && itemId === SPEC.defaults.item_id) {
    const oldItem = demoItem(itemId, "仕入", "80", "ml");
    oldVersion = await store.addPrice(oldItem, "架空デモ担当", {
      supplier_id: "demo-supplier",
      valid_from: DEMO_DATE,
      transaction_conditions: "月末締め翌月末払い",
      currency: "JPY",
      simulator: true,
      reason: "架空デモ初回価格",
    });
  }
  if (oldVersion === null) {
    throw new ValidationError("価格未確認: 比較する現行価格がありません");
  }

  const oldItem = oldVersion.item;
  const oldMetadata = (truthy(oldVersion.metadata) ? oldVersion.metadata : {}) as Json;
  const oldConditions = get(oldMetadata, "transaction_conditions");
  const candidateCurrency = get(candidate, "currency", "JPY");
  const oldCurrency = get(oldMetadata, "currency", "JPY");
  const keysMatch: Json = {
    item_id: oldItem.item_id === itemId,
    name: pyEqual(oldItem.name, item.name),
    category: pyEqual(oldItem.category, item.category),
    unit: pyEqual(oldItem.unit, item.unit),
    price_type: oldItem.price_type === priceType,
    supplier_id: pyEqual(oldVersion.supplier_id, supplierId),
    transaction_conditions: pyEqual(oldConditions, conditions),
    currency: pyEqual(oldCurrency, candidateCurrency),
  };
  let comparable = Object.values(keysMatch).every(Boolean);
  const oldPrice = Decimal.parse(oldItem.unit_price);
  const difference = unitPrice.sub(oldPrice);
  const rate = comparable && !oldPrice.isZero() ? difference.div(oldPrice).mul(Decimal.parse("100")) : null;
  if (oldPrice.isZero() && comparable) {
    comparable = false;
    keysMatch.unit_price_base = false;
  }
  return {
    comparable,
    match_keys: keysMatch,
    old_price_version_id: oldVersion.price_version_id,
    old_unit_price: oldPrice.toString(),
    candidate_unit_price: unitPrice.toString(),
    difference: comparable ? difference.toString() : null,
    difference_rate_percent: comparable ? String(rate) : null,
    old_supplier_id: oldVersion.supplier_id,
    candidate_supplier_id: supplierId,
    old_transaction_conditions: oldConditions,
    candidate_transaction_conditions: conditions,
    old_source: oldItem.source,
    candidate_source: item.source,
    simulator: truthy(get(oldMetadata, "simulator")) || truthy(get(candidate, "simulator")),
  };
}

async function adopt(candidate: Json, reviewer: string, reason: string, store: Store): Promise<PriceVersion> {
  const item: Json = { ...(candidate.item as Json) };
  item.updated_at = dateValue(get(candidate, "valid_from", item.updated_at), "valid_from");
  return store.addPrice(item, reviewer, {
    supplier_id: textValue(candidate.supplier_id, "candidate.supplier_id"),
    valid_from: item.updated_at,
    valid_until: get(candidate, "valid_until"),
    status: "approved",
    reason,
    transaction_conditions: textValue(candidate.transaction_conditions, "candidate.transaction_conditions"),
    currency: get(candidate, "currency", "JPY"),
    simulator: truthy(get(candidate, "simulator", false)),
  });
}

function response(saved: StoredRecord, comparison: Json): Json {
  return {
    status: "saved",
    review_id: saved.record_id,
    item_id: saved.item_id,
    decision: saved.decision,
    confirmed_by: saved.reviewer,
    reason: saved.reason,
    comparison,
  };
}
