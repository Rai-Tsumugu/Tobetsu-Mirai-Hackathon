// M12: OCR候補・人確認キュー（m12.py の移植）。mock OCR の候補を項目ごとに人が確定する。
import { Decimal } from "./decimal";
import {
  CATEGORIES,
  DEMO_DATE,
  ITEM_FIELDS,
  PRICE_TYPES,
  ValidationError,
  approvedBy,
  dateValue,
  decimalValue,
  textValue,
  validateItem,
  type Item,
  type Json,
  type PriceVersion,
  type Store,
} from "./core";
import { get, has, isDict, pyStr, pyStrip, sortedBy } from "./py";

const CONFIDENCE_THRESHOLD = 0.8;
const DEMO_FIELDS = {
  item_id: { value: "demo-m12-thinner", confidence: "0.99" },
  name: { value: "架空デモ溶剤", confidence: "0.96" },
  category: { value: "溶剤", confidence: "0.99" },
  unit: { value: "L", confidence: "0.98" },
  unit_price: { value: "480", confidence: "0.94" },
  price_type: { value: "仕入", confidence: "0.97" },
  source: { value: "simulator:架空OCR価格票", confidence: "0.92" },
  updated_at: { value: DEMO_DATE, confidence: "0.95" },
};

export const SPEC = {
  idea_id: "M12",
  title: "OCR候補・人確認キュー",
  description: "mock OCRの品目候補を項目ごとに確認し、全項目を人が確定した場合だけ価格登録します。",
  defaults: {
    action: "stage",
    source_key: "demo-m12-ocr",
    ocr_fields: DEMO_FIELDS,
    source: "simulator:架空OCR",
  },
};

/** float(value)。変換できなければ TypeError / ValueError 相当の例外。 */
function pyFloat(value: unknown): number {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number") return value;
  if (typeof value === "bigint") return Number(value);
  if (value instanceof Decimal) return Number(value.toString());
  if (typeof value === "string") {
    const text = pyStrip(value);
    const special = /^([+-]?)(inf|infinity|nan)$/i.exec(text);
    if (special) {
      if (special[2].toLowerCase() === "nan") return NaN;
      return special[1] === "-" ? -Infinity : Infinity;
    }
    if (/^[+-]?(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/.test(text)) {
      return Number(text.replace(/_/g, ""));
    }
    throw new ValueError(`could not convert string to float: ${JSON.stringify(value)}`);
  }
  throw new TypeError(`float() argument must be a string or a real number, not '${value === null ? "NoneType" : typeof value}'`);
}

class ValueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValueError";
  }
}

function extraKeys(payload: Json, allowed: string[]): boolean {
  return Object.keys(payload).some((key) => !allowed.includes(key));
}

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "stage");
  if (action === "stage") {
    if (extraKeys(payload, ["action", "source_key", "ocr_fields", "source"])) {
      throw new ValidationError("payload: OCR原文や未対応のデータは受け付けません");
    }
    return stage(payload, store);
  }
  if (action === "review") {
    if (extraKeys(payload, ["action", "candidate_id", "fields", "confirmed_by"])) {
      throw new ValidationError("payload: OCR原文や未対応のデータは受け付けません");
    }
    return review(payload, store);
  }
  throw new ValidationError("action: stage または review を指定してください");
}

async function stage(payload: Json, store: Store): Promise<Json> {
  const sourceKey = textValue(get(payload, "source_key"), "source_key");
  if ([...sourceKey].length > 128) {
    throw new ValidationError("source_key: 128文字以下にしてください");
  }
  const source = textValue(get(payload, "source", "simulator:架空OCR"), "source");
  const fields = get(payload, "ocr_fields");
  if (!isDict(fields) || Object.keys(fields).some((key) => !(ITEM_FIELDS as readonly string[]).includes(key))) {
    throw new ValidationError("ocr_fields: 共通品目項目の候補を指定してください");
  }

  // 項目ごとの候補だけを受け取り、伝票・画像の全文は保存しない。
  const candidates: Json = {};
  for (const field of ITEM_FIELDS) {
    const candidate = get(fields, field);
    let value: string | null = null;
    let confidence: string | null = null;
    if (isDict(candidate)) {
      const rawValue = get(candidate, "value");
      const rawConfidence = get(candidate, "confidence");
      if (rawValue !== null && typeof rawValue === "string") {
        value = pyStrip(rawValue) || null;
      }
      try {
        const number = pyFloat(rawConfidence);
        if (number >= 0 && number <= 1) confidence = pyStr(rawConfidence);
      } catch (error) {
        if (!(error instanceof TypeError || error instanceof ValueError)) throw error;
      }
    }
    if (confidence === null || pyFloat(confidence) < CONFIDENCE_THRESHOLD || value === null) {
      value = null;
    }
    candidates[field] = { candidate_value: value, confidence };
  }

  const queue = await store.put("m12_ocr_queue", {
    source_key: sourceKey,
    source,
    candidates,
    corrected_values: {},
    confirmed_fields: [],
    reviewer: null,
    status: "pending",
    ocr_connected: false,
    simulator: true,
  });
  return {
    status: "人の確認待ち",
    candidate_id: queue.record_id,
    candidates,
    confirmed_fields: [],
    missing_fields: [...ITEM_FIELDS],
    items: [],
    simulator: true,
    ocr_connected: false,
    message: "OCRはmock読取候補です。実画像OCRは未接続です。",
  };
}

async function review(payload: Json, store: Store): Promise<Json> {
  const candidateId = textValue(get(payload, "candidate_id"), "candidate_id");
  const reviewer = approvedBy(payload);
  const rawUpdates = get(payload, "fields");
  if (!isDict(rawUpdates) || Object.keys(rawUpdates).length === 0) {
    throw new ValidationError("fields: 確認する項目を指定してください");
  }
  if (Object.keys(rawUpdates).some((key) => !(ITEM_FIELDS as readonly string[]).includes(key))) {
    throw new ValidationError("fields: 共通品目項目だけ確認できます");
  }

  const queue = await store.latest("m12_ocr_queue", candidateId);
  if (queue.status === "approved") {
    throw new ValidationError("この候補はすでに登録されています");
  }

  const correctedValues: Json = { ...(queue.corrected_values as Json) };
  const confirmedFields = new Set(queue.confirmed_fields as string[]);
  const updates: Json = {};
  for (const [field, update] of Object.entries(rawUpdates)) {
    if (!isDict(update) || get(update, "confirmed") !== true) {
      throw new ValidationError(`${field}: 人の確認を明示してください`);
    }
    let value = get(update, "corrected_value");
    if (value === null || typeof value !== "string" || !pyStrip(value)) {
      throw new ValidationError(`${field}: 確認済みの値を入力してください`);
    }
    value = pyStrip(value);
    validateField(field, value as string);
    // 正規の項目と訂正値だけを保存し、元の文字列は保存しない。
    updates[field] = value;
    correctedValues[field] = value;
    confirmedFields.add(field);
  }

  if (!has(correctedValues, "source")) {
    correctedValues.source = queue.source;
  }
  const missingFields = ITEM_FIELDS.filter((field) => !confirmedFields.has(field));
  let status = "pending";
  let registered: Item | null = null;
  let version: PriceVersion | null = null;
  if (missingFields.length === 0) {
    const item = validateItem(correctedValues);
    version = await store.addPrice(item, reviewer, { reason: "OCR候補の全必須欄を人が確認", ocr_candidate_id: candidateId });
    registered = version.item;
    status = "approved";
  }

  const sortedConfirmed = sortedBy(confirmedFields, (field) => field);
  await store.transaction(async () => {
    await store.put(
      "m12_ocr_review",
      {
        candidate_id: candidateId,
        corrected_value: updates,
        confirmed_fields: sortedBy(Object.keys(updates), (field) => field),
        reviewer,
        status,
      },
      candidateId,
    );
    await store.put(
      "m12_ocr_queue",
      {
        source_key: queue.source_key,
        source: queue.source,
        candidates: queue.candidates,
        corrected_values: correctedValues,
        confirmed_fields: sortedConfirmed,
        reviewer,
        status,
        ocr_connected: false,
        simulator: true,
      },
      candidateId,
    );
  });

  const result: Json = {
    status: registered ? "approved" : "人の確認待ち",
    candidate_id: candidateId,
    corrected_value: updates,
    confirmed_fields: sortedBy(confirmedFields, (field) => field),
    missing_fields: missingFields,
    reviewer,
    items: registered ? [registered] : [],
    simulator: true,
    ocr_connected: false,
  };
  if (registered) {
    result.price_version_id = version!.price_version_id;
  }
  return result;
}

function validateField(field: string, value: string): void {
  if (field === "unit_price") {
    decimalValue(value, field);
  } else if (field === "updated_at") {
    dateValue(value, field);
  } else if (field === "category" && !(CATEGORIES as readonly string[]).includes(value)) {
    throw new ValidationError("category: 選択値を確認してください");
  } else if (field === "price_type" && !(PRICE_TYPES as readonly string[]).includes(value)) {
    throw new ValidationError("price_type: 選択値を確認してください");
  } else {
    textValue(value, field);
  }
}
