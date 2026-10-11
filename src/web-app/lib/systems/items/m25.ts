// M25: 手入力した原料指数を参考表示する。価格へは反映しない（m25.py の移植）。
import { ValidationError, decimalValue, textValue, type Json, type Store } from "./core";
import { get, isDict, parseIsoDatetime, truthy } from "./py";

export const SPEC = {
  idea_id: "M25",
  title: "原料指数参考カード",
  description: "手入力した原料指数を出所と利用条件の状態付きで参考表示します。",
  defaults: {
    action: "seed_demo",
    source: "simulator:架空データ出典",
    series: "架空ナフサ指数",
    value: "123.4",
    unit: "指数ポイント",
    published_at: "2026-10-01",
    fetched_at: "2026-10-11T09:00:00+09:00",
    terms_status: "未確認",
  },
};

export const NAMESPACE = "index_observation";
const FIELDS = ["source", "series", "value", "unit", "published_at", "fetched_at", "terms_status"];

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "list");
  if (action === "record") {
    checkKeys(payload, ["action", ...FIELDS]);
    return record(payload, store, false);
  }
  if (action === "seed_demo") {
    checkKeys(payload, ["action", ...FIELDS]);
    await record(payload, store, true);
    return list(store);
  }
  if (action === "list") {
    checkKeys(payload, ["action"]);
    return list(store);
  }
  throw new ValidationError("action: record / list / seed_demo を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

async function record(payload: Json, store: Store, fictional: boolean): Promise<Json> {
  const source = textValue(get(payload, "source"), "source");
  const series = textValue(get(payload, "series"), "series");
  const value = decimalValue(get(payload, "value"), "value");
  const unit = textValue(get(payload, "unit"), "unit");
  const publishedAt = timestamp(get(payload, "published_at"), "published_at");
  const fetchedAt = timestamp(get(payload, "fetched_at"), "fetched_at");
  const termsStatus = textValue(get(payload, "terms_status"), "terms_status");
  const row: Json = {
    source,
    series,
    value: value.toString(),
    unit,
    published_at: publishedAt,
    fetched_at: fetchedAt,
    terms_status: termsStatus,
    simulator: fictional,
    notice: "参考情報のみ。利用規約・再利用条件は未確認。品目の個別価格へ自動反映しません。",
  };
  if (fictional) {
    if (row.value !== SPEC.defaults.value || row.source !== SPEC.defaults.source) {
      throw new ValidationError("seed_demo: 架空デモ値を指定してください");
    }
  }
  const saved = await store.put(NAMESPACE, row);
  return { status: "saved", observation_id: saved.record_id, observation: row, simulator: fictional };
}

async function list(store: Store): Promise<Json> {
  const observations = await store.records(NAMESPACE);
  return {
    observations: observations.map((row) => {
      const out: Json = {};
      for (const key of [...FIELDS, "simulator", "notice"]) {
        if (!(key in row)) throw new TypeError(`KeyError: '${key}'`);
        out[key] = row[key];
      }
      return out;
    }),
    simulator: observations.some((row) => truthy(get(row, "simulator", false))),
    notice: "参考情報のみ。指数を個別品目価格・見積価格へ自動反映しません。",
  };
}

/** datetime.strptime(value, '%Y-%m-%d') の解釈（月日は1桁・日の先頭空白も許す）。 */
function strptimeDate(value: string): boolean {
  const m = /^(\d{4})-(1[0-2]|0[1-9]|[1-9])-(3[01]|[12]\d|0[1-9]|[1-9]| [1-9])$/.exec(value);
  if (!m) return false;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3].trim());
  const date = new Date(Date.UTC(2000, month - 1, day));
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  if (month === 2 && day === 29) return leap && year >= 1;
  return year >= 1 && date.getUTCMonth() === month - 1;
}

function timestamp(input: unknown, field: string): string {
  const value = textValue(input, field);
  // 公表日は日付だけでもよい。取得日時はタイムゾーン付きが必要。
  if (field === "published_at" && value.length === 10) {
    if (!strptimeDate(value)) throw new ValidationError(`${field}: ISO形式の日付または日時が必要です`);
    const m = /^(\d{4})-(\d{1,2})-\s?(\d{1,2})$/.exec(value)!;
    return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  }
  const parsed = parseIsoDatetime(value.replace(/Z/g, "+00:00"));
  if (!parsed) throw new ValidationError(`${field}: ISO形式の日付または日時が必要です`);
  if (field === "fetched_at" && parsed.offsetSeconds === null) {
    throw new ValidationError("fetched_at: タイムゾーン付き日時が必要です");
  }
  return value;
}
