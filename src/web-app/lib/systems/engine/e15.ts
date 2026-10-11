/* eslint-disable @typescript-eslint/no-explicit-any */
// E15: manual voice-note candidates that need a human before changing observations. 元: e15.py
// 入力は手入力の文字起こしのみ。生テキストは保存せず、許可されたタグだけを結果に出す。
import { type Dict, dedupe, deepcopy, get, isDict, isList, isStr, keysOf, or, pyEq, pyIn, truthy } from "./py";
import { referenceLabor } from "./contract";

export const ENGINE_ID = "e15_voice_candidate_confirmation";
export const RULE_VERSION = "e15-voice-candidate-confirmation-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。音声認識・実測工数・実価格・実車検証は行いません。";
const ALLOWED_TAGS: Record<string, [string, string]> = {
  rust_present: ["rust_observation", "present"],
  rust_absent: ["rust_observation", "absent"],
  rotor_seized: ["rotor_relevance", "relevant"],
  rotor_not_seized: ["rotor_relevance", "unrelated"],
  snow_present: ["snow_observation", "present"],
  snow_absent: ["snow_observation", "absent"],
};
const nullRange = () => ({ low: null, typical: null, high: null });
const isTag = (v: any): v is string => isStr(v) && Object.prototype.hasOwnProperty.call(ALLOWED_TAGS, v);
const VOICE_ID = /^voice-\d+$/;

function candidate(candidateId: string, tag: string, status: string, field: string | null = null, value: any = null, side: string | null = null, alternatives: string[] | null = null, ambiguity: string | null = null): Dict {
  const result: Dict = { candidate_id: candidateId, tag, status };
  if (field !== null) {
    result.field = field;
    result.value = value;
  }
  if (side !== null) result.side = side;
  if (alternatives && alternatives.length) result.alternatives = [...alternatives];
  if (ambiguity !== null) result.ambiguity = ambiguity;
  return result;
}

const CLAUSE_SPLIT = /[。.!！?？,、;；]/;

/** Recognize negation attached to this condition keyword, within its local clause. （位置は Python と同じコードポイント単位） */
function hasNegation(chars: string[], start: number, end: number, kind: string): boolean {
  let before = chars.slice(Math.max(0, start - 16), start).join("");
  let after = chars.slice(end, Math.min(chars.length, end + 16)).join("");
  before = before.split(CLAUSE_SPLIT).at(-1)!;
  after = after.split(CLAUSE_SPLIT)[0];
  const particle = "(?:は|が|も)?";
  const endings = "(?:ない|なく|無し|なし|ありません|ではない|じゃない|ではなく|じゃなく|見られない|見られず|出てない|出ていない|ていない|てない|てません|してない|していない|してません|ず)";
  if (new RegExp(particle + endings, "u").test(after)) return true;
  if (new RegExp(particle + endings + "\\s*$", "u").test(after)) return true;
  const targetNames = ({ rust: "(?:錆|さび|サビ)", rotor: "(?:固着|固ま)", snow: "(?:雪|氷|凍結)" } as Record<string, string>)[kind];
  return /(?:ではなく|じゃなく|ではない|じゃない|なく|なし|無し)\s*$/u.test(before) && new RegExp(targetNames + "\\s*$", "u").test(before);
}

/** Extract allowlisted condition tags from typed text, without returning the text. */
export function extractCandidates(manualTranscription: any): Dict {
  if (!isStr(manualTranscription)) return { candidates: [], unknowns: ["manual_transcription:string_required"] };
  const chars = Array.from(manualTranscription);
  if (chars.length > 2000) return { candidates: [], unknowns: ["manual_transcription:too_long"] };
  const text = manualTranscription;
  const patterns: [string, RegExp, string, string][] = [
    ["rust", /錆|さび|サビ/gu, "rust_present", "rust_absent"],
    ["rotor", /ローター[^\n]{0,8}固着|固着/gu, "rotor_seized", "rotor_not_seized"],
    ["snow", /雪|氷|凍結/gu, "snow_present", "snow_absent"],
  ];
  const marks = Array.from("。.!！?？,、;；\n");
  const detections: Dict[] = [];
  for (const [kind, pattern, positiveTag, negativeTag] of patterns) {
    for (const match of text.matchAll(pattern)) {
      const start = Array.from(text.slice(0, match.index)).length;
      const end = start + Array.from(match[0]).length;
      const tag = hasNegation(chars, start, end, kind) ? negativeTag : positiveTag;
      const clauseStart = Math.max(...marks.map((mark) => chars.slice(0, start).lastIndexOf(mark) + 1));
      const clauseEnds = marks.map((mark) => {
        const i = chars.indexOf(mark, end);
        return i;
      });
      const clauseEnd = Math.min(...clauseEnds.filter((p) => p >= 0), chars.length);
      const clause = chars.slice(clauseStart, clauseEnd).join("");
      const left = /左(?:側|輪|前|後)?/u.test(clause);
      const right = /右(?:側|輪|前|後)?/u.test(clause);
      const uncertain = /(?:左か右|右か左|左右どちら|左右どっち|どちらか)/u.test(clause);
      const both = /(?:左右|両側|両方)/u.test(clause);
      if (uncertain || (left && right && !both)) {
        detections.push({ kind, tag, side: null, ambiguous_side: true, start });
      } else if (both) {
        for (const side of ["left", "right"]) detections.push({ kind, tag, side, ambiguous_side: false, start });
      } else {
        detections.push({ kind, tag, side: left ? "left" : right ? "right" : null, ambiguous_side: false, start });
      }
    }
  }

  const grouped = new Map<string, { kind: string; side: string | null; items: Dict[] }>();
  for (const it of [...detections].sort((a, b) => a.start - b.start)) {
    const k = `${it.kind}|${it.side}`;
    if (!grouped.has(k)) grouped.set(k, { kind: it.kind, side: it.side, items: [] });
    grouped.get(k)!.items.push(it);
  }
  const candidates: Dict[] = [];
  for (const { side, items } of grouped.values()) {
    const tags = dedupe(items.map((i) => i.tag as string));
    const ambiguousSide = items.some((i) => i.ambiguous_side);
    if (tags.length > 1) {
      const field = ALLOWED_TAGS[tags[0]][0];
      candidates.push(candidate(`voice-${candidates.length + 1}`, tags[0], "ambiguous", field, ALLOWED_TAGS[tags[0]][1], side, tags, "condition_conflict"));
    } else {
      const tag = tags[0];
      const [field, value] = ALLOWED_TAGS[tag];
      if (ambiguousSide) candidates.push(candidate(`voice-${candidates.length + 1}`, tag, "ambiguous", field, value, null, ["left", "right"], "side"));
      else candidates.push(candidate(`voice-${candidates.length + 1}`, tag, "pending", field, value, side));
    }
  }
  const unknowns = candidates.length ? [] : text.trim() ? ["manual_transcription:no_allowed_tags"] : [];
  return { candidates, unknowns };
}

function safeCandidate(cand: any): [Dict | null, string | null] {
  if (!isDict(cand)) return [null, "candidate:object_required"];
  let tag = get(cand, "tag");
  const status = get(cand, "status");
  if (status === "ambiguous") {
    const alternatives = get(cand, "alternatives");
    tag = get(cand, "tag");
    const ambiguity = get(cand, "ambiguity", "side");
    const candidateId = get(cand, "candidate_id");
    let valid: boolean;
    if (ambiguity === "condition_conflict") {
      valid =
        isList(alternatives) && alternatives.length === 2 && alternatives.every((o) => isTag(o)) &&
        ALLOWED_TAGS[alternatives[0]][0] === ALLOWED_TAGS[alternatives[1]][0] &&
        ALLOWED_TAGS[alternatives[0]][1] !== ALLOWED_TAGS[alternatives[1]][1] &&
        pyIn(tag, alternatives) && pyEq(get(cand, "field"), ALLOWED_TAGS[alternatives[0]][0]) &&
        isTag(tag) && pyEq(get(cand, "value"), ALLOWED_TAGS[tag][1]) && pyIn(get(cand, "side"), [null, "left", "right"]);
    } else {
      valid = isTag(tag) && isList(alternatives) && pyEq(alternatives, ["left", "right"]) && ambiguity === "side";
    }
    if (!valid) return [null, "candidate:invalid_alternatives"];
    if (candidateId !== null && (!isStr(candidateId) || !VOICE_ID.test(candidateId))) return [null, "candidate:invalid_id"];
    return [{
      candidate_id: candidateId, status, tag, field: get(cand, "field", isTag(tag) ? ALLOWED_TAGS[tag][0] : null),
      value: isTag(tag) ? ALLOWED_TAGS[tag][1] : null, alternatives: [...alternatives], ambiguity, side: get(cand, "side"),
    }, null];
  }
  if (!isTag(tag)) return [null, "candidate:unknown_tag"];
  const [field, value] = ALLOWED_TAGS[tag];
  if (status !== "pending" || !pyEq(get(cand, "field"), field) || !pyEq(get(cand, "value"), value)) return [null, "candidate:invalid_or_already_resolved"];
  const side = get(cand, "side");
  if (!pyIn(side, [null, "left", "right"])) return [null, "candidate:invalid_side"];
  const candidateId = get(cand, "candidate_id");
  if (candidateId !== null && (!isStr(candidateId) || !VOICE_ID.test(candidateId))) return [null, "candidate:invalid_id"];
  return [{ candidate_id: candidateId, tag, status, field, value, side }, null];
}

/** Append an audited observation; never mutate the supplied scenario or overwrite history. */
export function confirmCandidate(
  scenarioInput: any, cand: any, actor: any, reason: any, approved: any = true, resolvedSide: any = null, resolvedTag: any = null,
): Dict {
  const scenario: Dict | null = isDict(scenarioInput) ? deepcopy(scenarioInput) : null;
  const [safe, err] = safeCandidate(cand);
  let error = err;
  if (scenario === null) error = "scenario_input:object_required";
  if (error) return { scenario_input: scenario, approval: null, error };
  const s = safe as Dict;
  const sc = scenario as Dict;
  if (!isStr(actor) || !actor.trim() || !isStr(reason) || !reason.trim()) return { scenario_input: scenario, approval: null, error: "confirmation:actor_and_reason_required" };
  if (typeof approved !== "boolean") return { scenario_input: scenario, approval: null, error: "confirmation:approved_boolean_required" };

  let tag = get(s, "tag");
  if (s.status === "ambiguous") {
    if (get(s, "ambiguity") === "condition_conflict") {
      if (!pyIn(resolvedTag, s.alternatives)) return { scenario_input: scenario, approval: null, error: "confirmation:ambiguous_candidate_requires_allowed_resolution" };
      tag = resolvedTag;
    } else if (!pyIn(resolvedSide, s.alternatives)) {
      return { scenario_input: scenario, approval: null, error: "confirmation:ambiguous_candidate_requires_allowed_resolution" };
    }
  } else if (resolvedSide !== null || resolvedTag !== null) {
    return { scenario_input: scenario, approval: null, error: "confirmation:resolution_only_for_ambiguous_candidate" };
  }
  if (!approved) {
    return { scenario_input: scenario, approval: { candidate_id: get(s, "candidate_id"), tag, actor: actor.trim(), reason: reason.trim(), approved: false }, error: null };
  }
  const [field, value] = ALLOWED_TAGS[tag];
  const side = get(s, "ambiguity") === "side" ? resolvedSide : get(s, "side");
  if (!isDict(get(sc, "fields"))) return { scenario_input: deepcopy(scenarioInput), approval: null, error: "scenario_input:fields_must_be_object" };
  if ("observations" in sc && !isList(sc.observations)) return { scenario_input: deepcopy(scenarioInput), approval: null, error: "scenario_input:observations_must_be_list" };
  const fields = sc.fields;
  const previous = get(fields, field);
  const oldValue = isDict(previous) ? get(previous, "value") : previous;
  const observation: Dict = {
    field, value, status: "confirmed", source: "e15_manual_voice", actor: actor.trim(), reason: reason.trim(), approved: true, candidate_id: get(s, "candidate_id"),
  };
  if (truthy(side)) observation.side = side;
  if (!("observations" in sc)) sc.observations = [];
  sc.observations.push(deepcopy(observation));
  if (get(s, "ambiguity") === "side" || !truthy(side)) {
    fields[field] = { value, status: "confirmed", source: "e15_manual_voice", confirmed_at: null };
  } else {
    if (!("side_observations" in sc)) sc.side_observations = {};
    const byField = sc.side_observations;
    if (!isDict(byField)) return { scenario_input: deepcopy(scenarioInput), approval: null, error: "scenario_input:side_observations_must_be_object" };
    if (!(field in byField)) byField[field] = {};
    const perSide = byField[field];
    if (!isDict(perSide)) return { scenario_input: deepcopy(scenarioInput), approval: null, error: "scenario_input:side_observations_field_must_be_object" };
    perSide[side] = { value, status: "confirmed", source: "e15_manual_voice", actor: actor.trim(), reason: reason.trim(), candidate_id: get(s, "candidate_id") };
  }
  const approval: Dict = { candidate_id: get(s, "candidate_id"), tag, field, actor: actor.trim(), reason: reason.trim(), approved: true, old_value: oldValue, new_value: value };
  if (truthy(side)) approval.side = side;
  return { scenario_input: scenario, approval, error: null };
}

function nullLabor(unknowns: string[]): Dict {
  return { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(unknowns) };
}

/** Run the common simulator calculation while keeping voice candidates pending. */
export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const pack: Dict | null = isDict(rulePack) ? deepcopy(rulePack) : null;
  let version: any = or(get(scenario, "rule_version"), RULE_VERSION);
  let candidates: Dict[] = [];
  const issues: string[] = [];
  if (!isDict(scenarioInput)) issues.push("scenario_input:object_required");
  if (rulePack !== null) {
    if (pack === null) {
      issues.push("rule_pack:object_required");
    } else {
      if (keysOf(pack).some((k) => !["engine_id", "rule_version", "manual_transcription"].includes(k))) issues.push("rule_pack:unknown_key");
      if (!pyIn(get(pack, "engine_id"), [null, ENGINE_ID, "e15"])) issues.push("rule_pack:engine_id_mismatch");
      if ("rule_version" in pack && (!isStr(pack.rule_version) || !pack.rule_version.trim())) issues.push("rule_pack:rule_version_required");
      if (truthy(get(pack, "rule_version")) && truthy(get(scenario, "rule_version")) && !pyEq(pack.rule_version, scenario.rule_version)) issues.push("rule_pack:pinned_version_mismatch");
      version = or(get(pack, "rule_version"), version);
      if ("manual_transcription" in pack) {
        const extracted = extractCandidates(pack.manual_transcription);
        candidates = extracted.candidates;
        issues.push(...extracted.unknowns);
      }
    }
  }
  if (!isStr(version) || !version.trim()) issues.push("rule_version:required");
  let labor: Dict;
  let status: string;
  let trace: Dict[];
  if (issues.length && issues.some((i) => !i.endsWith(":no_allowed_tags"))) {
    labor = nullLabor(issues);
    status = "missing-required";
    trace = [{ event: "voice_candidates_checked", tags: candidates.map((c) => c.tag), statuses: candidates.map((c) => c.status), raw_transcription_stored: false }];
  } else {
    labor = deepcopy(referenceLabor(scenario)[0]);
    const blocking = get(labor, "unknowns", []).filter((i: string) => !i.endsWith(":elapsed_duration_unknown"));
    status = blocking.length ? "missing-required" : truthy(get(labor, "unknowns")) ? "partial" : "proposed";
    trace = [
      { event: "voice_candidates_checked", tags: candidates.map((c) => c.tag), statuses: candidates.map((c) => c.status), raw_transcription_stored: false },
      { event: "labor_calculated", rule_version: version, operation_keys: get(labor, "breakdown", []).filter((r: Dict) => truthy(get(r, "operation_id"))).map((r: Dict) => get(r, "operation_id")) },
    ];
  }
  const approvals: Dict[] = [];
  for (const it of isList(get(scenario, "observations")) ? scenario.observations : []) {
    if (isDict(it) && get(it, "source") === "e15_manual_voice") {
      approvals.push(Object.fromEntries(["candidate_id", "field", "value", "actor", "reason"].map((k) => [k, get(it, k)])));
    }
  }
  return {
    engine_id: ENGINE_ID, rule_version: version, status, labor, trace,
    operation_keys: get(labor, "breakdown", []).filter((r: Dict) => truthy(get(r, "operation_id"))).map((r: Dict) => get(r, "operation_id")),
    approvals, simulator_notice: SIMULATOR_NOTICE, voice_candidates: candidates,
  };
}
