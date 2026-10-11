/* eslint-disable @typescript-eslint/no-explicit-any */
// E05: validate, preview, and publish immutable CSV rule packs. 元: e05.py
import {
  type Dict, PyTypeError, PyValueError, PyValueError as ValueError, codePointCompare, dedupe, deepcopy, get, isDict, isList, isStr, pyEq,
  pyFloat, pyJsonDumps, pySorted, pyStrip, sha256Hex, truthy,
} from "./py";
import { commonScenarioFixture } from "./contract";
import * as e02 from "./e02";
import { createHash } from "node:crypto";

export const ENGINE_ID = "e05_csv_import";
export const CSV_COLUMNS = ["job_id", "operation_key", "condition_field", "match_value", "low", "typical", "high", "unit", "source", "reason"];
export const RULE_KEYS = new Set(["base_service", "replacement_carry", "snow_melt", "penetrant_wait", "parts_wait", "wash", "rotor_seizure"]);
const ALLOWED_FIELDS = new Set(["work_scope", "included_operations", "parts_wait_stock_checked", "rotor_relevance"]);
const ELAPSED_KEYS = new Set(["snow_melt", "penetrant_wait", "parts_wait"]);
const PUBLISHED = new Map<string, PublishedRulePack>();

/** テスト用: 公開済みスナップショットの登録を空にする（元の _PUBLISHED.clear() 相当）。 */
export function resetPublished(): void {
  PUBLISHED.clear();
}

export class RuleRow {
  constructor(
    readonly job_id: string,
    readonly operation_key: string,
    readonly condition_field: string,
    readonly match_value: string,
    readonly low: number,
    readonly typical: number,
    readonly high: number,
    readonly unit: string,
    readonly source: string,
    readonly reason: string,
  ) {}

  hours(): Dict {
    return { low: this.low, typical: this.typical, high: this.high };
  }

  condition(): Dict {
    let value: any = this.match_value;
    if (this.condition_field === "parts_wait_stock_checked") value = pyStrip(this.match_value).toLowerCase() === "true";
    if (this.condition_field === "included_operations") return { field: this.condition_field, contains: value };
    return { field: this.condition_field, equals: value };
  }
}

export function rowSnapshot(row: RuleRow): Dict {
  return { job_id: row.job_id, operation_key: row.operation_key, condition: row.condition(), hours: row.hours(), unit: row.unit, source: row.source, reason: row.reason };
}

export interface ImportBatch {
  hash: string;
  rows: RuleRow[];
  errors: string[];
}

export class ApprovalAudit {
  constructor(
    readonly actor: string,
    readonly reason: string,
    readonly operation_key: string,
    readonly old_value: Dict | null,
    readonly new_value: Dict,
  ) {}
}

export class PublishedRulePack {
  constructor(
    readonly engine_id: string,
    readonly rule_version: string,
    readonly effective_from: string,
    readonly source: string,
    readonly basis_unit: string,
    readonly basis_definition: string,
    readonly import_hash: string,
    readonly snapshot_hash: string,
    readonly approved_by: string,
    readonly approval_reason: string,
    readonly rules: RuleRow[],
    readonly audit: ApprovalAudit[],
  ) {}

  toRulePack(): Dict {
    return {
      engine_id: e02.ENGINE_ID,
      rule_version: this.rule_version,
      status: "approved",
      approved_by: this.approved_by,
      effective_from: this.effective_from,
      source: this.source,
      basis_unit: this.basis_unit,
      basis_definition: this.basis_definition,
      rules: this.rules.map((row) => ({ job_id: row.job_id, operation_key: row.operation_key, condition: row.condition(), hours: row.hours(), unit: row.unit, source: row.source })),
    };
  }
}

/** dataclasses.replace 相当（テストで改ざんしたスナップショットを作る）。 */
export function replacePack(pack: PublishedRulePack, changes: Partial<PublishedRulePack>): PublishedRulePack {
  return Object.assign(Object.create(PublishedRulePack.prototype), pack, changes);
}

/** Python の csv.reader（excel 方言・非 strict）を再現した CSV パーサ。空行は [] で返す。 */
export function parseCsvRecords(text: string): string[][] {
  const lines = text.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g)?.filter((l, i, a) => l !== "" || i < a.length - 1) ?? [];
  const records: string[][] = [];
  let fields: string[] = [];
  let field = "";
  let state: "START_RECORD" | "START_FIELD" | "IN_FIELD" | "IN_QUOTED_FIELD" | "QUOTE_IN_QUOTED_FIELD" | "EAT_CRNL" = "START_RECORD";
  const saveField = () => {
    fields.push(field);
    field = "";
  };
  const feed = (c: string) => {
    // c === "\0" は行末マーカー
    switch (state) {
      case "START_RECORD":
        if (c === "\0") return;
        if (c === "\n" || c === "\r") {
          state = "EAT_CRNL";
          return;
        }
        state = "START_FIELD";
      // fallthrough
      case "START_FIELD":
        if (c === "\n" || c === "\r" || c === "\0") {
          saveField();
          state = c === "\0" ? "START_RECORD" : "EAT_CRNL";
        } else if (c === '"') state = "IN_QUOTED_FIELD";
        else if (c === ",") {
          saveField();
          state = "START_FIELD";
        } else {
          field += c;
          state = "IN_FIELD";
        }
        return;
      case "IN_FIELD":
        if (c === "\n" || c === "\r" || c === "\0") {
          saveField();
          state = c === "\0" ? "START_RECORD" : "EAT_CRNL";
        } else if (c === ",") {
          saveField();
          state = "START_FIELD";
        } else field += c;
        return;
      case "IN_QUOTED_FIELD":
        if (c === "\0") return;
        if (c === '"') state = "QUOTE_IN_QUOTED_FIELD";
        else field += c;
        return;
      case "QUOTE_IN_QUOTED_FIELD":
        if (c === '"') {
          field += c;
          state = "IN_QUOTED_FIELD";
        } else if (c === ",") {
          saveField();
          state = "START_FIELD";
        } else if (c === "\n" || c === "\r" || c === "\0") {
          saveField();
          state = c === "\0" ? "START_RECORD" : "EAT_CRNL";
        } else {
          field += c;
          state = "IN_FIELD";
        }
        return;
      case "EAT_CRNL":
        if (c === "\n" || c === "\r") return;
        if (c === "\0") state = "START_RECORD";
        else throw new PyValueError("new-line character seen in unquoted field");
        return;
    }
  };
  for (const line of lines) {
    for (const c of line) feed(c);
    feed("\0");
    if (state === "START_RECORD") {
      records.push(fields);
      fields = [];
      field = "";
    }
  }
  if (state !== "START_RECORD") {
    // 入力の終端で未完のレコード（クォートが閉じていない場合など）
    if (field.length !== 0 || state === "IN_QUOTED_FIELD") saveField();
    records.push(fields);
  }
  return records;
}

export function parseCsv(content: string | Uint8Array): ImportBatch {
  let raw: Uint8Array;
  let text: string;
  if (content instanceof Uint8Array) {
    raw = content;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(content);
    } catch {
      return { hash: createHash("sha256").update(raw).digest("hex"), rows: [], errors: ["csv:invalid_utf8"] };
    }
  } else if (typeof content === "string") {
    text = content;
    raw = new TextEncoder().encode(content);
  } else {
    throw new PyTypeError("content must be str or bytes");
  }
  const digest = createHash("sha256").update(raw).digest("hex");
  const errors: string[] = [];
  const records = parseCsvRecords(text);
  if (records.length === 0) return { hash: digest, rows: [], errors: ["csv:header_required"] };
  const fieldnames = records[0];
  const headers = fieldnames.map((h) => pyStrip(h));
  if (headers.length !== new Set(headers).size || headers.length !== CSV_COLUMNS.length || !CSV_COLUMNS.every((c) => headers.includes(c))) {
    errors.push("csv:header_mismatch");
    return { hash: digest, rows: [], errors };
  }
  const rows: RuleRow[] = [];
  let index = 1;
  for (const record of records.slice(1)) {
    if (record.length === 0) continue; // DictReader は空行を飛ばす
    index += 1;
    if (record.length > fieldnames.length) {
      errors.push(`row:${index}:extra_columns`);
      continue;
    }
    const rawRow = new Map<string, string>();
    fieldnames.forEach((name, i) => {
      if (i < record.length) rawRow.set(name, record[i]);
    });
    const row: Record<string, string> = {};
    for (const key of CSV_COLUMNS) row[key] = pyStrip(rawRow.get(key) ?? "");
    let values: number[];
    try {
      values = ["low", "typical", "high"].map((key) => pyFloat(row[key]));
    } catch (e) {
      if (e instanceof PyValueError) {
        errors.push(`row:${index}:invalid_numeric_range`);
        continue;
      }
      throw e;
    }
    if (values.some((v) => !Number.isFinite(v) || v < 0)) {
      errors.push(`row:${index}:invalid_numeric_range`);
      continue;
    }
    rows.push(new RuleRow(row.job_id, row.operation_key, row.condition_field, row.match_value, values[0], values[1], values[2], row.unit, row.source, row.reason));
  }
  return { hash: digest, rows, errors };
}

export function validateUnits(batch: ImportBatch): string[] {
  const errors = [...batch.errors];
  const seen = new Set<string>();
  batch.rows.forEach((row, i) => {
    const prefix = `row:${i + 2}`;
    if (!RULE_KEYS.has(row.operation_key)) errors.push(`${prefix}:unknown_operation_key:${row.operation_key}`);
    else if (seen.has(row.operation_key)) errors.push(`${prefix}:duplicate_operation_key:${row.operation_key}`);
    seen.add(row.operation_key);
    if (!row.job_id || !row.condition_field || !row.match_value || !row.source || !row.reason) errors.push(`${prefix}:required_value_missing`);
    if (!ALLOWED_FIELDS.has(row.condition_field)) errors.push(`${prefix}:unknown_condition_field:${row.condition_field}`);
    if (row.condition_field === "parts_wait_stock_checked" && !["true", "false"].includes(pyStrip(row.match_value).toLowerCase())) {
      errors.push(`${prefix}:invalid_boolean_condition:${row.condition_field}`);
    }
    const expectedUnit = ELAPSED_KEYS.has(row.operation_key) ? "elapsed_hours" : "person_hours";
    if (row.unit !== expectedUnit) errors.push(`${prefix}:unit_mismatch:${row.operation_key}`);
    const values = [row.low, row.typical, row.high];
    if (values.some((v) => !Number.isFinite(v) || v < 0) || !(row.low <= row.typical && row.typical <= row.high)) {
      errors.push(`${prefix}:invalid_or_misaligned_range`);
    }
  });
  for (const missing of [...RULE_KEYS].filter((k) => !seen.has(k)).sort(codePointCompare)) errors.push(`rule:${missing}:required`);
  return dedupe(errors);
}

export function previewDiff(batch: ImportBatch, previous: PublishedRulePack | null = null): Dict {
  const old = new Map<string, RuleRow>((previous ? previous.rules : []).map((r) => [r.operation_key, r]));
  const neu = new Map<string, RuleRow>(batch.rows.map((r) => [r.operation_key, r]));
  const changes: Dict[] = [];
  for (const key of pySorted([...new Set([...old.keys(), ...neu.keys()])])) {
    const before = old.get(key);
    const after = neu.get(key);
    const oldValue = before ? rowSnapshot(before) : null;
    const newValue = after ? rowSnapshot(after) : null;
    if (!pyEq(oldValue, newValue)) changes.push({ operation_key: key, old_value: oldValue, new_value: newValue });
  }
  return { import_hash: batch.hash, errors: validateUnits(batch), changes };
}

const canonicalHash = (snapshot: Dict) => sha256Hex(pyJsonDumps(snapshot, { sortKeys: true, ensureAscii: false, compact: true }));

function snapshotOf(version: string, effectiveFrom: string, basisUnit: any, basisDefinition: any, importHash: string, rules: RuleRow[]): Dict {
  return {
    engine_id: ENGINE_ID, rule_version: version, effective_from: effectiveFrom, source: "csv_import",
    basis_unit: basisUnit, basis_definition: basisDefinition, import_hash: importHash,
    rules: rules.map((row) => ({ job_id: row.job_id, operation_key: row.operation_key, condition: row.condition(), hours: row.hours(), unit: row.unit, source: row.source, reason: row.reason })),
  };
}

export function humanPublish(
  batch: ImportBatch, actor: any, reason: any, ruleVersion: any, effectiveFrom: any, basisUnit: any, basisDefinition: any,
  previous: PublishedRulePack | null = null,
): PublishedRulePack {
  if (!isStr(actor) || !actor.trim()) throw new ValueError("publish:actor_required");
  if (!isStr(reason) || !reason.trim()) throw new ValueError("publish:reason_required");
  if (!isStr(ruleVersion) || !ruleVersion.trim()) throw new ValueError("publish:rule_version_required");
  if (!isStr(effectiveFrom) || !effectiveFrom.trim()) throw new ValueError("publish:effective_from_required");
  if (!truthy(basisUnit) || !truthy(basisDefinition)) throw new ValueError("publish:basis_required");
  const errors = validateUnits(batch);
  if (errors.length) throw new ValueError("publish:validation_failed:" + errors.join(","));

  const old = new Map<string, RuleRow>((previous ? previous.rules : []).map((r) => [r.operation_key, r]));
  const audits: ApprovalAudit[] = [];
  for (const row of batch.rows) {
    const prior = old.get(row.operation_key);
    const oldValue = prior ? rowSnapshot(prior) : null;
    const newValue = rowSnapshot(row);
    if (!pyEq(oldValue, newValue)) audits.push(new ApprovalAudit(pyStrip(actor), pyStrip(reason), row.operation_key, oldValue, newValue));
  }
  const snapshotHash = canonicalHash(snapshotOf(pyStrip(ruleVersion), pyStrip(effectiveFrom), basisUnit, basisDefinition, batch.hash, batch.rows));
  const existing = PUBLISHED.get(pyStrip(ruleVersion));
  if (existing && existing.snapshot_hash !== snapshotHash) throw new ValueError("publish:published_version_is_immutable");
  if (existing) return existing;
  const published = new PublishedRulePack(
    ENGINE_ID, pyStrip(ruleVersion), pyStrip(effectiveFrom), "csv_import:" + batch.hash, basisUnit, basisDefinition,
    batch.hash, snapshotHash, pyStrip(actor), pyStrip(reason), [...batch.rows], audits,
  );
  PUBLISHED.set(published.rule_version, published);
  return published;
}

export const DEFAULT_CSV = `job_id,operation_key,condition_field,match_value,low,typical,high,unit,source,reason
front_brake_service,base_service,work_scope,front_brake_service,1.7,1.7,1.7,person_hours,fictional_csv:base,fictional deduplicated base
front_brake_service,replacement_carry,included_operations,remove_install,0.2,0.2,0.2,person_hours,fictional_csv:carry,replaces included transport
front_brake_service,snow_melt,included_operations,snow_removal,0.5,0.5,0.5,elapsed_hours,fictional_csv:snow,elapsed wait only
front_brake_service,penetrant_wait,work_scope,front_brake_service,0.25,0.25,0.25,elapsed_hours,fictional_csv:penetrant,elapsed wait only
front_brake_service,parts_wait,parts_wait_stock_checked,true,0,0,0,elapsed_hours,fictional_csv:parts,stock checked elapsed wait
front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fictional_csv:wash,performed nonbillable work
front_brake_service,rotor_seizure,rotor_relevance,relevant,0,0.25,0.5,person_hours,fictional_csv:rotor,human approved fictional condition width
`;

export function defaultPack(): PublishedRulePack {
  const batch = parseCsv(DEFAULT_CSV);
  const fixture = commonScenarioFixture();
  return humanPublish(batch, "fictional_shop_owner", "fictional fixture approval", "fictional-rule-v1", "2026-10-11T00:00:00+00:00", fixture.basis_unit, fixture.basis_definition);
}

function packSnapshotHash(pack: PublishedRulePack): string {
  return canonicalHash(snapshotOf(pack.rule_version, pack.effective_from, pack.basis_unit, pack.basis_definition, pack.import_hash, pack.rules));
}

export function packIntegrityErrors(pack: PublishedRulePack): string[] {
  const errors: string[] = [];
  const nonEmpty = (v: any) => isStr(v) && v.trim().length > 0;
  if (pack.engine_id !== ENGINE_ID || !nonEmpty(pack.rule_version)) errors.push("published_pack:identity_required");
  if (!nonEmpty(pack.effective_from)) errors.push("published_pack:effective_from_required");
  if (
    !isStr(pack.source) || pack.source !== "csv_import:" + pack.import_hash || !isStr(pack.import_hash) ||
    pack.import_hash.length !== 64 || [...pack.import_hash].some((ch) => !"0123456789abcdef".includes(ch))
  ) errors.push("published_pack:import_hash_or_source_invalid");
  if (!nonEmpty(pack.basis_unit) || !nonEmpty(pack.basis_definition)) errors.push("published_pack:basis_required");
  if (!nonEmpty(pack.approved_by)) errors.push("published_pack:approver_required");
  if (!nonEmpty(pack.approval_reason)) errors.push("published_pack:approval_reason_required");
  const rulesOk = isList(pack.rules) && pack.rules.every((row) => row instanceof RuleRow);
  if (!rulesOk) errors.push("published_pack:rules_invalid");
  else errors.push(...validateUnits({ hash: pack.import_hash, rows: pack.rules, errors: [] }).map((e) => "published_" + e));

  const expectedAudits = new Map<string, Dict>();
  if (rulesOk) for (const row of pack.rules) expectedAudits.set(row.operation_key, rowSnapshot(row));
  if (!isList(pack.audit) || !pack.audit.length) {
    errors.push("published_pack:required_approval_audit_missing");
  } else {
    const auditedKeys = new Set<string>();
    for (const audit of pack.audit) {
      if (!(audit instanceof ApprovalAudit)) {
        errors.push("published_pack:approval_audit_invalid");
        continue;
      }
      const expectedNew = expectedAudits.get(audit.operation_key);
      if (
        !nonEmpty(audit.actor) || !nonEmpty(audit.reason) || !truthy(expectedNew) || auditedKeys.has(audit.operation_key) ||
        (audit.old_value !== null && !isDict(audit.old_value)) || !pyEq(audit.new_value, expectedNew ?? null)
      ) errors.push("published_pack:approval_audit_mismatch");
      auditedKeys.add(audit.operation_key);
    }
    if (!auditedKeys.size) errors.push("published_pack:required_approval_audit_missing");
  }
  if (!(isStr(pack.snapshot_hash) && pack.snapshot_hash.length === 64 && pack.snapshot_hash === packSnapshotHash(pack))) {
    errors.push("published_pack:snapshot_hash_mismatch");
  }
  return dedupe(errors);
}

export function run(scenarioInput: Dict, rulePack: any = null): Dict {
  const scenario = deepcopy(scenarioInput);
  const pack = rulePack === null ? defaultPack() : rulePack;
  if (!(pack instanceof PublishedRulePack)) {
    const result = e02.run(scenario, null);
    result.engine_id = ENGINE_ID;
    result.trace.push({ event: "csv_import_rejected", reason: "published_pack_required" });
    return result;
  }
  const integrityErrors = packIntegrityErrors(pack);
  if (integrityErrors.length) {
    const result = e02.run(scenario, null);
    result.engine_id = ENGINE_ID;
    result.rule_version = truthy(get(scenario, "rule_version")) ? get(scenario, "rule_version") : pack.rule_version;
    result.trace.push({ event: "csv_import_rejected", reason: "published_pack_integrity_failed", errors: integrityErrors, import_hash: pack.import_hash });
    return result;
  }
  if (truthy(get(scenario, "rule_version")) && !pyEq(scenario.rule_version, pack.rule_version)) {
    const result = e02.run(scenario, null);
    result.engine_id = ENGINE_ID;
    result.rule_version = scenario.rule_version;
    result.trace.push({ event: "csv_import_rejected", reason: "pinned_version_mismatch", requested_version: scenario.rule_version, snapshot_version: pack.rule_version, import_hash: pack.import_hash });
    return result;
  }
  if (!pyEq(pack.basis_unit, get(scenario, "basis_unit")) || !pyEq(pack.basis_definition, get(scenario, "basis_definition"))) {
    const result = e02.run(scenario, null);
    result.engine_id = ENGINE_ID;
    result.rule_version = truthy(get(scenario, "rule_version")) ? get(scenario, "rule_version") : pack.rule_version;
    result.trace.push({ event: "csv_import_rejected", reason: "basis_mismatch", import_hash: pack.import_hash });
    return result;
  }
  const underlying = e02.run(scenario, pack.toRulePack());
  underlying.engine_id = ENGINE_ID;
  underlying.trace.unshift({ event: "csv_snapshot_loaded", import_hash: pack.import_hash, snapshot_hash: pack.snapshot_hash, rule_version: pack.rule_version });
  underlying.trace.push({ event: "csv_diff_reviewed", operation_keys: pack.rules.map((r) => r.operation_key) });
  underlying.approvals.unshift({
    type: "csv_publish", actor: pack.approved_by, reason: pack.approval_reason, import_hash: pack.import_hash,
    snapshot_hash: pack.snapshot_hash, rule_version: pack.rule_version,
    changes: pack.audit.map((it) => ({ operation_key: it.operation_key, old_value: it.old_value, new_value: it.new_value, actor: it.actor, reason: it.reason })),
  });
  return underlying;
}

