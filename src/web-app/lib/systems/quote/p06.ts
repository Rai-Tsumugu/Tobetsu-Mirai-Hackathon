// P06: 承認済みの最低工賃（または最低小計）との差額を調整行として加える。
import { BANDS, hasExactBands, tryDec, type Band, type DecRange } from "./common";
import { dateFromIso, deepcopy, Dec, get, isDict, isList, nonemptyStrOrInt, numStr, PyError, pyStr, QuoteError, setdefault, type Obj } from "./pyrt";

const LINE_ID = "minimum-rule-adjustment";

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote) || !isDict(inputs)) throw new QuoteError("quote and inputs must be objects");
  const rule = get(inputs, "minimum_rule");
  if (rule === null) return deepcopy(quote);
  const parsedRule = validateRule(rule);

  const result = deepcopy(quote);
  const lines = get(result, "lines");
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");
  const kept = lines.filter((line) => !(isDict(line) && get(line, "line_id") === LINE_ID));
  lines.splice(0, lines.length, ...kept);

  const current = { low: Dec.int(0), typical: Dec.int(0), high: Dec.int(0) } as DecRange;
  lines.forEach((line, index) => {
    if (!isDict(line)) throw new QuoteError(`quote.lines.${index} must be an object`);
    const kind = get(line, "kind");
    const values = amountByBand(get(line, "amount"), index, kind === "discount");
    if (parsedRule.scope === "labor" && kind !== "labor") return;
    for (const band of BANDS) current[band] = current[band].add(values[band]);
  });

  const approved = Boolean(parsedRule.approved_by);
  const adjustment = {} as Record<Band, number>;
  for (const band of BANDS) {
    let value = Dec.int(0);
    if (approved) {
      const diff = parsedRule.amount.sub(current[band]);
      value = diff.gt(Dec.int(0)) ? diff : Dec.int(0);
    }
    adjustment[band] = jsonNumber(value);
  }
  const reason = approved
    ? `${parsedRule.scope} minimum ${numStr(jsonNumber(parsedRule.amount))}; adjustment=max(0, minimum-current) by band`
    : "未承認の最低額ルール案。金額は加算していません。";
  lines.push({
    line_id: LINE_ID,
    kind: "adjustment",
    category: parsedRule.scope,
    description: parsedRule.scope === "labor" ? "最低工賃調整" : "最低小計調整",
    quantity_range: { low: 1, typical: 1, high: 1 },
    unit: "式",
    unit_price_range: deepcopy(adjustment),
    amount: adjustment,
    source_system: "minimum_rule",
    source_ref: parsedRule.effective_from,
    snapshot: { minimum_rule: deepcopy(rule), scope: parsedRule.scope },
    reason,
    status: approved ? "calculated" : "proposed",
  });
  if (!approved) setdefault(result, "reasons", []).push("最低額ルールは未承認のため、金額に反映していません。");
  return result;
}

type Rule = { scope: string; amount: Dec; effective_from: string; approved_by: string | null; reason: string };

function validateRule(rule: unknown): Rule {
  if (!isDict(rule)) throw new QuoteError("minimum_rule must be an object");
  const scope = get(rule, "scope");
  if (scope !== "labor" && scope !== "subtotal") throw new QuoteError("minimum_rule.scope must be labor or subtotal");
  const amount = decimal(get(rule, "amount"), "minimum_rule.amount", false);
  const effectiveFrom = get(rule, "effective_from");
  if (typeof effectiveFrom !== "string") throw new QuoteError("minimum_rule.effective_from must be an ISO date");
  try {
    dateFromIso(effectiveFrom);
  } catch (error) {
    if (error instanceof PyError) throw new QuoteError("minimum_rule.effective_from must be an ISO date");
    throw error;
  }
  const reason = get(rule, "reason");
  if (!nonemptyStrOrInt(reason)) throw new QuoteError("minimum_rule.reason is required");
  const approvedBy = get(rule, "approved_by");
  return {
    scope,
    amount,
    effective_from: effectiveFrom,
    approved_by: nonemptyStrOrInt(approvedBy) ? pyStr(approvedBy).trim() : null,
    reason: pyStr(reason).trim(),
  };
}

function amountByBand(value: unknown, index: number, allowNegative: boolean): DecRange {
  let raw: Record<string, unknown>;
  if (isDict(value)) {
    if (!hasExactBands(value)) throw new QuoteError(`quote.lines.${index}.amount must contain low, typical, and high`);
    raw = value;
  } else {
    raw = { low: value, typical: value, high: value };
  }
  const parsed = {} as DecRange;
  for (const band of BANDS) parsed[band] = decimal(raw[band], `quote.lines.${index}.amount.${band}`, allowNegative);
  if (!(parsed.low.le(parsed.typical) && parsed.typical.le(parsed.high))) {
    throw new QuoteError(`quote.lines.${index}.amount bands must be ordered`);
  }
  return parsed;
}

function decimal(value: unknown, label: string, allowNegative: boolean): Dec {
  if (value === null || value === undefined || typeof value === "boolean") throw new QuoteError(`${label} must be finite and non-negative`);
  const parsed = tryDec(value);
  if (parsed === null) throw new QuoteError(`${label} must be finite and non-negative`);
  if (!parsed.isFinite() || (parsed.lt(Dec.int(0)) && !allowNegative)) throw new QuoteError(`${label} must be finite and non-negative`);
  return parsed;
}

function jsonNumber(value: Dec): number {
  if (value.isIntegral()) return Number(value.toBigInt());
  const result = value.toNumber();
  if (!Number.isFinite(result)) throw new QuoteError("result must be finite");
  return result;
}
