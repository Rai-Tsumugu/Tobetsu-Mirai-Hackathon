// P15: 条件を変えた見積を新しい版として作る（保存は別）。旧版は変えない。
import { deepcopy, get, isDict, isInt, QuoteError, truthy, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

export type Calculate = (inputs: Obj) => unknown;

const RESET_FIELDS = ["selected_band", "confirmed_by", "confirmation", "override_reason"];

export async function revise_quote(
  store: QuoteStore,
  quote_id: unknown,
  from_version: unknown,
  inputs: unknown,
  calculate: Calculate,
): Promise<Obj> {
  if (typeof quote_id !== "string" || !quote_id.trim()) throw new QuoteError("quote_id is required");
  if (!isInt(from_version) || from_version < 1) throw new QuoteError("from_version must be a positive integer");
  if (!isDict(inputs)) throw new QuoteError("inputs must be an object");
  if (typeof calculate !== "function") throw new QuoteError("calculate must be callable");

  const source = await store.get_quote(quote_id, from_version);
  if (get(source, "quote_id") !== quote_id || get(source, "quote_version") !== from_version) {
    throw new QuoteError("source quote does not match requested quote version");
  }
  const changedInputs = deepcopy({ ...inputs });
  const inputQuoteId = get(changedInputs, "quote_id");
  if (inputQuoteId !== null && inputQuoteId !== quote_id) throw new QuoteError("inputs quote_id does not match requested quote");
  changedInputs.quote_id = quote_id;
  const latest = await store.get_quote(quote_id);
  const latestVersion = get(latest, "quote_version");
  if (!isInt(latestVersion) || latestVersion < 1) throw new QuoteError("latest quote has an invalid version");

  changedInputs.quote_version = latestVersion + 1;
  changedInputs.parent_version = from_version;
  const calculated = await calculate(deepcopy(changedInputs));
  if (!isDict(calculated)) throw new QuoteError("calculate must return a quote object");
  if (get(calculated, "quote_id") !== null && get(calculated, "quote_id") !== quote_id) {
    throw new QuoteError("calculated quote_id does not match requested quote");
  }
  const result = deepcopy({ ...calculated });
  Object.assign(result, { quote_id, quote_version: latestVersion + 1, parent_version: from_version });
  result.metadata = deepcopy(truthy(get(result, "metadata")) ? result.metadata : {});
  result.metadata.input_snapshot = deepcopy(changedInputs);
  result.status = get(calculated, "status") === "blocked" ? "blocked" : "proposed";
  for (const field of RESET_FIELDS) result[field] = null;
  return result;
}

export async function save_version(store: QuoteStore, quote: unknown): Promise<Obj> {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  const quoteId = get(quote, "quote_id");
  const quoteVersion = get(quote, "quote_version");
  if (typeof quoteId !== "string" || !quoteId.trim()) throw new QuoteError("quote_id is required");
  if (!isInt(quoteVersion) || quoteVersion < 1) throw new QuoteError("quote_version must be a positive integer");
  return store.save_quote(deepcopy({ ...quote }));
}
