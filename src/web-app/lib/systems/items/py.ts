// 元の Python 実装の標準ライブラリの振る舞いを TypeScript で再現する小さな道具。
// 文字列の strip / casefold / 並べ替え、ISO 日付の解釈と表記、JSON（小数は Decimal）を扱う。
import { Decimal } from "./decimal";

// ---- 文字列 ----

const PY_SPACE = String.fromCharCode(0x9, 0xa, 0xb, 0xc, 0xd, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000);

/** str.isspace() の1文字版。 */
export function isPySpace(ch: string): boolean {
  return ch.length > 0 && PY_SPACE.includes(ch);
}

/** str.strip()（Python の空白文字の集合で両端を落とす）。 */
export function pyStrip(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && PY_SPACE.includes(text[start])) start += 1;
  while (end > start && PY_SPACE.includes(text[end - 1])) end -= 1;
  return text.slice(start, end);
}

/** str.casefold() の近似（小文字化と ß→ss など主要な追加変換）。 */
export function casefold(text: string): string {
  return text.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ");
}

/** Python の文字列比較（コードポイント順）。 */
export function compareStrings(a: string, b: string): number {
  if (a === b) return 0;
  const ai = a[Symbol.iterator]();
  const bi = b[Symbol.iterator]();
  for (;;) {
    const x = ai.next();
    const y = bi.next();
    if (x.done && y.done) return 0;
    if (x.done) return -1;
    if (y.done) return 1;
    const cx = x.value.codePointAt(0)!;
    const cy = y.value.codePointAt(0)!;
    if (cx !== cy) return cx < cy ? -1 : 1;
  }
}

export type SortKey = string | number | bigint | boolean | null | Decimal | SortKey[];

/** Python のタプル比較（sorted の key 用）。型が混ざると TypeError。 */
export function compareKeys(a: SortKey, b: SortKey): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.min(a.length, b.length); i += 1) {
      // Python は等しい要素を飛ばして最初に異なる要素で比較する。
      if (pyEqual(a[i], b[i])) continue;
      return compareKeys(a[i], b[i]);
    }
    return a.length - b.length;
  }
  const isNum = (v: SortKey) => v instanceof Decimal || typeof v === "number" || typeof v === "bigint" || typeof v === "boolean";
  if (isNum(a) && isNum(b)) {
    const x = a instanceof Decimal ? a : Decimal.parse(String(typeof a === "boolean" ? Number(a) : a));
    const y = b instanceof Decimal ? b : Decimal.parse(String(typeof b === "boolean" ? Number(b) : b));
    return x.cmp(y);
  }
  if (typeof a === "string" && typeof b === "string") return compareStrings(a, b);
  throw new TypeError(`'<' not supported between instances of '${pyTypeName(a)}' and '${pyTypeName(b)}'`);
}

/** sorted(values, key=...)（安定ソート）。 */
export function sortedBy<T>(values: Iterable<T>, key: (value: T) => SortKey): T[] {
  return [...values]
    .map((value, index) => ({ value, index, key: key(value) }))
    .sort((x, y) => compareKeys(x.key, y.key) || x.index - y.index)
    .map((entry) => entry.value);
}

/** max(values, key=...)（同値なら最初のもの）。 */
export function maxBy<T>(values: T[], key: (value: T) => SortKey): T {
  if (values.length === 0) throw new TypeError("max() iterable argument is empty");
  let best = values[0];
  let bestKey = key(best);
  for (const value of values.slice(1)) {
    const k = key(value);
    if (compareKeys(k, bestKey) > 0) {
      best = value;
      bestKey = k;
    }
  }
  return best;
}

export function pyTypeName(value: unknown): string {
  if (value === null || value === undefined) return "NoneType";
  if (typeof value === "string") return "str";
  if (typeof value === "boolean") return "bool";
  if (typeof value === "number" || typeof value === "bigint") return Number.isInteger(Number(value)) ? "int" : "float";
  if (value instanceof Decimal) return "decimal.Decimal";
  if (Array.isArray(value)) return "list";
  return "dict";
}

// ---- 型の判定（JSON 由来の値） ----

/** isinstance(value, dict) */
export function isDict(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) && !(value instanceof Decimal);
}

/** isinstance(value, int) かつ bool ではない（JSON の整数）。 */
export function isInt(value: unknown): value is number | bigint {
  return (typeof value === "number" && Number.isInteger(value)) || typeof value === "bigint";
}

/** Python の真偽値判定（bool(value)）。 */
export function truthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false) return false;
  if (typeof value === "string") return value.length > 0;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "bigint") return value !== BigInt(0);
  if (value instanceof Decimal) return !value.isZero();
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

export function has(obj: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/** dict.get(key, default)：キーがなければ既定値（None は値として返す）。 */
export function get(obj: Record<string, unknown>, key: string, fallback: unknown = null): unknown {
  return has(obj, key) ? obj[key] : fallback;
}

/** Python の == （dict / list / Decimal / 数値を値で比較）。 */
export function pyEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === undefined || b === undefined) return false;
  const numeric = (v: unknown) =>
    v instanceof Decimal || typeof v === "number" || typeof v === "bigint" || typeof v === "boolean";
  if (numeric(a) && numeric(b)) {
    const x = a instanceof Decimal ? a : Decimal.parse(String(typeof a === "boolean" ? Number(a) : a));
    const y = b instanceof Decimal ? b : Decimal.parse(String(typeof b === "boolean" ? Number(b) : b));
    if (x.isNaN() || y.isNaN()) return false;
    return x.cmp(y) === 0;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((value, index) => pyEqual(value, b[index]));
  }
  if (isDict(a) && isDict(b)) {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((key) => has(b, key) && pyEqual(a[key], b[key]));
  }
  return false;
}

/** str(value)（Python の表記。None / True / False / dict / list も Python 風）。 */
export function pyStr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "bigint" || value instanceof Decimal) return String(value);
  return pyRepr(value);
}

/** repr(value) の近似（dict / list の表示用）。 */
export function pyRepr(value: unknown): string {
  if (typeof value === "string") return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
  if (value instanceof Decimal) return `Decimal('${value.toString()}')`;
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(", ")}]`;
  if (isDict(value)) return `{${Object.entries(value).map(([k, v]) => `${pyRepr(k)}: ${pyRepr(v)}`).join(", ")}}`;
  return pyStr(value);
}

// ---- 日付 ----

export type PyDate = { year: number; month: number; day: number };

export type PyDateTime = PyDate & {
  hour: number;
  minute: number;
  second: number;
  microsecond: number;
  /** UTC からのずれ（秒）。タイムゾーンなしは null。 */
  offsetSeconds: number | null;
};

function daysInMonth(year: number, month: number): number {
  if (month === 2) return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0 ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function validDate(year: number, month: number, day: number): boolean {
  return year >= 1 && year <= 9999 && month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth(year, month);
}

function utcDays(date: PyDate): number {
  const ms = new Date(0);
  ms.setUTCFullYear(date.year, date.month - 1, date.day);
  ms.setUTCHours(0, 0, 0, 0);
  return Math.round(ms.getTime() / 86400000);
}

function fromUtcDays(days: number): PyDate {
  const d = new Date(days * 86400000);
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

function fromIsoWeek(year: number, week: number, weekday: number): PyDate | null {
  if (week < 1 || week > 53 || weekday < 1 || weekday > 7) return null;
  // ISO 週: その年の1月4日を含む週が第1週。
  const jan4 = utcDays({ year, month: 1, day: 4 });
  const jan4Weekday = ((((jan4 + 4) % 7) + 7) % 7) || 7; // 1970-01-01 は木曜（4）
  const week1Monday = jan4 - (jan4Weekday - 1);
  if (week === 53) {
    const dec28 = utcDays({ year, month: 12, day: 28 });
    if (Math.floor((dec28 - week1Monday) / 7) + 1 < 53) return null;
  }
  return fromUtcDays(week1Monday + (week - 1) * 7 + (weekday - 1));
}

/** date.fromisoformat()（Python 3.11 以降: YYYY-MM-DD / YYYYMMDD / 週番号）。解釈できなければ null。 */
export function parseIsoDate(text: string): PyDate | null {
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text) ?? /^(\d{4})(\d{2})(\d{2})$/.exec(text);
  if (m) {
    const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
    return validDate(year, month, day) ? { year, month, day } : null;
  }
  m = /^(\d{4})-W(\d{2})(?:-(\d))?$/.exec(text) ?? /^(\d{4})W(\d{2})(\d)?$/.exec(text);
  if (m) {
    const year = Number(m[1]);
    if (year < 1) return null;
    return fromIsoWeek(year, Number(m[2]), m[3] ? Number(m[3]) : 1);
  }
  return null;
}

function parseIsoTime(text: string): Omit<PyDateTime, keyof PyDate> | null {
  let tz: number | null = null;
  let body = text;
  const tzMatch = /(?:([+-])(\d{2})(?::?(\d{2})(?::?(\d{2})(?:\.(\d{1,6}))?)?)?|Z)$/.exec(body);
  if (tzMatch && tzMatch.index > 0) {
    if (tzMatch[0] === "Z") {
      tz = 0;
    } else {
      const hours = Number(tzMatch[2]);
      const minutes = Number(tzMatch[3] ?? 0);
      const seconds = Number(tzMatch[4] ?? 0);
      if (hours > 23 || minutes > 59 || seconds > 59) return null;
      tz = (tzMatch[1] === "-" ? -1 : 1) * (hours * 3600 + minutes * 60 + seconds);
    }
    body = body.slice(0, tzMatch.index);
  }
  const m =
    /^(\d{2})(?::(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?$/.exec(body) ??
    /^(\d{2})(?:(\d{2})(?:(\d{2})(?:[.,](\d+))?)?)?$/.exec(body);
  if (!m) return null;
  const hour = Number(m[1]);
  const minute = Number(m[2] ?? 0);
  const second = Number(m[3] ?? 0);
  const fraction = m[4] ?? "";
  if (hour > 23 || minute > 59 || second > 59) return null;
  const microsecond = Number((fraction.slice(0, 6) + "000000").slice(0, 6));
  return { hour, minute, second, microsecond, offsetSeconds: tz };
}

/** datetime.fromisoformat()（Python 3.11 以降の主な形式）。解釈できなければ null。 */
export function parseIsoDatetime(text: string): PyDateTime | null {
  const dateOnly = parseIsoDate(text);
  if (dateOnly) return { ...dateOnly, hour: 0, minute: 0, second: 0, microsecond: 0, offsetSeconds: null };
  // 日付部分（10文字 / 8文字 / 週の7〜10文字）＋任意の区切り1文字＋時刻
  const chars = [...text];
  for (const length of [10, 8, 7, 9]) {
    if (chars.length <= length + 1) continue;
    const date = parseIsoDate(chars.slice(0, length).join(""));
    if (!date) continue;
    const time = parseIsoTime(chars.slice(length + 1).join(""));
    if (time) return { ...date, ...time };
  }
  return null;
}

const pad = (value: number, size = 2) => String(value).padStart(size, "0");

/** date.isoformat() */
export function isoDate(value: PyDate): string {
  return `${pad(value.year, 4)}-${pad(value.month)}-${pad(value.day)}`;
}

/** datetime.isoformat() */
export function isoDatetime(value: PyDateTime): string {
  let text = `${isoDate(value)}T${pad(value.hour)}:${pad(value.minute)}:${pad(value.second)}`;
  if (value.microsecond) text += `.${pad(value.microsecond, 6)}`;
  if (value.offsetSeconds !== null) {
    const sign = value.offsetSeconds < 0 ? "-" : "+";
    const total = Math.abs(value.offsetSeconds);
    text += `${sign}${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}`;
    if (total % 60) text += `:${pad(total % 60)}`;
  }
  return text;
}

/** 'YYYY-MM-DD' 同士の日数差（(a - b).days）。 */
export function daysBetween(a: string, b: string): number {
  return utcDays(parseIsoDate(a)!) - utcDays(parseIsoDate(b)!);
}

/** date + timedelta(days=n) を 'YYYY-MM-DD' で返す。 */
export function addDays(date: string, days: number): string {
  return isoDate(fromUtcDays(utcDays(parseIsoDate(date)!) + days));
}

/** datetime.now(timezone.utc).isoformat()（マイクロ秒は ms×1000）。 */
export function utcNowIso(): string {
  const now = new Date();
  return isoDatetime({
    year: now.getUTCFullYear(),
    month: now.getUTCMonth() + 1,
    day: now.getUTCDate(),
    hour: now.getUTCHours(),
    minute: now.getUTCMinutes(),
    second: now.getUTCSeconds(),
    microsecond: now.getUTCMilliseconds() * 1000,
    offsetSeconds: 0,
  });
}

/** uuid4().hex */
export function uuidHex(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

// ---- JSON ----

export class NonFiniteNumberError extends Error {
  constructor() {
    super("NaN / Infinity は使用できません");
    this.name = "NonFiniteNumberError";
  }
}

/**
 * json.loads(text, parse_float=Decimal)。小数・指数付きの数は Decimal、整数は number（安全な範囲を超えれば bigint）。
 * NaN / Infinity は受け付けない（元の HTTP 入口と同じ）。同じキーが重複したら後の値。
 */
export function parseJson(text: string): unknown {
  let index = 0;
  const fail = (message = "JSON形式を確認してください"): never => {
    // json.JSONDecodeError と同じ「行・桁・文字位置」の表記。
    const before = text.slice(0, index);
    const line = before.split("\n").length;
    const column = index - (before.lastIndexOf("\n") + 1) + 1;
    throw new SyntaxError(`${message}: line ${line} column ${column} (char ${index})`);
  };
  const ws = () => {
    while (index < text.length && " \t\n\r".includes(text[index])) index += 1;
  };
  const parseString = (): string => {
    index += 1;
    let out = "";
    for (;;) {
      if (index >= text.length) fail("Unterminated string");
      const ch = text[index];
      if (ch === '"') {
        index += 1;
        return out;
      }
      if (ch === "\\") {
        const next = text[index + 1];
        const map: Record<string, string> = { '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" };
        if (next === "u") {
          const hex = text.slice(index + 2, index + 6);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail("Invalid \\uXXXX escape");
          out += String.fromCharCode(parseInt(hex, 16));
          index += 6;
          continue;
        }
        if (!(next in map)) fail("Invalid \\escape");
        out += map[next];
        index += 2;
        continue;
      }
      if (ch < " ") fail("Invalid control character");
      out += ch;
      index += 1;
    }
  };
  const parseValue = (): unknown => {
    ws();
    const ch = text[index];
    if (ch === "{") {
      index += 1;
      const obj: Record<string, unknown> = {};
      ws();
      if (text[index] === "}") {
        index += 1;
        return obj;
      }
      for (;;) {
        ws();
        if (text[index] !== '"') fail("Expecting property name enclosed in double quotes");
        const key = parseString();
        ws();
        if (text[index] !== ":") fail("Expecting ':' delimiter");
        index += 1;
        const value = parseValue();
        Object.defineProperty(obj, key, { value, enumerable: true, writable: true, configurable: true });
        ws();
        if (text[index] === ",") {
          index += 1;
          continue;
        }
        if (text[index] === "}") {
          index += 1;
          return obj;
        }
        fail("Expecting ',' delimiter");
      }
    }
    if (ch === "[") {
      index += 1;
      const arr: unknown[] = [];
      ws();
      if (text[index] === "]") {
        index += 1;
        return arr;
      }
      for (;;) {
        arr.push(parseValue());
        ws();
        if (text[index] === ",") {
          index += 1;
          continue;
        }
        if (text[index] === "]") {
          index += 1;
          return arr;
        }
        fail("Expecting ',' delimiter");
      }
    }
    if (ch === '"') return parseString();
    if (text.startsWith("true", index)) {
      index += 4;
      return true;
    }
    if (text.startsWith("false", index)) {
      index += 5;
      return false;
    }
    if (text.startsWith("null", index)) {
      index += 4;
      return null;
    }
    if (text.startsWith("NaN", index) || text.startsWith("Infinity", index) || text.startsWith("-Infinity", index)) {
      throw new NonFiniteNumberError();
    }
    const m = /^-?(?:0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?/.exec(text.slice(index, index + 4000));
    if (!m) return fail("Expecting value");
    index += m[0].length;
    if (m[1] !== undefined || m[2] !== undefined) return Decimal.parse(m[0]);
    const big = BigInt(m[0]);
    return big >= BigInt(Number.MIN_SAFE_INTEGER) && big <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(big) : big;
  };
  const value = parseValue();
  ws();
  if (index !== text.length) fail("Extra data");
  return value;
}

/** Decimal を文字列、bigint を数値へ直した JSON 値（保存・レスポンス用）。 */
export function toJsonValue(value: unknown): unknown {
  if (value instanceof Decimal) return value.toString();
  if (typeof value === "bigint") return Number(value);
  if (Array.isArray(value)) return value.map(toJsonValue);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value)) {
      if (entry !== undefined) out[key] = toJsonValue(entry);
    }
    return out;
  }
  return value;
}

/** json.dumps 相当（Decimal は文字列）。 */
export function dumps(value: unknown, indent?: number): string {
  return JSON.stringify(toJsonValue(value), null, indent);
}

/** 保存して読み戻したときの値（json.loads(dumps(value))）。 */
export function roundTrip<T = unknown>(value: unknown): T {
  return JSON.parse(dumps(value)) as T;
}
