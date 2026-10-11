// P01: 人時と承認済み単価から工賃の帯を計算する。
import { add_ranges, BANDS, hasExactBands, tryDec, _json_number, type Band, type DecRange } from "./common";
import { calculate_billable_person_hours } from "./p02";
import { deepcopy, Dec, get, has, isDict, isList, pyIn, pyStr, ValueErr, noSpace, nonemptyStr, setdefault, type Obj } from "./pyrt";

function _decimal(value: unknown, label: string): Dec {
  if (value === null || value === undefined || typeof value === "boolean") {
    throw new ValueErr(`${label} is required and must be numeric`);
  }
  const result = tryDec(value);
  if (result === null) throw new ValueErr(`${label} must be numeric`);
  if (!result.isFinite()) throw new ValueErr(`${label} must be finite`);
  if (result.lt(Dec.int(0))) throw new ValueErr(`${label} must not be negative`);
  return result;
}

const STATUSES = ["proposed", "observed", "confirmed", "conditional", "approved_nonbillable"];

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote) || !isDict(inputs)) throw new ValueErr("quote and inputs must be objects");
  const labor = get(inputs, "labor");
  const rate = get(inputs, "labor_rate");
  if (!isDict(labor) || !isDict(rate)) throw new ValueErr("labor and labor_rate are required");
  const unknowns = get(labor, "unknowns", []);
  if (!isList(unknowns) || unknowns.length) throw new ValueErr("labor.unknowns must be empty before P01 calculation");
  const hours = get(labor, "person_hours");
  if (!isDict(hours)) throw new ValueErr("labor.person_hours is required");
  const parsedHours = {} as DecRange;
  for (const band of BANDS) {
    if (!has(hours, band)) throw new ValueErr(`labor.person_hours.${band} is required`);
    parsedHours[band] = _decimal(hours[band], `labor.person_hours.${band}`);
  }
  if (!(parsedHours.low.le(parsedHours.typical) && parsedHours.typical.le(parsedHours.high))) {
    throw new ValueErr("labor.person_hours bands must satisfy low <= typical <= high");
  }

  const breakdown = get(labor, "breakdown");
  if (!isList(breakdown) || !breakdown.length) throw new ValueErr("labor.breakdown must contain at least one operation");
  const allHours: Record<Band, number>[] = [];
  const excludedOperations: Obj[] = [];
  for (const entry of breakdown) {
    if (!isDict(entry)) throw new ValueErr("each labor.breakdown item must be an object");
    if (!nonemptyStr(get(entry, "operation"))) throw new ValueErr("labor.breakdown.operation is required");
    const rowHours = get(entry, "hours");
    if (!isDict(rowHours) || !hasExactBands(rowHours)) throw new ValueErr("labor.breakdown.hours must contain all three bands");
    const parsedRow = {} as DecRange;
    for (const band of BANDS) parsedRow[band] = _decimal(rowHours[band], `breakdown.hours.${band}`);
    if (!(parsedRow.low.le(parsedRow.typical) && parsedRow.typical.le(parsedRow.high))) {
      throw new ValueErr("labor.breakdown.hours bands must be ordered");
    }
    allHours.push({ low: _json_number(parsedRow.low), typical: _json_number(parsedRow.typical), high: _json_number(parsedRow.high) });
    const status = get(entry, "status", "proposed");
    if (!pyIn(status, STATUSES)) throw new ValueErr("unknown or unapproved labor status must be resolved");
    if (status === "approved_nonbillable") {
      const required = [get(entry, "reason"), get(entry, "approved_by"), get(entry, "billing_selection_ref")];
      if (!required.every((value) => nonemptyStr(value))) {
        throw new ValueErr("approved nonbillable operation requires reason, approver, and billing_selection_ref");
      }
      excludedOperations.push({
        operation_ref: entry.operation,
        source_ref: get(entry, "source_ref", get(labor, "source_ref", get(labor, "labor_id"))),
        person_hours: deepcopy(entry.hours),
        billing_selection_ref: entry.billing_selection_ref,
        reason: entry.reason,
        approved_by: entry.approved_by,
      });
    }
  }
  const summed = add_ranges(...allHours);
  if (BANDS.some((band) => !_decimal(summed[band], `breakdown.sum.${band}`).eq(parsedHours[band]))) {
    throw new ValueErr("labor.breakdown hours must sum to labor.person_hours in every band");
  }
  const billableHours = calculate_billable_person_hours(breakdown);
  const parsedBillable = {} as DecRange;
  for (const band of BANDS) parsedBillable[band] = _decimal(billableHours[band], `billable_hours.${band}`);
  if (!(parsedBillable.low.le(parsedBillable.typical) && parsedBillable.typical.le(parsedBillable.high))) {
    throw new ValueErr("billable person-hour bands must be ordered");
  }

  if (!has(rate, "yen_per_person_hour")) throw new ValueErr("labor_rate.yen_per_person_hour is required");
  const yenPerHour = _decimal(rate.yen_per_person_hour, "labor_rate.yen_per_person_hour");
  const basis = get(rate, "basis");
  if (
    !isList(basis) ||
    !basis.length ||
    !basis.some((entry) => isDict(entry) && Object.values(entry).some((value) => !pyIn(value, [null, ""])))
  ) {
    throw new ValueErr("labor_rate basis is required");
  }
  const unitOf = (entry: Obj) => noSpace(pyStr(get(entry, "unit", "")));
  if (!basis.some((entry) => isDict(entry) && unitOf(entry) === "円/人時")) {
    throw new ValueErr("labor_rate basis must include 円/人時 evidence");
  }
  for (const entry of basis) {
    if (!isDict(entry) || unitOf(entry) !== "円/人時") throw new ValueErr("labor_rate basis must use 円/人時");
    if (!_decimal(get(entry, "value"), "labor_rate.basis.value").eq(yenPerHour)) {
      throw new ValueErr("labor_rate basis rate must match yen_per_person_hour");
    }
  }
  const result = deepcopy(quote);
  const lines = setdefault(result, "lines", []);
  if (!isList(lines)) throw new ValueErr("quote.lines must be a list");
  const kept = lines.filter((line) => !(isDict(line) && line.line_id === "labor-total"));
  lines.splice(0, lines.length, ...kept);
  const amount = {} as Record<Band, number>;
  const billed = {} as Record<Band, number>;
  for (const band of BANDS) {
    amount[band] = _json_number(parsedBillable[band].mul(yenPerHour));
    billed[band] = _json_number(parsedBillable[band]);
  }
  const approvers = [
    ...new Set(breakdown.filter((entry) => get(entry, "status") === "approved_nonbillable").map((entry) => entry.approved_by)),
  ].sort();
  const billingSelection = {
    billed_person_hours: { ...billed },
    excluded_operations: excludedOperations,
    reason: "Approved nonbillable operations excluded; no elapsed-time or u_period charge applied",
    approved_by: approvers,
    u_period_applied: false,
  };
  const snapshot = { labor: deepcopy(labor), labor_rate: deepcopy(rate), billing_selection: deepcopy(billingSelection) };
  const unitPrice = _json_number(yenPerHour);
  lines.push({
    line_id: "labor-total",
    kind: "labor",
    category: "labor",
    description: "工賃",
    quantity_range: { ...billed },
    unit: "人時",
    unit_price_range: { low: unitPrice, typical: unitPrice, high: unitPrice },
    amount,
    source_system: "labor_engine",
    source_ref: get(labor, "source_ref", get(labor, "labor_id", "labor")),
    snapshot,
    reason: "labor.person_hours × labor_rate.yen_per_person_hour; elapsed_hours is excluded",
    status: "calculated",
  });
  result.billing_selection = deepcopy(billingSelection);
  return result;
}
