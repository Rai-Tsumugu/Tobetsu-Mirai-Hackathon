/* eslint-disable @typescript-eslint/no-explicit-any */
// 元のテスト（test_e04/e05/e06）の流れを TS で再現し、出力を元の Python 実装のものと照合する。
import { beforeEach, describe, expect, it } from "vitest";
import { approvedCommonScenarioFixture, commonScenarioFixture } from "../../../lib/systems/engine/contract";
import * as e04 from "../../../lib/systems/engine/e04";
import * as e05 from "../../../lib/systems/engine/e05";
import * as e06 from "../../../lib/systems/engine/e06";
import * as e11 from "../../../lib/systems/engine/e11";
import * as e12 from "../../../lib/systems/engine/e12";
import * as e14 from "../../../lib/systems/engine/e14";
import * as e18 from "../../../lib/systems/engine/e18";
import * as e24 from "../../../lib/systems/engine/e24";
import * as e29 from "../../../lib/systems/engine/e29";
import { PyIntegrityError, deepcopy, pyErrorName } from "../../../lib/systems/engine/py";
import { resetEngineState } from "../../../lib/systems/engine/runner";
import { E05_CSV, e04Pack, e06FixturePackPayload, e12Scenarios, golden } from "./fixtures";
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

describe("E24 (approval version update)", () => {
  it("creates a tamper-evident proposal and an immutable approved pack", () => {
    const out: any = {};
    const pack = {
      engine_id: "e02_versioned_json", rule_version: "fictional-rule-v1", status: "approved", approved_by: "fictional_shop_owner",
      effective_from: "2026-10-11", source: "fictional_fixture_only", basis_unit: "person_hour",
      basis_definition: commonScenarioFixture().basis_definition,
      rules: [
        { job_id: "front_brake_service", operation_key: "base_service", condition: { field: "work_scope", equals: "front_brake_service" }, hours: { low: 1.7, typical: 1.7, high: 1.7 }, unit: "person_hours", source: "fictional_json:base" },
        { job_id: "front_brake_service", operation_key: "wash", condition: { field: "work_scope", equals: "front_brake_service" }, hours: { low: 0.1, typical: 0.1, high: 0.1 }, unit: "person_hours", source: "fictional_json:wash" },
      ],
    };
    const newHours = { low: 1.6, typical: 1.8, high: 2.0 };
    const samples = [{ sample_id: "s1", hours: 1.8 }];
    const proposal = e24.propose(pack, "base_service", newHours, samples, "  measured  ");
    expect(proposal.reason).toBe("measured");
    expect(proposal.proposal_sha256).toMatch(/^[0-9a-f]{64}$/);
    const approved = e24.approve(proposal, "owner", "looks right", "fictional-rule-v2", "2026-10-12");
    expect(approved.rule_pack.rules[0].hours).toEqual(newHours);
    expect(pack.rules[0].hours.typical).toBe(1.7);
    const tampered = deepcopy(proposal);
    tampered.reason = "changed";
    const drafts = deepcopy(proposal);
    drafts.status = "approved";
    const swapped = deepcopy(proposal);
    swapped.old_pack.rules[0].hours = { low: 9, typical: 9, high: 9 };
    swapped.proposal_sha256 = e24.proposalHash(swapped);
    const cases: Record<string, () => unknown> = {
      propose_no_samples: () => e24.propose(pack, "base_service", newHours, [], "r"),
      propose_pack_type: () => e24.propose([], "base_service", newHours, samples, "r"),
      propose_reason: () => e24.propose(pack, "base_service", newHours, samples, " "),
      propose_unknown_op: () => e24.propose(pack, "nope", newHours, samples, "r"),
      propose_bad_hours: () => e24.propose(pack, "base_service", { low: 2, typical: 1, high: 3 }, samples, "r"),
      propose_bad_hours_bool: () => e24.propose(pack, "base_service", { low: true, typical: 1, high: 3 }, samples, "r"),
      approve_tampered: () => e24.approve(tampered, "o", "r", "v2", "2026-10-12"),
      approve_not_draft: () => e24.approve(drafts, "o", "r", "v2", "2026-10-12"),
      approve_blank: () => e24.approve(proposal, " ", "r", "v2", "2026-10-12"),
      approve_same_version: () => e24.approve(proposal, "o", "r", pack.rule_version, "2026-10-12"),
      approve_bad_date: () => e24.approve(proposal, "o", "r", "v2", "tomorrow"),
      approve_swapped_pack: () => e24.approve(swapped, "o", "r", "v2", "2026-10-12"),
      approve_not_dict: () => e24.approve([], "o", "r", "v2", "2026-10-12"),
    };
    const errs: any = {};
    for (const [name, call] of Object.entries(cases)) {
      try {
        call();
        errs[name] = null;
      } catch (e) {
        errs[name] = [pyErrorName(e), message(e)];
      }
    }
    out.errors = errs;
    out.run = e24.run(approvedCommonScenarioFixture());
    const expected = scripted.e24_flows;
    same(out.errors, expected.errors);
    same(out.run, expected.run);
    same({ reason: proposal.reason, status: proposal.status, operation_key: proposal.operation_key, old_value: proposal.old_value, new_value: proposal.new_value },
      { reason: expected.proposal.reason, status: expected.proposal.status, operation_key: expected.proposal.operation_key, old_value: expected.proposal.old_value, new_value: expected.proposal.new_value });
    same(approved.approval, expected.approved.approval);
  });
});

describe("E29 (offline snapshot queue)", () => {
  it("is idempotent and keeps version conflicts pending", () => {
    const out: any = {};
    const scenario = approvedCommonScenarioFixture();
    const queue = e29.queueSnapshot([], "snap-1", scenario, "fictional-rule-v1");
    out.queue = queue;
    out.again = e29.queueSnapshot(queue, "snap-1", scenario, "fictional-rule-v1");
    out.second = e29.queueSnapshot(queue, "snap-2", commonScenarioFixture(), "fictional-rule-v1");
    const snap = queue[0];
    out.sync_same = e29.syncSnapshot(snap, "fictional-rule-v1");
    out.sync_conflict = e29.syncSnapshot(snap, "fictional-rule-v2");
    out.keep = e29.syncSnapshot(snap, "fictional-rule-v2", { resolution: "keep_snapshot", actor: " a ", reason: " r " });
    out.rebase = e29.syncSnapshot(snap, "fictional-rule-v2", { resolution: "rebase_to_server", actor: "a", reason: "r" });
    const tampered = deepcopy(snap);
    tampered.scenario_input.person_count = 9;
    out.integrity = e29.syncSnapshot(tampered, "fictional-rule-v1");
    out.no_body = e29.syncSnapshot({ input_sha256: "x" }, "v");
    const cases: Record<string, () => unknown> = {
      queue_type: () => e29.queueSnapshot("x", "s", scenario, "v"),
      queue_blank_id: () => e29.queueSnapshot([], " ", scenario, "v"),
      queue_scenario: () => e29.queueSnapshot([], "s", 5, "v"),
      queue_version: () => e29.queueSnapshot([], "s", scenario, " "),
      queue_conflict: () => e29.queueSnapshot(queue, "snap-1", commonScenarioFixture(), "fictional-rule-v1"),
      queue_version_conflict: () => e29.queueSnapshot(queue, "snap-1", scenario, "other"),
      sync_type: () => e29.syncSnapshot([], "v"),
      sync_resolution: () => e29.syncSnapshot(snap, "v2", { resolution: "merge", actor: "a", reason: "r" }),
      sync_actor: () => e29.syncSnapshot(snap, "v2", { resolution: "keep_snapshot", actor: " ", reason: "r" }),
    };
    const errs: any = {};
    for (const [name, call] of Object.entries(cases)) {
      try {
        call();
        errs[name] = null;
      } catch (e) {
        errs[name] = [pyErrorName(e), message(e)];
      }
    }
    out.errors = errs;
    out.run = e29.run(scenario);
    same(out, scripted.e29_flows);
  });
});

describe("E18 (trace tree inspection)", () => {
  it("detects tampering of a tree built in this language", () => {
    const scenario = approvedCommonScenarioFixture();
    const tree = e18.buildTraceTree(scenario);
    const out: any = {
      tree, ok: e18.inspectTrace(tree, scenario), no_scenario: e18.inspectTrace(tree),
      other_scenario: e18.inspectTrace(tree, { ...scenario, person_count: 9 }),
      not_dict: e18.inspectTrace(5), wrong_root: e18.inspectTrace({ rule: "sum_children" }),
    };
    let t = deepcopy(tree);
    t.children[0].result.person_hours.typical = 99;
    out.leaf_changed = e18.inspectTrace(t, scenario);
    t = deepcopy(tree);
    t.children[1].node_id = t.children[0].node_id;
    t.children[2].rule_version = "x";
    t.children[3].input_hash = "x";
    t.children[4].input_refs = 5;
    t.children[5].input_refs = [{ path: "/nope", value: 1 }, { path: "x" }, { path: "/operations/99" }, 5];
    out.many_issues = e18.inspectTrace(t, scenario);
    t = deepcopy(tree);
    t.children[0].children = [1];
    out.leaf_with_children = e18.inspectTrace(t, scenario);
    t = deepcopy(tree);
    t.children[0].rule = "weird";
    t.children[1].result = 5;
    t.audit_expected = null;
    out.weird_rule = e18.inspectTrace(t);
    t = deepcopy(tree);
    t.children.push(5);
    t.input_hash = "short";
    out.short_hash = e18.inspectTrace(t, scenario);
    same(out, scripted.e18_inspect);
    expect(out.ok.valid).toBe(true);
  });
});

describe("E14 (photo candidate queue)", () => {
  it("promotes only audited human decisions", () => {
    const STAMP = "2026-10-11T01:02:03+00:00";
    const cand = (field = "rotor_seizure_hours", value: any = null, id = "cand_1") => ({
      candidate_id: id, photo_ref: { area: "brake", id: "photo_01" },
      ai_candidate: { field, value: deepcopy(value ?? { low: 0.0, typical: 0.25, high: 0.5 }) },
    });
    const rotorScenario = () => {
      const s = approvedCommonScenarioFixture();
      delete s.fields.rotor_seizure_hours;
      s.fields.rotor_relevance = { value: "relevant", status: "confirmed", source: "fictional_fixture", confirmed_at: STAMP };
      delete s.metadata.approved_condition_widths;
      return s;
    };
    const out: any = {};
    out.default = e14.run(approvedCommonScenarioFixture());
    const queued = e14.proposeCandidates(rotorScenario(), [cand()]);
    out.queued = queued;
    out.run_queued = e14.run(queued);
    const confirmed = e14.confirmCandidate(queued, "cand_1", "shop_owner", "visual check", STAMP);
    out.confirmed = confirmed;
    out.run_confirmed = e14.run(confirmed);
    const modified = e14.modifyCandidate(queued, "cand_1", { low: 0.1, typical: 0.3, high: 0.6 }, "shop_owner", "corrected by inspection", STAMP);
    out.modified = modified;
    out.run_modified = e14.run(modified);
    const rejected = e14.rejectCandidate(queued, "cand_1", "shop_owner", "not visible", STAMP);
    out.rejected = rejected;
    out.run_rejected = e14.run(rejected);
    let two = e14.proposeCandidates(rotorScenario(), [cand(), cand("rotor_relevance", "relevant", "cand_2"), cand("subframe_relevance", "unrelated", "cand_3")]);
    two = e14.confirmCandidate(two, "cand_1", "a", "r", "2026-10-11T01:02:03Z");
    two = e14.rejectCandidate(two, "cand_2", "b", "r2", STAMP);
    two = e14.confirmCandidate(two, "cand_3", "c", "r3", "2026-10-11 09:00:00+09:00");
    out.multi = two;
    out.run_multi = e14.run(two);
    const tampered = deepcopy(confirmed);
    tampered.photo_candidates[0].human_audit.reason = "changed";
    out.run_tampered_reason = e14.run(tampered);
    const t2 = deepcopy(confirmed);
    t2.fields.rotor_seizure_hours.value.high = 9;
    out.run_tampered_field = e14.run(t2);
    const t3 = deepcopy(confirmed);
    t3.metadata.photo_candidate_audit_log = [];
    out.run_log_missing = e14.run(t3);
    const t4 = deepcopy(confirmed);
    t4.metadata.approved_condition_widths.rotor_seizure_hours.actor = "x";
    out.run_tampered_approval = e14.run(t4);
    const t5 = deepcopy(confirmed);
    t5.photo_candidates[0].extra = 1;
    t5.photo_candidates.push(5);
    t5.photo_candidates.push({ candidate_id: "bad id", photo_ref: { area: "A", id: "x" }, ai_candidate: { field: "nope", value: 1 }, status: "weird" });
    out.run_bad_candidates = e14.run(t5);
    out.run_candidates_not_list = e14.run({ ...approvedCommonScenarioFixture(), photo_candidates: "x" });
    out.run_pending_with_audit = e14.run({ ...rotorScenario(), photo_candidates: [{ ...cand(), human_audit: { a: 1 } }] });
    out.run_custom_pack = e14.run(queued, { allowed_values: { rotor_relevance: ["relevant"], rotor_seizure_hours: "person_hour_range", subframe_relevance: ["x", "x"] } });
    out.run_pack_ok = e14.run(approvedCommonScenarioFixture(), { allowed_values: { rotor_relevance: ["relevant"], rotor_seizure_hours: "person_hour_range", subframe_relevance: ["x"] } });
    out.run_pack_bad = [[], { engine_id: "z", rule_version: "q", status: "d", other: 1 }, { allowed_values: 5 }, { allowed_values: { rotor_relevance: [] } }].map((p) => e14.run(approvedCommonScenarioFixture(), p));
    const cases: Record<string, () => unknown> = {
      propose_type: () => e14.proposeCandidates([], []),
      propose_item: () => e14.proposeCandidates({}, [5]),
      propose_state: () => e14.proposeCandidates({}, [{ ...cand(), status: "approved" }]),
      propose_list: () => e14.proposeCandidates({ photo_candidates: 5 }, []),
      confirm_again: () => e14.confirmCandidate(confirmed, "cand_1", "s", "again", STAMP),
      confirm_missing: () => e14.confirmCandidate(queued, "nope", "s", "r", STAMP),
      confirm_blank_actor: () => e14.confirmCandidate(queued, "cand_1", " ", "r", STAMP),
      confirm_naive: () => e14.confirmCandidate(queued, "cand_1", "s", "r", "2026-10-11T01:02:03"),
      confirm_badstamp: () => e14.confirmCandidate(queued, "cand_1", "s", "r", "yesterday"),
      confirm_date_only: () => e14.confirmCandidate(queued, "cand_1", "s", "r", "2026-10-11"),
      confirm_not_dict: () => e14.confirmCandidate([], "cand_1", "s", "r", STAMP),
      modify_bad: () => e14.modifyCandidate(queued, "cand_1", { low: 0.5, typical: 0.2, high: 0.7 }, "s", "r", STAMP),
      modify_bool: () => e14.modifyCandidate(queued, "cand_1", { low: true, typical: 1, high: 2 }, "s", "r", STAMP),
      reject_missing: () => e14.rejectCandidate(queued, "zzz", "s", "r", STAMP),
      reject_not_dict: () => e14.rejectCandidate(5, "cand_1", "s", "r"),
      fields_not_dict: () => e14.confirmCandidate({ ...queued, fields: [] }, "cand_1", "s", "r", STAMP),
      metadata_not_dict: () => e14.confirmCandidate({ ...queued, metadata: 5 }, "cand_1", "s", "r", STAMP),
    };
    const errs: any = {};
    for (const [name, call] of Object.entries(cases)) {
      try {
        call();
        errs[name] = null;
      } catch (e) {
        errs[name] = [pyErrorName(e), message(e)];
      }
    }
    out.errors = errs;
    same(out, scripted.e14_flows);
    expect(out.run_confirmed.labor.person_hours).toEqual({ low: 1.88, typical: 2.13, high: 2.38 });
  });
});

describe("E12 (delta recalculation)", () => {
  it("reuses verified rows and falls back to a full recalculation otherwise", () => {
    const scen = e12Scenarios(approvedCommonScenarioFixture, commonScenarioFixture);
    const out: any = {};
    const baseline = e12.run(deepcopy(scen.base));
    out.baseline = baseline;
    const withPrev = (scenario: any, snapshot: any) => {
      const s = deepcopy(scenario);
      s.metadata.previous_snapshot = deepcopy(snapshot);
      return s;
    };
    const snap = baseline.delta_snapshot;
    for (const [name, scenario] of Object.entries(scen)) out["delta_" + name] = e12.run(withPrev(scenario, snap));
    out.delta_via_pack = e12.run(deepcopy(scen.wash_changed), { previous_snapshot: deepcopy(snap) });
    out.pack_changes_hash = e12.run(withPrev(scen.base, snap), { extra: 1 });
    const forged = deepcopy(snap);
    forged.result.labor.person_hours.typical = 99;
    out.forged = e12.run(withPrev(scen.wash_changed, forged));
    out.garbage_snapshot = [5, "x", [], { a: 1 }].map((g) => e12.run(withPrev(scen.base, g)));
    const chained = e12.run(withPrev(scen.rotor_unrelated, snap));
    out.chain_2 = e12.run(withPrev(scen.wash_changed, chained.delta_snapshot));
    out.index = e12.buildDependencyIndex(scen.extra_field);
    out.index_bad = [5, {}, { fields: 3, operations: [5, { operation_id: "zz" }] }].map((x) => e12.buildDependencyIndex(x));
    out.evaluate = Object.fromEntries(
      ["base_service", "included_carry", "replacement_carry", "rotor_seizure", "snow_melt", "penetrant_wait", "parts_wait", "wash", "nope"].map((id) => [id, e12.evaluateOperation(scen.base, id)]),
    );
    out.evaluate_unrelated = e12.evaluateOperation(scen.rotor_unrelated, "rotor_seizure");
    out.evaluate_mismatch = e12.evaluateOperation(scen.approval_actor, "rotor_seizure");
    out.changed_fields = ["rotor_unrelated", "extra_field", "approval_actor", "fields_list"].map((k) => e12.changedFields(scen.base, scen[k]));
    same(out, scripted.e12_flows);
    expect(out.delta_wash_changed.trace.at(-1).cache_validated).toBe(true);
    expect(out.forged.trace.at(-1).cache_validated).toBe(false);
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
