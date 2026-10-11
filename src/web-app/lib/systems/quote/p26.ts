// P26: 同じ見積の2つの版を比べる（行・金額・条件の差）。
// 注: 元の Python は set の積集合の順で changed を並べるため順序が実行ごとに変わり得る。ここでは旧版の行順にする。
import { BANDS, tryDec, _json_number } from "./common";
import { deepcopy, Dec, get, isDict, isList, pyEq, pyRepr, QuoteError, truthy, type Obj } from "./pyrt";

export function compare_versions(from_quote: unknown, to_quote: unknown): Obj {
  if (!isDict(from_quote) || !isDict(to_quote)) throw new QuoteError("quotes must be objects");
  const quoteId = get(from_quote, "quote_id");
  if (!truthy(quoteId) || !pyEq(quoteId, get(to_quote, "quote_id"))) throw new QuoteError("quotes must have the same quote_id");
  const fromVersion = get(from_quote, "quote_version");
  const toVersion = get(to_quote, "quote_version");
  const oldLines = listOf(from_quote, "lines");
  const newLines = listOf(to_quote, "lines");

  const oldIds = uniqueIds(oldLines, "line_id", "from_quote.lines");
  const newIds = uniqueIds(newLines, "line_id", "to_quote.lines");
  const matched: [number, number][] = [];
  const usedOld = new Set<number>();
  const usedNew = new Set<number>();
  for (const [key, oi] of oldIds) {
    if (!newIds.has(key)) continue;
    const ni = newIds.get(key)!;
    matched.push([oi, ni]);
    usedOld.add(oi);
    usedNew.add(ni);
  }
  const warnings: string[] = [];
  const oldRefs = refIndexes(oldLines, usedOld);
  const newRefs = refIndexes(newLines, usedNew);
  for (const [key, entry] of oldRefs) {
    if (!newRefs.has(key)) continue;
    const oiList = entry.indexes;
    const niList = newRefs.get(key)!.indexes;
    if (oiList.length === 1 && niList.length === 1) {
      matched.push([oiList[0], niList[0]]);
      usedOld.add(oiList[0]);
      usedNew.add(niList[0]);
    } else {
      warnings.push(`ambiguous source_ref ${pyRepr(entry.ref)}; lines were left unmatched`);
    }
  }
  const added = newLines.filter((_, index) => !usedNew.has(index)).map((line) => deepcopy({ ...line }));
  const removed = oldLines.filter((_, index) => !usedOld.has(index)).map((line) => deepcopy({ ...line }));
  const changed: Obj[] = [];
  for (const [oi, ni] of matched) {
    const before = oldLines[oi];
    const after = newLines[ni];
    if (!pyEq(before, after)) changed.push({ from: deepcopy({ ...before }), to: deepcopy({ ...after }) });
  }
  return {
    quote_id: deepcopy(quoteId),
    from_version: deepcopy(fromVersion),
    to_version: deepcopy(toVersion),
    added,
    removed,
    changed,
    amount_delta: amountDelta(from_quote, to_quote),
    condition_delta: conditionDelta(listOf(from_quote, "conditions"), listOf(to_quote, "conditions")),
    warnings,
  };
}

function listOf(quote: Obj, key: string): Obj[] {
  const value = get(quote, key, []);
  if (!isList(value) || value.some((entry) => !isDict(entry))) throw new QuoteError(`quote.${key} must be a list of objects`);
  return value;
}

/** Python の dict キーとして使える値（ハッシュ可能）なら比較用のキー文字列を返す。 */
function hashKey(value: unknown): string | null {
  if (isDict(value) || isList(value)) return null;
  if (typeof value === "boolean") return `n:${Number(value)}`;
  if (typeof value === "number") return `n:${value}`;
  return `s:${String(value)}`;
}

function uniqueIds(lines: Obj[], key: string, path: string): Map<string, number> {
  const indexes = new Map<string, number>();
  lines.forEach((line, index) => {
    const value = get(line, key);
    if (value === null) return;
    const hashed = hashKey(value);
    if (hashed === null) throw new QuoteError(`${path}.${key} must be scalar`);
    if (indexes.has(hashed)) throw new QuoteError(`${path} contains duplicate ${key}`);
    indexes.set(hashed, index);
  });
  return indexes;
}

function refIndexes(lines: Obj[], excluded: Set<number>): Map<string, { ref: unknown; indexes: number[] }> {
  const result = new Map<string, { ref: unknown; indexes: number[] }>();
  lines.forEach((line, index) => {
    const ref = get(line, "source_ref");
    if (excluded.has(index) || ref === null) return;
    const hashed = hashKey(ref);
    if (hashed === null) throw new TypeError("unhashable type");
    if (!result.has(hashed)) result.set(hashed, { ref, indexes: [] });
    result.get(hashed)!.indexes.push(index);
  });
  return result;
}

function amountDelta(oldQuote: Obj, newQuote: Obj): Obj {
  const oldTotal = get(oldQuote, "total");
  const newTotal = get(newQuote, "total");
  if (!isDict(oldTotal) || !isDict(newTotal)) throw new QuoteError("quote.total must be an object");
  const result: Obj = {};
  for (const band of BANDS) {
    const before = amount(get(oldTotal, band), `from_quote.total.${band}`);
    const after = amount(get(newTotal, band), `to_quote.total.${band}`);
    result[band] = before === null || after === null ? null : _json_number(after.sub(before));
  }
  return result;
}

function amount(value: unknown, path: string): Dec | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") throw new QuoteError(`${path} must be a finite non-negative amount or null`);
  const parsed = tryDec(value);
  if (parsed === null || !parsed.isFinite() || parsed.lt(Dec.int(0))) throw new QuoteError(`${path} must be a finite non-negative amount or null`);
  return parsed;
}

function conditionDelta(oldConditions: Obj[], newConditions: Obj[]): Obj {
  const oldIndex = conditionIndex(oldConditions, "from_quote.conditions");
  const newIndex = conditionIndex(newConditions, "to_quote.conditions");
  const added: Obj[] = [];
  const removed: Obj[] = [];
  const changed: Obj[] = [];
  for (const [key, condition] of newIndex) {
    if (!oldIndex.has(key)) added.push(deepcopy({ ...condition }));
    else if (!pyEq(oldIndex.get(key), condition)) changed.push({ from: deepcopy({ ...oldIndex.get(key) }), to: deepcopy({ ...condition }) });
  }
  for (const [key, condition] of oldIndex) if (!newIndex.has(key)) removed.push(deepcopy({ ...condition }));
  return { added, removed, changed };
}

function conditionIndex(conditions: Obj[], path: string): Map<string, Obj> {
  const result = new Map<string, Obj>();
  for (const condition of conditions) {
    let key: string | null = null;
    for (const field of ["condition_ref", "source_ref", "id"]) {
      if (get(condition, field) !== null) {
        const hashed = hashKey(condition[field]);
        if (hashed === null) throw new QuoteError(`${path} identity must be scalar`);
        key = `${field}|${hashed}`;
        break;
      }
    }
    if (key === null) key = `value|${canonical(condition)}`;
    if (result.has(key)) throw new QuoteError(`${path} contains duplicate condition identity`);
    result.set(key, condition);
  }
  return result;
}

function canonical(value: unknown): string {
  if (isList(value)) return `[${value.map(canonical).join(",")}]`;
  if (isDict(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value ?? null);
}
