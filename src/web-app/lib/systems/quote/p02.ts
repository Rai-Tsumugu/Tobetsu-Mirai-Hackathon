// P02: 工賃を工程ごとの監査できる見積行に展開する。
import { add_ranges, BANDS, jsonRange, make_line, multiply_ranges, number, range_value, type Band, type DecRange } from "./common";
import { deepcopy, get, has, isDict, isInt, isList, item, nonemptyStr, pyIn, pyRepr, pyStr, QuoteError, setdefault, truthy, type Obj } from "./pyrt";

const LINE_PREFIX = "labor-breakdown:";
const NONBILLABLE = "approved_nonbillable";
const STATUSES = ["proposed", "observed", "confirmed", "conditional", "approved_nonbillable"];

export function calculate_billable_person_hours(breakdown: Obj[]): Record<Band, number> {
  const hours = breakdown.filter((entry) => get(entry, "status", "proposed") !== NONBILLABLE).map((entry) => item(entry, "hours"));
  return hours.length ? add_ranges(...hours) : { low: 0, typical: 0, high: 0 };
}

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote) || !isDict(inputs)) throw new QuoteError("quote and inputs must be objects");
  const labor = get(inputs, "labor");
  const rate = get(inputs, "labor_rate");
  if (!isDict(labor) || !isDict(rate)) throw new QuoteError("labor and labor_rate are required");
  const unknowns = get(labor, "unknowns", []);
  if (!isList(unknowns) || unknowns.length) throw new QuoteError("labor.unknowns must be an empty list before P02 calculation");

  const totalHours = range_value(get(labor, "person_hours"));
  if (!has(rate, "yen_per_person_hour")) throw new QuoteError("labor_rate.yen_per_person_hour is required");
  const parsedRate = number(rate.yen_per_person_hour);
  const basis = get(rate, "basis");
  if (
    !isList(basis) ||
    !basis.length ||
    !basis.some((entry) => isDict(entry) && Object.values(entry).some((value) => !pyIn(value, [null, ""])))
  ) {
    throw new QuoteError("labor_rate basis is required");
  }
  const breakdown = get(labor, "breakdown");
  if (!isList(breakdown) || !breakdown.length) throw new QuoteError("labor.breakdown must contain at least one operation");

  const parsedItems: Obj[] = [];
  const seen = new Set<string>();
  breakdown.forEach((entry, index) => {
    if (!isDict(entry)) throw new QuoteError("each labor.breakdown item must be an object");
    const operation = get(entry, "operation");
    if (!nonemptyStr(operation)) throw new QuoteError("labor.breakdown.operation is required");
    const hours = range_value(get(entry, "hours"));
    let sourceRef = get(entry, "source_ref", get(labor, "source_ref", get(labor, "labor_id")));
    if (sourceRef === null || !(typeof sourceRef === "string" || isInt(sourceRef)) || !pyStr(sourceRef).trim()) {
      sourceRef = `labor-breakdown-${index + 1}`;
    }
    sourceRef = pyStr(sourceRef);
    const identityKey = JSON.stringify([operation.trim(), sourceRef]);
    if (seen.has(identityKey)) {
      throw new QuoteError(`duplicate labor operation/source_ref: (${pyRepr(operation.trim())}, ${pyRepr(sourceRef)})`);
    }
    seen.add(identityKey);
    const status = get(entry, "status", "proposed");
    if (!pyIn(status, STATUSES)) throw new QuoteError("unknown or unapproved labor status must be resolved");
    const reason = get(entry, "reason");
    const approvedBy = get(entry, "approved_by");
    const billingSelectionRef = get(entry, "billing_selection_ref");
    if (status === NONBILLABLE && ![reason, approvedBy, billingSelectionRef].every((value) => nonemptyStr(value))) {
      throw new QuoteError("approved_nonbillable operations require reason, approved_by, and billing_selection_ref");
    }
    parsedItems.push({
      source: entry, hours, operation: operation.trim(), source_ref: sourceRef, status, reason,
      approved_by: approvedBy, billing_selection_ref: billingSelectionRef,
    });
  });

  const summed = add_ranges(...parsedItems.map((entry) => decRangeToJson(entry.hours)));
  if (BANDS.some((band) => !number(summed[band]).eq(totalHours[band]))) {
    throw new QuoteError("labor.breakdown hours must sum to labor.person_hours in every band");
  }
  const billableHours = calculate_billable_person_hours(parsedItems.map((entry) => ({ ...entry, hours: decRangeToJson(entry.hours) })));

  const result = deepcopy(quote);
  const lines = setdefault(result, "lines", []);
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");
  const kept = lines.filter(
    (line) => !(isDict(line) && (line.line_id === "labor-total" || (typeof line.line_id === "string" && line.line_id.startsWith(LINE_PREFIX)))),
  );
  lines.splice(0, lines.length, ...kept);

  const excludedOperations: Obj[] = [];
  parsedItems.forEach((entry, offset) => {
    const index = offset + 1;
    const hours = entry.hours as DecRange;
    const nonbillable = entry.status === NONBILLABLE;
    const amount = nonbillable ? { low: 0, typical: 0, high: 0 } : multiply_ranges(decRangeToJson(hours), parsedRate.toString());
    let billingSelection: Obj | null = null;
    if (nonbillable) {
      billingSelection = {
        operation_ref: entry.operation,
        source_ref: entry.source_ref,
        person_hours: jsonRange(hours),
        billing_selection_ref: entry.billing_selection_ref,
        reason: entry.reason,
        approved_by: entry.approved_by,
      };
      excludedOperations.push(deepcopy(billingSelection));
    }
    const snapshot: Obj = { operation: deepcopy(entry.source), labor_rate: deepcopy(rate) };
    if (billingSelection !== null) snapshot.billing_selection = deepcopy(billingSelection);
    const rateText = parsedRate.toString();
    const line = make_line({
      line_id: `${LINE_PREFIX}${index}`,
      kind: "labor",
      category: "labor",
      description: entry.operation,
      quantity_range: decRangeToJson(hours),
      unit: "人時",
      unit_price_range: { low: rateText, typical: rateText, high: rateText },
      amount,
      source_system: "labor_engine",
      source_ref: entry.source_ref,
      snapshot,
      reason: pyStr(truthy(entry.reason) ? entry.reason : "工程別人時 × 承認済み円/人時単価"),
      status: entry.status,
    });
    line.billing_selection_ref = entry.billing_selection_ref;
    lines.push(line);
  });
  result.billing_selection = { billed_person_hours: billableHours, excluded_operations: excludedOperations };
  return result;
}

/** Decimal の帯を、値を変えずに JSON の帯へ（Decimal(str(x)) で同じ値に戻る）。 */
function decRangeToJson(range: DecRange): Record<Band, string> {
  return { low: range.low.toString(), typical: range.typical.toString(), high: range.high.toString() };
}
