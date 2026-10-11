// integrated.py の移植: 確認状況 → 材料・価格登録／CSV候補の承認 → 見積保存 → 実使用量記録を1つの API で扱う。
import { approvedBy, DEMO_DATE, dateValue, priceConditions, textValue, validateItem, ValidationError, type Json, type PriceVersion, type Store } from "./core";
import * as m09 from "./m09";
import * as m23 from "./m23";
import * as m30 from "./m30";
import { moduleFor } from "./registry";
import { compareStrings, daysBetween, get, has, isDict, maxBy, pyEqual, pyStr, sortedBy, truthy, uuidHex } from "./py";

export const SPEC = {
  idea_id: "INTEGRATED",
  title: "品目・見積の統合ワークフロー",
  description: "在庫確認、品目登録、CSV取込、見積保存と実使用記録を一つのAPIで扱います。",
  defaults: {},
};

export const IMPORT_BATCH_NAMESPACE = "integrated_import_batch";

const TOOL_IDEAS = new Set(["M02", "M05", "M19", "M20", "M21", "M22", "M24", "M25", "M26", "M27", "M28", "M29"]);
/** Python の ValueError（HTTP では 400）。 */
class ValueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValueError";
  }
}

/** dict(value): dict はコピー、ほかは (キー, 値) の並びとして解釈する。 */
function pyDict(value: unknown): Json {
  if (isDict(value)) return { ...value };
  if (value === null || value === undefined || typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    const name = value === null || value === undefined ? "NoneType" : typeof value === "boolean" ? "bool" : "int";
    throw new TypeError(`'${name}' object is not iterable`);
  }
  const entries: unknown[] = typeof value === "string" ? [...value] : Array.isArray(value) ? value : [];
  const out: Json = {};
  entries.forEach((entry, index) => {
    const pair = typeof entry === "string" ? [...entry] : Array.isArray(entry) ? entry : null;
    if (pair === null) throw new TypeError(`cannot convert dictionary update sequence element #${index} to a sequence`);
    if (pair.length !== 2) {
      throw new ValueError(`dictionary update sequence element #${index} has length ${pair.length}; 2 is required`);
    }
    out[String(pair[0])] = pair[1];
  });
  return out;
}

const ADD_PRICE_PARAMS = ["supplier_id", "valid_from", "valid_until", "reason"];

/** 読み取り（dashboard / get_quote）以外は1つのトランザクションで行う。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = textValue(get(payload, "action"), "action");
  if (action === "dashboard" || action === "get_quote") {
    return dispatch(payload, store);
  }
  return store.transaction(() => dispatch(payload, store));
}

async function dispatch(payload: Json, store: Store): Promise<Json> {
  const action = textValue(get(payload, "action"), "action");
  if (action === "dashboard") return dashboard(payload, store);
  if (action === "register" || action === "update_price") return register(payload, store);
  if (action === "stage_csv") return stageCsv(payload, store);
  if (action === "approve_import") return approveImport(payload, store);
  if (action === "save_quote") return m30.run({ ...payload, action: "save" }, store);
  if (action === "get_quote") return m30.run({ action: "get", quote_id: get(payload, "quote_id") }, store);
  if (action === "record_usage") return m23.run({ ...payload, action: "record" }, store);
  if (action === "tool") {
    const ideaId = textValue(get(payload, "idea_id"), "idea_id");
    if (!TOOL_IDEAS.has(ideaId)) {
      throw new ValidationError("idea_id: 委譲可能な案を選択してください");
    }
    const toolPayload = get(payload, "payload");
    if (
      !isDict(toolPayload) ||
      !truthy(get(toolPayload, "action")) ||
      pyStr(get(toolPayload, "action", "")).endsWith("_demo") ||
      ["save_demo", "record_demo", "quote_demo"].includes(get(toolPayload, "action") as string)
    ) {
      throw new ValidationError("payload.action: デモ動作ではない入力を指定してください");
    }
    return (await moduleFor(ideaId)).run(toolPayload, store);
  }
  throw new ValidationError("action: dashboard / register / update_price / stage_csv / approve_import / save_quote / get_quote / record_usage");
}

async function dashboard(payload: Json, store: Store): Promise<Json> {
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const grouped = new Map<string, PriceVersion[]>();
  for (const version of await store.priceVersions()) {
    const item = (version.item ?? {}) as Partial<PriceVersion["item"]>;
    const key = JSON.stringify([item.item_id ?? null, item.price_type ?? null, get(version, "supplier_id", "")]);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(version);
  }
  const current: PriceVersion[] = [];
  for (const history of grouped.values()) {
    const eligible: { version: PriceVersion; index: number }[] = [];
    for (const [index, version] of history.entries()) {
      const start = dateValue(version.valid_from, "valid_from");
      if (get(version, "status") === "approved" && start <= asOf) eligible.push({ version, index });
    }
    current.push(
      eligible.length > 0 ? maxBy(eligible, (entry) => [entry.version.valid_from, entry.index]).version : history[history.length - 1],
    );
  }
  let inventory: Json[] = [];
  for (const version of current) {
    const item = version.item;
    const start = dateValue(version.valid_from, "valid_from");
    const end = truthy(get(version, "valid_until")) ? dateValue(version.valid_until, "valid_until") : null;
    const metadata = (get(version, "metadata", {}) ?? {}) as Json;
    const checkedAt = get(metadata, "checked_at");
    const checkedDate = truthy(checkedAt) ? dateValue(checkedAt, "checked_at") : null;
    const issues: string[] = [];
    if (checkedDate && checkedDate > asOf) issues.push("確認日が適用日より未来");
    if (get(version, "status") !== "approved") issues.push("未承認");
    if (start > asOf || (end && end < asOf)) issues.push("有効期間外");
    if (issues.length === 0 && checkedDate === null) issues.push("価格確認日不明");
    inventory.push({
      ...item,
      price_version_id: version.price_version_id,
      supplier_id: get(version, "supplier_id", ""),
      valid_from: version.valid_from,
      valid_until: get(version, "valid_until"),
      age_days: checkedDate ? daysBetween(asOf, checkedDate) : null,
      freshness: issues.includes("価格確認日不明") ? "未確認" : issues.length === 0 ? "current" : "stale",
      issues,
      conditions: priceConditions(version as unknown as Json),
    });
  }
  inventory = sortedBy(inventory, (row) => [row.item_id as string, row.price_type as string, row.supplier_id as string]);
  return {
    status: "ok",
    as_of: asOf,
    summary: {
      item_count: new Set(inventory.map((row) => row.item_id)).size,
      price_count: inventory.length,
      issue_count: inventory.filter((row) => (row.issues as string[]).length > 0).length,
    },
    inventory,
    quotes: await store.records(m30.QUOTE_NAMESPACE),
    issues: inventory
      .filter((row) => (row.issues as string[]).length > 0)
      .map((row) => ({ item_id: row.item_id, price_version_id: row.price_version_id, issues: row.issues })),
    simulator: inventory.some((row) => pyStr(get(row, "source", "")).startsWith("simulator:")),
  };
}

async function register(payload: Json, store: Store): Promise<Json> {
  const item = validateItem(get(payload, "item"));
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason"), "reason");
  const supplierId = await supplierIdFor(payload, store, item.item_id, item.price_type);
  const previous = await store.priceVersions(item.item_id, item.price_type, supplierId);
  const prior = previous.length > 0 ? previous[previous.length - 1] : null;
  const validFrom = get(payload, "valid_from", item.updated_at);
  const validUntil = get(payload, "valid_until", prior ? get(prior, "valid_until") : null);
  const suppliedConditions = get(payload, "conditions", {});
  if (!isDict(suppliedConditions)) {
    throw new ValidationError("conditions: 取引条件を確認してください");
  }
  const metadata: Json = prior ? pyDict(get(prior, "metadata", {})) : {};
  for (const [key, value] of Object.entries(suppliedConditions)) {
    if (key === "conditions" && isDict(value)) {
      const nested: Json = pyDict(get(metadata, "conditions", {}));
      Object.assign(nested, value);
      metadata[key] = nested;
      for (const [termKey, termValue] of Object.entries(value)) metadata[termKey] = termValue;
    } else {
      metadata[key] = value;
      const nested: Json = pyDict(get(metadata, "conditions", {}));
      if (has(nested, key)) {
        nested[key] = value;
        metadata.conditions = nested;
      }
    }
  }
  // 引継ぎ・指定した取引条件の表記を、版を追記する前に検査する。
  priceConditions({ metadata });
  if (truthy(get(payload, "checked_at"))) {
    metadata.checked_at = dateValue(payload.checked_at, "checked_at");
  }
  // Python ではキーワード引数の重複は TypeError になる。
  const duplicate = ADD_PRICE_PARAMS.find((name) => has(metadata, name));
  if (duplicate) {
    throw new TypeError(`Store.add_price() got multiple values for keyword argument '${duplicate}'`);
  }
  const saved = await store.addPrice(item, confirmer, {
    supplier_id: supplierId,
    valid_from: validFrom,
    valid_until: validUntil,
    reason,
    ...metadata,
  });
  return { status: "saved", item: saved.item, price_version: saved, simulator: pyStr(item.source).startsWith("simulator:") };
}

async function supplierIdFor(payload: Json, store: Store, itemId: string, priceType: string): Promise<string> {
  if (has(payload, "supplier_id")) {
    return truthy(payload.supplier_id) ? textValue(payload.supplier_id, "supplier_id") : "";
  }
  const suppliers = new Set((await store.priceVersions(itemId, priceType)).map((version) => get(version, "supplier_id", "") as string));
  if (suppliers.size > 1) {
    throw new ValidationError("supplier_id: 複数の仕入先があるため指定してください");
  }
  return suppliers.size > 0 ? [...suppliers][0] : "";
}

async function stageCsv(payload: Json, store: Store): Promise<Json> {
  return store.transaction(async () => {
    const stagePayload: Json = {
      action: "stage",
      csv_text: get(payload, "csv_text"),
      source: get(payload, "source", "CSV取込"),
      field_map: get(payload, "field_map"),
    };
    if (get(payload, "source_key") !== null) stagePayload.source_key = payload.source_key;
    const requested = get(payload, "import_batch_id", get(payload, "batch_id"));
    const batchId = requested !== null ? textValue(requested, "import_batch_id") : uuidHex();
    if ((await store.records(IMPORT_BATCH_NAMESPACE, batchId)).length > 0) {
      throw new ValidationError("import_batch_id: 既存バッチIDです");
    }
    const result = await m09.run(stagePayload, store);
    const candidateIds = (result.staged_rows as Json[]).map((row) => row.record_id);
    await store.put(
      IMPORT_BATCH_NAMESPACE,
      { batch_id: batchId, candidate_ids: candidateIds, source_key: result.source_key, mapping_version: result.mapping_version },
      batchId,
    );
    return { ...result, batch_id: batchId, import_batch_id: batchId };
  });
}

async function approveImport(payload: Json, store: Store): Promise<Json> {
  const batchId = textValue(get(payload, "import_batch_id", get(payload, "batch_id")), "import_batch_id");
  const batch = await store.latest(IMPORT_BATCH_NAMESPACE, batchId);
  const candidateIds = get(payload, "candidate_ids");
  if (!Array.isArray(candidateIds) || candidateIds.length === 0) {
    throw new ValidationError("candidate_ids: 候補IDを選択してください");
  }
  const owned = (batch.candidate_ids ?? []) as unknown[];
  if (candidateIds.some((candidateId) => !owned.some((entry) => pyEqual(entry, candidateId)))) {
    throw new ValidationError("candidate_ids: 指定バッチに属する候補を選択してください");
  }
  const confirmer = approvedBy(payload);
  return store.transaction(async () => {
    const result = await m09.run({ action: "approve", candidate_ids: candidateIds, confirmed_by: confirmer }, store);
    const approved = [...new Set([...((get(batch, "approved_candidate_ids", []) ?? []) as string[]), ...(candidateIds as string[])])];
    await store.put(
      IMPORT_BATCH_NAMESPACE,
      { ...batch, approved_candidate_ids: approved.sort(compareStrings) },
      batchId,
    );
    return result;
  });
}
