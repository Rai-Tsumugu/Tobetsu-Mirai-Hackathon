/* eslint-disable @typescript-eslint/no-explicit-any */
// Python の動的な振る舞い（真偽値判定・== ・round・sum・json.dumps など）を、
// 元実装（src/auto_repair_engine）と同じ結果になるよう再現する小さな補助関数群。
import { createHash } from "node:crypto";

export type Dict = Record<string, any>;

/** Python の TypeError / ValueError / KeyError。API では 422 に対応する。 */
export class PyTypeError extends Error {}
export class PyValueError extends Error {}
export class PyKeyError extends Error {}
/** Python の AttributeError（元実装では捕捉されず 500 になる）。 */
export class PyAttributeError extends Error {}
/** sqlite3.IntegrityError / sqlite3.ProgrammingError 相当（E04 のメモリ内 DB 模倣用）。 */
export class PyIntegrityError extends Error {}
export class PyProgrammingError extends Error {}

export const isDict = (v: unknown): v is Dict => v !== null && typeof v === "object" && !Array.isArray(v);
export const isList = (v: unknown): v is any[] => Array.isArray(v);
/** isinstance(v, (int, float)) and not isinstance(v, bool) */
export const isNumber = (v: unknown): v is number => typeof v === "number";
/** isinstance(v, int) and not isinstance(v, bool)（JSON では 2.0 と 2 を区別できないので整数値なら int とみなす） */
export const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);
export const isStr = (v: unknown): v is string => typeof v === "string";

/** Python の真偽値判定。 */
export function truthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false) return false;
  if (typeof v === "number") return v !== 0; // NaN は True
  if (typeof v === "string") return v.length > 0;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v as object).some((k) => (v as any)[k] !== undefined);
  return true;
}

/** Python の `a or b`。 */
export function or<T, U>(a: T, b: U): T | U {
  return truthy(a) ? a : b;
}

const hasOwn = (d: object, k: string) => Object.prototype.hasOwnProperty.call(d, k) && (d as any)[k] !== undefined;

/** dict.get(key, default)。dict 以外は AttributeError。 */
export function get(d: unknown, key: string, def: any = null): any {
  if (!isDict(d)) throw new PyAttributeError(`object has no attribute 'get'`);
  return hasOwn(d, key) ? d[key] : def;
}

export const has = (d: unknown, key: string): boolean => isDict(d) && hasOwn(d, key);

/** d[key]（無ければ KeyError）。 */
export function item(d: unknown, key: string): any {
  if (Array.isArray(d)) {
    throw new PyTypeError("list indices must be integers or slices, not str");
  }
  if (!isDict(d)) throw new PyTypeError("object is not subscriptable");
  if (!hasOwn(d, key)) throw new PyKeyError(JSON.stringify(key));
  return d[key];
}

/** Python の ==（bool と数値は等しい扱い、list / dict は再帰比較）。 */
export function pyEq(a: any, b: any): boolean {
  const norm = (x: any) => (typeof x === "boolean" ? (x ? 1 : 0) : x);
  const x = norm(a);
  const y = norm(b);
  if (x === null || x === undefined) return y === null || y === undefined;
  if (y === null || y === undefined) return false;
  if (typeof x === "number" || typeof y === "number") return typeof x === "number" && typeof y === "number" && x === y;
  if (typeof x === "string" || typeof y === "string") return x === y;
  if (Array.isArray(x) || Array.isArray(y)) {
    if (!Array.isArray(x) || !Array.isArray(y) || x.length !== y.length) return false;
    return x.every((v, i) => pyEq(v, y[i]));
  }
  const kx = keysOf(x);
  const ky = keysOf(y);
  if (kx.length !== ky.length) return false;
  return kx.every((k) => hasOwn(y, k) && pyEq(x[k], y[k]));
}

/** `x in container`（list / tuple / dict / str / set）。 */
export function pyIn(x: any, container: any): boolean {
  if (Array.isArray(container)) return container.some((v) => pyEq(v, x));
  if (container instanceof Set) return [...container].some((v) => pyEq(v, x));
  if (typeof container === "string") {
    if (typeof x !== "string") throw new PyTypeError("'in <string>' requires string as left operand");
    return container.includes(x);
  }
  if (isDict(container)) return typeof x === "string" && hasOwn(container, x);
  throw new PyTypeError("argument of type is not iterable");
}

export const keysOf = (d: Dict): string[] => Object.keys(d).filter((k) => d[k] !== undefined);

/** set(dict) == set(keys): dict のキー集合が一致するか。 */
export function keysAre(d: any, keys: string[]): boolean {
  if (!isDict(d)) return false;
  const k = keysOf(d);
  return k.length === keys.length && keys.every((x) => k.includes(x));
}

export function deepcopy<T>(v: T): T {
  return v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T);
}

/** float(x)。数値・bool・数値文字列を受け付け、それ以外は TypeError / ValueError。 */
export function pyFloat(v: any): number {
  if (typeof v === "number") return v;
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "string") {
    const s = v.trim().replace(/_/g, "");
    if (/^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?)$/.test(s)) return Number(s);
    if (/^[+-]?(inf|infinity)$/i.test(s)) return s.startsWith("-") ? -Infinity : Infinity;
    if (/^[+-]?nan$/i.test(s)) return NaN;
    throw new PyValueError(`could not convert string to float: '${v}'`);
  }
  throw new PyTypeError("float() argument must be a string or a real number");
}

/** int(x)（0 方向への切り捨て）。 */
export function pyInt(v: any): number {
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "number") {
    if (!Number.isFinite(v)) throw new PyValueError("cannot convert float to integer");
    return Math.trunc(v);
  }
  if (typeof v === "string") {
    const s = v.trim().replace(/_/g, "");
    if (/^[+-]?\d+$/.test(s)) return Number(s);
    throw new PyValueError(`invalid literal for int() with base 10: '${v}'`);
  }
  throw new PyTypeError("int() argument must be a string, a bytes-like object or a real number");
}

/** math.isfinite(x)（数値以外は TypeError）。 */
export function mathIsFinite(v: any): boolean {
  if (typeof v === "boolean") return true;
  if (typeof v !== "number") throw new PyTypeError("must be real number");
  return Number.isFinite(v);
}

/** Python の round(x, ndigits)。偶数丸め（厳密な 10 進展開で判定）。 */
export function pyRound(x: number, ndigits?: number): number {
  if (!Number.isFinite(x)) return x;
  if (ndigits === undefined) {
    if (Math.abs(x - Math.trunc(x)) === 0.5) return 2 * Math.round(x / 2);
    return Math.round(x);
  }
  const exact = Math.abs(x).toFixed(Math.min(ndigits + 60, 100));
  const dot = exact.indexOf(".");
  const tail = exact.slice(dot + 1 + ndigits);
  const isTie = /^50*$/.test(tail);
  if (!isTie) return Number(x.toFixed(ndigits));
  // 厳密な中間値: 偶数側に丸める
  const scaled = Number(exact.slice(0, dot) + exact.slice(dot + 1, dot + 1 + ndigits));
  const even = scaled % 2 === 0 ? scaled : scaled + 1;
  const result = even / Math.pow(10, ndigits);
  return x < 0 ? -result : result;
}

/** sum(iterable)（Python 3.12+ の浮動小数点は Neumaier 補償加算）。 */
export function pySum(values: number[], start = 0): number {
  let sum = start;
  let c = 0;
  for (const raw of values) {
    const x: number = typeof raw === "boolean" ? (raw ? 1 : 0) : raw;
    const t = sum + x;
    if (!Number.isFinite(t)) {
      sum = t;
      c = 0;
      continue;
    }
    if (Math.abs(sum) >= Math.abs(x)) c += sum - t + x;
    else c += x - t + sum;
    sum = t;
  }
  return Number.isFinite(c) && Number.isFinite(sum) ? sum + c : sum;
}

/** list(dict.fromkeys(items)) — 順序を保って重複を除く。 */
export function dedupe<T>(items: Iterable<T>): T[] {
  const out: T[] = [];
  for (const it of items) if (!out.some((o) => pyEq(o, it))) out.push(it);
  return out;
}

/** Python の float の repr に近い文字列（整数値は int として出力する）。 */
export function floatRepr(n: number): string {
  if (Number.isNaN(n)) return "NaN";
  if (n === Infinity) return "Infinity";
  if (n === -Infinity) return "-Infinity";
  if (Number.isInteger(n) && Math.abs(n) < 1e16) return String(n);
  const [mant, e] = n.toExponential().split("e");
  const exponent = Number(e);
  if (exponent < -4 || exponent >= 16) {
    const sign = exponent < 0 ? "-" : "+";
    return `${mant}e${sign}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  return String(n);
}

/** 値の repr（f"{x!r}"）。 */
export function repr(v: any): string {
  if (v === null || v === undefined) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (typeof v === "number") return floatRepr(v);
  if (typeof v === "string") {
    const q = v.includes("'") && !v.includes('"') ? '"' : "'";
    const body = v
      .replace(/\\/g, "\\\\")
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\r")
      .replace(/\t/g, "\\t")
      .replace(q === "'" ? /'/g : /"/g, "\\" + q);
    return q + body + q;
  }
  if (Array.isArray(v)) return "[" + v.map(repr).join(", ") + "]";
  if (isDict(v)) return "{" + keysOf(v).map((k) => repr(k) + ": " + repr(v[k])).join(", ") + "}";
  return String(v);
}

function jsonString(s: string, ensureAscii: boolean): string {
  let out = JSON.stringify(s);
  if (ensureAscii) out = out.replace(/[\u007f-￿]/g, (ch) => "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0"));
  return out;
}

/** Python の文字列比較（コードポイント順）。 */
export function codePointCompare(a: string, b: string): number {
  const x = Array.from(a);
  const y = Array.from(b);
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) {
    const p = x[i].codePointAt(0)!;
    const q = y[i].codePointAt(0)!;
    if (p !== q) return p < q ? -1 : 1;
  }
  return x.length === y.length ? 0 : x.length < y.length ? -1 : 1;
}

/** json.dumps(value, sort_keys=..., ensure_ascii=..., separators=...) */
export function pyJsonDumps(
  value: any,
  opts: { sortKeys?: boolean; ensureAscii?: boolean; compact?: boolean; defaultStr?: boolean; allowNan?: boolean } = {},
): string {
  const { sortKeys = false, ensureAscii = true, compact = false, defaultStr = false, allowNan = true } = opts;
  const itemSep = compact ? "," : ", ";
  const keySep = compact ? ":" : ": ";
  const walk = (v: any): string => {
    if (v === null || v === undefined) return "null";
    if (v === true) return "true";
    if (v === false) return "false";
    if (typeof v === "number") {
      if (!allowNan && !Number.isFinite(v)) throw new PyValueError("Out of range float values are not JSON compliant");
      return floatRepr(v);
    }
    if (typeof v === "string") return jsonString(v, ensureAscii);
    if (Array.isArray(v)) return "[" + v.map(walk).join(itemSep) + "]";
    if (isDict(v)) {
      let keys = keysOf(v);
      if (sortKeys) keys = [...keys].sort(codePointCompare);
      return "{" + keys.map((k) => jsonString(k, ensureAscii) + keySep + walk(v[k])).join(itemSep) + "}";
    }
    if (defaultStr) return jsonString(String(v), ensureAscii);
    throw new PyTypeError("Object is not JSON serializable");
  };
  return walk(value);
}

export const sha256Hex = (text: string): string => createHash("sha256").update(text, "utf8").digest("hex");

/** dict のキーとして使える値を文字列キーへ正規化する（list / dict は unhashable で TypeError）。 */
export function hashKey(v: any): string {
  if (v === null || v === undefined) return "n:";
  if (typeof v === "boolean") return "d:" + (v ? 1 : 0);
  if (typeof v === "number") return "d:" + v;
  if (typeof v === "string") return "s:" + v;
  throw new PyTypeError("unhashable type");
}

/** sorted(iterable)。文字列同士・数値同士のみ比較可能（混在は TypeError）。 */
export function pySorted<T>(values: T[]): T[] {
  const out = [...values];
  if (out.length < 2) return out;
  if (out.every((v) => typeof v === "string")) return (out as unknown as string[]).sort(codePointCompare) as unknown as T[];
  if (out.every((v) => typeof v === "number" || typeof v === "boolean")) return out.sort((a: any, b: any) => Number(a) - Number(b));
  throw new PyTypeError("'<' not supported between instances");
}

/** Python の str.strip() が取り除く空白文字。 */
const PY_WS = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const PY_STRIP_RE = new RegExp(`^[${PY_WS}]+|[${PY_WS}]+$`, "g");
export const pyStrip = (s: string): string => s.replace(PY_STRIP_RE, "");

/** date.fromisoformat(s)（Python 3.11 以降の ISO 8601 形式）。日付を YYYYMMDD の数値で返す。不正なら ValueError、str 以外は TypeError。 */
export function isoDate(s: any): number {
  if (typeof s !== "string") throw new PyTypeError("fromisoformat: argument must be str");
  const bad = () => new PyValueError(`Invalid isoformat string: '${s}'`);
  let year: number, month: number, day: number;
  let m: RegExpExecArray | null;
  if ((m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)) || (m = /^(\d{4})(\d{2})(\d{2})$/.exec(s))) {
    year = Number(m[1]);
    month = Number(m[2]);
    day = Number(m[3]);
  } else if ((m = /^(\d{4})-?W(\d{2})(?:-?(\d))?$/.exec(s))) {
    year = Number(m[1]);
    const week = Number(m[2]);
    const weekday = m[3] === undefined ? 1 : Number(m[3]);
    if (year < 1 || week < 1 || week > 53 || weekday < 1 || weekday > 7) throw bad();
    const jan4 = new Date(Date.UTC(year, 0, 4));
    const jan4Weekday = ((jan4.getUTCDay() + 6) % 7) + 1;
    const weeksInYear = (() => {
      const dec28 = new Date(Date.UTC(year, 11, 28));
      const dayOfYear = Math.floor((dec28.getTime() - Date.UTC(year, 0, 1)) / 86400000) + 1;
      const wd = ((dec28.getUTCDay() + 6) % 7) + 1;
      return Math.floor((dayOfYear - wd + 10) / 7);
    })();
    if (week > weeksInYear) throw bad();
    const monday = Date.UTC(year, 0, 4) - (jan4Weekday - 1) * 86400000;
    const target = new Date(monday + ((week - 1) * 7 + (weekday - 1)) * 86400000);
    year = target.getUTCFullYear();
    month = target.getUTCMonth() + 1;
    day = target.getUTCDate();
  } else {
    throw bad();
  }
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1) throw bad();
  const dim = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (day > dim) throw bad();
  return year * 10000 + month * 100 + day;
}

/** 例外を Python の例外クラス名に対応づける（ゴールデン照合用）。 */
export function pyErrorName(e: unknown): string {
  if (e instanceof PyTypeError) return "TypeError";
  if (e instanceof PyValueError) return "ValueError";
  if (e instanceof PyKeyError) return "KeyError";
  if (e instanceof PyAttributeError) return "AttributeError";
  if (e instanceof PyIntegrityError) return "IntegrityError";
  if (e instanceof PyProgrammingError) return "ProgrammingError";
  return e instanceof Error ? e.constructor.name : "Error";
}

/** datetime.now(timezone.utc).isoformat() 風の文字列。 */
export function utcNowIso(): string {
  const d = new Date();
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}000+00:00`;
}
