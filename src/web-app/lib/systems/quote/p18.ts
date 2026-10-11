// P18: 顧客に伝えた金額と条件を、保存済みの見積版に対して追記で記録する。
import { BANDS, isBand, number, _json_number } from "./common";
import { deepcopy, Dec, get, has, isDict, isInt, isUuid, nowIso, pyEq, QuoteError, uuid4, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

const ALLOWED = ["selected_band", "customer_ref", "vehicle_ref", "operator", "condition_note", "communicated_amount"];

// Python の re（Unicode の \d・\w・\b）と同じ判定にする。
const W = String.raw`[\p{L}\p{N}_]`;
const D = String.raw`\p{Nd}`;
const CONTACT_PATTERN = new RegExp(
  `(?:0${D}[${D.slice(0)} -]{8,}${D})|(?:(?<!${W})(?=${W})${D}{3}[ -]${D}{3}[ -]${D}{4}(?<=${W})(?!${W}))|[\\p{L}\\p{N}_.+-]+@[\\p{L}\\p{N}_.-]+\\.[A-Za-z]{2,}`,
  "u",
);

export async function record_communication(store: QuoteStore, quote: unknown, data: unknown): Promise<Obj> {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (!isDict(data)) throw new QuoteError("data must be an object");
  const quoteId = get(quote, "quote_id");
  const quoteVersion = get(quote, "quote_version");
  if (typeof quoteId !== "string" || !quoteId.trim()) throw new QuoteError("quote_id is required");
  if (!isInt(quoteVersion) || quoteVersion < 1) throw new QuoteError("quote_version must be a positive integer");
  const persisted = await store.get_quote(quoteId, quoteVersion);
  if (get(persisted, "quote_id") !== quoteId || get(persisted, "quote_version") !== quoteVersion) {
    throw new QuoteError("quote does not match persisted quote version");
  }
  if (!pyEq({ ...quote }, persisted)) throw new QuoteError("quote differs from persisted quote version");
  if (get(persisted, "status") === "blocked") throw new QuoteError("blocked quotes cannot be communicated");

  const clean: Obj = {};
  for (const key of ALLOWED) if (has(data, key)) clean[key] = deepcopy(data[key]);
  for (const key of ["selected_band", "customer_ref", "vehicle_ref", "operator", "condition_note"]) {
    if (!has(clean, key)) throw new QuoteError(`${key} is required`);
  }
  const band = clean.selected_band;
  if (!isBand(band)) throw new QuoteError("selected_band must be low, typical, or high");
  requireAnonymousRef(clean.customer_ref, "C-", "customer_ref");
  requireAnonymousRef(clean.vehicle_ref, "V-", "vehicle_ref");
  requireAnonymousRef(clean.operator, "operator-", "operator");
  if (typeof clean.condition_note !== "string" || !clean.condition_note.trim()) throw new QuoteError("condition_note is required");
  if (CONTACT_PATTERN.test(clean.condition_note)) {
    throw new QuoteError("condition_note must not contain phone numbers or email addresses");
  }
  const confirmation = get(persisted, "confirmation");
  let amount: number;
  if (get(persisted, "status") === "confirmed") {
    if (band !== get(persisted, "selected_band")) throw new QuoteError("communication band must match the confirmed quote");
    if (!isDict(confirmation) || get(confirmation, "final_amount") === null) throw new QuoteError("confirmed final amount is required");
    amount = jsonNumber(number(confirmation.final_amount));
    if (has(clean, "communicated_amount") && !number(clean.communicated_amount).eq(number(amount))) {
      throw new QuoteError("a different communicated amount requires a new quote version");
    }
  } else if (has(clean, "communicated_amount")) {
    amount = jsonNumber(number(clean.communicated_amount));
  } else {
    const total = get(persisted, "total");
    if (!isDict(total) || !has(total, band) || total[band] === null) throw new QuoteError("selected quote amount is unknown");
    amount = jsonNumber(number(total[band]));
  }
  const record = {
    communication_id: uuid4(),
    quote_id: quoteId,
    quote_version: quoteVersion,
    customer_ref: clean.customer_ref,
    vehicle_ref: clean.vehicle_ref,
    selected_band: band,
    communicated_amount: amount,
    condition_note: clean.condition_note,
    timestamp: nowIso(),
    operator: clean.operator,
  };
  return store.append_communication(record);
}

export function requireAnonymousRef(value: unknown, prefix: string, field: string, message?: string): void {
  if (typeof value !== "string" || !value.startsWith(prefix) || value.length <= prefix.length) {
    throw new QuoteError(message ?? `${field} must be an anonymous reference beginning with ${prefix}`);
  }
  const suffix = value.slice(prefix.length);
  if (prefix === "C-" || prefix === "V-") {
    const sequence = /^(?:DEMO-)?[0-9]{1,6}$/.test(suffix);
    if (!sequence && !isUuid(suffix)) throw new QuoteError(`${field} must be an opaque UUID or short anonymous sequence`);
  }
  if (![...suffix].every((char) => /^[A-Za-z0-9_-]$/.test(char))) throw new QuoteError(`${field} must be an anonymous reference`);
}

function jsonNumber(value: Dec): number {
  if (value.isIntegral()) return Number(value.toBigInt());
  const result = value.toNumber();
  if (!Number.isFinite(result)) throw new QuoteError("amount must remain finite as a stored number");
  return result;
}

export { BANDS };
