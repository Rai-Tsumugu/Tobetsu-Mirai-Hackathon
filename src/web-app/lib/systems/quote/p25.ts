// P25: 複数見積の行を合算し、人が承認した共通品目だけを重複として除く。
import { BANDS, hasExactBands, tryDec, _json_number, type Band } from "./common";
import { deepcopy, Dec, get, has, isDict, isList, pyEq, pyStr, QuoteError, type Obj } from "./pyrt";

export function combine_quotes(quotes: unknown, accepted_dedup_refs: unknown = null, approved_by: unknown = null): Obj {
  if (typeof quotes === "string" || isDict(quotes)) throw new QuoteError("quotes must be an iterable of quote objects");
  if (!isList(quotes)) throw new QuoteError("quotes must be an iterable of quote objects");
  const quoteRows = [...quotes];
  const candidates = new Map<string, { key: [string, string]; members: { ref: string; line: Obj }[] }>();
  const rows: Obj[] = [];
  const jobRefs: unknown[] = [];
  const seenRefs = new Set<string>();
  quoteRows.forEach((quote, qi) => {
    if (!isDict(quote)) throw new QuoteError(`quotes.${qi} must be an object`);
    const quoteId = get(quote, "quote_id");
    const version = get(quote, "quote_version");
    if (quoteId === null || version === null) throw new QuoteError(`quotes.${qi} requires quote_id and quote_version`);
    const jobRef = get(quote, "job_ref", get(quote, "job_id", quoteId));
    jobRefs.push(deepcopy(jobRef));
    const lines = get(quote, "lines");
    if (!isList(lines)) throw new QuoteError(`quotes.${qi}.lines must be a list`);
    lines.forEach((line, li) => {
      if (!isDict(line)) throw new QuoteError(`quotes.${qi}.lines.${li} must be an object`);
      const lineId = get(line, "line_id");
      if (lineId === null || !pyStr(lineId).trim()) throw new QuoteError(`quotes.${qi}.lines.${li}.line_id is required`);
      const ref = `${pyStr(quoteId)}:${pyStr(version)}:${pyStr(lineId)}`;
      if (seenRefs.has(ref)) throw new QuoteError(`duplicate line ref: ${ref}`);
      seenRefs.add(ref);
      const row = deepcopy({ ...line });
      row.line_id = ref;
      row.source_line_id = pyStr(lineId);
      row.quote_id = pyStr(quoteId);
      row.quote_version = pyStr(version);
      row.line_ref = ref;
      rows.push(row);
      if (get(line, "kind") !== "parts" && get(line, "kind") !== "materials") return;
      const snapshot = get(line, "snapshot");
      if (!isDict(snapshot)) return;
      const itemId = get(snapshot, "item_id");
      const usageRef = get(snapshot, "usage_ref");
      if (itemId === null || itemId === "" || usageRef === null || usageRef === "") return;
      const key: [string, string] = [pyStr(itemId), pyStr(usageRef)];
      const mapKey = JSON.stringify(key);
      if (!candidates.has(mapKey)) candidates.set(mapKey, { key, members: [] });
      candidates.get(mapKey)!.members.push({ ref, line });
    });
  });

  const groups: Obj[] = [];
  const eligibleRefs = new Set<string>();
  for (const { key, members } of candidates.values()) {
    if (members.length < 2) continue;
    const refs = members.map((member) => member.ref);
    refs.forEach((ref) => eligibleRefs.add(ref));
    const baseline = members[0].line;
    const differences = members.slice(1).map((member) => {
      const diff: Obj = {};
      for (const field of ["quantity_range", "unit", "amount"]) {
        if (!pyEq(get(member.line, field), get(baseline, field))) {
          diff[field] = { baseline: deepcopy(get(baseline, field)), candidate: deepcopy(get(member.line, field)) };
        }
      }
      return { ref: member.ref, differences: diff };
    });
    groups.push({ item_id: key[0], usage_ref: key[1], refs, differences });
  }

  let accepted: unknown[];
  if (accepted_dedup_refs === null) accepted = [];
  else if (typeof accepted_dedup_refs === "string") throw new QuoteError("accepted_dedup_refs must be an iterable of refs");
  else if (isList(accepted_dedup_refs)) accepted = [...accepted_dedup_refs];
  else if (isDict(accepted_dedup_refs)) accepted = Object.keys(accepted_dedup_refs);
  else throw new QuoteError("accepted_dedup_refs must be an iterable of refs");
  if (accepted.some((ref) => typeof ref !== "string" || !ref.trim())) throw new QuoteError("accepted dedup refs must be non-empty strings");
  if (new Set(accepted).size !== accepted.length) throw new QuoteError("accepted dedup refs must be unique");
  if (accepted.some((ref) => !eligibleRefs.has(ref as string))) {
    throw new QuoteError("accepted dedup ref must belong to a shared parts/materials candidate");
  }
  if (accepted.length && (typeof approved_by !== "string" || !approved_by.trim())) {
    throw new QuoteError("approved_by is required when dedup refs are accepted");
  }
  const removed = new Set(accepted as string[]);
  const included = rows.filter((row) => !removed.has(row.line_ref));
  return {
    job_refs: jobRefs,
    lines: included,
    shared_item_candidates: groups,
    accepted_dedup_refs: accepted,
    approved_by: accepted.length ? (approved_by as string).trim() : null,
    subtotal: sumRows(included),
    original_subtotal: sumRows(rows),
    delta: subtractRanges(sumRows(included), sumRows(rows)),
  };
}

function sumRows(rows: Obj[]): Record<Band, number | null> {
  const totals: Record<Band, Dec> = { low: Dec.int(0), typical: Dec.int(0), high: Dec.int(0) };
  const unknown: Record<Band, boolean> = { low: false, typical: false, high: false };
  for (const row of rows) {
    const amount = get(row, "amount");
    let values: Record<string, unknown>;
    if (isDict(amount)) {
      if (!hasExactBands(amount)) throw new QuoteError(`line ${pyStr(get(row, "line_ref"))} amount must contain all bands`);
      values = amount;
    } else if (amount === null) values = { low: null, typical: null, high: null };
    else values = { low: amount, typical: amount, high: amount };
    for (const band of BANDS) {
      const value = values[band];
      if (value === null) {
        unknown[band] = true;
        continue;
      }
      if (typeof value === "boolean") throw new QuoteError(`line ${pyStr(get(row, "line_ref"))} amount.${band} must be finite`);
      const parsed = tryDec(value);
      if (parsed === null || !parsed.isFinite()) throw new QuoteError(`line ${pyStr(get(row, "line_ref"))} amount.${band} must be finite`);
      totals[band] = totals[band].add(parsed);
    }
  }
  const result = {} as Record<Band, number | null>;
  for (const band of BANDS) result[band] = unknown[band] ? null : _json_number(totals[band]);
  return result;
}

function subtractRanges(left: Record<Band, number | null>, right: Record<Band, number | null>): Record<Band, number | null> {
  const result = {} as Record<Band, number | null>;
  for (const band of BANDS) {
    const a = left[band];
    const b = right[band];
    result[band] = a === null || b === null ? null : _json_number(Dec.fromPy(a).sub(Dec.fromPy(b)));
  }
  return result;
}

export { has };
