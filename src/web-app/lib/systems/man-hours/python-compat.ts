// Python の標準ライブラリと同じ結果を出すための小道具。
// 元の estimator.py は sum() / statistics / decimal / sorted を使っており、浮動小数点の最後の桁や
// 丸めの向き（ROUND_HALF_UP など）が結果の数値に出るので、同じ手順で計算する。
// ここは「Python の組み込みの再現」なので数値リテラルを使ってよい（estimator.ts には持ち込まない）。

/* eslint-disable @typescript-eslint/no-explicit-any -- JSON データを辞書として扱う（元の Python が dict のため） */
export type Obj = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

/** 元の Python の ValueError。メッセージは画面にそのまま出せる日本語。 */
export class ValueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValueError";
  }
}

const B0 = BigInt(0);
const B1 = BigInt(1);
const B2 = BigInt(2);
const B5 = BigInt(5);
const B10 = BigInt(10);
const B52 = BigInt(52);
const B63 = BigInt(63);

// ---------------------------------------------------------------- sum（CPython 3.12 以降の補償付き加算）

/** Python の sum()。float は Neumaier 補償付き加算（3.12 以降）で、素朴な左から右の加算と最後の桁が違うことがある。 */
export function pySum(values: Iterable<number>): number {
  let result = 0;
  let compensation = 0;
  for (const x of values) {
    const t = result + x;
    if (Math.abs(result) >= Math.abs(x)) {
      compensation += result - t + x;
    } else {
      compensation += x - t + result;
    }
    result = t;
  }
  if (compensation !== 0 && Number.isFinite(compensation)) {
    result += compensation;
  }
  return result;
}

// ---------------------------------------------------------------- statistics

/** statistics.median。偶数件は中央2つの平均。 */
export function pyMedian(values: number[]): number {
  if (values.length === 0) {
    throw new ValueError("no median for empty data");
  }
  const data = [...values].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const middle = Math.floor(data.length / 2);
  if (data.length % 2 === 1) {
    return data[middle];
  }
  return (data[middle - 1] + data[middle]) / 2;
}

const FLOAT_SCALE_BITS = 1074; // 倍精度の最小単位は 2^-1074

function floatToScaledBigInt(x: number): bigint {
  if (!Number.isFinite(x)) {
    throw new ValueError("有限の数ではありません");
  }
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const bits = view.getBigUint64(0);
  const negative = bits >> B63 === B1;
  const exponentField = Number((bits >> B52) & BigInt(0x7ff));
  const fraction = bits & ((B1 << B52) - B1);
  const magnitude = exponentField === 0 ? fraction : (fraction | (B1 << B52)) << BigInt(exponentField - 1);
  return negative ? -magnitude : magnitude;
}

function ldexp(value: number, exponent: number): number {
  const half = Math.trunc(exponent / 2);
  return value * 2 ** half * 2 ** (exponent - half);
}

function bitLength(value: bigint): number {
  return value === B0 ? 0 : value.toString(2).length;
}

/** statistics.mean（float）。厳密な和を件数で割ってから、最も近い倍精度に丸める。 */
export function pyMean(values: number[]): number {
  if (values.length === 0) {
    throw new ValueError("mean requires at least one data point");
  }
  const total = values.reduce((sum, x) => sum + floatToScaledBigInt(x), B0);
  if (total === B0) {
    return 0;
  }
  const negative = total < B0;
  const magnitude = negative ? -total : total;
  const count = BigInt(values.length);
  // 商が 64 ビット前後になるよう桁をそろえ、余りがあれば最下位ビットに印を付けて（sticky）丸めを正しくする
  const shift = 64 - (bitLength(magnitude) - bitLength(count));
  let quotient: bigint;
  let remainder: bigint;
  if (shift >= 0) {
    const numerator = magnitude << BigInt(shift);
    quotient = numerator / count;
    remainder = numerator % count;
  } else {
    const denominator = count << BigInt(-shift);
    quotient = magnitude / denominator;
    remainder = magnitude % denominator;
  }
  if (remainder !== B0) {
    quotient |= B1;
  }
  const result = ldexp(Number(quotient), -shift - FLOAT_SCALE_BITS);
  return negative ? -result : result;
}

// ---------------------------------------------------------------- 並べ替え・最大

export type SortKey = number | string | SortKey[];

export function compareValues(a: SortKey, b: SortKey): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    const length = Math.min(a.length, b.length);
    for (let i = 0; i < length; i += 1) {
      const result = compareValues(a[i], b[i]);
      if (result !== 0) {
        return result;
      }
    }
    return a.length - b.length;
  }
  return a < b ? -1 : a > b ? 1 : 0;
}

/** sorted(items, key=key, reverse=reverse)。安定（キーが同じものは元の順）。 */
export function sortedBy<T>(items: Iterable<T>, key: (item: T) => SortKey, reverse = false): T[] {
  return [...items].sort((x, y) => (reverse ? compareValues(key(y), key(x)) : compareValues(key(x), key(y))));
}

/** max(items, key=key)。同点は最初のもの。空なら ValueError。 */
export function maxBy<T>(items: Iterable<T>, key: (item: T) => SortKey): T {
  let best: T | undefined;
  let bestKey: SortKey | undefined;
  let found = false;
  for (const item of items) {
    const k = key(item);
    if (!found || compareValues(k, bestKey as SortKey) > 0) {
      best = item;
      bestKey = k;
      found = true;
    }
  }
  if (!found) {
    throw new ValueError("max() iterable argument is empty");
  }
  return best as T;
}

/** int(text)。読めなければ ValueError。 */
export function pyInt(text: string): number {
  if (!/^\s*[+-]?\d+(_\d+)*\s*$/.test(text)) {
    throw new ValueError(`invalid literal for int() with base 10: ${pyRepr(text)}`);
  }
  return Number(text.replaceAll("_", "").trim());
}

/** 辞書にキーがあるか（Python の `key in dict`）。 */
export function has(mapping: unknown, key: string): boolean {
  return typeof mapping === "object" && mapping !== null && Object.prototype.hasOwnProperty.call(mapping, key);
}

// ---------------------------------------------------------------- decimal.quantize

export type RoundingMode =
  | "ROUND_UP"
  | "ROUND_DOWN"
  | "ROUND_CEILING"
  | "ROUND_FLOOR"
  | "ROUND_HALF_UP"
  | "ROUND_HALF_DOWN"
  | "ROUND_HALF_EVEN"
  | "ROUND_05UP";

const ROUNDING_MODES: readonly string[] = [
  "ROUND_UP",
  "ROUND_DOWN",
  "ROUND_CEILING",
  "ROUND_FLOOR",
  "ROUND_HALF_UP",
  "ROUND_HALF_DOWN",
  "ROUND_HALF_EVEN",
  "ROUND_05UP",
];

/** getattr(decimal, name) 相当。未知の名前は Python では AttributeError。 */
export function roundingMode(name: string): RoundingMode {
  if (!ROUNDING_MODES.includes(name)) {
    throw new Error(`module 'decimal' has no attribute '${name}'`);
  }
  return name as RoundingMode;
}

const NUMBER_TEXT = /^(-?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i;

/** Decimal(str(value)) と同じ値を、符号・係数・10 の指数で返す。 */
function toDecimalParts(value: number): { negative: boolean; coefficient: bigint; exponent: number } {
  if (!Number.isFinite(value)) {
    throw new ValueError("有限の数ではありません");
  }
  const text = Object.is(value, -0) ? "-0" : String(value);
  const match = NUMBER_TEXT.exec(text);
  if (!match) {
    throw new ValueError(`数として読めません: ${text}`);
  }
  const fraction = match[3] ?? "";
  return {
    negative: match[1] === "-",
    coefficient: BigInt(match[2] + fraction),
    exponent: Number(match[4] ?? "0") - fraction.length,
  };
}

/** Decimal(str(value)).quantize(10^-decimals, rounding=mode) の符号・係数。値 = (-1)^negative × coefficient × 10^-decimals */
function quantizeParts(value: number, decimals: number, mode: RoundingMode): { negative: boolean; coefficient: bigint } {
  const { negative, coefficient, exponent } = toDecimalParts(value);
  const target = -decimals;
  if (exponent >= target) {
    return { negative, coefficient: coefficient * B10 ** BigInt(exponent - target) };
  }
  const divisor = B10 ** BigInt(target - exponent);
  let quotient = coefficient / divisor;
  const remainder = coefficient % divisor;
  const twice = remainder * B2;
  let up: boolean;
  switch (mode) {
    case "ROUND_DOWN":
      up = false;
      break;
    case "ROUND_UP":
      up = remainder > B0;
      break;
    case "ROUND_CEILING":
      up = !negative && remainder > B0;
      break;
    case "ROUND_FLOOR":
      up = negative && remainder > B0;
      break;
    case "ROUND_HALF_UP":
      up = twice >= divisor;
      break;
    case "ROUND_HALF_DOWN":
      up = twice > divisor;
      break;
    case "ROUND_HALF_EVEN":
      up = twice > divisor || (twice === divisor && quotient % B2 === B1);
      break;
    case "ROUND_05UP":
      up = remainder > B0 && (quotient % B10 === B0 || quotient % B10 === B5);
      break;
  }
  if (up) {
    quotient += B1;
  }
  return { negative, coefficient: quotient };
}

/** float(Decimal(str(value)).quantize(...))。値が負で丸めて 0 になったときは -0 を返す（Python と同じ）。 */
export function quantizeToFloat(value: number, decimals: number, mode: RoundingMode): number {
  const { negative, coefficient } = quantizeParts(value, decimals, mode);
  return Number(`${negative ? "-" : ""}${coefficient}e${-decimals}`);
}

/** int(Decimal(str(value)).quantize(...))。小数部は切り捨て。 */
export function quantizeToInt(value: number, decimals: number, mode: RoundingMode): number {
  const { negative, coefficient } = quantizeParts(value, decimals, mode);
  const scaled = decimals >= 0 ? coefficient / B10 ** BigInt(decimals) : coefficient * B10 ** BigInt(-decimals);
  return Number(negative ? -scaled : scaled);
}

// ---------------------------------------------------------------- 表示（repr / str）

function pyNumberText(value: number): string {
  return String(value);
}

/** repr()。エラーメッセージを元と同じ文面にするために使う。 */
export function pyRepr(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  if (typeof value === "string") {
    const quote = value.includes("'") && !value.includes('"') ? '"' : "'";
    return `${quote}${value}${quote}`;
  }
  if (typeof value === "number") {
    return pyNumberText(value);
  }
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (Array.isArray(value)) {
    return `[${value.map(pyRepr).join(", ")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.entries(value as Obj)
      .map(([key, item]) => `${pyRepr(key)}: ${pyRepr(item)}`)
      .join(", ")}}`;
  }
  return String(value);
}

/** str()。 */
export function pyStr(value: unknown): string {
  return typeof value === "string" ? value : pyRepr(value);
}

/** float を str() したときの表記（3.0 は "3.0"）。Markdown の表で使う。 */
export function pyFloatStr(value: number): string {
  if (Object.is(value, -0)) {
    return "-0.0";
  }
  return Number.isInteger(value) ? value.toFixed(1) : String(value);
}
