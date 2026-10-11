/* eslint-disable @typescript-eslint/no-explicit-any */
// E23: descriptive, non-publishing operation benchmark summaries. 元: e23.py
import { type Dict, codePointCompare, deepcopy, get, isDict, isInt, isList, isNumber, isStr, item, truthy } from "./py";
import { run as calculate } from "./e07";

export const ENGINE_ID = "e23_reference_buckets";
export const RULE_VERSION = "e23-reference-buckets-v1";

/** statistics.median（偶数個なら中央2値の平均）。 */
function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  if (n === 0) throw new Error("no median for empty data");
  if (n % 2 === 1) return sorted[(n - 1) / 2];
  return (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
}

export function summarizeBuckets(samples: any[], minimumSamples = 5): Dict[] {
  const grouped = new Map<string, { key: [string, string, string]; rows: Dict[] }>();
  for (const sample of samples) {
    const key: [string, string, string] = [item(sample, "operation_id"), item(sample, "unit"), item(sample, "condition")];
    const k = JSON.stringify(key);
    if (!grouped.has(k)) grouped.set(k, { key, rows: [] });
    grouped.get(k)!.rows.push(sample);
  }
  const entries = [...grouped.values()].sort((a, b) => {
    for (let i = 0; i < 3; i++) {
      const c = codePointCompare(a.key[i], b.key[i]);
      if (c !== 0) return c;
    }
    return 0;
  });
  return entries.map(({ key, rows }) => {
    const values = rows.map((r) => item(r, "hours"));
    return {
      operation_id: key[0], unit: key[1], condition: key[2], n: rows.length, median_hours: median(values),
      range_hours: { low: Math.min(...values), high: Math.max(...values) }, sample_ids: rows.map((r) => item(r, "sample_id")),
      reference_only: rows.length < minimumSamples, autopublished: false,
    };
  });
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const pack: Dict = isDict(rulePack) ? deepcopy(rulePack) : {};
  let samples: any = get(pack, "samples", []);
  const issues: string[] = rulePack !== null && !isDict(rulePack) ? ["rule_pack:object_required"] : [];
  if (!isList(samples)) {
    samples = [];
    issues.push("samples:list_required");
  }
  const seenIds = new Set<string>();
  samples.forEach((row: any, i: number) => {
    if (
      !isDict(row) || !["operation_id", "unit", "condition", "sample_id"].every((k) => isStr(get(row, k)) && truthy(get(row, k))) ||
      get(row, "unit") !== "person_hour" || typeof get(row, "hours") === "boolean" || !isNumber(get(row, "hours")) || !Number.isFinite(row.hours) || get(row, "hours", -1) < 0
    ) {
      issues.push(`samples[${i}]:invalid_observation`);
      return;
    }
    if (seenIds.has(row.sample_id)) issues.push(`samples[${i}]:duplicate_sample_id`);
    seenIds.add(row.sample_id);
  });
  let minimum = get(pack, "minimum_samples", 5);
  if (typeof minimum === "boolean" || !isInt(minimum) || minimum < 1) {
    issues.push("minimum_samples:positive_integer_required");
    minimum = 5;
  }
  const result = calculate(deepcopy(scenarioInput));
  Object.assign(result, {
    engine_id: ENGINE_ID, rule_version: RULE_VERSION,
    reference_report: issues.length ? [] : summarizeBuckets(samples, minimum), reference_issues: issues, autopublished: false,
  });
  return result;
}
