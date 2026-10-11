// API のゴールデン照合。golden/api.json のシナリオ（元の FastAPI に一時 SQLite と模擬 Gemini で流した結果）を、
// 移植した Route Handler に同じ順序で流し、ステータス・応答（キーの順序を含む）・Gemini への送信内容を比べる。
// TEST_DATABASE_URL の PostgreSQL に使い捨てのデータベースを作って実行し、最後に消す。なければスキップする。
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { migrate, readMigrations } from "../../../lib/db/migrate";
import { transaction } from "../../../lib/db/queryable";
import { seedDemo } from "../../../lib/systems/demo/seed";
import { ENDPOINT } from "../../../lib/systems/demo/gemini";
import * as cases from "../../../app/api/demo/cases/route";
import * as caseItem from "../../../app/api/demo/cases/[caseId]/route";
import * as configRoute from "../../../app/api/demo/config/route";
import * as estimates from "../../../app/api/demo/estimates/route";
import * as estimateItem from "../../../app/api/demo/estimates/[estimateId]/route";
import * as research from "../../../app/api/demo/price-research/route";
import * as jobs from "../../../app/api/demo/repair-jobs/route";
import * as vehicles from "../../../app/api/demo/vehicles/route";
import * as vehicleItem from "../../../app/api/demo/vehicles/[vehicleId]/route";
import golden from "./golden/api.json";
import { Normalizer, ordered } from "./normalize";

type Step = {
  name: string;
  method: string;
  path: string;
  body: unknown;
  env?: string;
  gemini?: { status: number; json?: unknown; text?: string }[];
  reset_throttle?: boolean;
  status: number;
  response: unknown;
  calls: { url: string; has_key: boolean; json: unknown }[];
};

type Handler = (request: Request, context: { params: Promise<Record<string, string>> }) => Promise<Response> | Response;
const ROUTES: [RegExp, string | null, Record<string, Handler>][] = [
  [/^\/api\/cases$/, null, cases as never],
  [/^\/api\/cases\/([^/]+)$/, "caseId", caseItem as never],
  [/^\/api\/config$/, null, configRoute as never],
  [/^\/api\/estimates$/, null, estimates as never],
  [/^\/api\/estimates\/([^/]+)$/, "estimateId", estimateItem as never],
  [/^\/api\/price-research$/, null, research as never],
  [/^\/api\/repair-jobs$/, null, jobs as never],
  [/^\/api\/vehicles$/, null, vehicles as never],
  [/^\/api\/vehicles\/([^/]+)$/, "vehicleId", vehicleItem as never],
];

async function call(method: string, target: string, body: unknown): Promise<Response> {
  const url = new URL("http://localhost/api/demo" + target.slice("/api".length));
  const pathname = "/api" + url.pathname.slice("/api/demo".length);
  for (const [pattern, param, module] of ROUTES) {
    const match = pattern.exec(pathname);
    if (!match) continue;
    const handler = module[method];
    if (!handler) throw new Error(`${method} ${pathname} は未実装`);
    const params = param ? { [param]: decodeURIComponent(match[1]) } : {};
    const request = new Request(url, {
      method,
      ...(body === null ? {} : { body: JSON.stringify(body), headers: { "Content-Type": "application/json" } }),
    });
    return handler(request, { params: Promise.resolve(params) });
  }
  throw new Error(`経路がない: ${pathname}`);
}

function lookup(ref: string, results: Record<string, unknown>): unknown {
  const [name, ...keys] = ref.split(".");
  let value: unknown = results[name];
  for (const key of keys) value = Array.isArray(value) ? value[Number(key)] : (value as Record<string, unknown>)[key];
  return value;
}

function resolve(value: unknown, results: Record<string, unknown>): unknown {
  if (Array.isArray(value)) return value.map((v) => resolve(v, results));
  if (value && typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 1 && keys[0] === "$ref") return lookup((value as { $ref: string }).$ref, results);
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolve(v, results)]));
  }
  return value;
}

const adminUrl = process.env.TEST_DATABASE_URL;
const databaseName = `webapp_demo_test_${randomUUID().replaceAll("-", "")}`;
let admin: Pool;
let pool: Pool;
const previousEnv = { DATABASE_URL: process.env.DATABASE_URL, GEMINI_API_KEY: process.env.GEMINI_API_KEY };

describe.skipIf(!adminUrl)("整備見積デモ: API のゴールデン照合", () => {
  const steps = golden as Step[];
  const results: Record<string, unknown> = {};
  const normalizer = new Normalizer();

  beforeAll(async () => {
    admin = new Pool({ connectionString: adminUrl });
    await admin.query(`CREATE DATABASE ${databaseName}`);
    const url = new URL(adminUrl!);
    url.pathname = `/${databaseName}`;
    pool = new Pool({ connectionString: url.toString() });
    await migrate(pool, await readMigrations(path.resolve(__dirname, "../../../db/migrations")));
    await transaction(pool, (tx) => seedDemo(tx));
    process.env.DATABASE_URL = url.toString();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  afterAll(async () => {
    process.env.DATABASE_URL = previousEnv.DATABASE_URL;
    process.env.GEMINI_API_KEY = previousEnv.GEMINI_API_KEY;
    await pool?.end();
    await admin?.query(`DROP DATABASE IF EXISTS ${databaseName} WITH (FORCE)`);
    await admin?.end();
  });

  it("seed は何度流しても同じ状態になる", async () => {
    await transaction(pool, (tx) => seedDemo(tx));
    const { rows } = await pool.query(
      "SELECT (SELECT count(*)::int FROM demo_vehicles) AS v, (SELECT count(*)::int FROM demo_repair_jobs) AS j",
    );
    expect(rows[0]).toEqual({ v: 9, j: 5 });
  });

  // シナリオは前の結果（案件 ID・見積番号・調査 ID・候補 ID）を参照するので、順番に流す。
  it.each(steps.map((step) => [step.name, step] as const))("%s", async (_name, step) => {
    if (step.reset_throttle) await pool.query("DELETE FROM demo_gemini_throttle");
    process.env.GEMINI_API_KEY = step.env ?? "test-placeholder";
    const queue = [...(step.gemini ?? [])];
    const calls: { url: string; has_key: boolean; json: unknown }[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url !== ENDPOINT) return realFetch(input, init);
      const headers = new Headers(init?.headers);
      calls.push({ url, has_key: headers.get("x-goog-api-key") === "test-placeholder", json: JSON.parse(String(init?.body)) });
      const spec = queue.shift();
      if (!spec) throw new Error("模擬応答が足りない");
      return new Response(spec.json !== undefined ? JSON.stringify(spec.json) : (spec.text ?? ""), { status: spec.status });
    });
    const target = step.path.replace(/\{([^}]+)\}/g, (_m, ref: string) => String(lookup(ref, results)));
    const response = await call(step.method, target, resolve(step.body, results));
    const text = await response.text();
    expect(response.status, text).toBe(step.status);
    const data = JSON.parse(text);
    results[step.name] = data;
    expect(ordered(normalizer.response(response.status, data))).toBe(ordered(step.response));
    expect(ordered(calls)).toBe(ordered(step.calls));
  });

  it("保存した見積もりの根拠（明細・候補・採用）が関連テーブルにそろう", async () => {
    const { rows } = await pool.query(`
      SELECT (SELECT count(*)::int FROM demo_estimates) AS estimates,
             (SELECT count(*)::int FROM demo_estimate_items i WHERE NOT EXISTS (SELECT 1 FROM demo_estimates e WHERE e.id = i.estimate_id)) AS orphan_items,
             (SELECT count(*)::int FROM demo_selected_sources s JOIN demo_price_sources p ON p.id = s.source_id WHERE p.item_id <> s.item_id) AS crossed`);
    expect(rows[0].orphan_items).toBe(0);
    expect(rows[0].crossed).toBe(0);
    const saved = steps.filter((s) => s.method === "POST" && s.path === "/api/estimates" && s.status === 201).length;
    expect(rows[0].estimates).toBe(saved);
    const basic = results.est_basic as { id: string };
    const counts = await pool.query(
      `SELECT count(DISTINCT p.id)::int AS sources, count(DISTINCT s.source_id)::int AS selected
       FROM demo_estimate_items i JOIN demo_price_sources p ON p.item_id = i.id
       LEFT JOIN demo_selected_sources s ON s.item_id = i.id WHERE i.estimate_id = $1`,
      [basic.id],
    );
    expect(counts.rows[0]).toEqual({ sources: 4, selected: 3 });
  });
});
