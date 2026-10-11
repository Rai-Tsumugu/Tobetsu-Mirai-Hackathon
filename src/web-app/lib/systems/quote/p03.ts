// P03: 単位を検証し、金額があいまいな見積を止める。
import { BANDS, range_value } from "./common";
import { deepcopy, get, has, isDict, isList, PyError, pyFloat, pyIn, QuoteError, ValueErr, type Obj } from "./pyrt";

const ITEM_CATEGORIES = ["部品", "塗料", "溶剤", "消耗品"];
const PRICE_TYPES = ["仕入", "販売"];

export type Issue = { code: string; path: string; message: string };

function unitKey(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  return value.split(/\s+/).join("");
}

export function validate_inputs(inputs: unknown): Issue[] {
  const issues: Issue[] = [];
  const add = (code: string, path: string, message: string) => issues.push({ code, path, message });
  if (!isDict(inputs)) return [{ code: "invalid_inputs", path: "", message: "inputs must be an object" }];

  const labor = get(inputs, "labor");
  if (!isDict(labor)) {
    add("missing_labor", "labor", "labor must be an object");
  } else {
    const hours = get(labor, "person_hours");
    if (!isDict(hours) || BANDS.some((band) => !has(hours, band))) {
      add("invalid_person_hours", "labor.person_hours", "low, typical, and high person-hours are required");
    } else {
      const parsed: Record<string, number> = {};
      for (const band of BANDS) {
        const value = hours[band];
        if (value === null || typeof value === "boolean") {
          add("invalid_person_hours", `labor.person_hours.${band}`, "value must be finite and non-negative");
          continue;
        }
        let parsedNumber: number;
        try {
          parsedNumber = pyFloat(value);
        } catch (error) {
          if (!(error instanceof PyError)) throw error;
          add("invalid_person_hours", `labor.person_hours.${band}`, "value must be finite and non-negative");
          continue;
        }
        if (!Number.isFinite(parsedNumber) || parsedNumber < 0) {
          add("invalid_person_hours", `labor.person_hours.${band}`, "value must be finite and non-negative");
        } else {
          parsed[band] = parsedNumber;
        }
      }
      if (Object.keys(parsed).length === BANDS.length && !(parsed.low <= parsed.typical && parsed.typical <= parsed.high)) {
        add("unordered_person_hours", "labor.person_hours", "must satisfy low <= typical <= high");
      }
    }
    const unknowns = get(labor, "unknowns", []);
    if (!isList(unknowns)) add("invalid_unknowns", "labor.unknowns", "unknowns must be a list");
    else if (unknowns.length) add("unresolved_unknowns", "labor.unknowns", "unresolved labor unknowns block quote amounts");
  }

  const rate = get(inputs, "labor_rate");
  if (!isDict(rate)) {
    add("missing_labor_rate", "labor_rate", "labor_rate must be an object");
  } else {
    const basis = get(rate, "basis");
    if (!isList(basis) || !basis.length) {
      add("missing_rate_basis", "labor_rate.basis", "rate basis and its evidence are required");
    } else {
      let hasEvidence = false;
      basis.forEach((entry, index) => {
        const path = `labor_rate.basis.${index}`;
        if (!isDict(entry)) {
          add("invalid_rate_basis", path, "basis entry must be an object");
          return;
        }
        if (unitKey(get(entry, "unit")) !== "円/人時") add("invalid_rate_unit", `${path}.unit`, "unit must be 円/人時");
        if (!pyIn(get(entry, "label"), [null, ""]) && get(entry, "value") !== null) hasEvidence = true;
      });
      if (!hasEvidence) add("missing_rate_evidence", "labor_rate.basis", "at least one basis entry needs label and value");
    }
    if (pyIn(get(rate, "effective_from"), [null, ""])) {
      add("missing_effective_from", "labor_rate.effective_from", "effective_from is required");
    }
  }

  const items = get(inputs, "items");
  if (!isList(items)) {
    add("invalid_items", "items", "items must be a list");
  } else {
    items.forEach((entry, index) => {
      const path = `items.${index}`;
      if (!isDict(entry)) {
        add("invalid_item", path, "item must be an object");
        return;
      }
      if (!pyIn(get(entry, "category"), ITEM_CATEGORIES)) {
        add("invalid_category", `${path}.category`, "category must be 部品, 塗料, 溶剤, or 消耗品");
      }
      if (!pyIn(get(entry, "price_type"), PRICE_TYPES)) {
        add("invalid_price_type", `${path}.price_type`, "price_type must be 仕入 or 販売");
      }
      const itemUnit = unitKey(get(entry, "unit"));
      if (itemUnit === null) add("missing_item_unit", `${path}.unit`, "item unit is required");
      const quantityUnit = unitKey(get(entry, "quantity_unit"));
      if (quantityUnit === null || itemUnit === null || quantityUnit !== itemUnit) {
        add("unit_mismatch", `${path}.quantity_unit`, "quantity_unit must match item.unit");
      }
      try {
        range_value(get(entry, "quantity_range"));
      } catch (error) {
        if (!(error instanceof QuoteError)) throw error;
        add("invalid_quantity_range", `${path}.quantity_range`, error.message);
      }
      for (const field of ["source", "updated_at"]) {
        if (pyIn(get(entry, field), [null, ""])) add(`missing_${field}`, `${path}.${field}`, `${field} is required`);
      }
    });
  }
  return issues;
}

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote)) throw new ValueErr("quote must be an object");
  const result = deepcopy(quote);
  const issues = validate_inputs(inputs);
  result.issues = deepcopy(issues);
  result.unit_checks = unitChecks(inputs);
  result.status = issues.length ? "blocked" : "proposed";
  if (!issues.length) return result;

  result.subtotal = result.tax = result.total = null;
  const laborFailed = issues.some((issue) => issue.path.startsWith("labor") || issue.path.startsWith("labor_rate"));
  const failedIndices = new Set<number>();
  for (const issue of issues) {
    const parts = issue.path.split(".");
    if (issue.path.startsWith("items.") && /^\d+$/.test(parts[1])) failedIndices.add(Number(parts[1]));
  }
  const items = isDict(inputs) ? get(inputs, "items", []) : [];
  const failedIds: unknown[] = [];
  for (const index of failedIndices) {
    if (isList(items) && index < items.length && isDict(items[index])) failedIds.push(get(items[index], "item_id"));
  }
  const lines = get(result, "lines", []);
  if (isList(lines)) {
    for (const line of lines) {
      if (!isDict(line)) continue;
      if ((laborFailed && get(line, "kind") === "labor") || pyIn(get(line, "source_ref"), failedIds)) line.amount = null;
    }
  }
  return result;
}

function unitChecks(inputs: unknown): Obj[] {
  if (!isDict(inputs)) return [];
  const checks: Obj[] = [];
  const rate = get(inputs, "labor_rate");
  const basis = isDict(rate) ? get(rate, "basis", []) : [];
  if (isList(basis)) {
    basis.forEach((entry, index) => {
      if (!isDict(entry)) return;
      const left = get(entry, "unit");
      checks.push({
        left_unit: left,
        right_unit: "円/人時",
        status: unitKey(left) === "円/人時" ? "matched" : "mismatch",
        confirmed_by: null,
        source_ref: get(entry, "source_ref", `labor_rate.basis.${index}`),
      });
    });
  }
  const items = get(inputs, "items", []);
  if (isList(items)) {
    items.forEach((entry, index) => {
      if (!isDict(entry)) return;
      const left = get(entry, "quantity_unit");
      const right = get(entry, "unit");
      const matched = unitKey(left) !== null && unitKey(left) === unitKey(right);
      checks.push({
        left_unit: left,
        right_unit: right,
        status: matched ? "matched" : "mismatch",
        confirmed_by: null,
        source_ref: get(entry, "item_id", `items.${index}`),
      });
    });
  }
  return checks;
}
