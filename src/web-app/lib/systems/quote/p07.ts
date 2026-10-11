// P07: 見積行を費目ごとにまとめ、帯ごとの小計を計算する。
import { BANDS, hasExactBands, tryDec, _json_number, type Band, type DecRange } from "./common";
import { deepcopy, Dec, get, isDict, isInt, isList, pyIn, pyStr, QuoteError, type Obj } from "./pyrt";

const KINDS = ["labor", "parts", "materials", "adjustment", "discount"];
const MATERIAL_CATEGORIES = ["塗料", "溶剤", "消耗品"];
const GROUPS = ["labor", "parts", "materials", "adjustments"] as const;

export function apply(quote: unknown, inputs: unknown = null): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (inputs !== null && !isDict(inputs)) throw new QuoteError("inputs must be an object when provided");
  const lines = get(quote, "lines");
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");

  const seen = new Set<string>();
  const totals: Record<string, DecRange> = {};
  for (const group of GROUPS) totals[group] = { low: Dec.int(0), typical: Dec.int(0), high: Dec.int(0) };
  lines.forEach((line, index) => {
    if (!isDict(line)) throw new QuoteError(`quote.lines.${index} must be an object`);
    const rawId = get(line, "line_id");
    if (!(typeof rawId === "string" || isInt(rawId)) || !pyStr(rawId).trim()) {
      throw new QuoteError(`quote.lines.${index}.line_id is required`);
    }
    const lineId = pyStr(rawId);
    if (seen.has(lineId)) throw new QuoteError(`duplicate line_id: ${lineId}`);
    seen.add(lineId);
    const kind = get(line, "kind");
    if (!pyIn(kind, KINDS)) throw new QuoteError(`quote.lines.${index}.kind is unknown`);
    const group = validateCategory(kind, get(line, "category"), index);
    const amount = amountRange(get(line, "amount"), index, kind === "discount", kind === "adjustment" || kind === "discount");
    for (const band of BANDS) totals[group][band] = totals[group][band].add(amount[band]);
  });

  const subtotal = {} as DecRange;
  for (const band of BANDS) {
    subtotal[band] = GROUPS.reduce((sum, group) => sum.add(totals[group][band]), Dec.int(0));
  }
  for (const band of BANDS) {
    if (subtotal[band].lt(Dec.int(0))) throw new QuoteError(`subtotal.${band} must not be negative after discounts`);
  }
  if (!(subtotal.low.le(subtotal.typical) && subtotal.typical.le(subtotal.high))) {
    throw new QuoteError("subtotal bands must satisfy low <= typical <= high");
  }
  const result = deepcopy(quote);
  result.labor_subtotal = jsonRange(totals.labor);
  result.parts_subtotal = jsonRange(totals.parts);
  result.materials_subtotal = jsonRange(totals.materials);
  result.adjustments_subtotal = jsonRange(totals.adjustments);
  result.subtotal = jsonRange(subtotal);
  return result;
}

export function group_lines(quote: unknown): Obj {
  const calculated = apply(isDict(quote) ? { ...quote } : quote);
  const groups: Obj = {
    labor: { lines: [], subtotal: calculated.labor_subtotal },
    parts: { lines: [], subtotal: calculated.parts_subtotal },
    materials: { lines: [], subtotal: calculated.materials_subtotal },
    adjustments: { lines: [], subtotal: calculated.adjustments_subtotal },
  };
  for (const line of calculated.lines as Obj[]) {
    const kind = line.kind;
    const group = kind === "adjustment" || kind === "discount" ? "adjustments" : kind;
    groups[group].lines.push(deepcopy(line));
  }
  return groups;
}

function validateCategory(kind: string, category: unknown, index: number): string {
  if (kind === "labor" && category === "labor") return "labor";
  if (kind === "parts" && category === "部品") return "parts";
  if (kind === "materials" && pyIn(category, MATERIAL_CATEGORIES)) return "materials";
  if (kind === "adjustment" && (category === "labor" || category === "subtotal")) return "adjustments";
  if (kind === "discount" && category === null) return "adjustments";
  throw new QuoteError(`quote.lines.${index}.category does not match kind ${kind}`);
}

function amountRange(value: unknown, index: number, allowNegative: boolean, allowUnordered: boolean): DecRange {
  const label = `quote.lines.${index}.amount`;
  let rawValues: Record<string, unknown>;
  if (isDict(value) && hasExactBands(value)) rawValues = value;
  else if (!isDict(value) && value !== null && value !== undefined) rawValues = { low: value, typical: value, high: value };
  else throw new QuoteError(`${label} must contain low, typical, and high`);
  const parsed = {} as DecRange;
  for (const band of BANDS) {
    const raw = rawValues[band];
    if (raw === null || typeof raw === "boolean") throw new QuoteError(`${label}.${band} must be finite`);
    const parsedNumber = tryDec(raw);
    if (parsedNumber === null) throw new QuoteError(`${label}.${band} must be finite`);
    if (!parsedNumber.isFinite() || (parsedNumber.lt(Dec.int(0)) && !allowNegative)) {
      throw new QuoteError(`${label}.${band} must be finite and non-negative`);
    }
    parsed[band] = parsedNumber;
  }
  if (!allowUnordered && !(parsed.low.le(parsed.typical) && parsed.typical.le(parsed.high))) {
    throw new QuoteError(`${label} bands must satisfy low <= typical <= high`);
  }
  return parsed;
}

function jsonRange(values: DecRange): Record<Band, number> {
  const result = { low: _json_number(values.low), typical: _json_number(values.typical), high: _json_number(values.high) };
  for (const value of Object.values(result)) {
    if (!Number.isFinite(value)) throw new QuoteError("subtotal must be finite");
  }
  return result;
}
