// P19: 登録済み・人が承認したプリセットを検証して読み込む（古い価格は警告する）。
import { number } from "./common";
import { dateFromIso, dateIso, deepcopy, get, has, isDict, isInt, isList, PyError, pyEq, pyIn, pyStr, QuoteError, today, truthy, type Obj, type PyDate } from "./pyrt";

export function load_preset(presets: unknown, preset_id: unknown, as_of: unknown = null): Obj {
  if (typeof preset_id !== "string" || !preset_id.trim()) throw new QuoteError("preset_id is required");
  if (!isList(presets)) throw new QuoteError("presets must be a sequence");
  const matches = presets.filter((preset) => isDict(preset) && pyEq(get(preset, "preset_id"), preset_id));
  if (matches.length !== 1) throw new QuoteError("preset_id must identify exactly one registered preset");

  const preset = deepcopy({ ...matches[0] });
  for (const field of ["job_ref", "approved_by", "version", "inputs", "required_conditions", "default_quantity", "rate_ref", "item_refs"]) {
    if (!has(preset, field)) throw new QuoteError(`preset.${field} is required`);
  }
  number(preset.default_quantity);
  requireText(preset.rate_ref, "preset.rate_ref");
  requireText(preset.job_ref, "preset.job_ref");
  requireText(preset.approved_by, "preset.approved_by");
  if (!isInt(preset.version) || preset.version < 1) throw new QuoteError("preset.version must be a positive integer");
  if (!isList(preset.item_refs) || !preset.item_refs.length) throw new QuoteError("preset.item_refs must be a non-empty list");
  if (preset.item_refs.some((ref: unknown) => typeof ref !== "string" || !ref.trim())) throw new QuoteError("preset.item_refs must contain nonempty IDs");
  if (!isList(preset.required_conditions)) throw new QuoteError("preset.required_conditions must be a list");

  let inputs = preset.inputs;
  if (!isDict(inputs)) throw new QuoteError("preset.inputs must be an object");
  inputs = deepcopy({ ...inputs });
  if (!pyEq(get(inputs, "job_ref"), preset.job_ref)) throw new QuoteError("preset job_ref does not match registered inputs");
  const rate = get(inputs, "labor_rate");
  if (!isDict(rate)) throw new QuoteError("preset inputs.labor_rate must be an object");
  if (get(preset, "rate_ref") !== null && !pyEq(get(rate, "rate_ref"), preset.rate_ref)) {
    throw new QuoteError("preset rate_ref does not match registered labor_rate");
  }
  if (!has(rate, "yen_per_person_hour") || !isList(get(rate, "basis")) || !rate.basis.length) {
    throw new QuoteError("labor_rate requires yen_per_person_hour and basis evidence");
  }
  number(rate.yen_per_person_hour);
  if (!has(rate, "effective_from")) throw new QuoteError("labor_rate.effective_from is required");
  const effectiveFrom = isoDate(rate.effective_from, "labor_rate.effective_from");

  const items = get(inputs, "items");
  if (!isList(items) || !items.length) throw new QuoteError("preset inputs.items must be a non-empty list");
  const itemById = new Map<string, Obj>();
  for (const entry of items) {
    if (isDict(entry) && !has(entry, "quantity_range")) {
      entry.quantity_range = { low: preset.default_quantity, typical: preset.default_quantity, high: preset.default_quantity };
      entry.quantity_unit = get(entry, "unit");
    }
  }
  for (const entry of items) {
    if (!isDict(entry)) throw new QuoteError("preset items must be objects");
    const itemId = get(entry, "item_id");
    requireText(itemId, "item.item_id");
    if (itemById.has(itemId)) throw new QuoteError("preset item_id values must be unique");
    itemById.set(itemId, entry);
    for (const field of ["name", "category", "unit", "unit_price", "price_type", "source", "updated_at"]) {
      if (!has(entry, field) || entry[field] === null) throw new QuoteError(`item.${field} is required`);
    }
    isoDate(entry.updated_at, `item ${itemId}.updated_at`);
    number(entry.unit_price);
    if (!hasText(entry.source)) throw new QuoteError(`item ${itemId}.source is required`);
    for (const field of ["name", "category", "unit"]) {
      if (!hasText(entry[field])) throw new QuoteError(`item ${itemId}.${field} is required`);
    }
    if (!pyIn(entry.price_type, ["仕入", "販売"])) throw new QuoteError(`item ${itemId}.price_type is invalid`);
    if (entry.price_type === "仕入") {
      const markup = get(entry, "markup");
      if (!isDict(markup) || !hasText(get(markup, "approved_by"))) throw new QuoteError(`item ${itemId} purchase markup requires approved_by`);
    }
  }
  const refs = preset.item_refs as string[];
  if (new Set(refs).size !== refs.length || new Set(refs).size !== itemById.size || refs.some((ref) => !itemById.has(ref))) {
    throw new QuoteError("preset.item_refs do not match registered items");
  }

  const referenceDate = as_of !== null ? isoDate(as_of, "as_of") : today();
  if (referenceDate.ordinal < effectiveFrom.ordinal) throw new QuoteError("preset labor rate is not yet effective as of requested date");

  const warnings: string[] = [];
  let refreshRequired = false;
  for (const [itemId, entry] of itemById) {
    if (isoDate(entry.updated_at, `item ${itemId}.updated_at`).ordinal < referenceDate.ordinal) {
      warnings.push(`価格が更新日より古い可能性があります: ${itemId} (${pyStr(entry.updated_at)})。人が更新を確認してください`);
      refreshRequired = true;
    }
  }
  for (const condition of preset.required_conditions as unknown[]) {
    if (!conditionResolved(condition)) {
      // Python の優先順位どおり: (label or condition or "条件") if dict else str(condition)
      const label = isDict(condition)
        ? firstTruthy(get(condition, "label"), get(condition, "condition"), "条件")
        : pyStr(condition);
      warnings.push(`未確認条件: ${pyStr(label)}。人が確認してください`);
    }
  }
  return {
    preset_id,
    default_quantity: preset.default_quantity,
    rate_ref: preset.rate_ref,
    item_refs: deepcopy(preset.item_refs),
    inputs,
    warnings,
    required_conditions: deepcopy(preset.required_conditions),
    version: preset.version,
    refresh_required: refreshRequired,
  };
}

function firstTruthy(...values: unknown[]): unknown {
  for (const value of values.slice(0, -1)) if (truthy(value)) return value;
  return values[values.length - 1];
}

function isoDate(value: unknown, field: string): PyDate {
  if (typeof value !== "string") throw new QuoteError(`${field} must be an ISO date`);
  let parsed: PyDate;
  try {
    parsed = dateFromIso(value);
  } catch (error) {
    if (error instanceof PyError) throw new QuoteError(`${field} must be an ISO date`);
    throw error;
  }
  if (dateIso(parsed) !== value) throw new QuoteError(`${field} must be an ISO date`);
  return parsed;
}

function requireText(value: unknown, field: string): void {
  if (!hasText(value)) throw new QuoteError(`${field} is required`);
}

function hasText(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

function conditionResolved(condition: unknown): boolean {
  return isDict(condition) && pyIn(get(condition, "status"), ["satisfied", "confirmed", "resolved"]) && get(condition, "value") !== null;
}
