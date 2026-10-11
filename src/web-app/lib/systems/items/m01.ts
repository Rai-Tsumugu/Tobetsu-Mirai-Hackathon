// M01: 塗料コード正規化（m01.py の移植）。価格を推測せず、原表記と正規化コードを分けて保持する。
import { DEMO_DATE, ValidationError, approvedBy, dateValue, textValue, type Json, type Store } from "./core";
import { get, isDict, isPySpace, pyEqual, pyStrip } from "./py";

export const SPEC = {
  idea_id: "M01",
  title: "塗料コード正規化",
  description: "原表記と正規化コード、仕上げを分けて保持し、確認済みの品目単価だけを返します。",
  defaults: {
    action: "register",
    item_id: "demo-paint",
    maker: "架空メーカー",
    raw_code: "DEMO-001",
    finish: "メタリック",
    price_type: "販売",
    as_of: DEMO_DATE,
    confirmed_by: "架空デモ担当",
  },
};

const CONTROL = /^\p{C}$/u;
const ALNUM = /^[\p{L}\p{N}]$/u;

/** 書式だけを正規化する（メーカー固有の規則は未確認）。 */
export function normalizeCode(rawCode: unknown): string {
  if (typeof rawCode !== "string" || !pyStrip(rawCode)) {
    throw new ValidationError("raw_code: 入力が必要です");
  }
  const normalized = pyStrip(rawCode.normalize("NFKC")).toUpperCase();
  const chars = [...normalized];
  if (chars.some((ch) => isPySpace(ch))) {
    throw new ValidationError("raw_code: コード内の空白は曖昧なため確認が必要です");
  }
  if (chars.some((ch) => CONTROL.test(ch))) {
    throw new ValidationError("raw_code: 制御文字を含むコードは使用できません");
  }
  if (!chars.some((ch) => ALNUM.test(ch))) {
    throw new ValidationError("raw_code: 英数字を含むコードが必要です");
  }
  return normalized;
}

function mappingId(maker: string, normalizedCode: string, finish: string): string {
  return JSON.stringify([maker, normalizedCode, finish]);
}

function mappingFields(payload: Json): [string, string, string, string] {
  const maker = textValue(get(payload, "maker"), "maker");
  const rawCode = get(payload, "raw_code");
  if (typeof rawCode !== "string" || !pyStrip(rawCode)) {
    throw new ValidationError("raw_code: 入力が必要です");
  }
  const finish = textValue(get(payload, "finish"), "finish");
  if ([maker, finish].some((value) => [...value].some((ch) => CONTROL.test(ch)))) {
    throw new ValidationError("maker / finish: 制御文字は使用できません");
  }
  const normalizedCode = normalizeCode(rawCode);
  return [maker, rawCode, normalizedCode, finish];
}

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "register");
  if (action === "register") return register(payload, store);
  if (action === "lookup") return lookup(payload, store);
  throw new ValidationError("action: register または lookup を選択してください");
}

async function register(payload: Json, store: Store): Promise<Json> {
  const [maker, rawCode, normalizedCode, finish] = mappingFields(payload);
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const priceType = textValue(get(payload, "price_type", "販売"), "price_type");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const confirmer = approvedBy(payload);

  // 承認済みの価格だけを解決する。色やコードから価格を作らない。
  const version = await store.getPrice(itemId, priceType, { as_of: asOf });
  const item = version.item;
  if (item.category !== "塗料") {
    throw new ValidationError("category: 塗料の品目を選択してください");
  }

  const id = mappingId(maker, normalizedCode, finish);
  const existing = await store.records("paint_code", id);
  const expected: Json = { maker, raw_code: rawCode, normalized_code: normalizedCode, finish, item_id: itemId };
  const sameMapping =
    existing.length > 0 &&
    existing.every((record) => Object.entries(expected).every(([key, value]) => pyEqual(get(record, key), value)));

  // 一般的な正規化で別の表記・別の品目が同じコードになる場合は、メーカー規則を確認するまで保留する。
  const collision = existing.length > 0 && !sameMapping;
  const status = collision ? "pending" : "approved";
  const record: Json = {
    maker,
    raw_code: rawCode,
    normalized_code: normalizedCode,
    finish,
    item_id: itemId,
    status,
    confirmed_by: confirmer,
    reason: status === "approved" ? "正規化コードの対応を人が確認" : "正規化後の対応が曖昧なため要確認",
  };
  if (!sameMapping || !pyEqual(get(existing[existing.length - 1], "status"), status)) {
    await store.transaction(() => store.put("paint_code", record, id));
  }

  if (status !== "approved") {
    return { status, paint_code: record, items: [], reason: record.reason };
  }
  return { status, paint_code: record, item, items: [item], price_version_id: version.price_version_id };
}

async function lookup(payload: Json, store: Store): Promise<Json> {
  const [maker, rawCode, normalizedCode, finish] = mappingFields(payload);
  const priceType = textValue(get(payload, "price_type", "販売"), "price_type");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const mappings = await store.records("paint_code", mappingId(maker, normalizedCode, finish));
  if (mappings.length === 0) {
    throw new ValidationError("paint_code: 登録済みの対応がありません");
  }
  const mapping = mappings[mappings.length - 1];
  if (mapping.status !== "approved" || mapping.raw_code !== rawCode) {
    throw new ValidationError("paint_code: 原表記または対応が未確認です");
  }
  const version = await store.getPrice(mapping.item_id as string, priceType, { as_of: asOf });
  const item = version.item;
  if (item.category !== "塗料") {
    throw new ValidationError("category: 塗料の品目を選択してください");
  }
  const { record_id: _recordId, ...paintCode } = mapping;
  void _recordId;
  return { status: "approved", paint_code: paintCode, item, items: [item], price_version_id: version.price_version_id };
}
