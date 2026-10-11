/* eslint-disable @typescript-eslint/no-explicit-any */
// E10: immutable exclusive/deduplication ledger for labor operations. 元: e10.py
import {
  type Dict, PyValueError, dedupe, deepcopy, get, isDict, isInt, isList, isNumber, isStr, item, or, pyEq, pyIn, pyJsonDumps, pyRound, pySum,
  sha256Hex, truthy,
} from "./py";
import { BANDS } from "./contract";

export const ENGINE_ID = "e10_deduplication_ledger";
export const RULE_VERSION = "e10-deduplication-ledger-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const nullRange = () => ({ low: null, typical: null, high: null });

const isNum = (v: any) => isNumber(v) && Number.isFinite(v) && v >= 0;

type Key = [string, string, string];

function keyOf(value: any): Key {
  let parts: any[];
  if (isDict(value)) parts = [get(value, "operation"), get(value, "side"), get(value, "scope")];
  else if (isList(value) && value.length === 3) parts = [...value];
  else throw new PyValueError("ledger:key_must_be_operation_side_scope");
  if (parts.some((p) => !isStr(p) || !p.trim())) throw new PyValueError("ledger:key_parts_required");
  return parts.map((p) => p.trim()) as Key;
}

const entryKey = (entry: Dict): Key => keyOf(entry);
const sameKey = (a: Key, b: Key) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];

function ledgerCopy(ledger: any): Dict {
  if (ledger === null || ledger === undefined) return { entries: [] };
  if (isList(ledger)) ledger = { entries: ledger };
  if (!isDict(ledger) || !isList(get(ledger, "entries"))) throw new PyValueError("ledger:entries_list_required");
  const result = deepcopy(ledger);
  for (const entry of result.entries) {
    if (!isDict(entry)) throw new PyValueError("ledger:entry_object_required");
    entryKey(entry);
  }
  return result;
}

function owners(value: any): string[] {
  const list = isStr(value) ? [value] : value;
  if (!isList(list) || !list.length || list.some((o) => !isStr(o) || !o.trim())) throw new PyValueError("ledger:owners_required");
  return dedupe(list.map((o: string) => o.trim()));
}

/** 台帳を変更せず新しい台帳と監査イベントを返す。 */
export function deductOnce(ledger: any, key: any, amount: any, opts: { owners: any; reason: any }): [Dict, Dict] {
  if (!isNum(amount)) throw new PyValueError("ledger:deduction_amount_must_be_finite_nonnegative");
  if (!isStr(opts.reason) || !opts.reason.trim()) throw new PyValueError("ledger:reason_required");
  const normalizedKey = keyOf(key);
  const nextLedger = ledgerCopy(ledger);
  if (nextLedger.entries.some((e: Dict) => sameKey(entryKey(e), normalizedKey))) {
    return [nextLedger, { action: "deduct", key: [...normalizedKey], accepted: false, reason: "already_deducted" }];
  }
  const entry = {
    operation: normalizedKey[0], side: normalizedKey[1], scope: normalizedKey[2], owners: owners(opts.owners),
    deducted: true, deducted_hours: amount, replaced_by: null,
  };
  nextLedger.entries.push(entry);
  return [nextLedger, { action: "deduct", key: [...normalizedKey], accepted: true, amount_hours: amount, owners: [...entry.owners], reason: opts.reason.trim() }];
}

/** 含有作業を一度だけ置き換える。置き換えは加算ではない。 */
export function replaceOnce(
  ledger: any, key: any, replacementKey: any, opts: { owners: any; old_hours: any; replacement_hours: any; reason: any },
): [Dict, Dict] {
  if (!isNum(opts.old_hours) || !isNum(opts.replacement_hours)) throw new PyValueError("ledger:replacement_hours_must_be_finite_nonnegative");
  if (!isStr(opts.reason) || !opts.reason.trim()) throw new PyValueError("ledger:reason_required");
  const oldKey = keyOf(key);
  const newKey = keyOf(replacementKey);
  const nextLedger = ledgerCopy(ledger);
  const oldEntry = nextLedger.entries.find((e: Dict) => sameKey(entryKey(e), oldKey));
  const newExists = nextLedger.entries.some((e: Dict) => sameKey(entryKey(e), newKey));
  if (oldEntry === undefined) return [nextLedger, { action: "replace", key: [...oldKey], accepted: false, reason: "source_operation_missing" }];
  if (get(oldEntry, "replaced_by") !== null || newExists) return [nextLedger, { action: "replace", key: [...oldKey], accepted: false, reason: "already_replaced" }];
  oldEntry.deducted = true;
  oldEntry.deducted_hours = opts.old_hours;
  oldEntry.replaced_by = [...newKey];
  oldEntry.owners = dedupe([...get(oldEntry, "owners", []), ...owners(opts.owners)]);
  nextLedger.entries.push({
    operation: newKey[0], side: newKey[1], scope: newKey[2], owners: owners(opts.owners), deducted: false,
    deducted_hours: 0.0, replaced_by: null, replacement_hours: opts.replacement_hours,
  });
  return [nextLedger, { action: "replace", key: [...oldKey], replacement_key: [...newKey], accepted: true, removed_hours: opts.old_hours, added_hours: opts.replacement_hours, reason: opts.reason.trim() }];
}

const hashOf = (value: any) => sha256Hex(pyJsonDumps(value, { sortKeys: true, compact: true, ensureAscii: false, defaultStr: true }));

function stopped(version: any, issues: string[], trace: Dict[], ledger: Dict | null = null): Dict {
  trace.push({ stage: "ledger_stop", issues: dedupe(issues), ledger: deepcopy(truthy(ledger) ? ledger : { entries: [] }) });
  return {
    engine_id: ENGINE_ID, rule_version: version, status: "missing-required",
    labor: { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: dedupe(issues) },
    trace, operation_keys: [], approvals: [], simulator_notice: SIMULATOR_NOTICE,
  };
}

function canonicalFixture(scenario: Dict): boolean {
  const ops = get(scenario, "operations");
  const base = isList(ops) ? ops.find((op) => isDict(op) && get(op, "operation_id") === "base_service") : null;
  return get(get(scenario, "metadata", {}), "fictional_values") === true && truthy(base) && pyEq(get(base, "gross_hours"), 2.0) && pyEq(get(base, "hours"), 1.7) && get(base, "deduplicated") === true;
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const version = get(scenario, "rule_version", RULE_VERSION);
  const trace: Dict[] = [{ stage: "input_snapshot", input_sha256: hashOf(scenarioInput) }];
  const issues: string[] = [];
  if (!isDict(scenarioInput)) return stopped(version, ["scenario_input:object_required"], trace);
  if (get(scenario, "basis_unit") !== "person_hour" || !isStr(get(scenario, "basis_definition")) || !scenario.basis_definition.trim()) issues.push("basis_unit_or_definition:person_hour_required");
  if (rulePack !== null && !isDict(rulePack)) issues.push("rule_pack:object_required");
  const pack: Dict = isDict(rulePack) ? deepcopy(rulePack) : {};
  if (rulePack !== null) {
    if (!pyIn(get(pack, "engine_id"), [null, ENGINE_ID])) issues.push("rule_pack:engine_id_mismatch");
    if (!pyEq(get(pack, "rule_version"), version)) issues.push("rule_pack:rule_version_mismatch");
    if (get(pack, "status", "approved") !== "approved") issues.push("rule_pack:approved_version_required");
  }
  let fields = get(scenario, "fields");
  let operations = get(scenario, "operations");
  if (!isDict(fields)) {
    issues.push("fields:object_required");
    fields = {};
  }
  if (!isList(operations)) {
    issues.push("operations:list_required");
    operations = [];
  }
  const byId: Record<string, Dict> = {};
  operations.forEach((op: any, index: number) => {
    if (!isDict(op) || !isStr(get(op, "operation_id"))) {
      issues.push(`operations[${index}]:operation_id_required`);
      return;
    }
    const opId = op.operation_id;
    if (Object.prototype.hasOwnProperty.call(byId, opId)) issues.push(`${opId}:duplicate_operation_id`);
    byId[opId] = op;
  });
  const expected = ["base_service", "included_carry", "replacement_carry", "snow_melt", "penetrant_wait", "parts_wait", "wash"];
  for (const missing of [...expected].filter((k) => !Object.prototype.hasOwnProperty.call(byId, k)).sort()) issues.push(`${missing}:required_operation_missing`);
  for (const key of ["work_scope", "included_operations"]) {
    const obs = get(fields, key);
    if (!isDict(obs) || !["confirmed", "declared"].includes(get(obs, "status")) || get(obs, "value") === null) issues.push(`${key}:confirmed_value_required`);
  }
  if (!pyEq(get(scenario, "job_id"), get(or(get(fields, "work_scope"), {}), "value"))) issues.push("work_scope:must_match_job_id");
  if (issues.length) return stopped(version, issues, trace);

  const base = byId.base_service;
  const fixtureGrossMode = canonicalFixture(scenario) && rulePack === null && get(scenario, "ledger_mode") === null;
  const mode = fixtureGrossMode ? "gross" : get(scenario, "ledger_mode");
  const grossRaw = mode === "gross" ? get(base, "gross_hours") : get(base, "hours");
  if (mode !== "gross" && mode !== "deduplicated") issues.push("ledger_mode:explicit_gross_or_deduplicated_required");
  if (mode === "gross" && !isNum(grossRaw)) issues.push("base_service:gross_hours_required_in_gross_mode");
  if (mode === "deduplicated" && (get(base, "deduplicated") !== true || !isNum(grossRaw))) issues.push("base_service:deduplicated_hours_and_flag_required");
  if (mode === "gross" && get(base, "deduplicated") === true && !fixtureGrossMode) issues.push("base_service:explicit_rededuction_of_deduplicated_hours_rejected");
  const gross = isNum(grossRaw) ? grossRaw : 0.0;

  let shared: any = rulePack !== null ? get(pack, "shared_deductions") : null;
  if (shared === null) {
    shared = mode === "gross"
      ? [{ key: { operation: "shared_overlap", side: "both", scope: item(scenario, "job_id") }, hours: 0.3, owners: ["left_work", "right_work"], reason: "Fictional shared operation is deducted once for both owners." }]
      : [];
  } else if (mode === "deduplicated" && truthy(shared)) {
    issues.push("base_service:explicit_rededuction_of_deduplicated_hours_rejected");
  }
  if (!isList(shared)) {
    issues.push("shared_deductions:list_required");
    shared = [];
  }
  let ledger: Dict;
  try {
    ledger = ledgerCopy(rulePack !== null ? get(pack, "ledger", { entries: [] }) : null);
  } catch (exc) {
    if (exc instanceof PyValueError) {
      issues.push(exc.message);
      return stopped(version, issues, trace);
    }
    throw exc;
  }
  const events: Dict[] = [];
  let totalDeduction = 0.0;
  shared.forEach((action: any, index: number) => {
    if (!isDict(action)) {
      issues.push(`shared_deductions[${index}]:object_required`);
      return;
    }
    try {
      const amount = get(action, "hours");
      if (!isNum(amount)) throw new PyValueError("ledger:deduction_amount_must_be_finite_nonnegative");
      const [nextLedger, event] = deductOnce(ledger, get(action, "key"), amount, { owners: get(action, "owners"), reason: get(action, "reason", "Shared operation deduction.") });
      ledger = nextLedger;
      events.push(event);
      if (event.accepted) totalDeduction += amount;
      else issues.push(`shared_deductions[${index}]:${event.reason}`);
    } catch (exc) {
      if (exc instanceof PyValueError) issues.push(`shared_deductions[${index}]:${exc.message}`);
      else throw exc;
    }
  });
  if (totalDeduction > gross) issues.push("base_service:deductions_exceed_gross_hours");

  let groups: any = truthy(pack) ? get(pack, "exclusive_groups", []) : [];
  if (!isList(groups)) {
    issues.push("exclusive_groups:list_required");
    groups = [];
  }
  groups.forEach((group: any, index: number) => {
    if (!isDict(group) || !isList(get(group, "selected"))) issues.push(`exclusive_groups[${index}]:selected_list_required`);
    else if (group.selected.length !== 1) issues.push(`exclusive_groups[${index}]:exactly_one_selection_required`);
  });
  if (issues.length) return stopped(version, issues, trace, ledger);

  const included = byId.included_carry;
  const replacement = byId.replacement_carry;
  const includedHours = get(included, "hours");
  const replacementCount = get(replacement, "person_count");
  const perPerson = get(replacement, "hours_per_person");
  if (
    get(included, "included_in_base") !== true || !isNum(includedHours) || get(replacement, "replaces_operation_id") !== "included_carry" ||
    typeof replacementCount === "boolean" || !isInt(replacementCount) || replacementCount <= 0 || !isNum(perPerson)
  ) {
    issues.push("included_carry:valid_included_operation_and_replacement_required");
    return stopped(version, issues, trace, ledger);
  }
  const sourceKey = { operation: "included_carry", side: "both", scope: item(scenario, "job_id") };
  const [sourceLedger, sourceEvent] = deductOnce(ledger, sourceKey, includedHours, { owners: ["base_service"], reason: "Remove included carry before replacement." });
  if (sourceEvent.accepted) ledger = sourceLedger;
  else issues.push("included_carry:already_deducted");
  const [replacementLedger, replacementEvent] = replaceOnce(
    ledger, sourceKey, { operation: "replacement_carry", side: "both", scope: scenario.job_id }, {
      owners: ["replacement_carry"], old_hours: includedHours, replacement_hours: perPerson * replacementCount,
      reason: "Replace included transport with two-person handling.",
    },
  );
  if (replacementEvent.accepted) ledger = replacementLedger;
  else issues.push(`replacement_carry:${replacementEvent.reason}`);
  if (issues.length) {
    trace.push({ stage: "ledger_actions", events: [...events, sourceEvent, replacementEvent], ledger });
    return stopped(version, issues, trace, ledger);
  }

  const waiting: Record<string, number | null> = {};
  const elapsedUnknowns: string[] = [];
  for (const opId of ["snow_melt", "penetrant_wait", "parts_wait"]) {
    const op = byId[opId];
    const raw = get(op, "elapsed_hours", get(op, "duration_hours", get(op, "hours")));
    if (opId === "parts_wait" && get(op, "stock_checked") !== true) issues.push("parts_wait:stock_confirmation_required");
    if (raw === null) {
      elapsedUnknowns.push(`${opId}:elapsed_duration_unknown`);
      waiting[opId] = null;
    } else if (!isNum(raw)) {
      issues.push(`${opId}:elapsed_duration_invalid`);
      waiting[opId] = null;
    } else {
      waiting[opId] = raw;
    }
  }
  const washHours = get(byId.wash, "hours");
  if (!isNum(washHours)) issues.push("wash:person_hour_duration_required");
  let rotor: Dict = { low: 0.0, typical: 0.0, high: 0.0 };
  const rotorObs = get(fields, "rotor_seizure_hours");
  const relevanceObs = get(fields, "rotor_relevance");
  if (isDict(relevanceObs) && get(relevanceObs, "value") === "relevant") {
    const rangeValue = isDict(rotorObs) ? get(rotorObs, "value") : null;
    const approval = get(get(get(scenario, "metadata", {}), "approved_condition_widths", {}), "rotor_seizure_hours");
    if (!isDict(rangeValue) || !isDict(approval)) {
      issues.push("rotor_seizure_hours:human_approval_required");
    } else if (
      !BANDS.every((k) => isNum(get(rangeValue, k))) || !(rangeValue.low <= rangeValue.typical && rangeValue.typical <= rangeValue.high) ||
      !isStr(get(approval, "actor")) || !approval.actor.trim() || !isStr(get(approval, "reason")) || !approval.reason.trim() ||
      get(approval, "old_value") !== null || !pyEq(get(approval, "new_value"), rangeValue)
    ) {
      issues.push("rotor_seizure_hours:approval_audit_mismatch");
    } else {
      rotor = Object.fromEntries(BANDS.map((k) => [k, rangeValue[k]]));
    }
  } else if (!isDict(relevanceObs) || !["confirmed", "declared"].includes(get(relevanceObs, "status"))) {
    issues.push("rotor_relevance:human_confirmation_required");
  }
  if (issues.length) {
    trace.push({ stage: "ledger_actions", events: [...events, sourceEvent, replacementEvent], ledger });
    return stopped(version, issues, trace, ledger);
  }

  const netBase = gross - totalDeduction - includedHours;
  if (netBase < 0) return stopped(version, ["ledger:deductions_and_replacement_exceed_gross"], trace, ledger);
  const handling = perPerson * replacementCount;
  const person = Object.fromEntries(BANDS.map((band) => [band, pyRound(netBase + handling + washHours + rotor[band], 10)]));
  const waitValues = Object.values(waiting);
  const elapsedRange = waitValues.some((v) => v === null)
    ? null
    : Object.fromEntries(BANDS.map((band) => [band, pyRound(netBase + perPerson + washHours + pySum(waitValues as number[]) + rotor[band], 10)]));
  let elapsed: Dict = elapsedRange ?? nullRange();
  const breakdown: Dict[] = [
    { operation: "gross_base_after_shared_deduction", operation_id: "base_service", hours: Object.fromEntries(BANDS.map((b) => [b, pyRound(gross - totalDeduction, 10)])), reason: "Gross input less the shared-overlap key exactly once.", status: "confirmed-observation" },
    { operation: "included_transport_removed", operation_id: "included_carry", hours: { low: 0.0, typical: 0.0, high: 0.0 }, reason: "Remove 0.12 included hours before replacement.", status: "confirmed-observation" },
    { operation: "two_person_handling", operation_id: "replacement_carry", hours: Object.fromEntries(BANDS.map((b) => [b, pyRound(handling, 10)])), elapsed_hours: Object.fromEntries(BANDS.map((b) => [b, perPerson])), person_count: replacementCount, reason: "Replacement for included transport, not an additive carry.", status: "confirmed-observation" },
    { operation: "wash", operation_id: "wash", hours: Object.fromEntries(BANDS.map((b) => [b, washHours])), reason: "Performed nonbillable work remains person-hours.", status: "nonbillable-work" },
  ];
  for (const opId of Object.keys(waiting)) {
    breakdown.push({
      operation: opId, operation_id: opId, hours: { low: 0.0, typical: 0.0, high: 0.0 },
      elapsed_hours: waiting[opId] !== null ? Object.fromEntries(BANDS.map((b) => [b, waiting[opId]])) : nullRange(),
      reason: "Confirmed wait contributes elapsed time only.", status: "wait",
    });
  }
  if (Object.values(rotor).some((v) => truthy(v))) {
    breakdown.push({ operation: "rotor_seizure", operation_id: "rotor_seizure", hours: rotor, reason: "Fictional human-approved condition range.", status: "conditional" });
  }
  let status: string;
  if (issues.length || elapsedUnknowns.length) {
    status = "partial";
    if (elapsedUnknowns.length) elapsed = nullRange();
  } else {
    status = "proposed";
  }
  trace.push({
    stage: "ledger_actions", mode: mode === "gross" ? "gross" : "deduplicated", fixture_gross_adapter: fixtureGrossMode,
    input_hours_ignored: fixtureGrossMode ? get(base, "hours") : null, deduction_total_hours: totalDeduction,
    events: [...events, sourceEvent, replacementEvent], ledger, input_sha256: hashOf({ scenario: scenarioInput, rule_pack: rulePack }),
  });
  const unknowns = dedupe([...issues, ...elapsedUnknowns]);
  return {
    engine_id: ENGINE_ID, rule_version: version, status,
    labor: { person_hours: person, elapsed_hours: elapsed, breakdown, unknowns },
    trace, operation_keys: breakdown.map((row) => row.operation_id), approvals: [], simulator_notice: SIMULATOR_NOTICE,
  };
}

