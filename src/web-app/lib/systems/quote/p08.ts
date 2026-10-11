// P08: low/typical/high の帯カードを条件付きで作る。
import { BANDS, isBand, tryDec } from "./common";
import { deepcopy, Dec, get, has, isDict, isList, QuoteError, type Obj } from "./pyrt";

export function band_cards(quote: unknown): Obj[] {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  const total = get(quote, "total");
  if (!isDict(total)) throw new QuoteError("quote.total must be an object");
  const conditions = get(quote, "conditions", []);
  if (!isList(conditions)) throw new QuoteError("quote.conditions must be a list");
  const selectedBand = get(quote, "selected_band");
  if (selectedBand !== null && !isBand(selectedBand)) throw new QuoteError("quote.selected_band is unknown");
  const quoteStatus = get(quote, "status");

  const cards: Obj[] = [];
  for (const band of BANDS) {
    const amount = get(total, band);
    if (amount !== null && (typeof amount === "boolean" || !finiteNonnegative(amount))) {
      throw new QuoteError(`quote.total.${band} must be finite and non-negative`);
    }
    const matching: { ref: unknown; condition: Obj }[] = [];
    conditions.forEach((condition, index) => {
      if (!isDict(condition)) throw new QuoteError(`quote.conditions.${index} must be an object`);
      let specified = get(condition, "bands", get(condition, "band"));
      let applies: boolean;
      if (specified === null) {
        applies = true;
      } else {
        if (typeof specified === "string") specified = [specified];
        if (!isList(specified) || specified.some((entry) => !isBand(entry))) {
          throw new QuoteError(`quote.conditions.${index}.bands is invalid`);
        }
        applies = specified.includes(band);
      }
      if (applies) {
        const ref = has(condition, "condition_ref")
          ? condition.condition_ref
          : has(condition, "source_ref")
            ? condition.source_ref
            : get(condition, "id", index);
        matching.push({ ref: deepcopy(ref), condition: deepcopy({ ...condition }) });
      }
    });
    const blocked = quoteStatus === "blocked";
    cards.push({
      band,
      amount: deepcopy(amount),
      condition_refs: matching.map((entry) => entry.ref),
      conditions: matching.map((entry) => entry.condition),
      selected: selectedBand === band && amount !== null && !blocked,
      status: blocked ? "blocked" : amount === null ? "unconfirmed" : "available",
      label: blocked ? "確定不可" : amount === null ? "未確認" : band,
    });
  }
  return cards;
}

export function apply(quote: unknown, inputs: unknown = null): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (inputs !== null && !isDict(inputs)) throw new QuoteError("inputs must be an object when provided");
  const result = deepcopy(quote);
  if (get(result, "status") === "blocked") result.selected_band = null;
  const selectedBand = inputs !== null ? get(inputs as Obj, "selected_band") : null;
  if (selectedBand !== null) {
    if (!isBand(selectedBand)) throw new QuoteError("inputs.selected_band is unknown");
    const total = get(result, "total");
    if (!isDict(total) || !has(total, selectedBand)) throw new QuoteError("selected band amount is unavailable");
    if (total[selectedBand] === null) throw new QuoteError("selected band amount is unconfirmed");
    if (get(result, "status") === "blocked") throw new QuoteError("blocked quote cannot select a final amount");
    result.selected_band = selectedBand;
  }
  result.band_cards = band_cards(result);
  return result;
}

function finiteNonnegative(value: unknown): boolean {
  const parsed = tryDec(value);
  return parsed !== null && parsed.isFinite() && parsed.ge(Dec.int(0));
}
