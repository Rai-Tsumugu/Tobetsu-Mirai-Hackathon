// P28: 伝達記録（追記のみ）を見積版ごとに検証して返す。
import { isBand, number } from "./common";
import { record_communication } from "./p18";
import { deepcopy, get, isDict, isInt, isUuid, KeyErr, PyError, QuoteError, ValueErr, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

export async function communication_ledger(store: QuoteStore, quote_id: unknown): Promise<Obj[]> {
  if (typeof quote_id !== "string" || !quote_id.trim()) throw new QuoteError("quote_id is required");
  const records = await store.list_communications(quote_id);
  const result: Obj[] = [];
  for (const record of records) {
    if (!isDict(record) || get(record, "quote_id") !== quote_id) throw new QuoteError("communication quote_id does not match ledger");
    const version = get(record, "quote_version");
    if (!isInt(version) || version < 1) throw new QuoteError("communication quote_version must be a positive integer");
    let quote: Obj;
    try {
      quote = await store.get_quote(quote_id, version);
    } catch (error) {
      if (error instanceof ValueErr || error instanceof KeyErr) throw new QuoteError("communication references a missing quote version");
      throw error;
    }
    if (get(quote, "quote_id") !== quote_id || get(quote, "quote_version") !== version) {
      throw new QuoteError("communication quote version reference is invalid");
    }
    if (!isBand(get(record, "selected_band"))) throw new QuoteError("communication selected_band is invalid");
    const amount = get(record, "communicated_amount");
    if (typeof amount === "boolean") throw new QuoteError("communicated_amount must be finite");
    let parsed;
    try {
      parsed = number(amount);
    } catch (error) {
      if (error instanceof PyError || error instanceof TypeError) throw new QuoteError("communicated_amount must be finite");
      throw error;
    }
    if (!parsed.isFinite() || !Number.isFinite(parsed.toNumber())) throw new QuoteError("communicated_amount must be finite");
    validateRef(get(record, "customer_ref"), "C-", "customer_ref");
    validateRef(get(record, "vehicle_ref"), "V-", "vehicle_ref");
    validateRef(get(record, "operator"), "operator-", "operator");
    result.push(deepcopy(record));
  }
  return result;
}

export async function append_communication(store: QuoteStore, quote: unknown, data: unknown): Promise<Obj> {
  return deepcopy(await record_communication(store, deepcopy(quote), deepcopy(data)));
}

export async function query_communications(
  store: QuoteStore,
  quote_id: unknown,
  quote_version: unknown = null,
  customer_ref: unknown = null,
  vehicle_ref: unknown = null,
): Promise<Obj[]> {
  let records = await communication_ledger(store, quote_id);
  if (quote_version !== null) {
    if (!isInt(quote_version) || quote_version < 1) throw new QuoteError("quote_version must be a positive integer");
    records = records.filter((row) => row.quote_version === quote_version);
  }
  if (customer_ref !== null) records = records.filter((row) => row.customer_ref === customer_ref);
  if (vehicle_ref !== null) records = records.filter((row) => row.vehicle_ref === vehicle_ref);
  return deepcopy(records);
}

function validateRef(value: unknown, prefix: string, field: string): void {
  if (typeof value !== "string" || !value.startsWith(prefix) || value.length <= prefix.length) {
    throw new QuoteError(`${field} must be an anonymous reference`);
  }
  const suffix = value.slice(prefix.length);
  if (prefix === "C-" || prefix === "V-") {
    const sequence = /^(?:DEMO-)?[0-9]{1,6}$/.test(suffix);
    if (!sequence && !isUuid(suffix)) throw new QuoteError(`${field} must be an opaque UUID or short anonymous sequence`);
  }
  if (![...suffix].every((char) => /^[A-Za-z0-9_-]$/.test(char))) throw new QuoteError(`${field} must be an anonymous reference`);
}
