// DB から組み立てたデータでも、同梱の JSON と同じ計算結果になることを確かめる。
// TEST_DATABASE_URL の PostgreSQL に使い捨てのデータベースを作って実行し、最後に消す。なければスキップする。
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrate, readMigrations } from "../../../lib/db/migrate";
import { seedDemoData } from "../../../lib/db/seed";
import {
  approveRateTable,
  estimateAndSave,
  getSavedEstimate,
  listRateTables,
  loadFromDatabase,
} from "../../../lib/db/repositories/man-hours-store";
import { estimate } from "../../../lib/systems/man-hours/estimator";
import type { Obj } from "../../../lib/systems/man-hours/python-compat";
import { loadJsonData } from "../../../lib/systems/man-hours/json-data";

const adminUrl = process.env.TEST_DATABASE_URL;
const appRoot = path.resolve(__dirname, "../../..");
const databaseName = `webapp_test_${randomUUID().replaceAll("-", "")}`;

let admin: Pool;
let pool: Pool;

describe.skipIf(!adminUrl)("工数エンジンのデータ取得（DB）", () => {
  beforeAll(async () => {
    admin = new Pool({ connectionString: adminUrl });
    await admin.query(`CREATE DATABASE ${databaseName}`);
    const url = new URL(adminUrl!);
    url.pathname = `/${databaseName}`;
    pool = new Pool({ connectionString: url.toString() });
    await migrate(pool, await readMigrations(path.join(appRoot, "db/migrations")));
    await seedDemoData(pool, path.resolve(appRoot, "../30-algorithm/integrated/data"));
  });

  afterAll(async () => {
    await pool?.end();
    await admin?.query(`DROP DATABASE IF EXISTS ${databaseName}`);
    await admin?.end();
  });

  it("DB から組み立てた入力は、JSON の入力と同じ結果になる", async () => {
    const json = loadJsonData();
    const db = await loadFromDatabase(pool, json.case.case_id);
    const fromJson = estimate(json.case, json.params, json.catalog, json.records);
    const fromDb = estimate(db.case, db.params, db.catalog, db.records);
    // jsonb で順が変わった辞書も restoreKeyOrder で戻るので、並びを含めて完全に一致する
    expect(fromDb).toEqual(fromJson);
  });

  it("計算結果を追記し、最新の結果を読める", async () => {
    const caseData = loadJsonData().case;
    const first = await estimateAndSave(pool, caseData, { createdBy: "mechanic-demo-01" });
    const second = await estimateAndSave(pool, caseData);
    expect(second.estimateId).not.toBe(first.estimateId);
    const saved = await getSavedEstimate(pool, caseData.case_id);
    expect((saved?.result as Obj).estimate.labor_hours).toEqual(first.result.estimate.labor_hours);
    const { rows } = await pool.query("SELECT count(*)::int AS n FROM man_hour_estimates WHERE case_id = $1", [caseData.case_id]);
    expect(rows[0].n).toBe(2);
  });

  it("存在しない入力はエラー", async () => {
    await expect(loadFromDatabase(pool, "no-such-case")).rejects.toThrow("no-such-case");
  });

  it("v2 の承認で、DB に候補を作って採用し、再計算の採用版が変わる", async () => {
    const caseData = loadJsonData().case;
    const before = await loadFromDatabase(pool, caseData.case_id);
    expect(before.params.adopted_rate_table).toBe("v1");
    expect((await listRateTables(pool)).map((t) => t.rateTableCode)).toEqual(["v1"]);

    expect(await approveRateTable(pool, "v2", "mechanic-demo-01")).toEqual({ adopted: "v2", created: true });
    const tables = Object.fromEntries((await listRateTables(pool)).map((t) => [t.rateTableCode, t.status]));
    expect(tables).toEqual({ v1: "retired", v2: "adopted" });

    const after = await loadFromDatabase(pool, caseData.case_id);
    expect(after.params.adopted_rate_table).toBe("v2");
    const result = estimate(after.case, after.params, after.catalog, after.records);
    expect(result.estimate.rate_table).toBe("v2");
    expect(result.estimate.labor_hours).toEqual(estimate(before.case, before.params, before.catalog, before.records).rates.candidate_labor_hours);

    // v2 を採用した状態でも、結果の保存が外部キー違反にならない
    const saved = await estimateAndSave(pool, caseData);
    expect(saved.result.estimate.rate_table).toBe("v2");

    // v1 に戻せる（すでにある版は作り直さない）
    expect(await approveRateTable(pool, "v1", "mechanic-demo-01")).toEqual({ adopted: "v1", created: false });
  });

  it("未知の版・未登録の承認者は採用できない", async () => {
    await expect(approveRateTable(pool, "v3", "mechanic-demo-01")).rejects.toThrow("v3");
    await expect(approveRateTable(pool, "v2", "nobody")).rejects.toThrow("nobody");
    await expect(approveRateTable(pool, "v2", " ")).rejects.toThrow("承認者");
  });
});
