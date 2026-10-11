// P05: 承認済みの値引きを税の前に1つだけ適用する。
import { BANDS, hasExactBands, make_line, number, range_value, tryDec, _json_number, type Band, type DecRange } from "./common";
import { apply as subtotal_apply } from "./p07";
import { apply as tax_apply } from "./p09";
import { deepcopy, Dec, get, has, isDict, isList, nonemptyStrOrInt, pyEq, pyStr, QuoteError, setdefault, truthy, type Obj } from "./pyrt";

const PREFIX = "discount:p05";

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote) || !isDict(inputs)) throw new QuoteError("quote and inputs must be objects");
  const discount = get(inputs, "discount");
  if (discount === null) return deepcopy(quote);
  if (!isDict(discount)) throw new QuoteError("discount must be an object");
  if (get(discount, "order") !== "before_tax") throw new QuoteError("only before_tax discounts are supported");
  const scope = get(discount, "scope");
  if (scope !== "lines" && scope !== "subtotal") throw new QuoteError("discount.scope must be lines or subtotal");
  const kind = get(discount, "kind");
  if (kind !== "amount" && kind !== "rate") throw new QuoteError("discount.kind must be amount or rate");
  if (!nonemptyStrOrInt(get(discount, "approved_by")) || !nonemptyStrOrInt(get(discount, "reason"))) {
    throw new QuoteError("discount requires approved_by and reason");
  }

  const lines = get(quote, "lines");
  if (!isList(lines) || lines.some((line) => !isDict(line))) throw new QuoteError("quote.lines must be a list of objects");
  const lineIds = get(discount, "line_ids");
  if (!isList(lineIds) || lineIds.some((lineId) => !nonemptyStrOrInt(lineId))) {
    throw new QuoteError("discount.line_ids must be a list of non-empty IDs");
  }
  if (new Set(lineIds.map((entry) => pyStr(entry))).size !== lineIds.length) {
    throw new QuoteError("discount.line_ids must not contain duplicates");
  }
  if (scope === "lines" && !lineIds.length) throw new QuoteError("line discounts require at least one line_id");
  if (scope === "subtotal" && lineIds.length) throw new QuoteError("subtotal discounts must use an empty line_ids list");

  const baseLines = lines.filter((line) => get(line, "line_id") !== PREFIX);
  let selected: Obj[] = [];
  if (scope === "lines") {
    const byId = new Map<unknown, Obj>();
    for (const line of baseLines) byId.set(get(line, "line_id"), line);
    const missing = lineIds.map((entry) => pyStr(entry)).filter((entry) => !byId.has(entry));
    if (missing.length) throw new QuoteError(`unknown discount line_id: ${missing[0]}`);
    selected = lineIds.map((entry) => byId.get(pyStr(entry))!);
  }

  const previous = lines.find((line) => get(line, "line_id") === PREFIX) ?? null;
  const previousAmount = previous ? negativeRange(get(previous, "amount")) : zeroRange();
  const base = baseAmount(scope, selected, quote, baseLines, previousAmount);
  const value = parseDiscountValue(get(discount, "value"), kind);
  const amount = {} as DecRange;
  for (const band of BANDS) {
    const reduction = kind === "rate" ? base[band].mul(value[band]) : value[band];
    if (reduction.lt(Dec.int(0)) || reduction.gt(base[band])) throw new QuoteError(`discount exceeds eligible ${band} amount`);
    amount[band] = reduction.neg();
  }

  const result = deepcopy(quote);
  const resultLines = (result.lines as Obj[]).filter((line) => get(line, "line_id") !== PREFIX);
  const priorReason = previous ? get(previous, "reason") : null;
  const sourceRef = scope === "subtotal" ? "subtotal" : lineIds.map((entry) => pyStr(entry)).join(",");
  const positive = {} as Record<Band, string>;
  for (const band of BANDS) positive[band] = amount[band].neg().toString();
  const line = make_line({
    line_id: PREFIX,
    kind: "discount",
    category: null,
    description: "承認済み値引き",
    quantity_range: { low: 1, typical: 1, high: 1 },
    unit: "式",
    unit_price_range: positive,
    amount: positive,
    source_system: "simulator",
    source_ref: sourceRef,
    snapshot: {
      discount: deepcopy({ ...discount }),
      scope,
      line_ids: lineIds.map((entry) => pyStr(entry)),
      eligible_amount: jsonRange(base),
      discount_amount: jsonRange({ low: amount.low.neg(), typical: amount.typical.neg(), high: amount.high.neg() }),
    },
    reason: `${pyStr(discount.reason)}（承認: ${pyStr(discount.approved_by)}）`,
  });
  line.amount = jsonRange(amount);
  resultLines.push(line);
  result.lines = resultLines;
  const reasons = setdefault(result, "reasons", []);
  if (truthy(priorReason) && isList(reasons)) {
    result.reasons = reasons.filter((entry) => !pyEq(entry, priorReason));
  }
  setdefault(result, "reasons", []).push(line.reason);
  const subtotaled = subtotal_apply(result);
  if (has(inputs, "tax_policy")) return tax_apply(subtotaled, inputs);
  subtotaled.tax = { low: null, typical: null, high: null };
  subtotaled.total = { low: null, typical: null, high: null };
  delete subtotaled.tax_snapshot;
  return subtotaled;
}

function zeroRange(): DecRange {
  return { low: Dec.int(0), typical: Dec.int(0), high: Dec.int(0) };
}

function jsonRange(values: DecRange): Record<Band, number> {
  return { low: _json_number(values.low), typical: _json_number(values.typical), high: _json_number(values.high) };
}

function baseAmount(scope: string, selected: Obj[], quote: Obj, baseLines: Obj[], previousAmount: DecRange): DecRange {
  if (scope === "lines") {
    const totals = zeroRange();
    for (const line of selected) {
      if (get(line, "kind") === "discount") throw new QuoteError("discount lines cannot be targeted");
      const values = positiveRange(get(line, "amount"), "target line amount");
      for (const band of BANDS) totals[band] = totals[band].add(values[band]);
    }
    return totals;
  }
  const subtotal = get(quote, "subtotal");
  if (subtotal !== null) {
    const values = positiveRange(subtotal, "quote.subtotal");
    return {
      low: values.low.sub(previousAmount.low),
      typical: values.typical.sub(previousAmount.typical),
      high: values.high.sub(previousAmount.high),
    };
  }
  const totals = zeroRange();
  for (const line of baseLines) {
    if (get(line, "kind") === "discount") continue;
    const values = positiveRange(get(line, "amount"), "line amount");
    for (const band of BANDS) totals[band] = totals[band].add(values[band]);
  }
  return totals;
}

function parseDiscountValue(value: unknown, kind: string): DecRange {
  const parsed = isDict(value) ? range_value(value) : { low: number(value), typical: number(value), high: number(value) };
  if (kind === "rate" && BANDS.some((band) => parsed[band].gt(Dec.int(1)))) {
    throw new QuoteError("discount rate must be between 0 and 1");
  }
  return parsed;
}

function positiveRange(value: unknown, label: string): DecRange {
  if (!isDict(value) || !hasExactBands(value)) throw new QuoteError(`${label} must contain low, typical, and high`);
  const parsed = {} as DecRange;
  for (const band of BANDS) {
    const raw = value[band];
    if (raw === null || typeof raw === "boolean") throw new QuoteError(`${label} must be finite and non-negative`);
    const dec = tryDec(raw);
    if (dec === null || !dec.isFinite() || dec.lt(Dec.int(0))) throw new QuoteError(`${label} must be finite and non-negative`);
    parsed[band] = dec;
  }
  return parsed;
}

function negativeRange(value: unknown): DecRange {
  if (!isDict(value) || !hasExactBands(value)) throw new QuoteError("existing P05 amount must contain low, typical, and high");
  const parsed = {} as DecRange;
  for (const band of BANDS) {
    const raw = value[band];
    if (raw === null || typeof raw === "boolean") throw new QuoteError("existing P05 amount must be finite and non-positive");
    const dec = tryDec(raw);
    if (dec === null || !dec.isFinite() || dec.gt(Dec.int(0))) throw new QuoteError("existing P05 amount must be finite and non-positive");
    parsed[band] = dec;
  }
  return parsed;
}
