// 元の Pydantic モデル（app.py の CaseInput / ManualVehicle / Research / Item / Estimate、gemini.py の Price）と
// 同じ入力を受け付け・拒否する検証。拒否したときは FastAPI と同じく 422 と、detail に配列を返す。
import { HttpError, PyFloat, pyLen } from "./py";

export type Issue = { type: string; loc: (string | number)[]; msg: string; input: unknown };
type Loc = (string | number)[];
/** 検証に失敗した値の印。 */
const INVALID = Symbol("invalid");
type Result<T> = T | typeof INVALID;
export type Validator<T> = (value: unknown, loc: Loc, issues: Issue[]) => Result<T>;
/** 検証に通った値の型。 */
export type Infer<V> = V extends Validator<infer T> ? T : never;

function fail(issues: Issue[], type: string, loc: Loc, msg: string, input: unknown): typeof INVALID {
  issues.push({ type, loc, msg, input: input instanceof PyFloat ? input.value : input });
  return INVALID;
}

export function str(options: { min?: number; max?: number; pattern?: RegExp } = {}): Validator<string> {
  return (value, loc, issues) => {
    if (typeof value !== "string") return fail(issues, "string_type", loc, "Input should be a valid string", value);
    const length = pyLen(value);
    if (options.min !== undefined && length < options.min) {
      return fail(issues, "string_too_short", loc, `String should have at least ${options.min} character`, value);
    }
    if (options.max !== undefined && length > options.max) {
      return fail(issues, "string_too_long", loc, `String should have at most ${options.max} characters`, value);
    }
    if (options.pattern && !options.pattern.test(value)) {
      return fail(issues, "string_pattern_mismatch", loc, `String should match pattern '${options.pattern.source}'`, value);
    }
    return value;
  };
}

function bounds(n: number, options: { ge?: number; le?: number }, loc: Loc, issues: Issue[], input: unknown): Result<number> {
  if (options.ge !== undefined && n < options.ge) {
    return fail(issues, "greater_than_equal", loc, `Input should be greater than or equal to ${options.ge}`, input);
  }
  if (options.le !== undefined && n > options.le) {
    return fail(issues, "less_than_equal", loc, `Input should be less than or equal to ${options.le}`, input);
  }
  return n;
}

/** Field(strict=True) の int。bool・小数（1.0 を含む）・文字列を拒否する。 */
export function strictInt(options: { ge?: number; le?: number } = {}): Validator<number> {
  return (value, loc, issues) => {
    if (typeof value !== "number" || !Number.isInteger(value)) {
      return fail(issues, "int_type", loc, "Input should be a valid integer", value);
    }
    return bounds(value, options, loc, issues, value);
  };
}

/** 通常（lax）の int。true/false、整数の小数（2023.0）、数字の文字列（" 2023"）も受け付ける。 */
export function laxInt(options: { ge?: number; le?: number } = {}): Validator<number> {
  return (value, loc, issues) => {
    let n: number;
    if (typeof value === "boolean") n = value ? 1 : 0;
    else if (typeof value === "number") n = value;
    else if (value instanceof PyFloat) {
      if (!Number.isFinite(value.value)) return fail(issues, "finite_number", loc, "Input should be a finite number", value);
      if (!Number.isInteger(value.value)) {
        return fail(issues, "int_from_float", loc, "Input should be a valid integer, got a number with a fractional part", value);
      }
      n = value.value;
    } else if (typeof value === "string") {
      const match = /^\s*([+-]?[0-9]+)(\.0*)?\s*$/.exec(value);
      if (!match) {
        return fail(issues, "int_parsing", loc, "Input should be a valid integer, unable to parse string as an integer", value);
      }
      n = Number(match[1]);
    } else return fail(issues, "int_type", loc, "Input should be a valid integer", value);
    return bounds(n, options, loc, issues, value);
  };
}

/** Field(strict=True) の bool。 */
export function strictBool(): Validator<boolean> {
  return (value, loc, issues) =>
    typeof value === "boolean" ? value : fail(issues, "bool_type", loc, "Input should be a valid boolean", value);
}

export function literal<T extends string | number>(values: readonly T[]): Validator<T> {
  return (value, loc, issues) => {
    const raw = value instanceof PyFloat ? value.value : value;
    const found = values.find((v) => v === raw);
    if (found === undefined) {
      return fail(issues, "literal_error", loc, `Input should be ${values.map((v) => JSON.stringify(v)).join(" or ")}`, value);
    }
    return found;
  };
}

export function nullable<T>(inner: Validator<T>): Validator<T | null> {
  return (value, loc, issues) => (value === null ? null : inner(value, loc, issues));
}

export function list<T>(item: Validator<T>, options: { min?: number; max?: number } = {}): Validator<T[]> {
  return (value, loc, issues) => {
    if (!Array.isArray(value)) return fail(issues, "list_type", loc, "Input should be a valid list", value);
    const before = issues.length;
    const out = value.map((v, i) => item(v, [...loc, i], issues));
    if (issues.length > before) return INVALID;
    if (options.min !== undefined && out.length < options.min) {
      return fail(issues, "too_short", loc, `List should have at least ${options.min} item after validation, not ${out.length}`, value);
    }
    if (options.max !== undefined && out.length > options.max) {
      return fail(issues, "too_long", loc, `List should have at most ${options.max} items after validation, not ${out.length}`, value);
    }
    return out as T[];
  };
}

function validCalendarDate(year: number, month: number, day: number): boolean {
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/** Pydantic の date。'YYYY-MM-DD'、0時ちょうどの日時、日単位の UNIX 時刻を受け付け、'YYYY-MM-DD' にする。 */
export function isoDate(): Validator<string> {
  return (value, loc, issues) => {
    const fromTimestamp = (n: number): Result<string> => {
      const ms = Math.abs(n) > 2e10 ? n : n * 1000;
      if (!Number.isFinite(ms) || ms % 86400000 !== 0) {
        return fail(issues, "date_from_datetime_inexact", loc, "Datetimes provided to dates should have zero time - e.g. be exact dates", value);
      }
      return new Date(ms).toISOString().slice(0, 10);
    };
    if (typeof value === "number") return fromTimestamp(value);
    if (value instanceof PyFloat) return fromTimestamp(value.value);
    if (typeof value !== "string") return fail(issues, "date_type", loc, "Input should be a valid date", value);
    if (/^[0-9]+$/.test(value)) return fromTimestamp(Number(value));
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[Tt_ ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(?:[Zz]|[+-]\d{2}:?\d{2})?)?$/.exec(value);
    if (!match || !validCalendarDate(Number(match[1]), Number(match[2]), Number(match[3]))) {
      return fail(issues, "date_from_datetime_parsing", loc, "Input should be a valid date or datetime", value);
    }
    const [, y, m, d, hh, mm, ss, frac] = match;
    if (hh !== undefined && (Number(hh) || Number(mm) || Number(ss ?? 0) || Number(frac ?? 0))) {
      return fail(issues, "date_from_datetime_inexact", loc, "Datetimes provided to dates should have zero time - e.g. be exact dates", value);
    }
    return `${y}-${m}-${d}`;
  };
}

type Field<T> = { validate: Validator<T>; default?: () => T };
type Fields = Record<string, Field<unknown>>;
type Output<F extends Fields> = { [K in keyof F]: F[K] extends Field<infer T> ? T : never };

export function field<T>(validate: Validator<T>, defaultValue?: () => T): Field<T> {
  return { validate, default: defaultValue };
}

/**
 * extra="forbid" の BaseModel。fieldsSet は入力に実際にあった項目（Pydantic の model_fields_set）。
 * 出力の項目の順序はモデルの定義順（model_dump の順序）。
 */
export function model<F extends Fields>(fields: F): Validator<Output<F> & { fieldsSet: Set<string> }> {
  return (value, loc, issues) => {
    if (typeof value !== "object" || value === null || Array.isArray(value) || value instanceof PyFloat) {
      return fail(issues, "model_attributes_type", loc, "Input should be a valid dictionary or object to extract fields from", value);
    }
    const input = value as Record<string, unknown>;
    const before = issues.length;
    const out: Record<string, unknown> = {};
    const fieldsSet = new Set<string>();
    for (const [name, spec] of Object.entries(fields)) {
      if (Object.hasOwn(input, name)) {
        fieldsSet.add(name);
        out[name] = spec.validate(input[name], [...loc, name], issues);
      } else if (spec.default) {
        out[name] = spec.default();
      } else {
        fail(issues, "missing", [...loc, name], "Field required", input);
      }
    }
    for (const name of Object.keys(input)) {
      if (!Object.hasOwn(fields, name)) fail(issues, "extra_forbidden", [...loc, name], "Extra inputs are not permitted", input[name]);
    }
    if (issues.length > before) return INVALID;
    return Object.assign(out, { fieldsSet }) as Output<F> & { fieldsSet: Set<string> };
  };
}

/** リクエストボディを検証する。失敗したら FastAPI と同じ 422（detail は配列）。 */
export function validateBody<T>(validator: Validator<T>, body: unknown): T {
  const issues: Issue[] = [];
  const result = validator(body, ["body"], issues);
  if (result === INVALID || issues.length) throw new HttpError(422, issues);
  return result;
}

/** Pydantic の model_validate。失敗したら null を返す（呼び出し側でエラーにする）。 */
export function tryValidate<T>(validator: Validator<T>, value: unknown): T | null {
  const issues: Issue[] = [];
  const result = validator(value, [], issues);
  return result === INVALID || issues.length ? null : result;
}

// ---- app.py のモデル ----

const CASE_STATUSES = ["unestimated", "estimating", "completed"] as const;
const WINTER_CONDITIONS = ["salt_roads", "rust_check", "cold_start"] as const;
const MODE = /^(simulator|live)$/;

export const CaseInput = model({
  vehicle_id: field(nullable(str({ min: 1, max: 80 })), () => null),
  recipient_name: field(str({ max: 120 }), () => ""),
  phone_memo: field(str({ max: 6000 }), () => ""),
  title: field(str({ min: 1, max: 120 })),
  vehicle_label: field(str({ max: 160 }), () => ""),
  status: field(literal(CASE_STATUSES), () => "unestimated" as const),
  amount: field(nullable(strictInt({ ge: 0, le: 110000000 })), () => null),
  due_date: field(nullable(isoDate()), () => null),
  notes: field(str({ max: 2000 }), () => ""),
});

export const ManualVehicle = model({
  maker: field(str({ min: 1, max: 80 })),
  model: field(str({ min: 1, max: 80 })),
  model_code: field(str({ min: 1, max: 40 })),
  year: field(laxInt({ ge: 1900, le: 2100 })),
  grade: field(str({ min: 1, max: 80 })),
});

export const Research = model({
  vehicle_id: field(str()),
  year: field(laxInt()),
  grade: field(str()),
  job_ids: field(list(str(), { min: 1, max: 5 })),
  mode: field(str({ pattern: MODE }), () => "simulator"),
});

export const Item = model({
  job_id: field(str()),
  selected_source_ids: field(list(str(), { max: 4 })),
  labor_price: field(strictInt({ ge: 0, le: 10000000 })),
  parts_price: field(strictInt({ ge: 0, le: 10000000 })),
  conditions: field(str({ max: 1000 }), () => ""),
  adjustment_reason: field(str({ max: 1000 }), () => ""),
});

export const Estimate = model({
  case_id: field(nullable(str({ max: 80 })), () => null),
  winter_conditions: field(list(literal(WINTER_CONDITIONS), { max: 3 }), () => []),
  mode: field(str({ pattern: MODE }), () => "simulator"),
  research_id: field(nullable(str()), () => null),
  vehicle_id: field(str()),
  year: field(laxInt()),
  grade: field(str()),
  items: field(list(Item, { min: 1, max: 5 })),
  notes: field(str({ max: 2000 }), () => ""),
});

// ---- gemini.py のモデル ----

export const Price = model({
  job_id: field(str({ max: 30 })),
  source_url: field(str({ max: 2000 })),
  labor_price: field(nullable(strictInt({ ge: 0, le: 10000000 }))),
  parts_price: field(nullable(strictInt({ ge: 0, le: 10000000 }))),
  total_price: field(nullable(strictInt({ ge: 0, le: 10000000 }))),
  tax_included: field(nullable(strictBool())),
  tax_rate: field(nullable(literal([0.05, 0.08, 0.1] as const)), () => null),
  vehicle_match: field(literal(["exact", "similar", "unknown"] as const)),
  work_matches: field(nullable(strictBool())),
  work_conditions: field(str({ max: 1000 })),
  published_at: field(nullable(str({ max: 80 }))),
  evidence: field(str({ max: 120 })),
});

export const Prices = model({
  sources: field(list(Price, { max: 20 })),
});

/** 検証済みの値から fieldsSet を外して、model_dump と同じ順序の素のオブジェクトにする。 */
export function dump<T extends { fieldsSet: Set<string> }>(value: T): Omit<T, "fieldsSet"> {
  const { fieldsSet, ...rest } = value;
  void fieldsSet;
  return rest;
}
