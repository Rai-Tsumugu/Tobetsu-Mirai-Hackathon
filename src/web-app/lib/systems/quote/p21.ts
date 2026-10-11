// P21: 過去の見積版を参照用として検索し、再提示は今回の条件で再計算する。
import { revise_quote, type Calculate } from "./p15";
import { deepcopy, get, isDict, isList, item, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

const HISTORY_NOTICE = "過去見積りの金額です。現在額として使用せず、今回の条件で再計算してください。";

export async function search_quotes(
  store: QuoteStore,
  customer_ref: unknown = null,
  vehicle_ref: unknown = null,
  job_ref: unknown = null,
): Promise<Obj[]> {
  const quotes = await store.list_quotes(customer_ref, vehicle_ref, job_ref);
  const results = deepcopy(quotes);
  for (const quote of results) {
    quote.reference_only = true;
    quote.history_notice = HISTORY_NOTICE;
    const snapshot = attr(attr(quote, "metadata", {}), "input_snapshot", {});
    quote.amount_snapshot = deepcopy(get(quote, "total"));
    const fallbackConditions = attr(snapshot, "conditions", []);
    quote.condition_snapshot = deepcopy(get(quote, "conditions", fallbackConditions));
    const rateDates = attr(snapshot, "labor_rate", {});
    const items = attr(snapshot, "items", []);
    if (!isList(items)) throw new TypeError("'items' is not iterable");
    quote.price_dates = {
      labor_rate: attr(rateDates, "effective_from", null),
      items: items.map((entry) => ({ item_id: attr(entry, "item_id", null), updated_at: attr(entry, "updated_at", null) })),
    };
  }
  return results;
}

/** value.get(key, default)（dict でなければ AttributeError 相当の TypeError）。 */
function attr(value: unknown, key: string, fallback: unknown): unknown {
  if (!isDict(value)) {
    if (value === null || value === undefined) throw new TypeError(`'NoneType' object has no attribute 'get'`);
    item(value, key);
  }
  return get(value as Obj, key, fallback);
}

export async function reoffer_quote(
  store: QuoteStore,
  quote_id: unknown,
  quote_version: unknown,
  current_inputs: unknown,
  calculate: Calculate,
): Promise<Obj> {
  return revise_quote(store, quote_id, quote_version, current_inputs, calculate);
}
