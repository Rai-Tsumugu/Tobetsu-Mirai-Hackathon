/* eslint-disable @typescript-eslint/no-explicit-any */
// 元のテスト（test_e04/e05/e06）の流れを TS で再現し、出力を元の Python 実装のものと照合する。
import { beforeEach, describe, expect, it } from "vitest";
import { approvedCommonScenarioFixture, commonScenarioFixture } from "../../../lib/systems/engine/contract";
import * as e04 from "../../../lib/systems/engine/e04";
import * as e05 from "../../../lib/systems/engine/e05";
import * as e06 from "../../../lib/systems/engine/e06";
import * as e11 from "../../../lib/systems/engine/e11";
import { PyIntegrityError, deepcopy, pyErrorName } from "../../../lib/systems/engine/py";
import { resetEngineState } from "../../../lib/systems/engine/runner";
import { E05_CSV, e04Pack, e06FixturePackPayload, golden } from "./fixtures";
import { normalize } from "./normalize";

const scripted = golden("scripted.json");
const same = (actual: any, expected: any) => expect(normalize(actual)).toEqual(normalize(expected));
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

beforeEach(() => resetEngineState());

describe("E04 (in-memory normalized store)", () => {
  it("replays pinned versions", () => {
    const db = e04.createDatabase();
    e04.seedDefaultRulePack(db);
    const scenario = approvedCommonScenarioFixture();
    const original = e04.run(scenario, null, db);
    e04.publishRulePack(db, e04Pack("fictional-rule-v2", 0.2));
    scenario.rule_version = "fictional-rule-v2";
    const changed = e04.run(scenario, null, db);
    const old = e04.run(approvedCommonScenarioFixture(), null, db);
    same({ original, changed, old_after_v2: old }, scripted.e04_replay);
    expect(changed.labor.person_hours.typical).toBe(2.23);
    expect(changed.labor.elapsed_hours.typical).toBe(2.88);
  });

  it("stops when the stored rotor range differs from the approval", () => {
    const db = e04.createDatabase();
    e04.seedDefaultRulePack(db, "fictional-rule-v1");
    const pack = e04Pack("fictional-rule-v2");
    pack.rules.find((r: any) => r.operation_id === "rotor_seizure").hours = { low: 8, typical: 8, high: 8 };
    e04.publishRulePack(db, pack);
    const scenario = approvedCommonScenarioFixture();
    scenario.rule_version = "fictional-rule-v2";
    same(e04.run(scenario, null, db), scripted.e04_rotor_mismatch);
  });

  it("rolls back a duplicate publish without a partial rule version", () => {
    const db = e04.createDatabase();
    const pack = e04Pack("fictional-duplicate");
    pack.rules.push(deepcopy(pack.rules[pack.rules.length - 1]));
    let msg = "";
    try {
      e04.publishRulePack(db, pack);
    } catch (e) {
      msg = message(e);
    }
    same({ message: msg, counts: [db.rules.length, db.ruleOperations.length, db.operations.length, db.evidence.length] }, scripted.e04_duplicate_publish);
  });

  it("rejects update and delete of published rows", () => {
    const db = e04.createDatabase();
    e04.seedDefaultRulePack(db, "fictional-rule-v1");
    for (const table of ["rules", "operations", "rule_operations", "evidence"] as const) {
      for (const kind of ["update", "delete"] as const) {
        expect(() => db.tamper(table, kind)).toThrow(PyIntegrityError);
      }
    }
    expect(e04.run(approvedCommonScenarioFixture(), null, db).labor.person_hours.typical).toBe(2.13);
    expect(() => e04.publishRulePack(db, e04Pack("fictional-rule-v2", 0.2))).not.toThrow();
  });

  it("rejects orphan rule operations and evidence (foreign keys)", () => {
    const db = e04.createDatabase();
    e04.seedDefaultRulePack(db);
    expect(() => db.insertRuleOperation("missing", "v1", "wash", 0.1, 0.1, 0.1, 1)).toThrow(PyIntegrityError);
    expect(() => db.insertEvidence("orphan", "fictional_labor_rules", "fictional-rule-v1", "missing", "fictional", "")).toThrow(PyIntegrityError);
    expect(pyErrorName(new PyIntegrityError("x"))).toBe("IntegrityError");
  });
});

describe("E05 (CSV import)", () => {
  it("parses and validates CSV input", () => {
    const encoder = new TextEncoder();
    const out: any = {};
    const toJson = (b: e05.ImportBatch) => ({ hash: b.hash, rows: b.rows.map((r) => ({ ...r })), errors: b.errors });
    out.fixture_bytes = toJson(e05.parseCsv(encoder.encode(E05_CSV)));
    out.fixture_errors = e05.validateUnits(e05.parseCsv(E05_CSV));
    out.preview = e05.previewDiff(e05.parseCsv(E05_CSV));
    const malformed = E05_CSV.replace("1.7,1.7,1.7,person_hours,fixture:base", "nan,-1,2,elapsed_hours,fixture:base").replace("front_brake_service,wash,", "front_brake_service,mystery_step,");
    out.malformed_batch_errors = e05.parseCsv(malformed).errors;
    out.malformed_validate = e05.validateUnits(e05.parseCsv(malformed));
    out.wrong_unit = e05.validateUnits(e05.parseCsv(E05_CSV.replace("0.5,0.5,0.5,elapsed_hours,fixture:snow", "0.5,0.5,0.5,person_hours,fixture:snow")));
    out.duplicate = e05.validateUnits(e05.parseCsv(E05_CSV + "front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fixture:wash2,duplicate\n"));
    out.bad_boolean = e05.validateUnits(e05.parseCsv(E05_CSV.replace("parts_wait_stock_checked,true,", "parts_wait_stock_checked,perhaps,")));
    out.misaligned = e05.validateUnits(e05.parseCsv(E05_CSV.replace("0,0.25,0.5", "0.5,0.25,0.1")));
    const odd = [
      "", "\n", "a,b\n", "job_id,operation_key\n1,2\n", "﻿" + E05_CSV,
      E05_CSV.replace(/\n/g, "\r\n"), E05_CSV.replace(/\n/g, "\r"), E05_CSV + "\n\n",
      E05_CSV.replace("fixture:base,base work", '"fixture:base","base, work"'),
      E05_CSV.replace("fixture:base,base work", '"fixture:base","base ""quoted"" work"'),
      E05_CSV.replace("fixture:base,base work", '"fixture:base","multi\nline"'),
      E05_CSV.replace(/\n+$/, "").replace("person_hours,fixture:wash,performed wash", "person_hours,fixture:wash") + "\n",
      E05_CSV.replace("fixture:carry,replacement handling", "fixture:carry,replacement handling,EXTRA"),
      E05_CSV.replace("job_id,operation_key", " job_id , operation_key"),
      E05_CSV.replace("1.7,1.7,1.7", " 1.7 , 1.7 ,1.7"),
      E05_CSV.replace("1.7,1.7,1.7", "1e0,+1.7,inf"),
      E05_CSV.replace("1.7,1.7,1.7", "abc,1.7,1.7"),
      E05_CSV.replace("1.7,1.7,1.7", ",,"),
      '"job_id","operation_key"\n"a,"b"c"\n',
      "x\n\n\ny\n",
      E05_CSV + '"unterminated,quoted\n',
    ];
    out.odd = odd.map((t) => toJson(e05.parseCsv(t)));
    out.invalid_utf8 = toJson(e05.parseCsv(new Uint8Array([0xff, 0xfe, 0x00])));
    same(out, scripted.e05_parse_and_validate);
  });

  it("publishes immutable snapshots and replays them", () => {
    const publish = (csv = E05_CSV, version = "e05-test-v1", previous: e05.PublishedRulePack | null = null) =>
      e05.humanPublish(e05.parseCsv(csv), "fixture_reviewer", "fixture approval reason", version, "2026-10-11T00:00:00+00:00", "person_hour",
        "架空の整備作業範囲。含有運搬を除き、承認済み作業行を人時で集計する", previous);
    const packJson = (p: e05.PublishedRulePack) => ({
      engine_id: p.engine_id, rule_version: p.rule_version, effective_from: p.effective_from, source: p.source, basis_unit: p.basis_unit,
      basis_definition: p.basis_definition, import_hash: p.import_hash, snapshot_hash: p.snapshot_hash, approved_by: p.approved_by,
      approval_reason: p.approval_reason, rules: p.rules.map((r) => ({ ...r })), audit: p.audit.map((a) => ({ ...a })),
    });
    const out: any = {};
    const scenario = approvedCommonScenarioFixture();
    const baselinePack = publish(E05_CSV, "e05-baseline-test-v1");
    out.baseline_pack = packJson(baselinePack);
    scenario.rule_version = baselinePack.rule_version;
    out.baseline = e05.run(deepcopy(scenario), baselinePack);
    const changedCsv = E05_CSV.replace("1.7,1.7,1.7", "2.0,2.0,2.0");
    const nextPack = publish(changedCsv, "e05-changed-test-v1", baselinePack);
    out.next_pack = packJson(nextPack);
    out.replay = e05.run(deepcopy(scenario), baselinePack);
    const changedScenario = deepcopy(scenario);
    changedScenario.rule_version = nextPack.rule_version;
    out.changed = e05.run(changedScenario, nextPack);
    const attrCsv = E05_CSV.replace("front_brake_service,base_service,work_scope,front_brake_service,", "other,base_service,work_scope,front_brake_service,");
    out.attr_preview = e05.previewDiff(e05.parseCsv(attrCsv), baselinePack);
    out.attr_pack = packJson(publish(attrCsv, "e05-attr-next-test-v1", baselinePack));
    out.source_preview = e05.previewDiff(e05.parseCsv(E05_CSV.replace("fixture:base", "fixture:base-v2")), baselinePack);
    const wrong = deepcopy(scenario);
    wrong.rule_version = "different-version";
    out.version_gate = e05.run(wrong, baselinePack);
    const forged = e05.replacePack(baselinePack, { import_hash: "f".repeat(64), snapshot_hash: "a".repeat(64), audit: [] });
    out.forged = e05.run(deepcopy(scenario), forged);
    const errs: any = {};
    const attempts: Record<string, () => unknown> = {
      actor: () => e05.humanPublish(e05.parseCsv(E05_CSV), " ", "reason", "v", "today", "person_hour", "fixture"),
      reason: () => e05.humanPublish(e05.parseCsv(E05_CSV), "reviewer", " ", "v", "today", "person_hour", "fixture"),
      version: () => e05.humanPublish(e05.parseCsv(E05_CSV), "reviewer", "r", " ", "today", "person_hour", "fixture"),
      effective: () => e05.humanPublish(e05.parseCsv(E05_CSV), "reviewer", "r", "v", "", "person_hour", "fixture"),
      basis: () => e05.humanPublish(e05.parseCsv(E05_CSV), "reviewer", "r", "v", "today", "", "fixture"),
      invalid: () => publish(E05_CSV.replace("parts_wait_stock_checked,true,", "parts_wait_stock_checked,perhaps,"), "e05-invalid-boolean-test-v1"),
      immutable: () => publish(E05_CSV.replace("1.7,1.7,1.7", "1.8,1.8,1.8"), baselinePack.rule_version),
    };
    for (const [name, call] of Object.entries(attempts)) {
      try {
        call();
        errs[name] = null;
      } catch (e) {
        errs[name] = message(e);
      }
    }
    out.errors = errs;
    out.same_again = packJson(publish(E05_CSV, "e05-baseline-test-v1"));
    same(out, scripted.e05_publish_flow);
    expect(out.baseline.labor.person_hours).toEqual({ low: 1.88, typical: 2.13, high: 2.38 });
  });
});

describe("E11 (independent comparison)", () => {
  it("compares methods and gates the audited selection", () => {
    const out: any = {};
    const scenario = approvedCommonScenarioFixture();
    const comparison = e11.compareMethods(scenario);
    out.comparison = comparison;
    out.chosen_a = e11.selectMethod(comparison, "A", "reviewer", "根拠の適用範囲を確認した");
    out.chosen_b = e11.selectMethod(comparison, "B", "reviewer", "ok");
    const tampered = deepcopy(comparison);
    tampered.runs[1].labor.person_hours = { low: 8, typical: 8, high: 8 };
    out.tampered = e11.selectMethod(tampered, "B", "human", "independently chose this run");
    out.no_actor = e11.selectMethod(comparison, "B", "", "why");
    const cleared = deepcopy(comparison);
    cleared.runs[1].labor.breakdown.length = 0;
    out.cleared = e11.selectMethod(cleared, "B", "human", "verified");
    const fresh = e11.compareMethods(scenario);
    out.input_binding = e11.selectMethod(fresh, "A", "human", "verified", { ...scenario, person_count: 999 });
    out.same_input = e11.selectMethod(fresh, "A", "human", "verified", scenario);
    out.wrong_version = e11.selectMethod(fresh, "A", "human", "verified", scenario, "wrong-version");
    out.absent = e11.selectMethod(comparison, "missing", "human", "reason");
    const incomplete = deepcopy(comparison);
    incomplete.runs[0].unknowns = ["evidence:missing"];
    const { comparison_hash: _h, ...rest } = incomplete;
    void _h;
    incomplete.comparison_hash = e11.hashOf(rest);
    out.incomplete = e11.selectMethod(incomplete, "A", "human", "reason");
    out.not_obj = e11.selectMethod([], "A", "h", "r");
    out.no_runs = e11.selectMethod({ runs: 5 }, "A", "h", "r");
    const badVersion = deepcopy(comparison);
    badVersion.runs[1].rule_version = "x";
    const { comparison_hash: _h2, ...rest2 } = badVersion;
    void _h2;
    badVersion.comparison_hash = e11.hashOf(rest2);
    out.selected_result_tampered = e11.selectMethod(badVersion, "B", "h", "r");
    out.with_version = e11.compareMethods(scenario, ["A", "B", "S05", "ZZ"], "fixture-r7");
    out.bad_methods = ["AB", [], ["A", "A"], [5], [""]].map((m) => e11.compareMethods(scenario, m));
    same(out, scripted.e11_flows);
    expect(out.chosen_a.selection.method).toBe("A");
    expect(out.tampered.labor.unknowns).toContain("comparison:payload_tampered");
  });
});

describe("E06 (approval lifecycle)", () => {
  it("publishes, audits and gates JSON packs", () => {
    const out: any = {};
    const scenario = approvedCommonScenarioFixture();
    out.default = e06.run(deepcopy(scenario));
    const fixturePack = () => e06.publishRulePack(e06FixturePackPayload(commonScenarioFixture()), "fictional_reviewer", "fixture rules approved", "2026-10-11", null);
    const pack = fixturePack();
    out.pack = pack;
    const changedPayload = deepcopy(pack);
    changedPayload.rule_version = "fictional-rule-v2";
    changedPayload.rules.find((r: any) => r.operation_key === "base_service").hours = { low: 1.9, typical: 1.9, high: 1.9 };
    delete changedPayload.payload_hash;
    const changed = e06.publishRulePack(changedPayload, "reviewer_2", "approved revised labor", "2026-10-11", pack);
    out.changed_pack = changed;
    const cs = deepcopy(scenario);
    cs.rule_version = changed.rule_version;
    out.revised = e06.run(cs, changed);
    const s2 = deepcopy(scenario);
    s2.rule_version = pack.rule_version;
    const stops: any[] = [];
    for (const mutate of [(p: any) => (p.status = "draft"), (p: any) => delete p.payload_hash, (p: any) => (p.rules[0].hours.typical = 99)]) {
      const bad = deepcopy(pack);
      mutate(bad);
      stops.push(e06.run(deepcopy(s2), bad));
    }
    out.stops = stops;
    const futurePayload = deepcopy(pack);
    delete futurePayload.payload_hash;
    futurePayload.rule_version = "fictional-e06-future-v1";
    const future = e06.publishRulePack(futurePayload, "reviewer", "scheduled future approval", "2027-01-01", pack);
    out.future = e06.run(deepcopy(s2), future);
    const wrong = deepcopy(s2);
    wrong.rule_version = "unpublished-v99";
    out.mismatch = e06.run(wrong, pack);
    const forged = deepcopy(pack);
    forged.rules[0].hours = { low: 8, typical: 8, high: 8 };
    forged.payload_hash = e06.payloadHash(forged);
    out.forged = e06.run(deepcopy(s2), forged);
    const revisedPayload = deepcopy(pack);
    delete revisedPayload.payload_hash;
    revisedPayload.rule_version = "fictional-e06-condition-v2";
    revisedPayload.rules.find((r: any) => r.operation_key === "base_service").condition = { field: "work_scope", equals: "different_job" };
    const revised = e06.publishRulePack(revisedPayload, "reviewer_3", "narrow rule applicability", "2026-10-11", pack);
    out.condition_pack = revised;
    const s3 = deepcopy(s2);
    s3.rule_version = revised.rule_version;
    out.condition_run = e06.run(s3, revised);
    const attrsPayload = deepcopy(pack);
    delete attrsPayload.payload_hash;
    attrsPayload.rule_version = "fictional-e06-pack-attrs-v2";
    attrsPayload.source = "fixture:reviewed-source";
    attrsPayload.basis_definition = "Revised fictional person-hour basis.";
    out.attrs_pack = e06.publishRulePack(attrsPayload, "reviewer_3", "clarify pack basis", "2026-10-12", pack);
    const changed2 = deepcopy(pack);
    changed2.rules[0].hours = { low: 2, typical: 2, high: 2 };
    const attempts: Record<string, () => unknown> = {
      immutable: () => e06.publishRulePack(changed2, "reviewer", "another change", "2026-10-11"),
      empty: () => e06.publishRulePack({ engine_id: e06.ENGINE_ID, rule_version: "fictional-e06-empty-v1", rules: [] }, "reviewer", "r", "2026-10-11"),
      actor: () => e06.publishRulePack(pack, " ", "r", "2026-10-11"),
      reason: () => e06.publishRulePack(pack, "a", "", "2026-10-11"),
      date: () => e06.publishRulePack(pack, "a", "r", "20261011x"),
      date_type: () => e06.publishRulePack(pack, "a", "r", 5),
      payload: () => e06.publishRulePack([], "a", "r", "2026-10-11"),
      version: () => e06.publishRulePack({ rules: [1] }, "a", "r", "2026-10-11"),
      mixed_keys: () => e06.publishRulePack({ rule_version: "mix", rules: [{ x: 1 }, { operation_key: "a" }] }, "a", "r", "2026-10-11"),
    };
    const errs: any = {};
    for (const [name, call] of Object.entries(attempts)) {
      try {
        call();
        errs[name] = null;
      } catch (e) {
        errs[name] = [pyErrorName(e), message(e)];
      }
    }
    out.errors = errs;
    expect(Object.keys(errs).length).toBe(9);
    same({ ...out, errors: Object.fromEntries(Object.entries(errs).map(([k, v]: any) => [k, v && v[0]])) },
      { ...scripted.e06_lifecycle, errors: Object.fromEntries(Object.entries(scripted.e06_lifecycle.errors).map(([k, v]: any) => [k, v && v[0]])), date_formats: undefined });
    expect(errs.immutable[1]).toBe("publish:published_version_is_immutable");
  });

  it("parses ISO dates like date.fromisoformat", async () => {
    const { isoDate } = await import("../../../lib/systems/engine/py");
    const expected = scripted.e06_lifecycle.date_formats as Record<string, string>;
    for (const [text, want] of Object.entries(expected)) {
      let got: string;
      try {
        const n = isoDate(text);
        got = `${String(Math.floor(n / 10000)).padStart(4, "0")}-${String(Math.floor(n / 100) % 100).padStart(2, "0")}-${String(n % 100).padStart(2, "0")}`;
      } catch (e) {
        got = pyErrorName(e);
      }
      expect(got, text).toBe(want);
    }
  });
});
