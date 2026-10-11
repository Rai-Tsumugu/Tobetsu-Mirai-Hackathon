// P12: 電話で伝えるための短い顧客向け説明を作る。
import { BANDS, isBand, number, _json_number, type Band } from "./common";
import { casefold, deepcopy, Dec, get, groupThousands, isDict, isList, nowIsoSecondsZ, pyStr, QuoteError, setdefault, truthy, type Obj } from "./pyrt";

export function customer_summary(quote: unknown, selected_band: unknown = null): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  const band = selected_band !== null ? selected_band : get(quote, "selected_band");
  if (band !== null && !isBand(band)) throw new QuoteError("selected_band must be low, typical, or high");

  let finalAmount = confirmedAmount(quote);
  let amount: unknown = finalAmount !== null ? finalAmount : amountOf(get(quote, "total"), band as Band | null);
  const conditions = conditionsOf(quote);
  const unresolved = conditions.some((entry) => entry.unresolved);
  const blocked = ["blocked", "unknown", "unconfirmed"].includes(get(quote, "status")) || amount === null || unresolved;
  if (blocked) {
    amount = null;
    finalAmount = null;
  }
  let conditionNote: string;
  if (blocked) conditionNote = "必要な条件・金額が未確認のため、確認後に確定します。";
  else if (conditions.length) {
    conditionNote = conditions.some((entry) => entry.unresolved)
      ? "条件確認後に確定します。"
      : "前提条件: " + conditions.map((entry) => entry.text).join("、");
  } else conditionNote = band === null && finalAmount === null ? "条件確認後に確定します。" : "";

  const components = blocked ? [] : componentsOf(quote, band as Band | null);
  const fictional = isFictional(quote);
  let amountText: string;
  if (finalAmount !== null) amountText = `確定額は ${yen(finalAmount)} 円です。`;
  else if (band === null) amountText = amount !== null ? `ご提案額は ${rangeText(amount as Obj)} 円です。` : "金額は条件確認後にご案内します。";
  else amountText = amount !== null ? `${band}帯のご提案額は ${yen(amount)} 円です。` : "金額は条件確認後にご案内します。";

  const parts: string[] = [];
  if (components.length) parts.push("内訳は" + components.join("、") + "です。");
  parts.push(amountText);
  if (conditionNote) parts.push(conditionNote);
  if (fictional) parts.push("金額例は架空のSimulatorデータです。");
  return {
    quote_version: deepcopy(get(quote, "quote_version")),
    selected_band: band,
    amount: deepcopy(amount),
    condition_note: conditionNote,
    text: parts.join(""),
    generated_at: nowIsoSecondsZ(),
    fictional,
  };
}

export function apply(quote: unknown, inputs: unknown = null): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (inputs !== null && !isDict(inputs)) throw new QuoteError("inputs must be an object when provided");
  const result = deepcopy(quote);
  if (isDict(inputs)) {
    setdefault(setdefault(result, "metadata", {}), "input_snapshot", deepcopy(inputs));
    const labor = get(inputs, "labor", {});
    const unknowns = isDict(labor) ? get(labor, "unknowns", []) : [];
    if (isList(unknowns) && unknowns.length) {
      const conditions = setdefault(result, "conditions", []);
      conditions.push(
        ...unknowns.map((value) => (typeof value === "string" ? { text: pyStr(value), status: "unknown" } : { ...deepcopy(value), status: "unknown" })),
      );
    }
  }
  result.summary_snapshot = customer_summary(result);
  return result;
}

function confirmedAmount(quote: Obj): number | null {
  const confirmation = get(quote, "confirmation");
  if (isDict(confirmation) && get(confirmation, "final_amount") !== null) return scalarAmount(confirmation.final_amount);
  if (get(quote, "final_amount") !== null && truthy(get(quote, "confirmed_by"))) return scalarAmount(quote.final_amount);
  return null;
}

function scalarAmount(value: unknown): number {
  return _json_number(number(value));
}

function amountOf(total: unknown, band: Band | null): unknown {
  if (isDict(total)) {
    if (BANDS.some((key) => get(total, key) === null)) return null;
    const parsed = { low: number(total.low), typical: number(total.typical), high: number(total.high) };
    if (!(parsed.low.le(parsed.typical) && parsed.typical.le(parsed.high))) {
      throw new QuoteError("quote.total must satisfy low <= typical <= high");
    }
    if (band === null) return { low: _json_number(parsed.low), typical: _json_number(parsed.typical), high: _json_number(parsed.high) };
    return _json_number(parsed[band]);
  }
  if (total === null) return null;
  return scalarAmount(total);
}

const UNRESOLVED = ["blocked", "unknown", "unconfirmed", "conditional", "conditional_proposed", "pending"];

function conditionsOf(quote: Obj): { text: string; unresolved: boolean }[] {
  const result: { text: string; unresolved: boolean }[] = [];
  for (const collection of [get(quote, "conditions", []), get(quote, "reasons", [])]) {
    if (!isList(collection)) continue;
    for (const entry of collection) {
      if (typeof entry === "string" && entry.trim()) {
        result.push({ text: entry.trim(), unresolved: false });
      } else if (isDict(entry)) {
        const text = truthy(get(entry, "text")) ? get(entry, "text") : truthy(get(entry, "reason")) ? get(entry, "reason") : get(entry, "operation");
        if (typeof text !== "string" || !text.trim()) continue;
        const status = casefold(pyStr(get(entry, "status", "unconfirmed")));
        const unresolved = UNRESOLVED.includes(status) || get(entry, "customer_ack_status") === "pending";
        result.push({ text: text.trim(), unresolved });
      }
    }
  }
  return result;
}

function componentsOf(quote: Obj, band: Band | null): string[] {
  const sums: Record<string, Dec> = { labor: Dec.int(0), parts: Dec.int(0), materials: Dec.int(0) };
  const seen = new Set<string>();
  const lines = get(quote, "lines", []);
  if (!isList(lines)) return [];
  for (const line of lines) {
    if (!isDict(line)) continue;
    const kind = get(line, "kind");
    if (!["labor", "parts", "materials"].includes(kind) || ["blocked", "unconfirmed"].includes(get(line, "status"))) continue;
    let value = get(line, "amount");
    if (isDict(value)) {
      if (BANDS.some((key) => get(value, key) === null)) continue;
      value = band !== null ? value[band] : value;
    }
    if (value === null) continue;
    try {
      if (isDict(value)) {
        const parsed = { low: number(value.low), typical: number(value.typical), high: number(value.high) };
        if (!(parsed.low.le(parsed.typical) && parsed.typical.le(parsed.high))) {
          throw new QuoteError("line amount must satisfy low <= typical <= high");
        }
        sums[kind] = sums[kind].add(parsed.low);
        sums[kind + "_high"] = (sums[kind + "_high"] ?? Dec.int(0)).add(parsed.high);
      } else {
        sums[kind] = sums[kind].add(number(value));
        sums[kind + "_high"] = (sums[kind + "_high"] ?? Dec.int(0)).add(number(value));
      }
      seen.add(kind);
    } catch (error) {
      if (error instanceof QuoteError) continue;
      throw error;
    }
  }
  const labels: Record<string, string> = { labor: "工賃", parts: "部品", materials: "材料" };
  return ["labor", "parts", "materials"]
    .filter((kind) => seen.has(kind))
    .map((kind) =>
      band === null ? `${labels[kind]} ${yen(sums[kind])}〜${yen(sums[kind + "_high"])} 円` : `${labels[kind]} ${yen(sums[kind])} 円`,
    );
}

function isFictional(quote: Obj): boolean {
  const metadata = get(quote, "metadata", {});
  const snapshot = isDict(metadata) ? get(metadata, "input_snapshot", {}) : {};
  const values: unknown[] = [get(quote, "source_system"), get(quote, "source"), get(quote, "data_mode")];
  if (isDict(snapshot)) values.push(get(snapshot, "source"), get(snapshot, "mode"));
  const lines = get(quote, "lines", []);
  for (const line of isList(lines) ? lines : []) {
    if (!isDict(line)) continue;
    values.push(get(line, "source_system"), get(line, "source"));
    const snap = get(line, "snapshot");
    if (isDict(snap)) values.push(get(snap, "source"), get(snap, "mode"));
  }
  return values.some((value) => typeof value === "string" && ["simulator", "fictional", "架空"].includes(casefold(value.trim())));
}

function yen(value: unknown): string {
  return groupThousands(scalarAmount(value));
}

function rangeText(value: Obj): string {
  return `${yen(value.low)}〜${yen(value.high)}（典型 ${yen(value.typical)}）`;
}
