// P30: 確定した見積を帳票用のデータにする（再計算しない）。
import { BANDS, isBand, number, range_value, _json_number, type DecRange } from "./common";
import { deepcopy, get, has, isDict, isInt, isList, pyEq, QuoteError, truthy, type Obj } from "./pyrt";

export function document_payload(quote: unknown): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (get(quote, "status") !== "confirmed") throw new QuoteError("only confirmed quotes can be rendered");
  if (truthy(get(quote, "unknowns"))) throw new QuoteError("quotes with unresolved unknowns cannot be rendered");
  const quoteId = get(quote, "quote_id");
  const version = get(quote, "quote_version");
  if (typeof quoteId !== "string" || !quoteId.trim()) throw new QuoteError("quote_id is required");
  if (!isInt(version) || version < 1) throw new QuoteError("quote_version must be a positive integer");
  const selectedBand = get(quote, "selected_band");
  const confirmedBy = get(quote, "confirmed_by");
  if (!isBand(selectedBand)) throw new QuoteError("selected_band must be low, typical, or high");
  if (typeof confirmedBy !== "string" || !confirmedBy.trim()) throw new QuoteError("confirmed_by is required");
  const confirmation = get(quote, "confirmation");
  if (!isDict(confirmation)) throw new QuoteError("matching confirmation record is required");
  if (!pyEq(get(confirmation, "selected_band"), selectedBand)) throw new QuoteError("confirmation selected_band must match quote");
  if (!pyEq(get(confirmation, "confirmed_by"), confirmedBy)) throw new QuoteError("confirmation confirmed_by must match quote");

  let subtotal: DecRange;
  let tax: DecRange;
  let total: DecRange;
  try {
    subtotal = range_value(get(quote, "subtotal"));
    tax = range_value(get(quote, "tax"));
    total = range_value(get(quote, "total"));
  } catch (error) {
    if (error instanceof QuoteError || error instanceof TypeError) {
      throw new QuoteError("subtotal, tax, and total must be complete ordered ranges");
    }
    throw error;
  }
  for (const band of BANDS) {
    if (!subtotal[band].add(tax[band]).eq(total[band])) throw new QuoteError(`subtotal plus tax must match total for ${band}`);
  }
  for (const key of ["lines", "reasons", "conditions"]) {
    if (!isList(get(quote, key))) throw new QuoteError(`quote.${key} must be a list`);
  }
  let sources: unknown;
  if (has(quote, "sources")) {
    sources = quote.sources;
    if (!isList(sources) && !isDict(sources)) throw new QuoteError("quote.sources must be a list or object");
  } else {
    sources = (quote.lines as unknown[])
      .filter((line) => isDict(line) && ["source_system", "source_ref", "snapshot"].some((key) => has(line, key)))
      .map((line) => {
        const entry: Obj = {};
        for (const key of ["source_system", "source_ref", "snapshot"]) if (has(line as Obj, key)) entry[key] = deepcopy((line as Obj)[key]);
        return entry;
      });
  }

  const proposedAmount = number(get(confirmation, "proposed_amount", total[selectedBand].toString()));
  const nestedFinal = get(confirmation, "final_amount");
  const topFinal = get(quote, "final_amount");
  if (nestedFinal === null && topFinal === null) throw new QuoteError("confirmed final_amount is required");
  const finalAmount = number(nestedFinal !== null ? nestedFinal : topFinal);
  if (nestedFinal !== null && topFinal !== null && !number(topFinal).eq(finalAmount)) throw new QuoteError("quote final_amount must match confirmation");
  if (!number(total[selectedBand]).eq(proposedAmount)) throw new QuoteError("confirmation proposed_amount must match selected total");

  const overrideReason = has(confirmation, "override_reason") ? confirmation.override_reason : get(quote, "override_reason");
  if (overrideReason !== null && (typeof overrideReason !== "string" || !overrideReason.trim())) {
    throw new QuoteError("override_reason must be a non-empty string when provided");
  }
  const amountAdjustment = _json_number(finalAmount.sub(proposedAmount));
  if (!finalAmount.eq(proposedAmount) && !truthy(overrideReason)) throw new QuoteError("an overridden final_amount requires override_reason");
  if (get(quote, "override_reason") !== null && get(confirmation, "override_reason") !== null && !pyEq(quote.override_reason, confirmation.override_reason)) {
    throw new QuoteError("quote and confirmation override_reason must match");
  }
  const confirmedAt = has(quote, "confirmed_at") ? quote.confirmed_at : get(confirmation, "confirmed_at");
  if (typeof confirmedAt !== "string" || !confirmedAt.trim()) throw new QuoteError("confirmed_at is required");
  if (truthy(get(quote, "confirmed_at")) && truthy(get(confirmation, "confirmed_at")) && !pyEq(quote.confirmed_at, confirmation.confirmed_at)) {
    throw new QuoteError("quote and confirmation confirmed_at must match");
  }
  return {
    quote_id: quoteId,
    quote_version: version,
    lines: deepcopy(quote.lines),
    subtotal: deepcopy(quote.subtotal),
    tax: deepcopy(quote.tax),
    total: deepcopy(quote.total),
    selected_band: selectedBand,
    selected_subtotal: _json_number(subtotal[selectedBand]),
    selected_tax: _json_number(tax[selectedBand]),
    selected_total: _json_number(total[selectedBand]),
    reasons: deepcopy(quote.reasons),
    conditions: deepcopy(quote.conditions),
    confirmed_by: confirmedBy,
    confirmed_at: confirmedAt,
    override_reason: deepcopy(overrideReason),
    sources: deepcopy(sources),
    final_amount: _json_number(finalAmount),
    proposed_amount: _json_number(proposedAmount),
    amount_adjustment: amountAdjustment,
    tax_allocation_note: "確定額の税配分は未確認。帳票側で税内訳を再計算しない。これは見積データであり請求書ではない。",
  };
}
