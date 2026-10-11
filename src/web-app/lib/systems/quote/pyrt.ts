// 元の Python 実装（src/auto_repair_quote）の振る舞いを TypeScript で再現するための基礎部品。
// Decimal（10進演算・28桁の精度）、str()/repr() の表記、例外の種類、日付の解釈、時計と uuid4 を持つ。
/* eslint-disable @typescript-eslint/no-explicit-any */

export type Json = any;
export type Obj = Record<string, any>;

// ---- 例外（Python の例外クラスに対応。API では種類ごとにステータスを決める） ----

export class PyError extends Error {
  kind = "Error";
}

/** ValueError（QuoteError・InvalidOperation を含む）。API では 422。 */
export class ValueErr extends PyError {
  kind = "ValueError";
}

/** common.QuoteError（ValueError の子）。 */
export class QuoteError extends ValueErr {}

/** KeyError。message は Python の str(KeyError(key)) と同じく repr(key)。 */
export class KeyErr extends PyError {
  kind = "KeyError";
  constructor(public key: unknown) {
    super(pyRepr(key));
  }
}

/** sqlite3.IntegrityError（主キー重複・外部キー違反）。API では 409。 */
export class IntegrityErr extends PyError {
  kind = "IntegrityError";
}

/** TypeError / AttributeError。API では 500。 */
export class TypeErr extends PyError {
  kind = "TypeError";
}

export function errorKind(error: unknown): string {
  if (error instanceof PyError) return error.kind;
  if (error instanceof TypeError) return "TypeError";
  return "Error";
}

// ---- 型の判定（Python の isinstance に対応） ----

export function isDict(value: unknown): value is Obj {
  return value !== null && typeof value === "object" && !Array.isArray(value) && !(value instanceof Dec);
}
export const isList = Array.isArray as (value: unknown) => value is any[];
export function isStr(value: unknown): value is string {
  return typeof value === "string";
}
export function isNum(value: unknown): value is number {
  return typeof value === "number";
}
/** isinstance(value, int)（bool を除く）。JSON の 1.0 と 1 は区別できないので整数値なら int とみなす。 */
export function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}
export function has(obj: Obj, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}
/** dict.get(key, default) */
export function get(obj: Obj, key: string, fallback: any = null): any {
  return has(obj, key) ? obj[key] : fallback;
}
/** dict[key]（無ければ KeyError） */
export function item(obj: any, key: string): any {
  if (isDict(obj)) {
    if (!has(obj, key)) throw new KeyErr(key);
    return obj[key];
  }
  if (obj === null || obj === undefined) throw new TypeErr("'NoneType' object is not subscriptable");
  throw new TypeErr(`${pyTypeName(obj)} indices must be integers or slices, not str`);
}

export function pyTypeName(value: unknown): string {
  if (value === null || value === undefined) return "NoneType";
  if (typeof value === "boolean") return "bool";
  if (typeof value === "number") return Number.isInteger(value) ? "int" : "float";
  if (typeof value === "string") return "str";
  if (Array.isArray(value)) return "list";
  if (value instanceof Dec) return "decimal.Decimal";
  return "dict";
}

/** Python の真偽判定。 */
export function truthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === 0 || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (value instanceof Dec) return !value.isZero();
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return true;
}

/** Python の == （dict は順序を問わず、1 == 1.0 == True）。 */
export function pyEq(a: unknown, b: unknown): boolean {
  if ((typeof a === "number" || typeof a === "boolean") && (typeof b === "number" || typeof b === "boolean")) {
    return Number(a) === Number(b);
  }
  if (a instanceof Dec || b instanceof Dec) {
    const left = a instanceof Dec ? a : typeof a === "number" ? Dec.fromPy(a) : null;
    const right = b instanceof Dec ? b : typeof b === "number" ? Dec.fromPy(b) : null;
    return left !== null && right !== null && left.eq(right);
  }
  if (a === null || a === undefined) return b === null || b === undefined;
  if (typeof a === "string") return a === b;
  if (Array.isArray(a)) {
    return Array.isArray(b) && a.length === b.length && a.every((value, index) => pyEq(value, b[index]));
  }
  if (isDict(a)) {
    if (!isDict(b)) return false;
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((key) => has(b, key) && pyEq(a[key], b[key]));
  }
  return false;
}

/** x in container（list/tuple/set は ==、dict はキー）。 */
export function pyIn(value: unknown, container: readonly unknown[]): boolean {
  return container.some((entry) => pyEq(value, entry));
}

/** copy.deepcopy（JSON 互換の値）。 */
export function deepcopy<T>(value: T): T {
  if (Array.isArray(value)) return value.map((entry) => deepcopy(entry)) as T;
  if (isDict(value)) {
    const result: Obj = {};
    for (const key of Object.keys(value)) result[key] = deepcopy(value[key]);
    return result as T;
  }
  return value;
}

// ---- 文字列 ----

export function strip(value: string): string {
  return value.trim();
}
/** " ".join(value.split()) */
export function squash(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}
/** "".join(value.split()) */
export function noSpace(value: string): string {
  return value.split(/\s+/).join("");
}
export function casefold(value: string): string {
  return value.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ");
}

/** float の repr（Python の最短表記と指数の規則）。 */
export function floatRepr(value: number): string {
  if (Number.isNaN(value)) return "nan";
  if (!Number.isFinite(value)) return value > 0 ? "inf" : "-inf";
  if (Object.is(value, -0)) return "-0.0";
  const [mantissa, expText] = value.toExponential().split("e");
  const exp = Number(expText);
  const negative = mantissa.startsWith("-");
  const digits = mantissa.replace("-", "").replace(".", "");
  let body: string;
  if (exp >= -4 && exp < 16) {
    if (exp >= 0) {
      const intPart = digits.slice(0, exp + 1).padEnd(exp + 1, "0");
      const frac = digits.slice(exp + 1);
      body = `${intPart}.${frac || "0"}`;
    } else {
      body = `0.${"0".repeat(-exp - 1)}${digits}`;
    }
  } else {
    const frac = digits.slice(1);
    body = `${digits[0]}${frac ? "." + frac : ""}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  return (negative ? "-" : "") + body;
}

/** 数値の str()。整数値は int とみなす（JSON では 2 と 2.0 を区別できない）。 */
export function numStr(value: number): string {
  if (Number.isInteger(value) && !Object.is(value, -0)) return BigInt(value).toString();
  return floatRepr(value);
}

function stringRepr(value: string): string {
  const quote = value.includes("'") && !value.includes('"') ? '"' : "'";
  let out = quote;
  for (const char of value) {
    const code = char.codePointAt(0)!;
    if (char === "\\") out += "\\\\";
    else if (char === quote) out += "\\" + quote;
    else if (char === "\n") out += "\\n";
    else if (char === "\r") out += "\\r";
    else if (char === "\t") out += "\\t";
    else if (code < 0x20 || code === 0x7f) out += "\\x" + code.toString(16).padStart(2, "0");
    else out += char;
  }
  return out + quote;
}

/** repr() */
export function pyRepr(value: unknown): string {
  if (typeof value === "string") return stringRepr(value);
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(", ")}]`;
  if (isDict(value)) return `{${Object.keys(value).map((key) => `${stringRepr(key)}: ${pyRepr(value[key])}`).join(", ")}}`;
  if (value instanceof Dec) return `Decimal('${value.toString()}')`;
  return pyStr(value);
}

/** str() */
export function pyStr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "number") return numStr(value);
  if (typeof value === "string") return value;
  if (value instanceof Dec) return value.toString();
  return pyRepr(value);
}

/** f"{value:,}"（整数は3桁区切り、小数は repr に区切りを付ける）。 */
export function groupThousands(value: number): string {
  const text = numStr(value);
  if (/e/.test(text)) return text;
  const negative = text.startsWith("-");
  const [intPart, frac] = text.replace("-", "").split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (negative ? "-" : "") + grouped + (frac !== undefined ? "." + frac : "");
}

function asciiDigits(value: string): string {
  return value.replace(/[０-９]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0xfee0));
}

/** float(value)。変換できなければ ValueErr / TypeErr。 */
export function pyFloat(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (value instanceof Dec) return value.toNumber();
  if (typeof value === "string") {
    const text = asciiDigits(value.trim()).toLowerCase();
    const special = /^([+-]?)(inf|infinity|nan)$/.exec(text);
    if (special) return special[2] === "nan" ? NaN : special[1] === "-" ? -Infinity : Infinity;
    const digits = String.raw`\d(?:_?\d)*`;
    const pattern = new RegExp(`^[+-]?(?:${digits}(?:\\.(?:${digits})?)?|\\.${digits})(?:e[+-]?${digits})?$`);
    if (!pattern.test(text)) throw new ValueErr(`could not convert string to float: ${pyRepr(value)}`);
    return Number(text.replace(/_/g, ""));
  }
  throw new TypeErr(`float() argument must be a string or a real number, not '${pyTypeName(value)}'`);
}

// ---- Decimal ----

const PREC = 28;
const TEN = BigInt(10);
const ZERO = BigInt(0);
const ONE = BigInt(1);
const TWO = BigInt(2);

function pow10(n: number): bigint {
  return TEN ** BigInt(n);
}
function absBig(value: bigint): bigint {
  return value < ZERO ? -value : value;
}

/** decimal.Decimal（既定のコンテキスト: 28桁、ROUND_HALF_EVEN）。 */
export class Dec {
  private constructor(
    readonly special: "" | "inf" | "nan",
    readonly coef: bigint,
    readonly exp: number,
    readonly negative = false,
  ) {}

  static finite(coef: bigint, exp: number): Dec {
    return new Dec("", coef, exp, coef < ZERO);
  }

  static int(value: number | bigint): Dec {
    return Dec.finite(BigInt(value), 0);
  }

  /** Decimal(text)。解釈できなければ null（Python では InvalidOperation）。 */
  static parse(text: string): Dec | null {
    const value = asciiDigits(text.trim()).replace(/_/g, "");
    const special = /^([+-]?)(inf|infinity|s?nan\d*)$/i.exec(value);
    if (special) {
      return special[2].toLowerCase().includes("nan")
        ? new Dec("nan", ZERO, 0, special[1] === "-")
        : new Dec("inf", ZERO, 0, special[1] === "-");
    }
    const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
    if (!match || (match[2] === "" && (match[3] ?? "") === "")) return null;
    const digits = match[2] + (match[3] ?? "");
    const exp = Number(match[4] ?? 0) - (match[3] ?? "").length;
    let coef = BigInt(digits);
    if (match[1] === "-") coef = -coef;
    return new Dec("", coef, exp, match[1] === "-");
  }

  /** Decimal(str(value))。解釈できなければ InvalidOperation 相当の ValueErr。 */
  static fromPy(value: unknown): Dec {
    if (value instanceof Dec) return value;
    const parsed = Dec.parse(pyStr(value));
    if (parsed === null) throw new ValueErr("[<class 'decimal.ConversionSyntax'>]");
    return parsed;
  }

  isFinite(): boolean {
    return this.special === "";
  }
  isNaN(): boolean {
    return this.special === "nan";
  }
  isZero(): boolean {
    return this.special === "" && this.coef === ZERO;
  }

  private static round(coef: bigint, exp: number): Dec {
    const digits = absBig(coef).toString().length;
    if (digits <= PREC) return Dec.finite(coef, exp);
    const drop = digits - PREC;
    const divisor = pow10(drop);
    const sign = coef < ZERO ? -ONE : ONE;
    const magnitude = absBig(coef);
    let quotient = magnitude / divisor;
    const remainder = magnitude % divisor;
    const twice = remainder * TWO;
    if (twice > divisor || (twice === divisor && quotient % TWO === ONE)) quotient += ONE;
    let newExp = exp + drop;
    if (quotient.toString().length > PREC) {
      quotient /= TEN;
      newExp += 1;
    }
    return Dec.finite(sign * quotient, newExp);
  }

  private static align(a: Dec, b: Dec): [bigint, bigint, number] {
    const exp = Math.min(a.exp, b.exp);
    return [a.coef * pow10(a.exp - exp), b.coef * pow10(b.exp - exp), exp];
  }

  add(other: Dec): Dec {
    if (!this.isFinite() || !other.isFinite()) {
      if (this.isNaN() || other.isNaN()) return new Dec("nan", ZERO, 0);
      if (!this.isFinite() && !other.isFinite() && this.negative !== other.negative) {
        throw new ValueErr("[<class 'decimal.InvalidOperation'>]");
      }
      return this.isFinite() ? other : this;
    }
    const [x, y, exp] = Dec.align(this, other);
    return Dec.round(x + y, exp);
  }

  neg(): Dec {
    if (!this.isFinite()) return new Dec(this.special, ZERO, 0, !this.negative);
    return Dec.finite(-this.coef, this.exp);
  }

  sub(other: Dec): Dec {
    return this.add(other.neg());
  }

  mul(other: Dec): Dec {
    if (!this.isFinite() || !other.isFinite()) {
      if (this.isNaN() || other.isNaN()) return new Dec("nan", ZERO, 0);
      if (this.isZero() || other.isZero()) throw new ValueErr("[<class 'decimal.InvalidOperation'>]");
      return new Dec("inf", ZERO, 0, this.sign() * other.sign() < 0);
    }
    return Dec.round(this.coef * other.coef, this.exp + other.exp);
  }

  sign(): number {
    if (this.special === "inf") return this.negative ? -1 : 1;
    return this.coef < ZERO ? -1 : this.coef > ZERO ? 1 : 0;
  }

  /** 比較。NaN との大小比較は Python と同じく InvalidOperation。 */
  cmp(other: Dec): number {
    if (this.isNaN() || other.isNaN()) throw new ValueErr("[<class 'decimal.InvalidOperation'>]");
    if (!this.isFinite() || !other.isFinite()) {
      const left = this.isFinite() ? 0 : this.sign() * 2;
      const right = other.isFinite() ? 0 : other.sign() * 2;
      if (left !== right) return left < right ? -1 : 1;
      if (left !== 0) return 0;
      return this.isFinite() ? -other.sign() : this.sign();
    }
    const [x, y] = Dec.align(this, other);
    return x < y ? -1 : x > y ? 1 : 0;
  }

  eq(other: Dec): boolean {
    if (this.isNaN() || other.isNaN()) return false;
    return this.cmp(other) === 0;
  }
  lt(other: Dec): boolean {
    return this.cmp(other) < 0;
  }
  le(other: Dec): boolean {
    return this.cmp(other) <= 0;
  }
  gt(other: Dec): boolean {
    return this.cmp(other) > 0;
  }
  ge(other: Dec): boolean {
    return this.cmp(other) >= 0;
  }

  /** value == value.to_integral_value() */
  isIntegral(): boolean {
    if (!this.isFinite()) return false;
    if (this.exp >= 0) return true;
    return this.coef % pow10(-this.exp) === ZERO;
  }

  /** int(value)（0 方向に切り捨て）。 */
  toBigInt(): bigint {
    if (!this.isFinite()) throw new ValueErr("cannot convert Infinity/NaN to integer");
    if (this.exp >= 0) return this.coef * pow10(this.exp);
    return this.coef / pow10(-this.exp);
  }

  /** float(value) */
  toNumber(): number {
    if (this.special === "nan") return NaN;
    if (this.special === "inf") return this.negative ? -Infinity : Infinity;
    return Number(`${this.coef}e${this.exp}`);
  }

  /** quantize(Decimal("1"), rounding) */
  quantizeUnit(mode: "floor" | "half_up" | "ceil"): Dec {
    if (!this.isFinite()) throw new ValueErr("[<class 'decimal.InvalidOperation'>]");
    if (this.exp >= 0) return Dec.finite(this.coef * pow10(this.exp), 0);
    const divisor = pow10(-this.exp);
    let quotient = this.coef / divisor;
    const remainder = this.coef % divisor;
    if (remainder !== ZERO) {
      if (mode === "floor" && this.coef < ZERO) quotient -= ONE;
      else if (mode === "ceil" && this.coef > ZERO) quotient += ONE;
      else if (mode === "half_up" && absBig(remainder) * TWO >= divisor) quotient += this.coef < ZERO ? -ONE : ONE;
    }
    return Dec.finite(quotient, 0);
  }

  /** str(Decimal)（to-scientific-string）。 */
  toString(): string {
    if (this.special === "nan") return "NaN";
    if (this.special === "inf") return this.negative ? "-Infinity" : "Infinity";
    const sign = this.negative ? "-" : "";
    const digits = absBig(this.coef).toString();
    const adjusted = this.exp + digits.length - 1;
    if (this.exp <= 0 && adjusted >= -6) {
      if (this.exp === 0) return sign + digits;
      const point = digits.length + this.exp;
      return point > 0
        ? `${sign}${digits.slice(0, point)}.${digits.slice(point)}`
        : `${sign}0.${"0".repeat(-point)}${digits}`;
    }
    const mantissa = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
    return `${sign}${mantissa}E${adjusted >= 0 ? "+" : ""}${adjusted}`;
  }
}

export function sumDec(values: Dec[]): Dec {
  return values.reduce((total, value) => total.add(value), Dec.int(0));
}

// ---- 日付 ----

export type PyDate = { year: number; month: number; day: number; ordinal: number };

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

function makeDate(year: number, month: number, day: number): PyDate {
  if (year < 1 || month < 1 || month > 12) throw new ValueErr("month must be in 1..12");
  const max = daysInMonth(year, month);
  if (day < 1 || day > max) throw new ValueErr(`day ${day} must be in range 1..${max} for month ${month} in year ${year}`);
  const ordinal = Date.UTC(year, month - 1, day) / 86400000;
  return { year, month, day, ordinal };
}

/** date.fromisoformat（Python 3.11 以降の形式: YYYY-MM-DD / YYYYMMDD / 週番号）。 */
export function dateFromIso(value: unknown): PyDate {
  if (typeof value !== "string") throw new TypeErr("fromisoformat: argument must be str");
  let match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) ?? /^(\d{4})(\d{2})(\d{2})$/.exec(value);
  if (match) return makeDate(Number(match[1]), Number(match[2]), Number(match[3]));
  match = /^(\d{4})-W(\d{2})(?:-(\d))?$/.exec(value) ?? /^(\d{4})W(\d{2})(\d)?$/.exec(value);
  if (match) {
    const year = Number(match[1]);
    const week = Number(match[2]);
    const weekday = Number(match[3] ?? 1);
    if (week < 1 || week > 53 || weekday < 1 || weekday > 7) throw new ValueErr(`Invalid isoformat string: ${pyRepr(value)}`);
    const jan4 = Date.UTC(year, 0, 4);
    const jan4Weekday = (new Date(jan4).getUTCDay() + 6) % 7;
    const monday = jan4 - jan4Weekday * 86400000;
    const result = new Date(monday + ((week - 1) * 7 + weekday - 1) * 86400000);
    if (week === 53) {
      const dec28 = new Date(Date.UTC(year, 11, 28));
      const lastWeekMonday = Date.UTC(year, 11, 28) - ((dec28.getUTCDay() + 6) % 7) * 86400000;
      if (lastWeekMonday < monday + 52 * 7 * 86400000) throw new ValueErr("Invalid week: 53");
    }
    return makeDate(result.getUTCFullYear(), result.getUTCMonth() + 1, result.getUTCDate());
  }
  throw new ValueErr(`Invalid isoformat string: ${pyRepr(value)}`);
}

export function dateIso(date: PyDate): string {
  return `${String(date.year).padStart(4, "0")}-${String(date.month).padStart(2, "0")}-${String(date.day).padStart(2, "0")}`;
}

/** datetime.fromisoformat の主な形式。aware はタイムゾーン付きか。micros は UTC 換算のマイクロ秒。 */
export function datetimeFromIso(value: string): { aware: boolean; micros: number } {
  const match =
    /^(\d{4}-\d{2}-\d{2}|\d{8})(?:[T ](\d{2})(?::?(\d{2})(?::?(\d{2})(?:[.,](\d{1,6}))?)?)?)?(Z|[+-]\d{2}(?::?\d{2}(?::?\d{2}(?:\.\d{1,6})?)?)?)?$/.exec(value);
  if (!match) throw new ValueErr(`Invalid isoformat string: ${pyRepr(value)}`);
  const date = dateFromIso(match[1]);
  const hour = Number(match[2] ?? 0);
  const minute = Number(match[3] ?? 0);
  const second = Number(match[4] ?? 0);
  if (hour > 23 || minute > 59 || second > 59) throw new ValueErr(`Invalid isoformat string: ${pyRepr(value)}`);
  const micro = Number((match[5] ?? "").padEnd(6, "0") || 0);
  let micros = (((date.ordinal * 24 + hour) * 60 + minute) * 60 + second) * 1e6 + micro;
  const tz = match[6];
  if (tz && tz !== "Z") {
    const sign = tz.startsWith("-") ? -1 : 1;
    const parts = tz.slice(1).replace(/:/g, "");
    const offset = (Number(parts.slice(0, 2)) * 3600 + Number(parts.slice(2, 4) || 0) * 60 + Number(parts.slice(4, 6) || 0)) * 1e6;
    micros -= sign * offset;
  }
  return { aware: Boolean(tz), micros };
}

// ---- 時計・今日・uuid4（テストでは固定値に差し替える） ----

type Runtime = { fixed: boolean; uuidSeq: number };
const runtime: Runtime = { fixed: false, uuidSeq: 0 };

/** テスト用: 時計を 2026-10-11T03:04:05.123456Z、今日を 2026-10-11、uuid4 を連番にする（ゴールデン生成と同じ）。 */
export function useFixedRuntime(uuidSeq: number): void {
  runtime.fixed = true;
  runtime.uuidSeq = uuidSeq;
}

export function useRealRuntime(): void {
  runtime.fixed = false;
}

type UtcNow = { ms: number; micro: number };

function utcNow(): UtcNow {
  if (runtime.fixed) return { ms: Date.UTC(2026, 9, 11, 3, 4, 5, 123), micro: 123456 };
  const ms = Date.now();
  return { ms, micro: (ms % 1000) * 1000 };
}

function isoBase(now: UtcNow): string {
  return new Date(now.ms).toISOString().slice(0, 19);
}

/** datetime.now(timezone.utc).isoformat() */
export function nowIso(): string {
  const now = utcNow();
  const fraction = now.micro === 0 ? "" : "." + String(now.micro).padStart(6, "0");
  return `${isoBase(now)}${fraction}+00:00`;
}

/** datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") */
export function nowIsoSecondsZ(): string {
  return `${isoBase(utcNow())}Z`;
}

/** date.today()（サーバーのローカル日付）。 */
export function today(): PyDate {
  if (runtime.fixed) return makeDate(2026, 10, 11);
  const now = new Date();
  return makeDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

/** str(uuid4()) */
export function uuid4(): string {
  if (runtime.fixed) {
    runtime.uuidSeq += 1;
    const hex = runtime.uuidSeq.toString(16).padStart(8, "0") + "0".repeat(24);
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return crypto.randomUUID();
}

/** uuid4().hex */
export function uuid4Hex(): string {
  return uuid4().replace(/-/g, "");
}

/** uuid.UUID(text) が通るか。 */
export function isUuid(text: string): boolean {
  let hex = text.replace("urn:", "").replace("uuid:", "");
  hex = hex.replace(/^[{}]+|[{}]+$/g, "").replace(/-/g, "");
  return hex.length === 32 && /^[0-9a-fA-F]+$/.test(hex);
}

/** dict.setdefault(key, default) */
export function setdefault(obj: Obj, key: string, fallback: any): any {
  if (!has(obj, key)) obj[key] = fallback;
  return obj[key];
}

/** isinstance(value, str) and value.strip() */
export function nonemptyStr(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

/** isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip() */
export function nonemptyStrOrInt(value: unknown): boolean {
  return (typeof value === "string" || isInt(value)) && pyStr(value).trim() !== "";
}
