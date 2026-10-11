// Neon（PostgreSQL）上の PgStore でも、ゴールデン照合の全シナリオが元の Python と同じ結果になることを確かめる。
// TEST_DATABASE_URL のサーバーに使い捨てのデータベースを作り、シナリオごとに BEGIN〜ROLLBACK で実行して最後に消す。
// TEST_DATABASE_URL がなければスキップする。
import { randomUUID } from "node:crypto";
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { migrate, readMigrations } from "../../../lib/db/migrate";
import { Transaction, type PoolClientLike } from "../../../lib/db/queryable";
import { PgStore } from "../../../lib/systems/items/pg-store";
import { comparable, GOLDEN_DIR, loadGolden, loadModule, runScenario } from "./harness";

const adminUrl = process.env.TEST_DATABASE_URL;
const appRoot = path.resolve(__dirname, "../../..");
const databaseName = `items_test_${randomUUID().replaceAll("-", "")}`;

let admin: Pool;
let pool: Pool;

const names = readdirSync(path.join(GOLDEN_DIR, "scenarios"))
  .filter((file) => file.endsWith(".json"))
  .map((file) => file.replace(/\.json$/, ""))
  .filter((name) => existsSync(path.join(GOLDEN_DIR, `${name}.json`)))
  .filter((name) => !process.env.ITEMS_PG_ONLY || process.env.ITEMS_PG_ONLY.split(",").includes(name))
  .sort();

async function withRollback<T>(fn: (store: PgStore, client: PoolClientLike) => Promise<T>): Promise<T> {
  const client = (await pool.connect()) as unknown as PoolClientLike;
  try {
    await client.query("BEGIN");
    return await fn(new PgStore(new Transaction(client)), client);
  } finally {
    await client.query("ROLLBACK").catch(() => undefined);
    client.release();
  }
}

describe.skipIf(!adminUrl)("auto_repair_items PgStore（Neon）", () => {
  beforeAll(async () => {
    admin = new Pool({ connectionString: adminUrl });
    await admin.query(`CREATE DATABASE ${databaseName}`);
    const url = new URL(adminUrl!);
    url.pathname = `/${databaseName}`;
    pool = new Pool({ connectionString: url.toString(), max: 4 });
    await migrate(pool, await readMigrations(path.join(appRoot, "db/migrations")));
  }, 120000);

  afterAll(async () => {
    await pool?.end();
    await admin?.query(`DROP DATABASE IF EXISTS ${databaseName} WITH (FORCE)`);
    await admin?.end();
  });

  for (const name of names) {
    describe(name, () => {
      const golden = loadGolden(name);
      for (const scenario of golden.scenarios) {
        it(scenario.name, async () => {
          const outcomes = await withRollback((store) => runScenario(scenario.steps, scenario.expected, store));
          const { expected, actual } = comparable(outcomes);
          for (let i = 0; i < expected.length; i += 1) {
            expect(actual[i], `${name} / ${scenario.name} / step ${i} (${scenario.steps[i].op})`).toEqual(expected[i]);
          }
        }, 120000);
      }
    });
  }

  it("見積スナップショット・実使用量・単位換算を既存の表に写す", async () => {
    await withRollback(async (store, client) => {
      const { run: m30 } = await loadModule("M30");
      const { run: m23 } = await loadModule("M23");
      const { run: m02 } = await loadModule("M02");
      await store.addPrice(
        { item_id: "paint-a", name: "塗料A", category: "塗料", unit: "ml", unit_price: "120", price_type: "販売", source: "simulator:架空値", updated_at: "2026-10-11" },
        "価格承認者",
      );
      const saved = (await m30(
        { action: "save", quote_id: "q-pg", confirmed_by: "見積担当", lines: [{ quote_line_id: "l1", item_id: "paint-a", quantity: "2.5", unit: "ml", price_type: "販売" }] },
        store,
      )) as { quote: { lines: { price_version_id: string }[] } };
      await m23({ action: "record", quote_id: "q-pg", quote_line_id: "l1", actual_qty: "2.25", reason: "実績", confirmed_by: "整備士" }, store);
      const version = await client.query(
        `SELECT v.version_no, v.subtotal_typical::text AS subtotal, v.confirmed_by, q.origin,
                l.line_id, l.kind, l.quantity_typical::text AS quantity, l.amount_typical::text AS amount,
                l.item_code, l.price_version_id::text AS price_version_id
           FROM quotes q JOIN quote_versions v USING (quote_id) JOIN quote_lines l USING (quote_id, version_no)
          WHERE q.quote_id = 'q-pg'`,
      );
      expect(version.rows).toEqual([
        {
          version_no: 1,
          subtotal: "300.0",
          confirmed_by: "見積担当",
          origin: "items",
          line_id: "l1",
          kind: "materials",
          quantity: "2.5",
          amount: "300.0",
          item_code: "paint-a",
          price_version_id: saved.quote.lines[0].price_version_id,
        },
      ]);
      const usage = await client.query(
        `SELECT line_id, estimated_quantity::text AS estimated, actual_quantity::text AS actual, difference::text AS difference
           FROM material_usages WHERE quote_id = 'q-pg'`,
      );
      expect(usage.rows).toEqual([{ line_id: "l1", estimated: "2.5", actual: "2.25", difference: "-0.25" }]);

      await store.addPrice(
        { item_id: "can-a", name: "缶A", category: "塗料", unit: "缶", unit_price: "1000", price_type: "仕入", source: "simulator:架空値", updated_at: "2026-10-11" },
        "価格承認者",
      );
      await m02(
        { item_id: "can-a", source_unit: "缶", base_unit: "個", factor: "4", evidence: "simulator:架空", quantity: "1", price_type: "仕入", confirmed_by: "担当" },
        store,
      );
      const conversion = await client.query(
        `SELECT item_code, from_unit, to_unit, factor::text AS factor, confirmed_by FROM unit_conversions WHERE item_code = 'can-a'`,
      );
      expect(conversion.rows).toEqual([{ item_code: "can-a", from_unit: "缶", to_unit: "個", factor: "4", confirmed_by: "担当" }]);
    });
  }, 120000);

  it("ほかのシステムが登録した単価の版も元の形で読める", async () => {
    await withRollback(async (store, client) => {
      await client.query(`INSERT INTO staff (staff_code, display_name) VALUES ('架空デモ担当', '架空デモ担当')`);
      const items = await import("../../../lib/db/repositories/items");
      const tx = new Transaction(client);
      await items.registerItemPrice(tx, {
        item: { itemCode: "demo-paint", name: "架空サンプル塗料", category: "塗料", unit: "ml" },
        unitPrice: "120",
        priceType: "販売",
        source: "simulator:架空値",
        updatedOn: "2026-10-11",
        confirmedBy: "架空デモ担当",
        reason: "初回登録",
      });
      const version = await store.getPrice("demo-paint");
      expect({ ...version, price_version_id: "x" }).toEqual({
        price_version_id: "x",
        item: {
          item_id: "demo-paint",
          name: "架空サンプル塗料",
          category: "塗料",
          unit: "ml",
          unit_price: "120",
          price_type: "販売",
          source: "simulator:架空値",
          updated_at: "2026-10-11",
        },
        confirmed_by: "架空デモ担当",
        supplier_id: "",
        valid_from: "2026-10-11",
        valid_until: null,
        status: "approved",
        reason: "初回登録",
        metadata: {},
      });
    });
  }, 120000);
});
