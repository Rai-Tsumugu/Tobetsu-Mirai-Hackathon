// ゴールデン照合の実行器。scenarios/<name>.json の手順を MemoryStore で実行し、
// generate.py が元の Python で出した golden/<name>.json と比べる。
import { readFileSync } from "node:fs";
import path from "node:path";
import { seedDemo, Store, ValidationError, type Json } from "../../../lib/systems/items/core";
import { MemoryStore } from "../../../lib/systems/items/memory-store";
import { parseJson, roundTrip } from "../../../lib/systems/items/py";

export const GOLDEN_DIR = path.join(__dirname, "golden");

export type Step = Json & { op: string };
export type Expected = { ok: unknown } | { error: string; message: string };
type ModuleLike = { run: (payload: unknown, store: Store) => Promise<unknown> };

export async function loadModule(name: string): Promise<ModuleLike> {
  const file = name === "INTEGRATED" ? "integrated" : name.toLowerCase();
  return (await import(`../../../lib/systems/items/${file}.ts`)) as ModuleLike;
}

function resolve(value: unknown, results: unknown[]): unknown {
  if (typeof value === "string" && value.startsWith("$ref:")) {
    const parts = value.slice(5).split(".");
    let current = results[Number(parts[0])] as unknown;
    for (const part of parts.slice(1)) {
      current = Array.isArray(current) ? current[Number(part)] : (current as Json)[part];
    }
    return current;
  }
  if (Array.isArray(value)) return value.map((entry) => resolve(entry, results));
  if (value && typeof value === "object" && value.constructor === Object) {
    return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, resolve(entry, results)]));
  }
  return value;
}

async function execute(step: Step, store: Store): Promise<unknown> {
  const s = step as Json;
  switch (step.op) {
    case "specs":
      return (await import("../../../lib/systems/items/registry")).specifications();
    case "seed_demo":
      await seedDemo(store);
      return null;
    case "run":
      return (await loadModule(s.module as string)).run(s.payload, store);
    case "add_price":
      return store.addPrice(s.item, s.confirmed_by, (s.kwargs as Json) ?? {});
    case "put":
      return store.put(s.namespace, s.record, s.record_id ?? null);
    case "records":
      return store.records(s.namespace as string, (s.record_id as string) ?? null);
    case "latest":
      return store.latest(s.namespace as string, s.record_id as string);
    case "price_versions":
      return store.priceVersions((s.item_id as string) ?? null, (s.price_type as string) ?? null, (s.supplier_id as string) ?? null);
    case "get_price": {
      const kwargs = ((s.kwargs as Json) ?? {}) as Json;
      return store.getPrice(s.item_id as string, s.price_type ?? "販売", kwargs);
    }
    default:
      throw new Error(`unknown op ${step.op}`);
  }
}

export type StepOutcome = { step: Step; expected: Expected; actual: Expected };

export async function runScenario(steps: Step[], expected: Expected[], store: Store = new MemoryStore()): Promise<StepOutcome[]> {
  const results: unknown[] = [];
  const outcomes: StepOutcome[] = [];
  for (const [index, step] of steps.entries()) {
    const resolved = resolve(step, results) as Step;
    let actual: Expected;
    try {
      const result = await execute(resolved, store);
      actual = { ok: roundTrip(result ?? null) };
      results.push(result);
    } catch (error) {
      const err = error as Error;
      actual = { error: err instanceof ValidationError ? "ValidationError" : err.name, message: err.message };
      results.push(null);
    }
    outcomes.push({ step, expected: expected[index], actual });
  }
  return outcomes;
}

const ID_PATTERN = /[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}/g;
const SET_KEYS = new Set(["approved_candidate_ids"]);
const NOW_PATTERN = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00/g;

/**
 * 乱数の ID と保存時刻は実行ごとに変わるので、出現順の記号に置き換える。
 * キーは並べ替えて走査する（Python と TS の dict の順序の違いを番号に影響させない）。
 */
export function normalize(values: unknown[]): unknown[] {
  const ids = new Map<string, string>();
  const replace = (text: string) =>
    text
      .replace(ID_PATTERN, (id) => {
        const key = id.replace(/-/g, "");
        if (!ids.has(key)) ids.set(key, `<id${ids.size + 1}>`);
        return ids.get(key)!;
      })
      .replace(NOW_PATTERN, "<now>");
  const walk = (value: unknown, key = ""): unknown => {
    if (typeof value === "string") return replace(value);
    // sorted(set(乱数のID)) は実行ごとに順序が変わるので、集合として比べる。
    if (Array.isArray(value) && SET_KEYS.has(key)) return value.map((entry) => walk(entry)).sort();
    if (Array.isArray(value)) return value.map((entry) => walk(entry));
    if (value && typeof value === "object") {
      const out: Json = {};
      for (const key of Object.keys(value).sort()) out[replace(key)] = walk((value as Json)[key], key);
      return out;
    }
    return value;
  };
  return values.map((value) => walk(value));
}

export type GoldenFile = { name: string; scenarios: { name: string; steps: Step[]; expected: Expected[] }[] };

export function loadGolden(name: string): GoldenFile {
  const input = parseJson(readFileSync(path.join(GOLDEN_DIR, "scenarios", `${name}.json`), "utf8")) as {
    scenarios: { name: string; steps: Step[] }[];
  };
  const output = JSON.parse(readFileSync(path.join(GOLDEN_DIR, `${name}.json`), "utf8")) as {
    scenarios: { name: string; expected: Expected[] }[];
  };
  return {
    name,
    scenarios: input.scenarios.map((scenario, index) => {
      if (output.scenarios[index]?.name !== scenario.name) {
        throw new Error(`${name}: golden が古いです（generate.py を再実行してください）`);
      }
      return { name: scenario.name, steps: scenario.steps, expected: output.scenarios[index].expected };
    }),
  };
}

/** 期待値と実際を比べられる形にする。ValidationError 以外の例外は種類だけを比べる。 */
export function comparable(outcomes: StepOutcome[]): { expected: unknown[]; actual: unknown[] } {
  const shape = (value: Expected, other: Expected): unknown => {
    if ("error" in value && value.error !== "ValidationError") {
      // Python の KeyError / TypeError などは TS では別の例外になる。例外で止まることだけを比べる。
      return "error" in other && other.error !== "ValidationError" ? { error: "non-validation" } : value;
    }
    return value;
  };
  return {
    expected: normalize(outcomes.map((o) => shape(o.expected, o.actual))),
    actual: normalize(outcomes.map((o) => shape(o.actual, o.expected))),
  };
}
