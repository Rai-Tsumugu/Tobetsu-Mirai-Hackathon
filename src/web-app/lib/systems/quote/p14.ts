// P14: 人が明示的に選んだ帯（と理由付きの手動額）で見積を確定する。
import { BANDS, isBand, number, range_value, _json_number } from "./common";
import { deepcopy, get, isDict, nowIso, QuoteError, truthy, type Obj } from "./pyrt";

export function confirm_quote(
  quote: unknown,
  selected_band: unknown,
  confirmed_by: unknown,
  final_amount: unknown = null,
  override_reason: unknown = null,
): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (get(quote, "status") === "confirmed" || get(quote, "confirmation") !== null) throw new QuoteError("quote is already confirmed");
  const status = get(quote, "status");
  if (typeof status === "string" && (status === "blocked" || status === "unknown")) {
    throw new QuoteError("blocked or unknown quotes cannot be confirmed");
  }
  if (truthy(get(quote, "unknowns"))) throw new QuoteError("quote unknowns must be resolved before confirmation");
  if (!isBand(selected_band)) throw new QuoteError("selected_band must be explicitly selected from low, typical, or high");
  if (typeof confirmed_by !== "string" || !confirmed_by.trim()) throw new QuoteError("confirmed_by is required");

  const proposedRange = range_value(get(quote, "total"));
  const proposedAmount = proposedRange[selected_band];
  const amount = final_amount === null ? proposedAmount : number(final_amount);
  const changed = !amount.eq(proposedAmount);
  const outside = !(proposedRange.low.le(amount) && amount.le(proposedRange.high));
  const reason = typeof override_reason === "string" ? override_reason.trim() : "";
  if ((changed || outside) && !reason) throw new QuoteError("override_reason is required for a manually changed amount");

  const result = deepcopy({ ...quote });
  result.selected_band = selected_band;
  result.confirmed_by = confirmed_by.trim();
  result.override_reason = reason || null;
  result.status = "confirmed";
  result.final_amount = _json_number(amount);
  result.confirmed_at = nowIso();
  result.confirmation = {
    proposed_range: Object.fromEntries(BANDS.map((band) => [band, _json_number(proposedRange[band])])),
    proposed_amount: _json_number(proposedAmount),
    final_amount: _json_number(amount),
    selected_band,
    confirmed_by: confirmed_by.trim(),
    override_reason: reason || null,
    confirmed_at: result.confirmed_at,
  };
  return result;
}
