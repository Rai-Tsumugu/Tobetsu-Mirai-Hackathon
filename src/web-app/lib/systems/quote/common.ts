// common.py: 帯（low/typical/high）と10進演算の共通部品。
import { Dec, QuoteError, deepcopy, isDict, isList, pyEq, type Json, type Obj } from "./pyrt";

export const BANDS = ["low", "typical", "high"] as const;
export type Band = (typeof BANDS)[number];

/** set(value) == set(BANDS) */
export function hasExactBands(value: Obj): boolean {
  const keys = Object.keys(value);
  return keys.length === 3 && BANDS.every((band) => keys.includes(band));
}

export function isBand(value: unknown): value is Band {
  return typeof value === "string" && (BANDS as readonly string[]).includes(value);
}

/** Decimal(str(value)) を試し、失敗したら null（InvalidOperation / ValueError / TypeError）。 */
export function tryDec(value: unknown): Dec | null {
  try {
    return Dec.fromPy(value);
  } catch {
    return null;
  }
}

export function number(value: unknown): Dec {
  if (value === null || value === undefined || typeof value === "boolean") {
    throw new QuoteError("number must be a finite non-negative value");
  }
  const result = tryDec(value);
  if (result === null || !result.isFinite() || result.lt(Dec.int(0))) {
    throw new QuoteError("number must be a finite non-negative value");
  }
  return result;
}

export type DecRange = Record<Band, Dec>;

export function range_value(value: unknown): DecRange {
  if (!isDict(value) || !hasExactBands(value)) {
    throw new QuoteError("range must contain exactly low, typical, and high");
  }
  const result = { low: number(value.low), typical: number(value.typical), high: number(value.high) };
  if (!(result.low.le(result.typical) && result.typical.le(result.high))) {
    throw new QuoteError("range values must satisfy low <= typical <= high");
  }
  return result;
}

export function _json_number(value: Dec): number {
  if (value.isIntegral()) return Number(value.toBigInt());
  return value.toNumber();
}

export function jsonRange(values: Record<Band, Dec>): Record<Band, number> {
  return { low: _json_number(values.low), typical: _json_number(values.typical), high: _json_number(values.high) };
}

export function money_range(value: unknown): Record<Band, number> {
  let parsed: DecRange;
  if (isDict(value)) {
    parsed = range_value(value);
  } else {
    const scalar = number(value);
    parsed = { low: scalar, typical: scalar, high: scalar };
  }
  return jsonRange(parsed);
}

function operand(value: unknown): DecRange {
  if (isDict(value)) return range_value(value);
  return { low: number(value), typical: number(value), high: number(value) };
}

export function add_ranges(...values: unknown[]): Record<Band, number> {
  const totals: DecRange = { low: Dec.int(0), typical: Dec.int(0), high: Dec.int(0) };
  for (const value of values) {
    const parsed = operand(value);
    for (const band of BANDS) totals[band] = totals[band].add(parsed[band]);
  }
  return jsonRange(totals);
}

export function multiply_ranges(left: unknown, right: unknown): Record<Band, number> {
  const lhs = operand(left);
  const rhs = operand(right);
  return jsonRange({
    low: lhs.low.mul(rhs.low),
    typical: lhs.typical.mul(rhs.typical),
    high: lhs.high.mul(rhs.high),
  });
}

export function new_quote(labor: Json, labor_rate: Json, items: Json): Obj {
  if (!isDict(labor) || !isDict(labor_rate) || !isList(items)) {
    throw new QuoteError("labor, labor_rate, and items must be mappings/list");
  }
  return {
    lines: [],
    subtotal: money_range(0),
    tax: money_range(0),
    total: money_range(0),
    reasons: [],
    confirmed_by: null,
    override_reason: null,
    status: "proposed",
    metadata: { input_snapshot: deepcopy({ labor, labor_rate, items }) },
  };
}

export type LineArgs = {
  line_id: string;
  kind: string;
  category: string | null;
  description: string;
  quantity_range: Json;
  unit: string;
  unit_price_range: Json;
  amount: Json;
  source_system: string;
  source_ref: string | null;
  snapshot: Obj;
  reason: string;
  status?: string;
};

export function make_line(args: LineArgs): Obj {
  return {
    line_id: args.line_id,
    kind: args.kind,
    category: args.category,
    description: args.description,
    quantity_range: money_range(args.quantity_range),
    unit: args.unit,
    unit_price_range: money_range(args.unit_price_range),
    amount: money_range(args.amount),
    source_system: args.source_system,
    source_ref: args.source_ref,
    snapshot: deepcopy({ ...args.snapshot }),
    reason: args.reason,
    status: args.status ?? "proposed",
  };
}

/** Python の Decimal を JSON 値へ（json_ready 相当の単体版）。 */
export function decToJson(value: Dec): number {
  return _json_number(value);
}

export function rangeOf(value: Dec): DecRange {
  return { low: value, typical: value, high: value };
}

export { pyEq };
