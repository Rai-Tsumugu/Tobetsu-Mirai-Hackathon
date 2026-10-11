// DB 層の結合テスト。TEST_DATABASE_URL の PostgreSQL に使い捨てのデータベースを作って実行し、最後に消す。
// TEST_DATABASE_URL がなければスキップする（本番の DATABASE_URL は使わない）。
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { DataValidationError } from "../../lib/db/errors";
import { migrate, readMigrations } from "../../lib/db/migrate";
import { transaction } from "../../lib/db/queryable";
import * as items from "../../lib/db/repositories/items";
import * as manHours from "../../lib/db/repositories/man-hours";
import * as masters from "../../lib/db/repositories/masters";
import * as quotes from "../../lib/db/repositories/quotes";
import { seedDemoData } from "../../lib/db/seed";

const adminUrl = process.env.TEST_DATABASE_URL;
const appRoot = path.resolve(__dirname, "../..");
const databaseName = `webapp_test_${randomUUID().replaceAll("-", "")}`;

let admin: Pool;
let pool: Pool;

describe.skipIf(!adminUrl)("DB 層", () => {
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

  describe("マイグレーション・シード", () => {
    it("2回目は何も適用せず、シードも重複しない", async () => {
      expect(await migrate(pool, await readMigrations(path.join(appRoot, "db/migrations")))).toEqual([]);
      await seedDemoData(pool, path.resolve(appRoot, "../30-algorithm/integrated/data"));
      const { rows } = await pool.query("SELECT count(*)::int AS n FROM item_prices WHERE item_code = 'demo-paint'");
      expect(rows[0].n).toBe(2);
    });

    it("/db-check が読む検証用の行がある", async () => {
      const { rows } = await pool.query("SELECT value, unit FROM db_display_check WHERE id = 1");
      expect(rows[0]).toEqual({ value: 1234, unit: "件" });
    });

    it("適用済みのマイグレーションの書き換えを止める", async () => {
      const migrations = await readMigrations(path.join(appRoot, "db/migrations"));
      migrations[0] = { ...migrations[0], sql: `${migrations[0].sql}\n-- changed` };
      await expect(migrate(pool, migrations)).rejects.toThrow("変更されています");
    });
  });

  describe("共有マスタ", () => {
    it("電子車検証の型式と初度登録年月から vehicle_key を作る", async () => {
      const vehicle = await masters.getVehicle(pool, "V-EX-2027-01-20");
      expect(vehicle?.vehicleKey).toBe("ABC-XYZ10/2014-01");
      const observations = await manHours.listVehicleObservations(pool, vehicle!.vehicleKey!);
      expect(observations.map((row) => row.recordCode)).toEqual(["R11"]);
    });

    it("作業と工程を順番どおりに返し、部分一致で検索できる", async () => {
      const job = await masters.getJob(pool, "J2");
      expect(job?.baseLaborHours).toBe("1.4");
      expect(job?.operations[0]).toEqual({ operationCode: "OP-LIFT", hours: "0.1", shared: true });
      expect((await masters.listJobs(pool, "ブレーキ")).map((row) => row.jobCode)).toEqual(["J2", "JOB-DEMO-01"]);
      expect(await masters.listJobs(pool, "%")).toEqual([]);
    });
  });

  describe("工数", () => {
    it("採用中の補正表 v1 と現行の工場パラメータを返す", async () => {
      const table = await manHours.getRateTable(pool);
      expect(table?.rateTableCode).toBe("v1");
      expect(table?.entries.find((entry) => entry.operationCode === "PRE-SNOW")?.hours).toEqual({
        low: "0.1",
        typical: "0.15",
        high: "0.25",
      });
      expect((await manHours.getCurrentShopParameters(pool))?.params).toHaveProperty("rate_update_rule");
    });

    it("候補の補正表は承認するまで使わず、承認すると前の採用版は retired になる", async () => {
      await manHours.createRateTable(pool, {
        rateTableCode: "v2-test",
        entries: [{ operationCode: "FX-SEIZE", hours: { low: "0.1", typical: "0.15", high: "0.2" } }],
      });
      expect((await manHours.getRateTable(pool))?.rateTableCode).toBe("v1");
      await manHours.adoptRateTable(pool, "v2-test", "mechanic-demo-01");
      expect((await manHours.getRateTable(pool))?.rateTableCode).toBe("v2-test");
      expect((await manHours.getRateTable(pool, "v1"))?.status).toBe("retired");
      await manHours.adoptRateTable(pool, "v1", "mechanic-demo-01");
    });

    it("原因タグを1単位あたりの人時にして、件数の足りるタグだけ最小・中央値・最大を出す", async () => {
      const summaries = await manHours.summarizeTagSamples(pool, 3);
      const seize = summaries.find((row) => row.tag === "固着対応");
      expect(seize).toBeDefined();
      expect(seize!.sampleCount).toBeGreaterThanOrEqual(3);
      const values = seize!.perUnitHours.values.map(Number);
      expect(values).toEqual([...values].sort((a, b) => a - b));
      expect(Number(seize!.perUnitHours.low)).toBe(values[0]);
      expect(Number(seize!.perUnitHours.high)).toBe(values.at(-1));
    });

    it("計算結果は追記だけで、書き換えられない", async () => {
      const estimateId = await manHours.saveManHourEstimate(pool, {
        caseId: "EX-2027-01-20",
        parameterVersion: (await manHours.getCurrentShopParameters(pool))!.version,
        rateTableCode: "v1",
        personHours: { low: "2.1", typical: "2.9", high: "4.3" },
        elapsedHours: { low: "2.5", typical: "3.6", high: "5.4" },
        result: { note: "test" },
      });
      expect((await manHours.getLatestManHourEstimate(pool, "EX-2027-01-20"))?.estimateId).toBe(estimateId);
      await expect(pool.query("UPDATE man_hour_estimates SET result = '{}'")).rejects.toThrow("追記専用");
    });

    it("人時の帯が low <= typical <= high でなければ保存しない", async () => {
      await expect(
        manHours.saveManHourEstimate(pool, {
          caseId: "EX-2027-01-20",
          parameterVersion: (await manHours.getCurrentShopParameters(pool))!.version,
          rateTableCode: "v1",
          personHours: { low: "3", typical: "2", high: "4" },
          result: {},
        }),
      ).rejects.toThrow();
    });
  });

  describe("品目単価", () => {
    it("基準日に適用する承認済みの版を、valid_from と追記順で選ぶ", async () => {
      const base = {
        item: { itemCode: "t-paint", name: "テスト塗料", category: "塗料" as const, unit: "ml" },
        priceType: "販売" as const,
        source: "simulator:test",
        confirmedBy: "架空デモ担当",
        reason: "テスト",
      };
      await items.registerItemPrice(pool, { ...base, unitPrice: "100", updatedOn: "2026-10-01" });
      await items.registerItemPrice(pool, { ...base, unitPrice: "130", updatedOn: "2026-11-01" });
      await items.registerItemPrice(pool, { ...base, unitPrice: "999", updatedOn: "2026-10-15", status: "pending" });
      expect((await items.getEffectivePrice(pool, "t-paint", "販売", { asOf: "2026-10-20" })).unitPrice).toBe("100");
      expect((await items.getEffectivePrice(pool, "t-paint", "販売", { asOf: "2026-11-01" })).unitPrice).toBe("130");
      await expect(items.getEffectivePrice(pool, "t-paint", "販売", { asOf: "2026-09-30" })).rejects.toThrow("価格未確認");
      await expect(items.getEffectivePrice(pool, "t-paint", "販売", { asOf: "2026-11-01", unit: "L" })).rejects.toThrow("単位不一致");
    });

    it("品目の名称・分類・単位は単価の更新で変えられない", async () => {
      await expect(
        items.registerItemPrice(pool, {
          item: { itemCode: "t-paint", name: "改名", category: "塗料", unit: "ml" },
          unitPrice: "1",
          priceType: "販売",
          source: "simulator:test",
          updatedOn: "2026-12-01",
          confirmedBy: "架空デモ担当",
          reason: "テスト",
        }),
      ).rejects.toBeInstanceOf(DataValidationError);
    });

    it("複数の仕入先に価格があれば、仕入先の選択を求める", async () => {
      await pool.query("INSERT INTO suppliers (supplier_code, name) VALUES ('S-A', 'A'), ('S-B', 'B')");
      for (const supplierCode of ["S-A", "S-B"]) {
        await items.registerItemPrice(pool, {
          item: { itemCode: "t-solvent", name: "テスト溶剤", category: "溶剤", unit: "L" },
          unitPrice: supplierCode === "S-A" ? "500" : "520",
          priceType: "仕入",
          supplierCode,
          source: "simulator:test",
          updatedOn: "2026-10-01",
          confirmedBy: "架空デモ担当",
          reason: "テスト",
        });
      }
      await expect(items.getEffectivePrice(pool, "t-solvent", "仕入", { asOf: "2026-10-11" })).rejects.toThrow("仕入先の選択");
      expect((await items.getEffectivePrice(pool, "t-solvent", "仕入", { asOf: "2026-10-11", supplierCode: "S-B" })).unitPrice).toBe("520");
    });

    it("単価の版は書き換えられない", async () => {
      await expect(pool.query("UPDATE item_prices SET unit_price = 0")).rejects.toThrow("追記専用");
    });

    it("確認状況の一覧で、確認日のない版を『未確認』にする", async () => {
      const inventory = await items.priceInventory(pool, "2026-10-11");
      const paint = inventory.find((row) => row.itemCode === "demo-paint" && row.priceType === "販売");
      expect(paint?.freshness).toBe("未確認");
      expect(paint?.issues).toEqual(["価格確認日不明"]);
    });

    it("取込候補は承認で単価の版になり、1件でも不備があれば何も承認しない", async () => {
      const parsed = (code: string): items.ImportedPrice => ({
        item: { itemCode: code, name: `取込品 ${code}`, category: "消耗品", unit: "枚" },
        unitPrice: "30",
        priceType: "仕入",
        source: "CSV取込",
        updatedOn: "2026-10-11",
      });
      const candidates = await items.stageImportBatch(pool, {
        batchId: "batch-1",
        source: "CSV取込",
        rows: [
          { raw: { row: 1 }, parsed: parsed("imp-1") },
          { raw: { row: 2 }, parsed: parsed("imp-2"), issues: ["単価を確認"] },
        ],
      });
      await expect(
        items.approveImportCandidates(pool, {
          batchId: "batch-1",
          candidateIds: candidates.map((row) => row.candidateId),
          confirmedBy: "架空デモ担当",
        }),
      ).rejects.toThrow("確認が必要");
      expect(await items.listPriceVersions(pool, { itemCode: "imp-1" })).toEqual([]);

      const [approved] = await items.approveImportCandidates(pool, {
        batchId: "batch-1",
        candidateIds: [candidates[0].candidateId],
        confirmedBy: "架空デモ担当",
      });
      expect(approved.unitPrice).toBe("30");
      const after = await items.listImportCandidates(pool, "batch-1");
      expect(after[0]).toMatchObject({ status: "approved", priceVersionId: approved.priceVersionId });
      await expect(items.stageImportBatch(pool, { batchId: "batch-1", source: "CSV取込", rows: [] })).rejects.toThrow("既存バッチ");
    });

    it("配合は保存のたびに新しい版になる", async () => {
      const input = {
        formulaCode: "F-1",
        baseQuantity: "100",
        baseUnit: "ml",
        components: [{ itemCode: "demo-paint", quantity: "80", unit: "ml" }],
        confirmedBy: "架空デモ担当",
      };
      expect(await items.saveFormula(pool, input)).toBe(1);
      expect(await items.saveFormula(pool, { ...input, baseQuantity: "200" })).toBe(2);
      expect((await items.getFormula(pool, "F-1"))?.baseQuantity).toBe("200");
    });
  });

  describe("見積", () => {
    const band = (low: string, typical: string, high: string) => ({ low, typical, high });

    it("版を追記し、旧版をそのまま残す。単価の版を行から参照する", async () => {
      const price = await items.getEffectivePrice(pool, "SIM-PART-001", "販売", { asOf: "2026-10-11" });
      const base: quotes.QuoteVersionInput = {
        quoteId: "Q-1",
        origin: "quote",
        customerRef: "C-DEMO-01",
        vehicleRef: "V-DEMO-01",
        jobCode: "JOB-DEMO-01",
        status: "proposed",
        subtotal: band("9000", "13000", "21000"),
        tax: band("900", "1300", "2100"),
        total: band("9900", "14300", "23100"),
        snapshot: { quote_id: "Q-1" },
        lines: [
          {
            lineId: "labor-1",
            kind: "labor",
            description: "架空: デモ作業",
            unit: "人時",
            quantity: band("1", "1.5", "2.5"),
            unitPrice: 8000,
            amount: band("8000", "12000", "20000"),
            sourceSystem: "man_hours",
            status: "proposed",
          },
          {
            lineId: "part-1",
            kind: "parts",
            description: "架空: 販売部品",
            unit: "個",
            quantity: 1,
            unitPrice: price.unitPrice,
            amount: price.unitPrice,
            sourceSystem: "items",
            priceVersionId: price.priceVersionId,
            status: "proposed",
          },
        ],
      };
      const v1 = await quotes.saveQuoteVersion(pool, base);
      expect(v1.versionNo).toBe(1);
      expect(v1.lines[1]).toMatchObject({ itemCode: "SIM-PART-001", quantity: band("1", "1", "1") });

      const v2 = await quotes.saveQuoteVersion(pool, {
        ...base,
        parentVersionNo: 1,
        status: "confirmed",
        selectedBand: "typical",
        confirmedBy: "operator-demo-01",
        finalAmount: "15000",
        overrideReason: "架空: 端数を調整",
      });
      expect(v2.versionNo).toBe(2);
      expect((await quotes.getQuoteVersion(pool, "Q-1", 1))?.status).toBe("proposed");
      expect((await quotes.listQuotes(pool, { customerRef: "C-DEMO-01" })).map((row) => row.versionNo)).toEqual([2]);
      await expect(quotes.saveQuoteVersion(pool, { ...base, versionNo: 2 })).rejects.toThrow("保存済み");
    });

    it("確定額を帯の合計から変えるときは理由がないと保存しない", async () => {
      await expect(
        quotes.saveQuoteVersion(pool, {
          quoteId: "Q-2",
          origin: "quote",
          status: "confirmed",
          selectedBand: "typical",
          confirmedBy: "operator-demo-01",
          subtotal: band("1", "2", "3"),
          tax: band("0", "0", "0"),
          total: band("1", "2", "3"),
          finalAmount: "5",
          snapshot: {},
          lines: [],
        }),
      ).rejects.toThrow();
      expect(await quotes.getQuoteVersion(pool, "Q-2")).toBeUndefined();
    });

    it("行の保存に失敗したら、版も見出しも残さない", async () => {
      await expect(
        quotes.saveQuoteVersion(pool, {
          quoteId: "Q-3",
          origin: "items",
          status: "calculated",
          subtotal: band("0", "0", "0"),
          tax: band("0", "0", "0"),
          total: band("0", "0", "0"),
          snapshot: {},
          lines: [
            {
              lineId: "x",
              kind: "materials",
              description: "不正な単価の版",
              unit: "ml",
              quantity: 1,
              unitPrice: 1,
              amount: 1,
              sourceSystem: "items",
              priceVersionId: randomUUID(),
              status: "proposed",
            },
          ],
        }),
      ).rejects.toThrow("単価の版がありません");
      const { rows } = await pool.query("SELECT 1 FROM quotes WHERE quote_id = 'Q-3'");
      expect(rows).toEqual([]);
    });

    it("説明と変更の記録を版ごとに追記する", async () => {
      await quotes.appendCommunication(pool, {
        communicationId: "comm-1",
        quoteId: "Q-1",
        versionNo: 2,
        payload: { told_amount: 15000 },
        recordedBy: "operator-demo-01",
      });
      await quotes.appendChangeEvent(pool, { eventId: "chg-1", quoteId: "Q-1", fromVersion: 1, toVersion: 2, payload: {} });
      expect(await quotes.listCommunications(pool, "Q-1", 1)).toEqual([]);
      expect((await quotes.listCommunications(pool, "Q-1", 2)).map((row) => row.communicationId)).toEqual(["comm-1"]);
      expect((await quotes.listChangeEvents(pool, "Q-1")).map((row) => row.eventId)).toEqual(["chg-1"]);
      await expect(pool.query("DELETE FROM quote_communications")).rejects.toThrow("追記専用");
    });

    it("実使用量は選んだ帯の数量との差を記録し、見積は変えない", async () => {
      const usage = await quotes.recordMaterialUsage(pool, {
        quoteId: "Q-1",
        lineId: "labor-1",
        actualQuantity: "2",
        reason: "架空: 固着で延長",
        confirmedBy: "架空デモ担当",
      });
      expect(usage).toMatchObject({ versionNo: 2, estimatedQuantity: "1.5", actualQuantity: "2", difference: "0.5" });
      await expect(
        quotes.recordMaterialUsage(pool, {
          quoteId: "Q-1",
          versionNo: 1,
          lineId: "labor-1",
          actualQuantity: "2",
          reason: "x",
          confirmedBy: "架空デモ担当",
        }),
      ).rejects.toThrow("帯を選んだ版");
    });

    it("下書きは上書きでき、プリセットは別名で検索できる", async () => {
      await quotes.saveDraft(pool, { draftId: "d-1", step: 1, payload: { a: 1 } });
      await quotes.saveDraft(pool, { draftId: "d-1", step: 2, payload: { a: 2 } });
      expect(await quotes.getDraft(pool, "d-1")).toMatchObject({ step: 2, payload: { a: 2 } });
      expect((await quotes.searchJobPresets(pool, "パッド")).map((row) => row.presetId)).toEqual(["PRESET-DEMO-01"]);
    });
  });

  describe("トランザクション", () => {
    it("入れ子はセーブポイントになり、内側の失敗だけを取り消せる", async () => {
      await transaction(pool, async (tx) => {
        await masters.upsertStaff(tx, { staffCode: "outer", displayName: "外側", isSimulator: true });
        await expect(
          transaction(tx, async (inner) => {
            await masters.upsertStaff(inner, { staffCode: "inner", displayName: "内側", isSimulator: true });
            throw new Error("rollback inner");
          }),
        ).rejects.toThrow("rollback inner");
      });
      const { rows } = await pool.query("SELECT staff_code FROM staff WHERE staff_code IN ('outer', 'inner')");
      expect(rows.map((row) => row.staff_code)).toEqual(["outer"]);
    });
  });
});
