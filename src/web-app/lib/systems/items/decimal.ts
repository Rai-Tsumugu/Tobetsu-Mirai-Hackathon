// Python の decimal.Decimal と同じ結果を返す十進数（auto_repair_items の金額・数量計算用）。
// 係数（BigInt）と指数で持ち、加減乗除は正確に計算してから文脈の精度（prec）で丸める。
// str() の表記（指数表記に切り替える条件）、quantize、to_integral_value も Python に合わせる。
// 浮動小数点は一切通さない。

export type Rounding =
  | "ROUND_HALF_EVEN"
  | "ROUND_HALF_UP"
  | "ROUND_HALF_DOWN"
  | "ROUND_DOWN"
  | "ROUND_UP"
  | "ROUND_FLOOR"
  | "ROUND_CEILING";

/** 元の HTTP サーバー（app.py）は全案を localcontext(prec=120) の中で実行する。 */
export const DEFAULT_PREC = 120;

export type DecimalContext = { prec?: number; rounding?: Rounding };

/** Python の decimal.InvalidOperation / DivisionByZero 相当。 */
export class InvalidOperation extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidOperation";
  }
}

const ZERO = BigInt(0);
const ONE = BigInt(1);
const TEN = BigInt(10);
const FIVE = BigInt(5);

function pow10(n: number): bigint {
  let result = ONE;
  let base = TEN;
  let k = n;
  while (k > 0) {
    if (k & 1) result *= base;
    base *= base;
    k >>= 1;
  }
  return result;
}

function absBig(value: bigint): bigint {
  return value < ZERO ? -value : value;
}

function digitCount(value: bigint): number {
  return value === ZERO ? 1 : value.toString().length;
}

type Special = "finite" | "inf" | "nan" | "snan";

/** Unicode の10進数字（全角など）を ASCII に直す。Python の Decimal() は Nd の数字を受け付ける。 */
function asciiDigits(text: string): string {
  let out = "";
  for (const ch of text) {
    if (/^[0-9]$/.test(ch)) {
      out += ch;
      continue;
    }
    if (/^\p{Nd}$/u.test(ch)) {
      // Nd の文字は 0〜9 が連続して並ぶので、連続の先頭からの位置 % 10 が値になる。
      let cp = ch.codePointAt(0)!;
      let offset = 0;
      while (cp > 0 && /^\p{Nd}$/u.test(String.fromCodePoint(cp - 1))) {
        cp -= 1;
        offset += 1;
      }
      out += String(offset % 10);
      continue;
    }
    out += ch;
  }
  return out;
}

const PY_SPACE = String.fromCharCode(0x9, 0xa, 0xb, 0xc, 0xd, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000);

function stripPySpace(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && PY_SPACE.includes(text[start])) start += 1;
  while (end > start && PY_SPACE.includes(text[end - 1])) end -= 1;
  return text.slice(start, end);
}

export class Decimal {
  /** 符号（true なら負）。-0 も表せる。 */
  readonly negative: boolean;
  /** 係数（非負）。 */
  readonly coefficient: bigint;
  /** 指数。 */
  readonly exponent: number;
  readonly special: Special;

  private constructor(negative: boolean, coefficient: bigint, exponent: number, special: Special = "finite") {
    this.negative = negative;
    this.coefficient = coefficient;
    this.exponent = exponent;
    this.special = special;
  }

  static fromParts(negative: boolean, coefficient: bigint, exponent: number): Decimal {
    return new Decimal(negative, coefficient, exponent);
  }

  /** Decimal(str) と同じ解釈。解釈できなければ InvalidOperation。 */
  static parse(input: string): Decimal {
    const text = asciiDigits(stripPySpace(input));
    const special = /^([+-])?(inf|infinity|nan|snan)(\d*)$/i.exec(text);
    if (special) {
      const name = special[2].toLowerCase();
      const negative = special[1] === "-";
      if ((name === "inf" || name === "infinity") && special[3] === "") {
        return new Decimal(negative, ZERO, 0, "inf");
      }
      if (name === "nan" || name === "snan") {
        return new Decimal(negative, special[3] ? BigInt(special[3]) : ZERO, 0, name === "nan" ? "nan" : "snan");
      }
      throw new InvalidOperation(`Invalid literal for Decimal: ${JSON.stringify(input)}`);
    }
    // 数字の間の "_" は Python 3.6 以降の Decimal() で使える（"1_000"）。
    const match = /^([+-])?((?:\d(?:_?\d)*)?)(?:\.((?:\d(?:_?\d)*)?))?(?:[eE]([+-]?\d(?:_?\d)*))?$/.exec(text);
    if (!match || (match[2] === "" && (match[3] === undefined || match[3] === ""))) {
      throw new InvalidOperation(`Invalid literal for Decimal: ${JSON.stringify(input)}`);
    }
    const intPart = match[2].replace(/_/g, "");
    const fracPart = (match[3] ?? "").replace(/_/g, "");
    const exp = match[4] ? Number(match[4].replace(/_/g, "")) : 0;
    const digits = (intPart + fracPart).replace(/^0+(?=\d)/, "") || "0";
    return new Decimal(match[1] === "-", BigInt(digits), exp - fracPart.length);
  }

  static fromInt(value: number | bigint): Decimal {
    const big = typeof value === "bigint" ? value : BigInt(value);
    return new Decimal(big < ZERO, absBig(big), 0);
  }

  isFinite(): boolean {
    return this.special === "finite";
  }

  isNaN(): boolean {
    return this.special === "nan" || this.special === "snan";
  }

  isZero(): boolean {
    return this.special === "finite" && this.coefficient === ZERO;
  }

  /** as_tuple().digits の個数。 */
  digitCount(): number {
    return digitCount(this.coefficient);
  }

  /** adjusted(): 最上位桁の指数。 */
  adjusted(): number {
    return this.exponent + digitCount(this.coefficient) - 1;
  }

  private signed(): bigint {
    return this.negative ? -this.coefficient : this.coefficient;
  }

  private requireFinite(other?: Decimal): void {
    if (!this.isFinite() || (other && !other.isFinite())) {
      throw new InvalidOperation("非有限の Decimal は計算できません");
    }
  }

  /** 正確な結果を文脈の精度で丸める（_fix）。 */
  private static fix(negative: boolean, coefficient: bigint, exponent: number, ctx: DecimalContext = {}): Decimal {
    const prec = ctx.prec ?? DEFAULT_PREC;
    const rounding = ctx.rounding ?? "ROUND_HALF_EVEN";
    const count = digitCount(coefficient);
    if (count <= prec) {
      return new Decimal(negative, coefficient, exponent);
    }
    const drop = count - prec;
    let rounded = roundCoefficient(coefficient, drop, negative, rounding);
    let exp = exponent + drop;
    if (digitCount(rounded) > prec) {
      rounded /= TEN;
      exp += 1;
    }
    return new Decimal(negative, rounded, exp);
  }

  add(other: Decimal, ctx?: DecimalContext): Decimal {
    this.requireFinite(other);
    const exp = Math.min(this.exponent, other.exponent);
    const a = this.signed() * pow10(this.exponent - exp);
    const b = other.signed() * pow10(other.exponent - exp);
    const sum = a + b;
    if (sum === ZERO) {
      // Python: 両方が負のゼロのときだけ -0。符号が違えば ROUND_FLOOR 以外は +0。
      const rounding = ctx?.rounding ?? "ROUND_HALF_EVEN";
      let negative: boolean;
      if (this.isZero() && other.isZero()) {
        negative = (this.negative && other.negative) || (this.negative !== other.negative && rounding === "ROUND_FLOOR");
      } else {
        negative = rounding === "ROUND_FLOOR";
      }
      return Decimal.fix(negative, ZERO, exp, ctx);
    }
    return Decimal.fix(sum < ZERO, absBig(sum), exp, ctx);
  }

  sub(other: Decimal, ctx?: DecimalContext): Decimal {
    return this.add(other.negateRaw(), ctx);
  }

  mul(other: Decimal, ctx?: DecimalContext): Decimal {
    this.requireFinite(other);
    return Decimal.fix(this.negative !== other.negative, this.coefficient * other.coefficient, this.exponent + other.exponent, ctx);
  }

  /** Python の __truediv__ と同じ（正確に割り切れれば理想指数へ寄せる）。 */
  div(other: Decimal, ctx?: DecimalContext): Decimal {
    this.requireFinite(other);
    const prec = ctx?.prec ?? DEFAULT_PREC;
    const negative = this.negative !== other.negative;
    if (other.isZero()) {
      throw new InvalidOperation(this.isZero() ? "[<class 'decimal.DivisionUndefined'>]" : "[<class 'decimal.DivisionByZero'>]");
    }
    if (this.isZero()) {
      return Decimal.fix(negative, ZERO, this.exponent - other.exponent, ctx);
    }
    const shift = digitCount(other.coefficient) - digitCount(this.coefficient) + prec + 1;
    let exp = this.exponent - other.exponent - shift;
    let coeff: bigint;
    let remainder: bigint;
    if (shift >= 0) {
      const numerator = this.coefficient * pow10(shift);
      coeff = numerator / other.coefficient;
      remainder = numerator % other.coefficient;
    } else {
      const denominator = other.coefficient * pow10(-shift);
      coeff = this.coefficient / denominator;
      remainder = this.coefficient % denominator;
    }
    if (remainder !== ZERO) {
      if (coeff % FIVE === ZERO) coeff += ONE;
    } else {
      const ideal = this.exponent - other.exponent;
      while (exp < ideal && coeff % TEN === ZERO) {
        coeff /= TEN;
        exp += 1;
      }
    }
    return Decimal.fix(negative, coeff, exp, ctx);
  }

  private negateRaw(): Decimal {
    return new Decimal(!this.negative, this.coefficient, this.exponent, this.special);
  }

  /** 単項マイナス（-x）。Python では 0 の符号は +0 になる。 */
  neg(ctx?: DecimalContext): Decimal {
    this.requireFinite();
    if (this.isZero()) return Decimal.fix(false, ZERO, this.exponent, ctx);
    return Decimal.fix(!this.negative, this.coefficient, this.exponent, ctx);
  }

  abs(ctx?: DecimalContext): Decimal {
    this.requireFinite();
    return Decimal.fix(false, this.coefficient, this.exponent, ctx);
  }

  /** 比較（-1 / 0 / 1）。NaN は比較できない。 */
  cmp(other: Decimal | number): number {
    const o = typeof other === "number" ? Decimal.fromInt(other) : other;
    if (this.isNaN() || o.isNaN()) {
      throw new InvalidOperation("[<class 'decimal.InvalidOperation'>]");
    }
    if (this.special === "inf" || o.special === "inf") {
      const av = this.special === "inf" ? (this.negative ? -2 : 2) : 0;
      const bv = o.special === "inf" ? (o.negative ? -2 : 2) : 0;
      if (av !== 0 || bv !== 0) {
        if (av === bv) return 0;
        if (av !== 0 && bv !== 0) return av < bv ? -1 : 1;
        if (av !== 0) return av < 0 ? -1 : 1;
        return bv < 0 ? 1 : -1;
      }
    }
    const exp = Math.min(this.exponent, o.exponent);
    const a = this.signed() * pow10(this.exponent - exp);
    const b = o.signed() * pow10(o.exponent - exp);
    return a < b ? -1 : a > b ? 1 : 0;
  }

  eq(other: Decimal | number): boolean {
    if (this.isNaN() || (other instanceof Decimal && other.isNaN())) return false;
    return this.cmp(other) === 0;
  }

  lt(other: Decimal | number): boolean {
    return this.cmp(other) < 0;
  }

  lte(other: Decimal | number): boolean {
    return this.cmp(other) <= 0;
  }

  gt(other: Decimal | number): boolean {
    return this.cmp(other) > 0;
  }

  gte(other: Decimal | number): boolean {
    return this.cmp(other) >= 0;
  }

  /** _rescale: 指数を exp にして、係数を rounding で丸める（精度の検査はしない）。 */
  private rescale(exp: number, rounding: Rounding): Decimal {
    if (this.isZero()) return new Decimal(this.negative, ZERO, exp);
    if (this.exponent >= exp) {
      return new Decimal(this.negative, this.coefficient * pow10(this.exponent - exp), exp);
    }
    const drop = exp - this.exponent;
    return new Decimal(this.negative, roundCoefficient(this.coefficient, drop, this.negative, rounding), exp);
  }

  /** quantize(exp, rounding)。結果の桁が精度を超えると InvalidOperation。 */
  quantize(exp: Decimal, rounding: Rounding = "ROUND_HALF_EVEN", ctx?: DecimalContext): Decimal {
    this.requireFinite(exp);
    const prec = ctx?.prec ?? DEFAULT_PREC;
    if (this.isZero()) {
      return new Decimal(this.negative, ZERO, exp.exponent);
    }
    if (this.adjusted() - exp.exponent + 1 > prec) {
      throw new InvalidOperation("[<class 'decimal.InvalidOperation'>]");
    }
    const result = this.rescale(exp.exponent, rounding);
    if (digitCount(result.coefficient) > prec) {
      throw new InvalidOperation("[<class 'decimal.InvalidOperation'>]");
    }
    return result;
  }

  /** to_integral_value(): 指数が負なら整数へ丸める。 */
  toIntegralValue(rounding: Rounding = "ROUND_HALF_EVEN"): Decimal {
    this.requireFinite();
    if (this.exponent >= 0) return this;
    return this.rescale(0, rounding);
  }

  /** scaleb(n): 指数に n を足す。 */
  scaleb(n: number, ctx?: DecimalContext): Decimal {
    this.requireFinite();
    return Decimal.fix(this.negative, this.coefficient, this.exponent + n, ctx);
  }

  /** int(x): 0 方向へ切り捨てた整数。 */
  toBigInt(): bigint {
    this.requireFinite();
    if (this.exponent >= 0) return this.signed() * pow10(this.exponent);
    return this.signed() / pow10(-this.exponent);
  }

  /** Python の str(Decimal)（to-scientific-string）。 */
  toString(): string {
    const sign = this.negative ? "-" : "";
    if (this.special === "inf") return `${sign}Infinity`;
    if (this.special === "nan" || this.special === "snan") {
      const payload = this.coefficient === ZERO ? "" : this.coefficient.toString();
      return `${sign}${this.special === "nan" ? "NaN" : "sNaN"}${payload}`;
    }
    const digits = this.coefficient.toString();
    const exp = this.exponent;
    const leftdigits = exp + digits.length;
    let dotplace: number;
    if (exp <= 0 && leftdigits > -6) {
      dotplace = leftdigits;
    } else {
      dotplace = 1;
    }
    let intpart: string;
    let fracpart: string;
    if (dotplace <= 0) {
      intpart = "0";
      fracpart = "." + "0".repeat(-dotplace) + digits;
    } else if (dotplace >= digits.length) {
      intpart = digits + "0".repeat(dotplace - digits.length);
      fracpart = "";
    } else {
      intpart = digits.slice(0, dotplace);
      fracpart = "." + digits.slice(dotplace);
    }
    let expPart = "";
    if (leftdigits !== dotplace) {
      const e = leftdigits - dotplace;
      expPart = "E" + (e >= 0 ? "+" : "-") + Math.abs(e);
    }
    return sign + intpart + fracpart + expPart;
  }

  /** 指数表記を使わない10進表記（numeric 列へ渡す用）。 */
  toPlainString(): string {
    this.requireFinite();
    const sign = this.negative && this.coefficient !== ZERO ? "-" : "";
    const digits = this.coefficient.toString();
    if (this.exponent >= 0) return sign + digits + "0".repeat(this.exponent);
    const scale = -this.exponent;
    const padded = digits.padStart(scale + 1, "0");
    return sign + padded.slice(0, padded.length - scale) + "." + padded.slice(padded.length - scale);
  }

  toJSON(): string {
    return this.toString();
  }
}

/** coefficient の下位 drop 桁を rounding で落とした係数を返す。 */
function roundCoefficient(coefficient: bigint, drop: number, negative: boolean, rounding: Rounding): bigint {
  const divisor = pow10(drop);
  const quotient = coefficient / divisor;
  const remainder = coefficient % divisor;
  if (remainder === ZERO) return quotient;
  const half = divisor / BigInt(2);
  const twice = remainder * BigInt(2);
  let up: boolean;
  switch (rounding) {
    case "ROUND_DOWN":
      up = false;
      break;
    case "ROUND_UP":
      up = true;
      break;
    case "ROUND_FLOOR":
      up = negative;
      break;
    case "ROUND_CEILING":
      up = !negative;
      break;
    case "ROUND_HALF_UP":
      up = remainder >= half && twice >= divisor;
      break;
    case "ROUND_HALF_DOWN":
      up = twice > divisor;
      break;
    case "ROUND_HALF_EVEN":
    default:
      up = twice > divisor || (twice === divisor && quotient % BigInt(2) === ONE);
      break;
  }
  return up ? quotient + ONE : quotient;
}

/** sum(values, Decimal('0')) と同じ。 */
export function decimalSum(values: Iterable<Decimal>, ctx?: DecimalContext): Decimal {
  let total = Decimal.parse("0");
  for (const value of values) total = total.add(value, ctx);
  return total;
}

export function isDecimal(value: unknown): value is Decimal {
  return value instanceof Decimal;
}
