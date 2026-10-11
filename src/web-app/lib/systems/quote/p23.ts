// P23: 帯ごとの金額・行の寄与・条件を比べる（読み取りのみ）。
import { BANDS, isBand, tryDec, _json_number } from "./common";
import { deepcopy, Dec, get, has, isDict, isList, QuoteError, type Obj } from "./pyrt";

export function compare_bands(quote: unknown): Obj[] {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  const total = get(quote, "total");
  if (!isDict(total)) throw new QuoteError("quote.total must be an object");
  const lines = get(quote, "lines", []);
  const conditions = get(quote, "conditions", []);
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");
  if (!isList(conditions)) throw new QuoteError("quote.conditions must be a list");

  const typicalTotal = decimalOrNone(get(total, "typical"), "quote.total.typical");
  const comparisons: Obj[] = [];
  for (const band of BANDS) {
    const amount = deepcopy(get(total, band));
    decimalOrNone(amount, `quote.total.${band}`);
    lines.forEach((line, index) => {
      if (!isDict(line)) throw new QuoteError(`quote.lines.${index} must be an object`);
      const amounts = get(line, "amount");
      if (!isDict(amounts)) throw new QuoteError(`quote.lines.${index}.amount must be an object`);
      decimalOrNone(get(amounts, band), `quote.lines.${index}.amount.${band}`);
      decimalOrNone(get(amounts, "typical"), `quote.lines.${index}.amount.typical`);
    });
    const contributions: Obj[] = [];
    const lineIds: unknown[] = [];
    for (const line of lines as Obj[]) {
      const amounts = line.amount as Obj;
      const bandAmount = get(amounts, band);
      const typicalAmount = get(amounts, "typical");
      const bandValue = decimalOrNone(bandAmount, `line.amount.${band}`);
      const typicalValue = decimalOrNone(typicalAmount, "line.amount.typical");
      const lineId = deepcopy(get(line, "line_id"));
      lineIds.push(lineId);
      contributions.push({
        line_id: lineId,
        amount: deepcopy(bandAmount),
        typical_amount: deepcopy(typicalAmount),
        difference_from_typical: bandValue !== null && typicalValue !== null ? _json_number(bandValue.sub(typicalValue)) : null,
        source_ref: deepcopy(get(line, "source_ref")),
      });
    }
    const matched: { ref: unknown; condition: Obj }[] = [];
    conditions.forEach((condition, index) => {
      if (!isDict(condition)) throw new QuoteError(`quote.conditions.${index} must be an object`);
      let specified = get(condition, "bands", get(condition, "band"));
      let applies: boolean;
      if (specified === null) applies = false;
      else {
        if (typeof specified === "string") specified = [specified];
        if (!isList(specified) || specified.some((entry) => !isBand(entry))) throw new QuoteError(`quote.conditions.${index}.bands is invalid`);
        applies = specified.includes(band);
      }
      if (applies) {
        const ref = has(condition, "condition_ref")
          ? condition.condition_ref
          : has(condition, "source_ref")
            ? condition.source_ref
            : get(condition, "id", index);
        matched.push({ ref: deepcopy(ref), condition: deepcopy({ ...condition }) });
      }
    });
    const bandTotal = decimalOrNone(amount, `quote.total.${band}`);
    const delta = bandTotal === null || typicalTotal === null ? null : !bandTotal.eq(typicalTotal);
    comparisons.push({
      band,
      amount,
      condition_refs: matched.map((entry) => entry.ref),
      conditions: matched.map((entry) => entry.condition),
      line_ids: lineIds,
      contributions,
      explanation_status: matched.length || delta === false ? "explained" : "unexplained",
    });
  }
  return comparisons;
}

function decimalOrNone(value: unknown, path: string): Dec | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") throw new QuoteError(`${path} must be a finite non-negative amount or null`);
  const parsed = tryDec(value);
  if (parsed === null || !parsed.isFinite() || parsed.lt(Dec.int(0))) throw new QuoteError(`${path} must be a finite non-negative amount or null`);
  return parsed;
}
