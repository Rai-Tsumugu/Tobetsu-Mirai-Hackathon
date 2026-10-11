// P13: 見積入力を手順（車両→作業→条件→金額→確定）ごとに検査する。
import { isBand, range_value } from "./common";
import { validate_inputs, type Issue } from "./p03";
import { deepcopy, get, isDict, isInt, QuoteError, type Obj } from "./pyrt";

const LABELS = ["vehicle", "job", "conditions", "amount", "confirm"];

function stepIndex(step: unknown): number {
  if (!isInt(step) || !(step >= 0 && step < LABELS.length)) throw new QuoteError("step must be an integer from 0 through 4");
  return step;
}

export function validate_step(inputs: unknown, step: unknown, quote: unknown = null): Issue[] {
  const index = stepIndex(step);
  if (!isDict(inputs)) return [issue("invalid_inputs", "inputs", "inputs must be an object")];
  const issues: Issue[] = [];
  if (index === 0) requiredRef(inputs, "vehicle_ref", issues);
  else if (index === 1) requiredRef(inputs, "job_ref", issues);
  else if (index === 2) issues.push(...validate_inputs({ ...inputs }));
  else if (index === 3) {
    const total = isDict(quote) ? get(quote, "total") : null;
    try {
      range_value(total);
    } catch (error) {
      if (!(error instanceof QuoteError)) throw error;
      issues.push(issue("invalid_proposed_amount", "quote.total", error.message));
    }
  } else {
    issues.push(...validate_step(inputs, 3, quote));
    if (isDict(quote) && ["blocked", "unknown", "pending"].includes(get(quote, "status"))) {
      issues.push(issue("unavailable_quote", "quote.status", "quote cannot be confirmed"));
    }
    const selectedBand = isDict(quote) ? get(quote, "selected_band") : null;
    const confirmedBy = isDict(quote) ? get(quote, "confirmed_by") : null;
    if (!isBand(selectedBand)) issues.push(issue("missing_selected_band", "quote.selected_band", "a valid selected band is required"));
    if (!nonempty(confirmedBy)) issues.push(issue("missing_confirmed_by", "quote.confirmed_by", "confirmed_by is required"));
  }
  return issues;
}

export function advance_step(draft: unknown, quote: unknown = null): Obj {
  if (!isDict(draft)) throw new QuoteError("draft must be an object");
  const step = stepIndex(get(draft, "step"));
  const issues = validate_step(get(draft, "inputs"), step, quote);
  if (issues.length) throw new QuoteError(`step ${step} is incomplete: ${issues[0].code} at ${issues[0].path}`);
  if (step === LABELS.length - 1) throw new QuoteError("confirm is the final step");
  const result = deepcopy({ ...draft });
  result.step = step + 1;
  return result;
}

export function form_state(inputs: unknown, step: unknown = 0, quote: unknown = null): Obj {
  const index = stepIndex(step);
  const issues = validate_step(inputs, index, quote);
  return { step: index, label: LABELS[index], issues, can_advance: !issues.length };
}

function requiredRef(inputs: Obj, field: string, issues: Issue[]): void {
  if (!nonempty(get(inputs, field))) issues.push(issue(`missing_${field}`, field, `${field} is required`));
}

function issue(code: string, path: string, message: string): Issue {
  return { code, path, message };
}

function nonempty(value: unknown): boolean {
  return typeof value === "string" && value.trim() !== "";
}
