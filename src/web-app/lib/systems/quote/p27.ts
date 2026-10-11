// P27: 確定した見積を検証し、変えられないスナップショットとして保存する。
import { BANDS, hasExactBands, isBand, number, range_value, tryDec, type DecRange } from "./common";
import { apply as validate_lines_and_subtotal } from "./p07";
import { datetimeFromIso, deepcopy, Dec, get, has, isDict, isInt, isList, PyError, pyEq, QuoteError, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

export async function save_snapshot(store: QuoteStore, quote: unknown): Promise<Obj> {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (get(quote, "status") !== "confirmed") throw new QuoteError("only confirmed quotes can be snapshotted");
  const quoteId = get(quote, "quote_id");
  const version = get(quote, "quote_version");
  if (typeof quoteId !== "string" || !quoteId.trim()) throw new QuoteError("quote_id is required");
  if (!isInt(version) || version < 1) throw new QuoteError("quote_version must be a positive integer");
  if (!isBand(get(quote, "selected_band"))) throw new QuoteError("selected_band must be low, typical, or high");
  const confirmedBy = get(quote, "confirmed_by");
  if (typeof confirmedBy !== "string" || !confirmedBy.trim()) throw new QuoteError("confirmed_by is required");
  const confirmation = get(quote, "confirmation");
  if (!isDict(confirmation)) throw new QuoteError("confirmation is required");
  if (!pyEq(get(confirmation, "selected_band"), get(quote, "selected_band"))) {
    throw new QuoteError("confirmation.selected_band must match selected_band");
  }
  if (!pyEq(get(confirmation, "confirmed_by"), confirmedBy)) throw new QuoteError("confirmation.confirmed_by must match confirmed_by");
  const confirmedAt = get(quote, "confirmed_at");
  const confirmationAt = get(confirmation, "confirmed_at");
  if (!nonempty(confirmedAt) || !nonempty(confirmationAt)) throw new QuoteError("confirmed_at is required in quote and confirmation");
  if (!timestampsConsistent(confirmedAt, confirmationAt)) throw new QuoteError("confirmation.confirmed_at must match confirmed_at");
  if (!has(quote, "final_amount") || !has(confirmation, "final_amount")) {
    throw new QuoteError("final_amount is required in quote and confirmation");
  }
  if (!number(quote.final_amount).eq(number(confirmation.final_amount))) {
    throw new QuoteError("confirmation.final_amount must match final_amount");
  }
  if (!pyEq(get(quote, "override_reason"), get(confirmation, "override_reason"))) {
    throw new QuoteError("confirmation.override_reason must match override_reason");
  }

  const metadata = get(quote, "metadata");
  const inputs = isDict(metadata) ? get(metadata, "input_snapshot") : null;
  if (!isDict(inputs)) throw new QuoteError("metadata.input_snapshot is required");
  if (!["labor", "labor_rate", "items"].every((key) => has(inputs, key))) {
    throw new QuoteError("input snapshot must include labor, labor_rate, and items");
  }
  if (!isDict(inputs.labor) || !isDict(inputs.labor_rate) || !isList(inputs.items)) {
    throw new QuoteError("input snapshot labor/rate/items have invalid types");
  }
  validateFiniteNumbers(inputs, "metadata.input_snapshot");

  const lines = get(quote, "lines");
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");
  lines.forEach((line, index) => {
    if (!isDict(line)) throw new QuoteError(`quote.lines.${index} must be an object`);
    if (!nonempty(get(line, "source_system")) || !nonempty(get(line, "source_ref"))) {
      throw new QuoteError(`quote.lines.${index} source_system and source_ref are required`);
    }
    const snapshot = get(line, "snapshot");
    if (!isDict(snapshot) || !Object.keys(snapshot).length) throw new QuoteError(`quote.lines.${index}.snapshot is required`);
    bandRange(get(line, "quantity_range"), `quote.lines.${index}.quantity_range`);
    if (has(line, "unit_price_range")) {
      unitPriceRange(line.unit_price_range, `quote.lines.${index}.unit_price_range`, get(line, "kind") !== "adjustment");
    }
  });

  const validated = validate_lines_and_subtotal({ ...quote });
  const subtotal = bandRange(get(quote, "subtotal"), "subtotal");
  const calculatedSubtotal = bandRange(get(validated, "subtotal"), "calculated subtotal");
  if (BANDS.some((band) => !subtotal[band].eq(calculatedSubtotal[band]))) throw new QuoteError("subtotal must match line amounts");
  for (const field of ["labor_subtotal", "parts_subtotal", "materials_subtotal", "adjustments_subtotal"]) {
    if (!has(quote, field)) continue;
    const provided = quote[field];
    if (!isDict(provided) || !hasExactBands(provided)) throw new QuoteError(`${field} must contain all bands`);
    for (const band of BANDS) {
      if (typeof provided[band] === "boolean") throw new QuoteError(`${field} contains invalid values`);
      const value = tryDec(provided[band]);
      if (value === null) throw new QuoteError(`${field} contains invalid values`);
      if (!value.isFinite() || !value.eq(Dec.fromPy(validated[field][band]))) throw new QuoteError(`${field} must match categorized line amounts`);
    }
  }
  const tax = bandRange(get(quote, "tax"), "tax");
  const total = bandRange(get(quote, "total"), "total");
  for (const band of BANDS) {
    if (!subtotal[band].add(tax[band]).eq(total[band])) throw new QuoteError(`total.${band} must equal subtotal plus tax`);
  }
  const finalAmount = quote.final_amount;
  if (finalAmount !== null) {
    const amount = number(finalAmount);
    if (!amount.eq(total[quote.selected_band as keyof DecRange]) && !nonempty(get(quote, "override_reason"))) {
      const nested = isDict(confirmation) ? get(confirmation, "override_reason") : null;
      if (!nonempty(nested)) throw new QuoteError("a changed final_amount requires override_reason");
    }
  }

  const saved = deepcopy({ ...quote });
  saved.inputs = deepcopy({ ...inputs });
  const subtotals: Obj = {};
  for (const [key, value] of Object.entries(saved)) if (key.endsWith("_subtotal")) subtotals[key] = deepcopy(value);
  subtotals.subtotal = deepcopy(quote.subtotal);
  saved.subtotals = subtotals;
  await store.transaction(async () => {
    await store.save_quote(saved);
  });
  return deepcopy(saved);
}

export async function load_snapshot(store: QuoteStore, quote_id: unknown, quote_version: unknown = null): Promise<Obj> {
  if (quote_version !== null && (!isInt(quote_version) || quote_version < 1)) throw new QuoteError("quote_version must be a positive integer");
  return deepcopy(await store.get_quote(quote_id, quote_version));
}

function bandRange(value: unknown, path: string): DecRange {
  try {
    return range_value(value);
  } catch (error) {
    if (error instanceof QuoteError || error instanceof TypeError) {
      throw new QuoteError(`${path} must contain finite low, typical, and high values`);
    }
    throw error;
  }
}

function unitPriceRange(value: unknown, path: string, ordered: boolean): DecRange {
  if (!isDict(value) || !hasExactBands(value)) throw new QuoteError(`${path} must contain low, typical, and high`);
  const parsed = { low: number(value.low), typical: number(value.typical), high: number(value.high) };
  if (ordered && !(parsed.low.le(parsed.typical) && parsed.typical.le(parsed.high))) throw new QuoteError(`${path} bands must be ordered`);
  return parsed;
}

function validateFiniteNumbers(value: unknown, path: string): void {
  if (typeof value === "boolean" || value === null || typeof value === "string") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new QuoteError(`${path} contains a non-finite number`);
    return;
  }
  if (isDict(value)) {
    for (const [key, entry] of Object.entries(value)) validateFiniteNumbers(entry, `${path}.${key}`);
  } else if (isList(value)) {
    value.forEach((entry, index) => validateFiniteNumbers(entry, `${path}.${index}`));
  }
}

function timestampsConsistent(left: string, right: string): boolean {
  let a: { aware: boolean; micros: number };
  let b: { aware: boolean; micros: number };
  try {
    a = datetimeFromIso(left.replace("Z", "+00:00"));
    b = datetimeFromIso(right.replace("Z", "+00:00"));
  } catch (error) {
    if (error instanceof PyError) return false;
    throw error;
  }
  if (!a.aware || !b.aware) return false;
  return Math.abs(a.micros - b.micros) / 1e6 <= 1;
}

function nonempty(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}
