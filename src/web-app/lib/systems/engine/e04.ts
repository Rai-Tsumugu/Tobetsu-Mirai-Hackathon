/* eslint-disable @typescript-eslint/no-explicit-any */
// E04: normalized, version-pinned rules for fictional labor estimates. 元: e04.py
// 元実装は :memory: の SQLite を使う。ここでは同じ表・制約（主キー、CHECK、外部キー、UNIQUE、不変トリガー）を
// メモリ内の小さなデータベースで再現する（Vercel のサーバーレス関数でも動くようにするため）。
import {
  type Dict, PyIntegrityError, PyProgrammingError, PyValueError, codePointCompare, dedupe, deepcopy, get, isDict, isInt, isList, isNumber, isStr,
  keysAre, or, pyEq, pyRound, repr, truthy,
} from "./py";
import { BANDS, referenceLabor } from "./contract";

export const ENGINE_ID = "e04_sqlite_normalized";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const DEFAULT_RULES: [string, string, string, string, [number, number, number], number][] = [
  ["base_service", "承認済み基準作業", "work", "person_hours", [1.7, 1.7, 1.7], 1],
  ["included_carry", "含有運搬", "work", "person_hours", [0.12, 0.12, 0.12], 1],
  ["replacement_carry", "二人作業の運搬", "work", "person_hours", [0.2, 0.2, 0.2], 2],
  ["rotor_seizure", "ローター固着", "work", "person_hours", [0.0, 0.25, 0.5], 1],
  ["snow_melt", "雪の融解待ち", "wait", "elapsed_hours", [0.5, 0.5, 0.5], 0],
  ["penetrant_wait", "浸透待ち", "wait", "elapsed_hours", [0.25, 0.25, 0.25], 0],
  ["parts_wait", "部品待ち", "wait", "elapsed_hours", [0.0, 0.0, 0.0], 0],
  ["wash", "洗浄", "work", "person_hours", [0.1, 0.1, 0.1], 1],
];

/** バインドされる値を TEXT 列へ（数値は文字列化、dict / list は ProgrammingError）。 */
function txt(v: any): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return v ? "1" : "0";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v;
  throw new PyProgrammingError("Error binding parameter: type is not supported");
}

const notNull = (...values: (string | null)[]) => {
  if (values.some((v) => v === null)) throw new PyIntegrityError("NOT NULL constraint failed");
};

type Snapshot = { rules: Dict[]; operations: Dict[]; ruleOperations: Dict[]; evidence: Dict[] };

/** :memory: SQLite データベースの代わりとなるメモリ内データベース。 */
export class E04Database {
  rules: Dict[] = [];
  operations: Dict[] = [];
  ruleOperations: Dict[] = [];
  evidence: Dict[] = [];

  snapshot(): Snapshot {
    return deepcopy({ rules: this.rules, operations: this.operations, ruleOperations: this.ruleOperations, evidence: this.evidence });
  }

  restore(s: Snapshot): void {
    this.rules = s.rules;
    this.operations = s.operations;
    this.ruleOperations = s.ruleOperations;
    this.evidence = s.evidence;
  }

  insertRule(id: any, version: any, status: any, approvedBy: any, effectiveFrom: any, source: any): void {
    const [i, v, st, ap, ef, so] = [txt(id), txt(version), txt(status), txt(approvedBy), txt(effectiveFrom), txt(source)];
    notNull(i, v, st, ef, so);
    if (st !== "approved" && st !== "draft") throw new PyIntegrityError("CHECK constraint failed: status");
    if (this.rules.some((r) => r.id === i && r.version === v)) throw new PyIntegrityError("UNIQUE constraint failed: rules.id, rules.version");
    this.rules.push({ id: i, version: v, status: st, approved_by: ap, effective_from: ef, source: so });
  }

  insertOperationDoNothing(id: any, operationKey: any, name: any, kind: any, unit: any): void {
    const [i, k, n, kd, u] = [txt(id), txt(operationKey), txt(name), txt(kind), txt(unit)];
    notNull(i, k, n, kd, u);
    if (this.operations.some((o) => o.id === i)) return;
    if (kd !== "work" && kd !== "wait") throw new PyIntegrityError("CHECK constraint failed: kind");
    if (u !== "person_hours" && u !== "elapsed_hours") throw new PyIntegrityError("CHECK constraint failed: unit");
    if (this.operations.some((o) => o.operation_key === k)) throw new PyIntegrityError("UNIQUE constraint failed: operations.operation_key");
    this.operations.push({ id: i, operation_key: k, name: n, kind: kd, unit: u });
  }

  operationById(id: any): Dict | null {
    return this.operations.find((o) => o.id === txt(id)) ?? null;
  }

  insertRuleOperation(ruleId: any, version: any, operationId: any, low: number, typical: number, high: number, personCount: number): void {
    const [r, v, o] = [txt(ruleId), txt(version), txt(operationId)];
    notNull(r, v, o);
    if (!(low >= 0)) throw new PyIntegrityError("CHECK constraint failed: low");
    if (!(typical >= low)) throw new PyIntegrityError("CHECK constraint failed: typical");
    if (!(high >= typical)) throw new PyIntegrityError("CHECK constraint failed: high");
    if (!(personCount >= 0)) throw new PyIntegrityError("CHECK constraint failed: person_count");
    if (this.ruleOperations.some((x) => x.rule_id === r && x.version === v && x.operation_id === o)) throw new PyIntegrityError("UNIQUE constraint failed: rule_operations");
    if (!this.rules.some((x) => x.id === r && x.version === v)) throw new PyIntegrityError("FOREIGN KEY constraint failed");
    if (!this.operations.some((x) => x.id === o)) throw new PyIntegrityError("FOREIGN KEY constraint failed");
    this.ruleOperations.push({ rule_id: r, version: v, operation_id: o, low, typical, high, person_count: personCount });
  }

  insertEvidence(id: any, ruleId: any, version: any, operationId: any, source: any, note: any): void {
    const [i, r, v, o, s, n] = [txt(id), txt(ruleId), txt(version), txt(operationId), txt(source), txt(note)];
    notNull(i, r, v, o, s, n);
    if (this.evidence.some((x) => x.id === i && x.rule_id === r && x.version === v && x.operation_id === o)) throw new PyIntegrityError("UNIQUE constraint failed: evidence");
    if (!this.ruleOperations.some((x) => x.rule_id === r && x.version === v && x.operation_id === o)) throw new PyIntegrityError("FOREIGN KEY constraint failed");
    this.evidence.push({ id: i, rule_id: r, version: v, operation_id: o, source: s, note: n });
  }

  /** UPDATE / DELETE は不変トリガーが RAISE(ABORT) する（対象行がある場合）。 */
  tamper(table: "rules" | "operations" | "rule_operations" | "evidence", kind: "update" | "delete"): void {
    const rows = { rules: this.rules, operations: this.operations, rule_operations: this.ruleOperations, evidence: this.evidence }[table];
    const labels = { rules: "published rule versions", operations: "operation definitions", rule_operations: "published rule operations", evidence: "published evidence" };
    if (rows.length) throw new PyIntegrityError(`${labels[table]} are immutable (${kind})`);
  }
}

export function initializeDatabase(db: E04Database): void {
  void db; // 表と制約は E04Database 自体が持つ
}

export function createDatabase(): E04Database {
  return new E04Database();
}

function ruleVersion(pack: Dict): string {
  const version = get(pack, "rule_version", get(pack, "version"));
  if (!isStr(version) || !version.trim()) throw new PyValueError("rule_pack requires a non-empty rule_version");
  return version;
}

function normalizeRange(value: any): [number, number, number] {
  if (isNumber(value)) value = { low: value, typical: value, high: value };
  if (!isDict(value) || !keysAre(value, [...BANDS])) throw new PyValueError("hours must be a number or a low/typical/high object");
  const numbers: number[] = [];
  for (const band of BANDS) {
    const raw = value[band];
    if (typeof raw === "boolean" || !isNumber(raw)) throw new PyValueError(`hours.${band} must be numeric`);
    const number = raw;
    if (number < 0 || number !== number || number === Infinity || number === -Infinity) throw new PyValueError(`hours.${band} must be finite and non-negative`);
    numbers.push(number);
  }
  const sorted = [...numbers].sort((a, b) => a - b);
  if (numbers.some((n, i) => n !== sorted[i])) throw new PyValueError("hours must satisfy low <= typical <= high");
  return [numbers[0], numbers[1], numbers[2]];
}

const pyStr = (v: any): string => (typeof v === "string" ? v : repr(v));

export function publishRulePack(db: E04Database, rulePack: any): string {
  if (!isDict(rulePack)) throw new PyValueError("rule_pack must be an object");
  const version = ruleVersion(rulePack);
  const ruleId = pyStr(get(rulePack, "id", "fictional_labor_rules"));
  const status = get(rulePack, "status", "approved");
  if (status !== "approved" && status !== "draft") throw new PyValueError("rule_pack status must be approved or draft");
  const approvedBy = get(rulePack, "approved_by");
  if (status === "approved" && (!isStr(approvedBy) || !approvedBy.trim())) throw new PyValueError("approved rule_pack requires approved_by");
  const effectiveFrom = get(rulePack, "effective_from", "2026-10-11");
  const source = get(rulePack, "source", "fictional_simulator_fixture");
  const entries = get(rulePack, "rules");
  if (!isList(entries) || !entries.length) throw new PyValueError("rule_pack rules must be a non-empty list");

  const saved = db.snapshot();
  try {
    db.insertRule(ruleId, version, status, approvedBy, effectiveFrom, source);
    const seen = new Set<string>();
    entries.forEach((entry: any, index: number) => {
      if (!isDict(entry)) throw new PyValueError(`rule_pack rules[${index}] must be an object`);
      const operationId = get(entry, "operation_id");
      const operationKey = get(entry, "operation_key", operationId);
      const name = get(entry, "operation", operationId);
      const kind = get(entry, "kind", get(entry, "unit") === "elapsed_hours" ? "wait" : "work");
      const unit = get(entry, "unit", kind === "wait" ? "elapsed_hours" : "person_hours");
      if (![operationId, operationKey, name].every((x) => isStr(x) && x.trim())) {
        throw new PyValueError(`rule_pack rules[${index}] requires operation_id, operation_key, and operation`);
      }
      if (seen.has(operationId)) throw new PyValueError(`duplicate operation_id: ${operationId}`);
      seen.add(operationId);
      if ((kind !== "work" && kind !== "wait") || unit !== (kind === "wait" ? "elapsed_hours" : "person_hours")) {
        throw new PyValueError(`invalid kind/unit for operation: ${operationId}`);
      }
      const personCount = get(entry, "person_count", kind === "wait" ? 0 : 1);
      if (typeof personCount === "boolean" || !isInt(personCount) || personCount < 0) {
        throw new PyValueError(`person_count must be a non-negative integer: ${operationId}`);
      }
      const [low, typical, high] = normalizeRange(get(entry, "hours"));
      db.insertOperationDoNothing(operationId, operationKey, name, kind, unit);
      const existing = db.operationById(operationId)!;
      if (existing.operation_key !== operationKey || existing.kind !== kind || existing.unit !== unit) {
        throw new PyValueError(`operation definition conflicts with existing id: ${operationId}`);
      }
      db.insertRuleOperation(ruleId, version, operationId, low, typical, high, personCount);
      const evidenceRows = or(get(entry, "evidence"), [{ source: get(entry, "source", source), note: "架空のSimulator用規則" }]);
      (evidenceRows as any[]).forEach((it: any, evidenceIndex: number) => {
        if (!isDict(it) || !isStr(get(it, "source")) || !it.source.trim()) throw new PyValueError(`evidence source required for operation: ${operationId}`);
        const note = get(it, "note", "");
        if (!isStr(note)) throw new PyValueError(`evidence note must be a string: ${operationId}`);
        const evidenceId = get(it, "id", `${operationId}-evidence-${evidenceIndex + 1}`);
        db.insertEvidence(evidenceId, ruleId, version, operationId, it.source, note);
      });
    });
  } catch (error) {
    db.restore(saved);
    throw error;
  }
  return version;
}

export function seedDefaultRulePack(db: E04Database, version = "fictional-rule-v1"): void {
  const entries = DEFAULT_RULES.map(([operationId, name, kind, unit, numbers, personCount]) => ({
    operation_id: operationId,
    operation_key: operationId,
    operation: name,
    kind,
    unit,
    hours: { low: numbers[0], typical: numbers[1], high: numbers[2] },
    person_count: personCount,
    source: "fictional_simulator_fixture",
    evidence: [{ source: "fictional_simulator_fixture", note: "架空の比較用fixture。実測値ではない" }],
  }));
  publishRulePack(db, {
    id: "fictional_labor_rules", rule_version: version, status: "approved",
    approved_by: "fictional_shop_owner", effective_from: "2026-10-11",
    source: "fictional_simulator_fixture", rules: entries,
  });
}

function loadJoinedRules(db: E04Database, ruleId: any, version: any): [Dict | null, Dict[]] {
  const r = txt(ruleId);
  const v = txt(version);
  const rule = db.rules.find((x) => x.id === r && x.version === v) ?? null;
  if (!rule) return [null, []];
  const rows: Dict[] = [];
  for (const ro of db.ruleOperations) {
    if (ro.rule_id !== rule.id || ro.version !== rule.version) continue;
    const op = db.operations.find((o) => o.id === ro.operation_id);
    if (!op) continue;
    const evs = db.evidence.filter((e) => e.rule_id === ro.rule_id && e.version === ro.version && e.operation_id === ro.operation_id);
    const base = {
      operation_id: ro.operation_id, operation_key: op.operation_key, name: op.name, kind: op.kind, unit: op.unit,
      low: ro.low, typical: ro.typical, high: ro.high, person_count: ro.person_count,
    };
    if (!evs.length) rows.push({ ...base, evidence_source: null, evidence_note: null, _eid: "" });
    for (const e of evs) rows.push({ ...base, evidence_source: e.source, evidence_note: e.note, _eid: e.id });
  }
  rows.sort((a, b) => codePointCompare(a.operation_id, b.operation_id) || codePointCompare(a._eid, b._eid));
  return [rule, rows];
}

function observation(scenario: Dict, key: string): [any, string] {
  const value = get(or(get(scenario, "fields"), {}), key);
  if (isDict(value) && "value" in value) return [get(value, "value"), get(value, "status", "unknown")];
  return [value, value !== null ? "declared" : "unknown"];
}

const nullBands = () => ({ low: null, typical: null, high: null });

export function run(scenarioInput: Dict, rulePack: any = null, connection: E04Database | null = null): Dict {
  const scenario = deepcopy(scenarioInput);
  const db = connection ?? createDatabase();
  if (connection === null && rulePack === null) {
    const seedVersion = or(get(scenario, "rule_version"), "fictional-rule-v1");
    seedDefaultRulePack(db, seedVersion);
  }

  const pinnedVersion = get(scenario, "rule_version");
  let versionGap: string | null = null;
  if (rulePack !== null) {
    let packVersion: string;
    try {
      packVersion = publishRulePack(db, deepcopy(rulePack));
    } catch (error) {
      const name = error instanceof PyIntegrityError ? "IntegrityError" : error instanceof PyProgrammingError ? "ProgrammingError" : error instanceof PyValueError ? "ValueError" : (error as Error).constructor.name;
      return {
        engine_id: ENGINE_ID, rule_version: or(pinnedVersion, "unbound"), status: "missing-required",
        labor: { person_hours: nullBands(), elapsed_hours: nullBands(), breakdown: [], unknowns: [`rule_pack:database_write_failed:${name}`] },
        trace: [{ event: "rule_pack_transaction_rolled_back" }], operation_keys: [], approvals: [], simulator_notice: SIMULATOR_NOTICE,
      };
    }
    if (truthy(pinnedVersion) && packVersion !== pinnedVersion) versionGap = "rule_pack:pinned_version_mismatch";
  }

  const version: any = or(or(pinnedVersion, truthy(rulePack) ? ruleVersion(rulePack) : rulePack), "fictional-rule-v1");
  const ruleId = get(or(rulePack, {}), "id", "fictional_labor_rules");
  const [rule, joined] = loadJoinedRules(db, ruleId, version);
  const grouped = new Map<string, Dict>();
  for (const row of joined) {
    let it = grouped.get(row.operation_id);
    if (!it) {
      it = {
        operation_id: row.operation_id, operation_key: row.operation_key, operation: row.name,
        kind: row.kind, unit: row.unit, hours: { low: row.low, typical: row.typical, high: row.high },
        person_count: row.person_count, evidence: [],
      };
      grouped.set(row.operation_id, it);
    }
    if (truthy(row.evidence_source) && !it.evidence.some((ev: Dict) => ev.source === row.evidence_source && ev.note === row.evidence_note)) {
      it.evidence.push({ source: row.evidence_source, note: row.evidence_note });
    }
  }

  const [labor, , canonicalUnknowns] = referenceLabor(scenario);
  const unknowns: string[] = [...canonicalUnknowns];
  if (!rule) unknowns.push(`rule_pack:version_not_found:${version}`);
  else if (rule.status !== "approved") unknowns.push("rule_pack:approved_status_required");
  if (versionGap) unknowns.push(versionGap);
  const [rotorRelevance] = observation(scenario, "rotor_relevance");
  if (rotorRelevance === "relevant") {
    const [rotorValue, rotorStatus] = observation(scenario, "rotor_seizure_hours");
    const approval = get(get(or(get(scenario, "metadata"), {}), "approved_condition_widths", {}), "rotor_seizure_hours");
    const storedRotor = grouped.get("rotor_seizure")?.hours;
    if (rotorStatus !== "confirmed" || !isDict(rotorValue) || !keysAre(rotorValue, [...BANDS]) || !isDict(approval) || !pyEq(get(approval, "new_value"), rotorValue) || !pyEq(storedRotor ?? null, rotorValue)) {
      unknowns.push("rotor_seizure_hours:rule_approval_mismatch");
    }
  }
  const requiredIds = DEFAULT_RULES.map((e) => e[0]);
  for (const operationId of [...requiredIds].sort(codePointCompare)) {
    if (!grouped.has(operationId)) unknowns.push(`${operationId}:rule_missing`);
  }

  const trace: Dict[] = [{ event: "rule_version_pinned", rule_id: ruleId, rule_version: version }];
  for (const operationId of [...grouped.keys()].sort(codePointCompare)) {
    const it = grouped.get(operationId)!;
    trace.push({ event: "rule_operation_joined", operation_id: operationId, operation_key: it.operation_key, hours: { ...it.hours }, unit: it.unit, rule_version: version, evidence: deepcopy(it.evidence) });
  }

  const rowsById = new Map<any, Dict>();
  for (const row of get(labor, "breakdown", [])) if (truthy(get(row, "operation_id"))) rowsById.set(get(row, "operation_id"), row);
  if (!unknowns.length) {
    for (const operationId of requiredIds) {
      const it = grouped.get(operationId)!;
      const row = rowsById.get(operationId);
      if (row === undefined) continue;
      const hours = { ...it.hours };
      row.operation = it.operation;
      row.evidence_refs = it.evidence.map((ev: Dict) => ev.source);
      row.rule_version = version;
      if (operationId === "included_carry") {
        row.operation_key = "included_transport_removed";
        row.hours = { low: 0.0, typical: 0.0, high: 0.0 };
        trace.push({ event: "included_hours_credited", operation_id: operationId, hours, rule_version: version });
      } else if (it.kind === "wait") {
        row.status = "wait";
        row.hours = { low: 0.0, typical: 0.0, high: 0.0 };
        row.elapsed_hours = hours;
      } else if (operationId === "rotor_seizure" && observation(scenario, "rotor_relevance")[0] === "unrelated") {
        row.hours = { low: 0.0, typical: 0.0, high: 0.0 };
      } else {
        row.hours = hours;
        if (operationId === "rotor_seizure" && get(row, "status") === "conditional") row.status = "conditional";
      }
    }
    const included = grouped.get("included_carry")!.hours;
    const base = grouped.get("base_service")!.hours;
    const replacement = grouped.get("replacement_carry")!.hours;
    const person: Dict = { low: 0.0, typical: 0.0, high: 0.0 };
    const elapsed: Dict = { low: 0.0, typical: 0.0, high: 0.0 };
    for (const band of BANDS) {
      const netBase = base[band] - included[band];
      if (netBase < 0) unknowns.push("included_transport:credit_exceeds_base");
      person[band] += netBase + replacement[band];
      elapsed[band] += netBase + replacement[band] / Math.max(1, grouped.get("replacement_carry")!.person_count);
      const wash = grouped.get("wash")!.hours[band];
      person[band] += wash;
      elapsed[band] += wash;
      if (rotorRelevance === "relevant") {
        const rotor = grouped.get("rotor_seizure")!.hours[band];
        person[band] += rotor;
        elapsed[band] += rotor;
      }
      for (const operationId of ["snow_melt", "penetrant_wait", "parts_wait"]) elapsed[band] += grouped.get(operationId)!.hours[band];
    }
    if (!unknowns.length) {
      labor.person_hours = Object.fromEntries(BANDS.map((b) => [b, pyRound(person[b], 10)]));
      labor.elapsed_hours = canonicalUnknowns.some((u) => u.endsWith(":elapsed_duration_unknown"))
        ? Object.fromEntries(BANDS.map((b) => [b, null]))
        : Object.fromEntries(BANDS.map((b) => [b, pyRound(elapsed[b], 10)]));
    }
  }

  const blocking = unknowns.filter((u) => !u.endsWith(":elapsed_duration_unknown"));
  if (blocking.length) {
    labor.person_hours = nullBands();
    labor.elapsed_hours = nullBands();
    for (const row of get(labor, "breakdown", [])) {
      row.hours = nullBands();
      if ("elapsed_hours" in row) row.elapsed_hours = nullBands();
      row.status = "missing-required";
    }
  }
  labor.unknowns = dedupe(unknowns);

  const approvals: Dict[] = [];
  if (rule && rule.status === "approved") {
    approvals.push({ type: "rule_pack", approver: rule.approved_by, effective_from: rule.effective_from, source: rule.source, rule_version: version });
  }
  const approval = get(get(or(get(scenario, "metadata"), {}), "approved_condition_widths", {}), "rotor_seizure_hours");
  if (truthy(approval) && observation(scenario, "rotor_relevance")[0] === "relevant") {
    approvals.push({
      operation_key: "rotor_seizure", actor: get(approval, "actor"), reason: get(approval, "reason"),
      old_value: deepcopy(get(approval, "old_value")), new_value: deepcopy(get(approval, "new_value")),
      applied_range: deepcopy(grouped.get("rotor_seizure")?.hours ?? null), rule_version: version,
    });
  }
  const operationKeys = dedupe([...grouped.values()].map((it) => it.operation_key));
  const status = blocking.length ? "missing-required" : unknowns.length ? "partial" : "proposed";
  return { engine_id: ENGINE_ID, rule_version: version, status, labor, trace, operation_keys: operationKeys, approvals, simulator_notice: SIMULATOR_NOTICE };
}
