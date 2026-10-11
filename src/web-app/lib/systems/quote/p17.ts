// P17: 入力途中の見積を下書き保存し、価格の扱いを明示して再開する。
import { deepcopy, get, has, isDict, isInt, isList, nowIsoSecondsZ, pyEq, pyRepr, pyStr, QuoteError, truthy, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

const ITEM_WORK_FIELDS = ["item_id", "quantity_range", "quantity_unit", "unit"];

export async function save_draft(store: QuoteStore, draft_id: unknown, inputs: unknown, step: unknown = 0): Promise<Obj> {
  if (typeof draft_id !== "string" || !draft_id.trim()) throw new QuoteError("draft_id is required");
  if (!isDict(inputs)) throw new QuoteError("inputs must be an object");
  if (!isInt(step) || step < 0) throw new QuoteError("step must be a non-negative integer");
  const savedInputs = deepcopy({ ...inputs });
  const inputRefs: Obj = {};
  for (const key of ["job_ref", "customer_ref", "vehicle_ref"]) {
    if (has(savedInputs, key)) inputRefs[key] = deepcopy(savedInputs[key]);
  }
  const draft = {
    draft_id,
    inputs: savedInputs,
    input_refs: inputRefs,
    step,
    price_snapshots: priceSnapshot(savedInputs),
    paused_at: nowIsoSecondsZ(),
    resume_mode: null,
  };
  return store.save_draft(draft);
}

export async function resume_draft(store: QuoteStore, draft_id: unknown, resume_mode: unknown, current_inputs: unknown = null): Promise<Obj> {
  if (resume_mode !== "current" && resume_mode !== "snapshot") throw new QuoteError("resume_mode must be explicitly current or snapshot");
  const draft = await store.get_draft(draft_id);
  const savedInputs = get(draft, "inputs");
  if (!isDict(savedInputs)) throw new QuoteError("saved draft inputs are invalid");
  const resumed = deepcopy({ ...savedInputs });
  let notice: string;
  if (resume_mode === "current") {
    if (!isDict(current_inputs)) throw new QuoteError("current_inputs are required for current price mode");
    updateCurrentPrices(resumed, current_inputs);
    notice = "現在価格に更新しました。";
  } else {
    const pausedAt = get(draft, "paused_at");
    if (!truthy(pausedAt)) throw new QuoteError("saved price snapshot date is missing");
    notice = `当時価格のまま再開しています（保存日: ${pyStr(pausedAt)}）。`;
  }
  draft.resume_mode = resume_mode;
  await store.save_draft(draft);
  return { draft_id, inputs: resumed, step: get(draft, "step", 0), resume_mode, price_notice: notice };
}

export async function list_drafts(store: QuoteStore): Promise<Obj[]> {
  return deepcopy(await store.list_drafts());
}

function updateCurrentPrices(saved: Obj, current: Obj): void {
  const currentRate = get(current, "labor_rate");
  const currentItems = get(current, "items");
  const savedItems = get(saved, "items");
  if (!isDict(currentRate)) throw new QuoteError("current labor_rate is unavailable");
  if (!isList(savedItems) || !isList(currentItems)) throw new QuoteError("current item prices are unavailable");
  const savedById = itemsById(savedItems, "saved");
  const currentById = itemsById(currentItems, "current");
  const savedKeys = [...savedById.keys()];
  const currentKeys = [...currentById.keys()];
  if (savedKeys.length !== currentKeys.length || savedKeys.some((key) => !currentById.has(key))) {
    const missing = savedKeys.filter((key) => !currentById.has(key)).sort();
    const extra = currentKeys.filter((key) => !savedById.has(key)).sort();
    throw new QuoteError(`current item price mapping mismatch (missing=${pyRepr(missing)}, extra=${pyRepr(extra)})`);
  }
  saved.labor_rate = deepcopy({ ...currentRate });
  for (const [itemId, oldItem] of savedById) {
    const newItem = currentById.get(itemId)!;
    if (!pyEq(get(newItem, "unit"), get(oldItem, "unit"))) throw new QuoteError(`current unit mismatch for item_id: ${itemId}`);
    if (!has(newItem, "unit_price") || newItem.unit_price === null) throw new QuoteError(`current price is unavailable for item_id: ${itemId}`);
    for (const [field, value] of Object.entries(newItem)) {
      if (!ITEM_WORK_FIELDS.includes(field)) oldItem[field] = deepcopy(value);
    }
  }
}

function itemsById(items: unknown[], label: string): Map<string, Obj> {
  const result = new Map<string, Obj>();
  for (const entry of items) {
    if (!isDict(entry)) throw new QuoteError(`${label} items must be objects`);
    const itemId = get(entry, "item_id");
    if (typeof itemId !== "string" || !itemId.trim() || result.has(itemId)) {
      throw new QuoteError(`${label} items require unique item_id values`);
    }
    result.set(itemId, entry);
  }
  return result;
}

function priceSnapshot(inputs: Obj): Obj {
  const items = get(inputs, "items", []);
  return {
    labor_rate: deepcopy(get(inputs, "labor_rate")),
    items: isList(items)
      ? items
          .filter((entry) => isDict(entry))
          .map((entry) => Object.fromEntries(Object.entries(entry).filter(([key]) => !ITEM_WORK_FIELDS.includes(key)).map(([key, value]) => [key, deepcopy(value)])))
      : [],
  };
}
