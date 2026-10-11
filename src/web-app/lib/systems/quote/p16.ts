// P16: 登録済みプリセットで電話時の概算を出す（確定はしない）。
import { calculate } from "./pipeline";
import { casefold, deepcopy, get, isDict, isList, pyEq, pyIn, pyStr, QuoteError, setdefault, uuid4, type Obj } from "./pyrt";

export function quick_quote(presets: unknown, preset_id: unknown, vehicle_ref: unknown = null): Obj {
  if (!isList(presets)) throw new QuoteError("presets must be a sequence");
  const matches = presets.filter((preset) => isDict(preset) && pyEq(get(preset, "preset_id"), preset_id));
  if (matches.length !== 1) throw new QuoteError("preset_id must identify exactly one registered preset");

  const preset = deepcopy({ ...matches[0] });
  const sourceInputs = get(preset, "inputs");
  if (!isDict(sourceInputs)) throw new QuoteError("preset.inputs must be a registered input bundle");
  const inputs = deepcopy({ ...sourceInputs });
  const selectedVehicle = vehicle_ref !== null ? vehicle_ref : get(inputs, "vehicle_ref");
  const checks = registrationChecks(preset, inputs, selectedVehicle);

  inputs.quote_id = uuid4();
  if (selectedVehicle !== null) inputs.vehicle_ref = selectedVehicle;

  const unresolved = unresolvedConditions(get(preset, "required_conditions", []));
  if (unresolved.length) {
    const labor = get(inputs, "labor");
    if (isDict(labor)) {
      let existing = get(labor, "unknowns");
      if (!isList(existing)) existing = [];
      labor.unknowns = [...existing, ...unresolved];
    }
  }
  const quote = calculate(inputs);
  setdefault(quote, "reasons", []).push("Simulatorの登録価格スナップショットを使った架空デモ。現在価格・実相場ではありません。");
  const shortcutAvailable = Object.values(checks).every(Boolean) && !unresolved.length && get(quote, "status") !== "blocked";
  if (!shortcutAvailable) {
    quote.status = "blocked";
    quote.selected_band = null;
    quote.issues = [...(get(quote, "issues", []) as Obj[]), { code: "shortcut_unavailable", path: "preset", message: "登録・出所・今回条件を確認してください" }];
    for (const field of ["subtotal", "tax", "total"]) quote[field] = { low: null, typical: null, high: null };
  }
  return {
    inputs,
    quote,
    tap_count: 3,
    shortcut_available: shortcutAvailable,
    registration_checks: checks,
    fictional: get(quote, "fictional", false),
  };
}

function registrationChecks(preset: Obj, inputs: Obj, vehicleRef: unknown): Record<string, boolean> {
  const jobRef = truthyOr(get(preset, "job_ref"), get(preset, "job_id"));
  const jobRegistered = nonempty(jobRef) && pyEq(get(inputs, "job_ref"), jobRef) && nonempty(get(preset, "name"));

  const rate = get(inputs, "labor_rate");
  let rateRegistered =
    isDict(rate) &&
    nonempty(get(rate, "yen_per_person_hour")) &&
    nonempty(get(rate, "effective_from")) &&
    isList(get(rate, "basis")) &&
    get(rate, "basis").length > 0;
  const rateRef = get(preset, "rate_ref");
  if (rateRef !== null) rateRegistered = rateRegistered && pyEq(get(rate, "rate_ref"), rateRef);

  const items = get(inputs, "items");
  const itemIds: unknown[] = [];
  if (isList(items)) {
    for (const entry of items) {
      if (isDict(entry) && nonempty(get(entry, "item_id")) && !pyIn(entry.item_id, itemIds)) itemIds.push(entry.item_id);
    }
  }
  const expected = get(preset, "item_refs");
  let itemsRegistered = isList(items) && items.length > 0 && itemIds.length === items.length;
  if (expected !== null) {
    itemsRegistered =
      itemsRegistered &&
      isList(expected) &&
      new Set(expected.map((ref) => JSON.stringify(ref))).size === itemIds.length &&
      itemIds.every((id) => pyIn(id, expected)) &&
      expected.every((ref) => pyIn(ref, itemIds));
  }
  if (itemsRegistered) {
    for (const entry of items as Obj[]) {
      if (get(entry, "price_type") === "仕入") {
        const markup = get(entry, "markup");
        if (!isDict(markup) || !nonempty(get(markup, "approved_by")) || !nonempty(get(markup, "reason"))) {
          itemsRegistered = false;
          break;
        }
      } else if (get(entry, "price_type") !== "販売") {
        itemsRegistered = false;
        break;
      }
      if (!simulator(get(entry, "source"))) {
        itemsRegistered = false;
        break;
      }
    }
  }
  let vehicleRegistered = nonempty(vehicleRef);
  let registered = get(preset, "vehicle_refs");
  if (registered === null) registered = [get(inputs, "vehicle_ref")];
  vehicleRegistered = vehicleRegistered && isList(registered) && pyIn(vehicleRef, registered);
  const allItems = get(inputs, "items", []);
  return {
    job_registered: Boolean(jobRegistered),
    rate_registered: Boolean(rateRegistered),
    items_registered: Boolean(itemsRegistered),
    vehicle_registered: Boolean(vehicleRegistered),
    simulator_only: (isList(allItems) ? allItems : []).filter((entry) => isDict(entry)).every((entry) => simulator(get(entry, "source"))),
  };
}

function unresolvedConditions(conditions: unknown): string[] {
  if (conditions === null || (isList(conditions) && !conditions.length)) return [];
  if (!isList(conditions)) return ["required_conditionsの形式が不明"];
  const unresolved: string[] = [];
  for (const condition of conditions) {
    if (isDict(condition)) {
      if (pyIn(get(condition, "status"), ["satisfied", "confirmed", "resolved"]) && get(condition, "value") !== null) continue;
      const label = truthyOr(truthyOr(get(condition, "label"), get(condition, "condition")), "条件");
      unresolved.push(`未確認条件: ${pyStr(label)}`);
    } else if (typeof condition === "string" && condition.trim()) {
      unresolved.push(`未確認条件: ${condition.trim()}`);
    } else {
      unresolved.push("required_conditionsに不明な値");
    }
  }
  return unresolved;
}

function truthyOr(value: unknown, fallback: unknown): unknown {
  if (value === null || value === false || value === 0 || value === "") return fallback;
  if (isList(value) && !value.length) return fallback;
  if (isDict(value) && !Object.keys(value).length) return fallback;
  return value;
}

function simulator(value: unknown): boolean {
  return typeof value === "string" && ["simulator", "架空", "fictional"].includes(casefold(value.trim()));
}

function nonempty(value: unknown): boolean {
  return value !== null && value !== undefined && typeof value !== "boolean" && pyStr(value).trim() !== "";
}
