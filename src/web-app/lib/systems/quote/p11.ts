// P11: 見積の前提条件・未確認事項・対象外作業をまとめる。
import { casefold, deepcopy, get, has, isDict, isList, pyStr, QuoteError, squash, truthy, type Obj } from "./pyrt";

const EXCLUDED = ["excluded", "nonbillable", "non_billable", "not_billable", "approved_nonbillable"];

export function conditions_panel(quote: unknown, inputs: unknown): Obj[] {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (!isDict(inputs)) throw new QuoteError("inputs must be an object");
  const rows: Obj[] = [];
  const prior = get(quote, "conditions", []);
  if (!isList(prior)) throw new QuoteError("quote.conditions must be a list");
  prior.forEach((entry, index) => rows.push(condition(entry, `quote.conditions.${index}`)));

  const rawConditions = get(inputs, "conditions", []);
  if (!isList(rawConditions)) throw new QuoteError("inputs.conditions must be a list");
  rawConditions.forEach((entry, index) => rows.push(condition(entry, `conditions.${index}`)));

  const labor = get(inputs, "labor", {});
  if (!isDict(labor)) throw new QuoteError("inputs.labor must be an object");
  const unknowns = get(labor, "unknowns", []);
  if (!isList(unknowns)) throw new QuoteError("labor.unknowns must be a list");
  unknowns.forEach((entry, index) => rows.push(condition(entry, `labor.unknowns.${index}`, "unknown", true)));

  const breakdown = get(labor, "breakdown", []);
  if (!isList(breakdown)) throw new QuoteError("labor.breakdown must be a list");
  breakdown.forEach((entry, index) => {
    if (!isDict(entry)) throw new QuoteError(`labor.breakdown.${index} must be an object`);
    const status = casefold(pyStr(get(entry, "status", "proposed")));
    if (EXCLUDED.includes(status)) {
      rows.push(condition(entry, `labor.breakdown.${index}`, "excluded", true));
    } else if (["conditional", "condition", "conditional_proposed"].includes(status)) {
      rows.push(condition(entry, `labor.breakdown.${index}`, "conditional", true));
    }
  });
  return dedupe(rows);
}

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (!isDict(inputs)) throw new QuoteError("inputs must be an object");
  const result = deepcopy(quote);
  const conditions = conditions_panel(result, inputs);
  result.conditions = conditions;
  const reasons = get(result, "reasons", []);
  if (!isList(reasons)) throw new QuoteError("quote.reasons must be a list");
  const appended = deepcopy(reasons);
  const seen = new Set(appended.map(reasonKey));
  const candidates: unknown[] = conditions.map((entry) => entry.text);
  const labor = get(inputs, "labor", {});
  if (isDict(labor)) {
    const breakdown = get(labor, "breakdown", []);
    for (const entry of isList(breakdown) ? breakdown : []) {
      if (!isDict(entry)) continue;
      const explanation = truthy(get(entry, "reason")) ? get(entry, "reason") : get(entry, "operation");
      if (nonempty(explanation)) candidates.push(explanation);
    }
  }
  for (const reason of candidates) {
    const key = reasonKey(reason);
    if (key && !seen.has(key)) {
      appended.push(deepcopy(reason));
      seen.add(key);
    }
  }
  result.reasons = appended;
  return result;
}

function condition(value: unknown, fallbackRef: string, status: string | null = null, ackRequired: boolean | null = null): Obj {
  let raw: Obj;
  if (typeof value === "string") raw = { text: value };
  else if (isDict(value)) raw = value;
  else throw new QuoteError(`condition at ${fallbackRef} must be text or an object`);
  const text = truthy(get(raw, "text")) ? get(raw, "text") : truthy(get(raw, "reason")) ? get(raw, "reason") : get(raw, "operation");
  if (!nonempty(text)) throw new QuoteError(`condition at ${fallbackRef} requires text`);
  const resolvedStatus = status ?? (truthy(get(raw, "status")) ? get(raw, "status") : "unconfirmed");
  const required = ackRequired !== null ? ackRequired : get(raw, "customer_ack_required", true);
  if (typeof required !== "boolean") throw new QuoteError(`condition at ${fallbackRef}.customer_ack_required must be boolean`);
  let ackStatus = get(raw, "customer_ack_status");
  if (ackStatus === null) ackStatus = required ? "pending" : "not_required";
  if (typeof ackStatus !== "string" || !ackStatus.trim()) {
    throw new QuoteError(`condition at ${fallbackRef}.customer_ack_status must be non-empty text`);
  }
  const bands = get(raw, "bands", get(raw, "hours"));
  const row: Obj = {
    text: deepcopy(text),
    source_ref: deepcopy(get(raw, "source_ref", fallbackRef)),
    status: deepcopy(resolvedStatus),
    customer_ack_required: required,
    approved_by: deepcopy(get(raw, "approved_by")),
    customer_ack_status: ackStatus,
  };
  if (bands !== null) row.bands = deepcopy(bands);
  return row;
}

function dedupe(rows: Obj[]): Obj[] {
  const result: Obj[] = [];
  const indexes = new Map<string, number>();
  for (const row of rows) {
    const key = JSON.stringify([reasonKey(row.text), pyStr(row.source_ref), pyStr(row.status)]);
    if (!indexes.has(key)) {
      indexes.set(key, result.length);
      result.push(row);
      continue;
    }
    const old = result[indexes.get(key)!];
    if (get(old, "approved_by") === null && get(row, "approved_by") !== null) old.approved_by = deepcopy(row.approved_by);
    if (get(row, "customer_ack_status") !== null && get(row, "customer_ack_status") !== "pending") {
      old.customer_ack_status = row.customer_ack_status;
    }
    if (!has(old, "bands") && has(row, "bands")) old.bands = deepcopy(row.bands);
  }
  return result;
}

function reasonKey(value: unknown): string {
  return typeof value === "string" ? casefold(squash(value)) : "";
}

function nonempty(value: unknown): boolean {
  return typeof value === "string" && value.trim() !== "";
}
