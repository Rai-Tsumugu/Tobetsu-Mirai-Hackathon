// seedItems（元の seed_demo）が何度実行しても同じ状態になることを確かめる。
// TEST_DATABASE_URL のサーバーに使い捨てのデータベースを作って実行し、最後に消す。なければスキップする。
import { randomUUID } from "node:crypto";
import path from "node:path";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrate, readMigrations } from "../../../lib/db/migrate";
import { transaction } from "../../../lib/db/queryable";
import { seedDemoData } from "../../../lib/db/seed";
import { PgStore } from "../../../lib/systems/items/pg-store";
import { seedItems } from "../../../lib/systems/items/seed";

const adminUrl = process.env.TEST_DATABASE_URL;
const appRoot = path.resolve(__dirname, "../../..");
const databaseName = `items_seed_${randomUUID().replaceAll("-", "")}`;

let admin: Pool;
let pool: Pool;

describe.skipIf(!adminUrl)("seedItems", () => {
  beforeAll(async () => {
    admin = new Pool({ connectionString: adminUrl });
    await admin.query(`CREATE DATABASE ${databaseName}`);
    const url = new URL(adminUrl!);
    url.pathname = `/${databaseName}`;
    pool = new Pool({ connectionString: url.toString() });
    await migrate(pool, await readMigrations(path.join(appRoot, "db/migrations")));
  }, 120000);

  afterAll(async () => {
    await pool?.end();
    await admin?.query(`DROP DATABASE IF EXISTS ${databaseName} WITH (FORCE)`);
    await admin?.end();
  });

  it("空の DB に架空塗料を入れ、2回目以降は何もしない", async () => {
    await transaction(pool, (tx) => seedItems(tx));
    await transaction(pool, (tx) => seedItems(tx));
    const versions = await transaction(pool, (tx) => new PgStore(tx).priceVersions("demo-paint"));
    expect(versions.map((version) => [version.item.price_type, version.item.unit_price, version.confirmed_by])).toEqual([
      ["仕入", "80", "架空デモ担当"],
      ["販売", "120", "架空デモ担当"],
    ]);
    // lib/db/seed.ts（共通のシード）と組み合わせても重複しない。
    await seedDemoData(pool, path.resolve(appRoot, "../30-algorithm/integrated/data"));
    await transaction(pool, (tx) => seedItems(tx));
    const { rows } = await pool.query("SELECT count(*)::int AS n FROM item_prices WHERE item_code = 'demo-paint'");
    expect(rows[0].n).toBe(2);
  }, 120000);
});
