// P09: 帯ごとに独立して税を計算する（税率・端数処理は Simulator の明示設定）。
import { BANDS, hasExactBands, tryDec, _json_number, type Band, type DecRange } from "./common";
import { apply as subtotal_apply } from "./p07";
import { deepcopy, Dec, get, has, isDict, isInt, isList, pyStr, QuoteError, type Obj } from "./pyrt";

const ROUNDING: Record<string, "floor" | "half_up" | "ceil"> = { floor: "floor", half_up: "half_up", ceil: "ceil" };
const ALLOWED = ["rate", "rounding", "source", "approved_by", "effective_date", "taxable_line_ids"];

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (!isDict(inputs)) throw new QuoteError("inputs must be an object");
  const policy = get(inputs, "tax_policy");
  if (!isDict(policy)) throw new QuoteError("inputs.tax_policy must be an object");
  if (Object.keys(policy).some((key) => !ALLOWED.includes(key))) throw new QuoteError("tax_policy contains unknown settings");
  if (!["rate", "rounding", "source"].every((key) => has(policy, key))) {
    throw new QuoteError("tax_policy requires rate, rounding, and source");
  }
  const rate = parseRate(policy.rate);
  const rounding = policy.rounding;
  if (typeof rounding !== "string" || !has(ROUNDING, rounding)) throw new QuoteError("tax_policy.rounding is unknown");
  const source = policy.source;
  if (source !== "simulator" && source !== "factory") throw new QuoteError("tax_policy.source is unknown");
  const approvedBy = get(policy, "approved_by");
  const effectiveDate = get(policy, "effective_date");
  if (source === "factory" && (!nonemptyString(approvedBy) || !nonemptyString(effectiveDate))) {
    throw new QuoteError("factory tax policy requires approved_by and effective_date");
  }

  const lines = get(quote, "lines");
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");
  const lineIds: string[] = [];
  const lineById = new Map<string, Obj>();
  lines.forEach((line, index) => {
    if (!isDict(line)) throw new QuoteError(`quote.lines.${index} must be an object`);
    const lineId = get(line, "line_id");
    if (!(typeof lineId === "string" || isInt(lineId)) || !pyStr(lineId).trim()) {
      throw new QuoteError(`quote.lines.${index}.line_id is required`);
    }
    const key = pyStr(lineId);
    if (lineById.has(key)) throw new QuoteError(`duplicate line_id: ${key}`);
    lineIds.push(key);
    lineById.set(key, line);
  });

  if (source === "factory" && !has(policy, "taxable_line_ids")) {
    throw new QuoteError("factory tax policy requires explicit taxable_line_ids");
  }
  const taxable = has(policy, "taxable_line_ids") ? policy.taxable_line_ids : lineIds;
  if (!isList(taxable)) throw new QuoteError("tax_policy.taxable_line_ids must be a list");
  const taxableIds: string[] = [];
  for (const entry of taxable) {
    if (!(typeof entry === "string" || isInt(entry)) || !pyStr(entry).trim()) {
      throw new QuoteError("tax_policy.taxable_line_ids contains an invalid id");
    }
    const key = pyStr(entry);
    if (!lineById.has(key)) throw new QuoteError(`unknown taxable line id: ${key}`);
    if (taxableIds.includes(key)) throw new QuoteError(`duplicate taxable line id: ${key}`);
    taxableIds.push(key);
  }

  if (has(policy, "taxable_line_ids")) {
    const taxableSet = new Set(taxableIds);
    for (const [key, line] of lineById) {
      if (get(line, "kind") !== "discount") continue;
      const snapshot = get(line, "snapshot", {});
      let targetIds: unknown[] = get(snapshot, "line_ids", []);
      if (get(snapshot, "scope") === "subtotal") {
        targetIds = [...lineById].filter(([, target]) => get(target, "kind") !== "discount").map(([ref]) => ref);
      }
      if (!targetIds.length) throw new QuoteError("discount tax treatment requires target lines");
      const targetSet = new Set(targetIds);
      const overlap = [...targetSet].filter((ref) => taxableSet.has(ref as string));
      if (overlap.length && overlap.length !== targetSet.size) {
        throw new QuoteError("mixed-tax discount requires separate approved target lines");
      }
      if (overlap.length && !taxableSet.has(key)) {
        taxableIds.push(key);
        taxableSet.add(key);
      }
      if (!overlap.length && taxableSet.has(key)) throw new QuoteError("non-taxable discount cannot be marked taxable");
    }
  }
  const calculated = subtotal_apply(quote);
  const taxableSubtotal = { low: Dec.int(0), typical: Dec.int(0), high: Dec.int(0) } as DecRange;
  for (const lineId of taxableIds) {
    const values = signedRange(get(lineById.get(lineId)!, "amount"), lineId);
    for (const band of BANDS) taxableSubtotal[band] = taxableSubtotal[band].add(values[band]);
  }
  const taxes = {} as DecRange;
  const totals = {} as DecRange;
  for (const band of BANDS) {
    taxes[band] = taxableSubtotal[band].mul(rate).quantizeUnit(ROUNDING[rounding]);
    totals[band] = Dec.fromPy(calculated.subtotal[band]).add(taxes[band]);
  }
  const result = deepcopy(calculated);
  result.tax = jsonRange(taxes);
  result.total = jsonRange(totals);
  result.tax_snapshot = {
    rate: _json_number(rate),
    rounding,
    taxable_line_ids: deepcopy(taxableIds),
    effective_date: effectiveDate,
    source,
  };
  if (approvedBy !== null) result.tax_snapshot.approved_by = approvedBy;
  return result;
}

export function tax_summary(quote: unknown): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  const snapshot = get(quote, "tax_snapshot");
  if (!isDict(snapshot)) throw new QuoteError("quote.tax_snapshot is required");
  const subtotal = subtotal_apply({ ...quote }).subtotal;
  const tax = get(quote, "tax");
  const total = get(quote, "total");
  const result: Obj = {};
  for (const band of BANDS) {
    result[band] = {
      subtotal: subtotal[band],
      tax: rangeValue(tax, band, "tax"),
      total: rangeValue(total, band, "total"),
    };
  }
  return result;
}

function jsonRange(values: DecRange): Record<Band, number> {
  return { low: _json_number(values.low), typical: _json_number(values.typical), high: _json_number(values.high) };
}

function parseRate(value: unknown): Dec {
  if (value === null || typeof value === "boolean") throw new QuoteError("tax_policy.rate must be between 0 and 1");
  const rate = tryDec(value);
  if (rate === null || !rate.isFinite() || !(Dec.int(0).le(rate) && rate.le(Dec.int(1)))) {
    throw new QuoteError("tax_policy.rate must be between 0 and 1");
  }
  return rate;
}

function signedRange(value: unknown, lineId: string): DecRange {
  let raw: Record<string, unknown>;
  if (isDict(value)) {
    if (!hasExactBands(value)) throw new QuoteError(`line ${lineId} amount must contain low, typical, and high`);
    raw = value;
  } else if (value !== null && value !== undefined) {
    raw = { low: value, typical: value, high: value };
  } else {
    throw new QuoteError(`line ${lineId} amount must be finite`);
  }
  const parsed = {} as DecRange;
  for (const band of BANDS) {
    const entry = raw[band];
    if (entry === null || typeof entry === "boolean") throw new QuoteError(`line ${lineId} amount.${band} must be finite`);
    const dec = tryDec(entry);
    if (dec === null || !dec.isFinite()) throw new QuoteError(`line ${lineId} amount.${band} must be finite`);
    parsed[band] = dec;
  }
  return parsed;
}

function rangeValue(value: unknown, band: Band, label: string): number {
  if (!isDict(value) || !hasExactBands(value)) throw new QuoteError(`quote.${label} must contain low, typical, and high`);
  const raw = value[band];
  if (raw === null || typeof raw === "boolean") throw new QuoteError(`quote.${label}.${band} must be finite`);
  const parsed = tryDec(raw);
  if (parsed === null || !parsed.isFinite()) throw new QuoteError(`quote.${label}.${band} must be finite`);
  return _json_number(parsed);
}

function nonemptyString(value: unknown): boolean {
  return typeof value === "string" && value.trim() !== "";
}
