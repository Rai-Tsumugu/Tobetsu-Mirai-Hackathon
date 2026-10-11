/* eslint-disable @typescript-eslint/no-explicit-any */
// E14: simulator photo candidates require an auditable human decision. 元: e14.py
import {
  type Dict, PyTypeError, PyValueError, dedupe, deepcopy, get, has, isDict, isList, isNumber, isStr, isoDatetime, item, keysAre, keysOf, pyEq, pyIn, truthy, utcNowIso,
} from "./py";
import { BANDS } from "./contract";
import * as e07 from "./e07";

export const ENGINE_ID = "e14_photo_candidate_approval_queue";
export const RULE_VERSION = "e14-photo-candidate-approval-v1";
const SIMULATOR_NOTICE = "写真分類はローカルの架空Simulator候補です。画像・顧客情報・外部AIは使用しません。";
const nullRange = () => ({ low: null, typical: null, high: null });
const DEFAULT_ALLOWED: Dict = { rotor_relevance: ["relevant", "unrelated"], rotor_seizure_hours: "person_hour_range", subframe_relevance: ["relevant", "unrelated"] };
const AREA = /^[a-z][a-z0-9_-]{0,31}$/;
const REF_ID = /^[A-Za-z0-9_-]{1,48}$/;
const CANDIDATE_KEYS = new Set(["candidate_id", "photo_ref", "ai_candidate", "status", "human_audit", "human_value"]);
const AUDIT_LOG_KEY = "photo_candidate_audit_log";
const hashOf = e07.hashOf;

/** `x in {a, b}`（集合なので unhashable は TypeError）。 */
function inSet(x: any, values: any[]): boolean {
  if (isList(x) || isDict(x)) throw new PyTypeError("unhashable type");
  return values.some((v) => pyEq(v, x));
}

const fieldSnapshot = (fields: Dict, field: string): Dict => ({ present: has(fields, field), value: deepcopy(get(fields, field)) });

function snapshotValue(snapshot: Dict): any {
  const fieldState = get(snapshot, "value");
  if (truthy(get(snapshot, "present")) && isDict(fieldState)) return deepcopy(get(fieldState, "value"));
  return truthy(get(snapshot, "present")) ? deepcopy(fieldState) : null;
}

function validValue(field: any, value: any, allowed: Dict): boolean {
  const options = get(allowed, field);
  if (options === "person_hour_range") {
    return (
      isDict(value) && keysAre(value, [...BANDS]) &&
      BANDS.every((k) => isNumber(value[k]) && 0 <= value[k] && value[k] < Infinity) &&
      value.low <= value.typical && value.typical <= value.high
    );
  }
  return isList(options) && pyIn(value, options);
}

function rules(rulePack: any, scenario: Dict): [Dict, any, string[]] {
  const issues: string[] = [];
  let version = get(scenario, "rule_version", RULE_VERSION);
  let allowed: Dict = deepcopy(DEFAULT_ALLOWED);
  if (rulePack !== null) {
    if (!isDict(rulePack)) {
      issues.push("rule_pack:object_required");
    } else {
      const pack = deepcopy(rulePack);
      if (!pyIn(get(pack, "engine_id"), [null, ENGINE_ID])) issues.push("rule_pack:engine_id_mismatch");
      if (!pyEq(get(pack, "rule_version"), version)) issues.push("rule_pack:rule_version_mismatch");
      if (get(pack, "status", "approved") !== "approved") issues.push("rule_pack:approved_version_required");
      if (keysOf(pack).some((k) => !["engine_id", "rule_version", "status", "allowed_values"].includes(k))) issues.push("rule_pack:unknown_key");
      if ("allowed_values" in pack) {
        const custom = pack.allowed_values;
        if (!isDict(custom) || !keysAre(custom, Object.keys(DEFAULT_ALLOWED))) {
          issues.push("rule_pack:allowed_values_must_define_known_fields");
        } else {
          for (const [field, values] of Object.entries(custom)) {
            const valid = field === "rotor_seizure_hours"
              ? values === "person_hour_range"
              : isList(values) && values.length > 0 && values.every((v) => isStr(v) && v) && values.length === new Set(values).size;
            if (!valid) issues.push(`rule_pack:${field}_invalid_allowed_values`);
          }
          if (!issues.length) allowed = deepcopy(custom);
        }
      }
    }
  }
  if (!isStr(version) || !version.trim()) {
    issues.push("rule_version:required");
    version = RULE_VERSION;
  }
  return [allowed, version, dedupe(issues)];
}

function photoRef(value: any): boolean {
  return isDict(value) && keysAre(value, ["area", "id"]) && isStr(value.area) && AREA.test(value.area) && isStr(value.id) && REF_ID.test(value.id);
}

function candidateIssues(candidates: any, allowed: Dict): string[] {
  if (!isList(candidates)) return ["photo_candidates:list_required"];
  const issues: string[] = [];
  const seen = new Set<string>();
  candidates.forEach((candidate, index) => {
    const prefix = `photo_candidates[${index}]`;
    if (!isDict(candidate)) {
      issues.push(`${prefix}:object_required`);
      return;
    }
    if (keysOf(candidate).some((k) => !CANDIDATE_KEYS.has(k))) issues.push(`${prefix}:unknown_or_private_data_rejected`);
    const cid = get(candidate, "candidate_id");
    if (!isStr(cid) || !REF_ID.test(cid)) issues.push(`${prefix}:candidate_id_invalid`);
    else if (seen.has(cid)) issues.push(`${cid}:duplicate_candidate_id`);
    else seen.add(cid);
    if (!photoRef(get(candidate, "photo_ref"))) issues.push(`${prefix}:anonymous_photo_ref_required`);
    const ai = get(candidate, "ai_candidate");
    if (!isDict(ai) || !keysAre(ai, ["field", "value"])) issues.push(`${prefix}:simulator_candidate_shape`);
    else if (!isStr(get(ai, "field")) || !validValue(ai.field, get(ai, "value"), allowed)) issues.push(`${prefix}:candidate_value_not_allowed`);
    const status = get(candidate, "status", "pending");
    if (!inSet(status, ["pending", "approved", "modified", "rejected"])) issues.push(`${prefix}:invalid_state`);
    const audit = get(candidate, "human_audit");
    if (inSet(status, ["approved", "modified", "rejected"])) {
      if (
        !isDict(audit) || !keysAre(audit, ["actor", "reason", "old_value", "new_value", "timestamp", "before_sha256", "after_sha256"]) ||
        !["actor", "reason", "timestamp"].every((k) => isStr(get(audit, k)) && audit[k].trim())
      ) {
        issues.push(`${prefix}:human_audit_required`);
      } else if (status === "rejected") {
        if (!pyEq(audit.new_value, "rejected")) issues.push(`${prefix}:rejected_audit_mismatch`);
      } else if (!pyEq(audit.new_value, get(candidate, "human_value")) || !validValue(get(ai, "field"), audit.new_value, allowed)) {
        issues.push(`${prefix}:observation_audit_mismatch`);
      }
    } else if (audit !== null || "human_value" in candidate) {
      issues.push(`${prefix}:pending_must_not_have_human_audit`);
    }
  });
  return issues;
}

/** Append simulator proposals as pending, without mutating either argument. */
export function proposeCandidates(scenarioInput: any, candidates: any): Dict {
  if (!isDict(scenarioInput) || !isList(candidates)) throw new PyValueError("scenario_input:object_and_candidates:list_required");
  const result = deepcopy(scenarioInput);
  const queued = deepcopy(get(result, "photo_candidates", []));
  if (!isList(queued)) throw new PyValueError("photo_candidates:list_required");
  for (const it of deepcopy(candidates)) {
    if (!isDict(it)) throw new PyValueError("candidate:object_required");
    if (["status", "human_audit", "human_value"].some((k) => k in it)) throw new PyValueError("candidate:proposal_cannot_set_human_state");
    queued.push({ ...it, status: "pending" });
  }
  result.photo_candidates = queued;
  return result;
}

function decision(scenarioInput: any, candidateId: any, actor: any, reason: any, status: string, observedValue: any = null, timestamp: any = null): Dict {
  if (!isDict(scenarioInput)) throw new PyValueError("scenario_input:object_required");
  if (![candidateId, actor, reason].every((v) => isStr(v) && v.trim())) throw new PyValueError("candidate_id_actor_reason:required");
  const result = deepcopy(scenarioInput);
  const candidates = get(result, "photo_candidates");
  if (!isList(candidates)) throw new PyValueError("photo_candidates:list_required");
  const matches = candidates.filter((c) => isDict(c) && pyEq(get(c, "candidate_id"), candidateId));
  if (matches.length !== 1) throw new PyValueError("candidate_id:must_match_exactly_one_pending_candidate");
  const candidate = matches[0];
  if (get(candidate, "status", "pending") !== "pending") throw new PyValueError("candidate:only_pending_can_transition");
  const ai = get(candidate, "ai_candidate");
  if (!isDict(ai) || !keysAre(ai, ["field", "value"])) throw new PyValueError("candidate:simulator_candidate_shape");
  const fieldsBefore = get(result, "fields", {});
  if (!isDict(fieldsBefore)) throw new PyValueError("fields:object_required");
  const beforeSnapshot = fieldSnapshot(fieldsBefore, ai.field);
  const oldValue = snapshotValue(beforeSnapshot);
  const finalValue = deepcopy(status === "approved" ? get(ai, "value") : observedValue);
  const [allowed, , ruleIssues] = rules(null, result);
  if (ruleIssues.length || !validValue(get(ai, "field"), finalValue, allowed)) throw new PyValueError("observed_value:not_allowed");
  const stamp = truthy(timestamp) ? timestamp : utcNowIso();
  if (!isStr(stamp)) throw new PyTypeError("timestamp must be a string");
  let parsed;
  try {
    parsed = isoDatetime(stamp.replace(/Z/g, "+00:00"));
  } catch (e) {
    if (e instanceof PyValueError) throw new PyValueError("timestamp:iso8601_required");
    throw e;
  }
  if (!parsed.aware) throw new PyValueError("timestamp:timezone_required");
  candidate.status = status;
  candidate.human_value = finalValue;
  candidate.human_audit = {
    actor: actor.trim(), reason: reason.trim(), old_value: oldValue,
    new_value: status === "rejected" ? "rejected" : deepcopy(finalValue), timestamp: stamp,
  };
  let fields: Dict = fieldsBefore;
  if (status !== "rejected") {
    if (!("fields" in result)) result.fields = {};
    fields = result.fields;
    fields[ai.field] = { value: deepcopy(finalValue), status: "confirmed", source: "human-confirmed-photo-candidate", confirmed_at: stamp };
  }
  const afterSnapshot = fieldSnapshot(status === "rejected" ? fieldsBefore : fields, ai.field);
  candidate.human_audit.before_sha256 = hashOf(beforeSnapshot);
  candidate.human_audit.after_sha256 = hashOf(afterSnapshot);
  if (!("metadata" in result)) result.metadata = {};
  const metadata = result.metadata;
  if (!isDict(metadata)) throw new PyValueError("metadata:object_required");
  if (!(AUDIT_LOG_KEY in metadata)) metadata[AUDIT_LOG_KEY] = [];
  const auditLog = metadata[AUDIT_LOG_KEY];
  if (!isList(auditLog)) throw new PyValueError("photo_candidate_audit_log:list_required");
  auditLog.push({
    candidate_id: candidateId, field: ai.field, before_snapshot: deepcopy(beforeSnapshot), after_snapshot: deepcopy(afterSnapshot),
    before_sha256: candidate.human_audit.before_sha256, after_sha256: candidate.human_audit.after_sha256,
  });
  if (status !== "rejected" && ai.field === "rotor_seizure_hours") {
    if (!("approved_condition_widths" in metadata)) metadata.approved_condition_widths = {};
    const approvals = metadata.approved_condition_widths;
    if (!isDict(approvals)) throw new PyValueError("approved_condition_widths:object_required");
    approvals.rotor_seizure_hours = { actor: actor.trim(), reason: reason.trim(), old_value: oldValue, new_value: deepcopy(finalValue) };
  }
  return result;
}

/** Accept the simulator's value as an observation after explicit human review. */
export const confirmCandidate = (scenarioInput: any, candidateId: any, actor: any, reason: any, timestamp: any = null): Dict =>
  decision(scenarioInput, candidateId, actor, reason, "approved", null, timestamp);

/** Accept a human-corrected value with old/new values preserved. */
export const modifyCandidate = (scenarioInput: any, candidateId: any, observedValue: any, actor: any, reason: any, timestamp: any = null): Dict =>
  decision(scenarioInput, candidateId, actor, reason, "modified", observedValue, timestamp);

/** Reject a proposal without writing its suggested condition to observations. */
export function rejectCandidate(scenarioInput: any, candidateId: any, actor: any, reason: any, timestamp: any = null): Dict {
  if (!isDict(scenarioInput)) throw new PyValueError("scenario_input:object_required");
  const candidates = get(scenarioInput, "photo_candidates");
  const candidate = isList(candidates) ? candidates.find((c) => isDict(c) && pyEq(get(c, "candidate_id"), candidateId)) : undefined;
  if (candidate === undefined || !isDict(get(candidate, "ai_candidate"))) throw new PyValueError("candidate_id:pending_candidate_required");
  return decision(scenarioInput, candidateId, actor, reason, "rejected", deepcopy(get(candidate.ai_candidate, "value")), timestamp);
}

const APPROVED_STATES = ["approved", "modified", "rejected"];

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const original: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const [allowed, version, issues] = rules(rulePack, original);
  const candidates = get(original, "photo_candidates", []);
  issues.push(...candidateIssues(candidates, allowed));
  if (issues.length) {
    const labor = { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(issues) };
    return {
      engine_id: ENGINE_ID, rule_version: version, status: "missing-required", labor,
      trace: [{ stage: "photo_candidate_stop", rule_sha256: hashOf(allowed), input_sha256: hashOf(original), issues: labor.unknowns }],
      operation_keys: [], approvals: [], simulator_notice: SIMULATOR_NOTICE,
    };
  }
  const scenario = deepcopy(original);
  delete scenario.photo_candidates;
  if (!("fields" in scenario)) scenario.fields = {};
  let fields = scenario.fields;
  if (!isDict(fields)) {
    fields = {};
    scenario.fields = fields;
  }
  let metadata = get(scenario, "metadata", {});
  const auditLog: any = isDict(metadata) ? get(metadata, AUDIT_LOG_KEY, []) : null;
  const logById = new Map<string, Dict>();
  if (!isList(auditLog)) {
    issues.push("photo_candidate_audit_log:list_required");
  } else {
    for (const entry of auditLog) {
      if (!isDict(entry) || !keysAre(entry, ["candidate_id", "field", "before_snapshot", "after_snapshot", "before_sha256", "after_sha256"])) {
        issues.push("photo_candidate_audit_log:entry_invalid");
        continue;
      }
      const cid = get(entry, "candidate_id");
      if (
        !isStr(cid) || !REF_ID.test(cid) || !pyIn(get(entry, "field"), allowed) ||
        !["before_snapshot", "after_snapshot"].every((key) => isDict(entry[key]) && keysAre(entry[key], ["present", "value"]) && typeof get(entry[key], "present") === "boolean") ||
        !["before_sha256", "after_sha256"].every((key) => isStr(entry[key]) && /^[0-9a-f]{64}$/.test(entry[key]))
      ) {
        issues.push("photo_candidate_audit_log:entry_invalid");
        continue;
      }
      if (logById.has(cid)) issues.push(`${cid}:duplicate_audit_snapshot`);
      logById.set(cid, entry);
    }
  }
  for (const candidate of candidates) {
    if (!APPROVED_STATES.includes(get(candidate, "status", "pending"))) continue;
    const ai = item(candidate, "ai_candidate");
    const field = item(ai, "field");
    const value = item(candidate, "human_value");
    const audit = item(candidate, "human_audit");
    const entry = isList(auditLog) ? logById.get(candidate.candidate_id) : undefined;
    if (!isDict(entry)) {
      issues.push(`${candidate.candidate_id}:confirmed_observation_missing_or_mismatch`);
      continue;
    }
    const beforeSnapshot = entry.before_snapshot;
    const afterSnapshot = entry.after_snapshot;
    if (
      hashOf(beforeSnapshot) !== entry.before_sha256 || hashOf(afterSnapshot) !== entry.after_sha256 ||
      !pyEq(get(audit, "before_sha256"), entry.before_sha256) || !pyEq(get(audit, "after_sha256"), entry.after_sha256) ||
      !pyEq(get(audit, "old_value"), snapshotValue(beforeSnapshot)) ||
      (get(candidate, "status") === "rejected" && (!pyEq(beforeSnapshot, afterSnapshot) || !pyEq(get(audit, "new_value"), "rejected"))) ||
      (get(candidate, "status") !== "rejected" && !pyEq(snapshotValue(afterSnapshot), get(audit, "new_value"))) ||
      !pyEq(get(entry, "field"), field)
    ) {
      issues.push(`${candidate.candidate_id}:condition_approval_audit_mismatch`);
      continue;
    }
    if (get(candidate, "status") === "rejected") continue;
    const current = get(fields, field);
    if (!isDict(current) || !pyEq(current, item(afterSnapshot, "value")) || !pyEq(get(current, "value"), value) || get(current, "status") !== "confirmed" || !pyEq(get(current, "confirmed_at"), item(audit, "timestamp"))) {
      issues.push(`${candidate.candidate_id}:confirmed_observation_missing_or_mismatch`);
      continue;
    }
    if (field === "rotor_seizure_hours") {
      metadata = get(scenario, "metadata", {});
      const approvals = isDict(metadata) ? get(metadata, "approved_condition_widths", {}) : {};
      const expected = { actor: item(audit, "actor"), reason: item(audit, "reason"), old_value: item(audit, "old_value"), new_value: item(audit, "new_value") };
      if (!pyEq(get(approvals, field), expected)) issues.push(`${candidate.candidate_id}:condition_approval_audit_mismatch`);
    }
  }
  if (isList(auditLog)) {
    const approvedIds = new Set<string>(candidates.filter((c: Dict) => APPROVED_STATES.includes(get(c, "status"))).map((c: Dict) => item(c, "candidate_id")));
    if (logById.size !== approvedIds.size || [...logById.keys()].some((k) => !approvedIds.has(k))) issues.push("photo_candidate_audit_log:candidate_state_mismatch");
  }
  let labor: Dict;
  let status: string;
  let inner: Dict | null = null;
  if (issues.length) {
    labor = { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(issues) };
    status = "missing-required";
  } else {
    inner = e07.run(scenario, null);
    labor = inner.labor;
    status = inner.status;
  }
  const trace: Dict[] = [{
    stage: "photo_candidate_queue", input_sha256: hashOf(original), rule_sha256: hashOf(allowed), rule_version: version,
    candidate_states: candidates.map((c: Dict) => ({ candidate_id: item(c, "candidate_id"), status: get(c, "status", "pending"), photo_ref: deepcopy(item(c, "photo_ref")), ai_candidate: deepcopy(item(c, "ai_candidate")) })),
    confirmed_observation_count: candidates.filter((c: Dict) => ["approved", "modified"].includes(get(c, "status"))).length,
  }];
  if (inner) trace.push(...deepcopy(inner.trace));
  return {
    engine_id: ENGINE_ID, rule_version: version, status, labor: deepcopy(labor), trace,
    operation_keys: inner ? [...get(inner, "operation_keys", [])] : [], approvals: inner ? deepcopy(get(inner, "approvals", [])) : [], simulator_notice: SIMULATOR_NOTICE,
  };
}
