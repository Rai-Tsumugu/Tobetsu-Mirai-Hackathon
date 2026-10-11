// P24: 品目ごとの仕入・販売の価格履歴を、単位をまたがずに並べる。
import { money_range } from "./common";
import { selling_price } from "./p04";
import { dateFromIso, deepcopy, get, has, isDict, isList, PyError, pyStr, QuoteError, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

export function price_comparison(history: unknown, item_id: unknown): Obj {
  if (typeof item_id !== "string" || !item_id.trim()) throw new QuoteError("item_id is required");
  let rows: unknown[];
  if (isList(history)) rows = [...history];
  else if (isDict(history)) rows = Object.keys(history);
  else if (typeof history === "string") rows = [...history];
  else throw new QuoteError("history must be iterable");

  const prices: Obj[] = [];
  const units = new Set<string>();
  rows.forEach((raw, index) => {
    if (!isDict(raw)) throw new QuoteError(`history.${index} must be an object`);
    if (pyStr(get(raw, "item_id", "")) !== item_id) return;
    const priceType = get(raw, "price_type");
    const unit = get(raw, "unit");
    if (priceType !== "仕入" && priceType !== "販売") throw new QuoteError(`history.${index}.price_type must be 仕入 or 販売`);
    if (typeof unit !== "string" || !unit.trim()) throw new QuoteError(`history.${index}.unit is required`);
    for (const field of ["source", "updated_at"]) {
      const value = get(raw, field);
      if (typeof value !== "string" || !value.trim()) throw new QuoteError(`history.${index}.${field} is required`);
    }
    validateDate(raw.updated_at, index);
    let proposal: unknown = null;
    let confirmationStatus = "未確認";
    try {
      proposal = selling_price(raw);
      confirmationStatus = priceType === "販売" ? "確認済み" : "承認済み掛率";
    } catch (error) {
      if (!(error instanceof QuoteError) || priceType === "販売") throw error;
    }
    prices.push({
      price_type: priceType,
      unit,
      unit_price: deepcopy(get(raw, "unit_price")),
      source: raw.source,
      updated_at: raw.updated_at,
      selling_price_proposal: deepcopy(proposal),
      confirmation_status: confirmationStatus,
    });
    units.add(unit.split(/\s+/).join(""));
  });
  if (units.size > 1) throw new QuoteError("unit mismatch: do not compare prices across different units");
  return { item_id, prices, unit_mismatch: false };
}

export async function save_price_history(store: QuoteStore, entry: unknown): Promise<void> {
  if (!isDict(entry)) throw new QuoteError("item must be an object");
  try {
    selling_price(entry);
  } catch (error) {
    if (!(error instanceof QuoteError) || get(entry, "price_type") !== "仕入") throw error;
    money_range(get(entry, "unit_price"));
  }
  for (const field of ["item_id", "unit", "source", "updated_at"]) {
    const value = get(entry, field);
    if (typeof value !== "string" || !value.trim()) throw new QuoteError(`${field} is required`);
  }
  validateDate(entry.updated_at, 0);
  await store.save_price(deepcopy({ ...entry }));
}

export async function compare_item_prices(store: QuoteStore, item_id: unknown): Promise<Obj> {
  if (typeof item_id !== "string" || !item_id.trim()) throw new QuoteError("item_id is required");
  return price_comparison(await store.list_prices(item_id), item_id);
}

function validateDate(value: string, index: number): void {
  try {
    dateFromIso(value);
  } catch (error) {
    if (error instanceof PyError) throw new QuoteError(`history.${index}.updated_at must be an ISO date`);
    throw error;
  }
}

export { has };
