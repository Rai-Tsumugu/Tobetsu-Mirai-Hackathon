/* eslint-disable @typescript-eslint/no-explicit-any */
// E09: precedence- and worker-constrained labor scheduling. 元: e09.py
import {
  type Dict, PyTypeError, deepcopy, get, isDict, isInt, isList, isNumber, isStr, keysAre, pyEq, pyIn, pyJsonDumps, pyRound, pySum, sha256Hex,
} from "./py";
import { BANDS } from "./contract";
import { run as runPipeline } from "./e07";

export const ENGINE_ID = "e09_process_dag";
export const RULE_VERSION = "e09-process-dag-v1";
const SIMULATOR_NOTICE = "すべて架空のSimulator値です。実測工数・実価格・実車検証ではありません。";
const nullRange = () => ({ low: null, typical: null, high: null });

const validNumber = (v: any) => isNumber(v) && Number.isFinite(v) && v >= 0;

function stop(version: any, issues: string[], trace: Dict[]): Dict {
  return {
    engine_id: ENGINE_ID, rule_version: version, status: "missing-required",
    labor: { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: issues },
    trace, operation_keys: [], approvals: [], simulator_notice: SIMULATOR_NOTICE,
  };
}

function rangeOf(raw: any): Dict | null {
  if (validNumber(raw)) return { low: raw, typical: raw, high: raw };
  if (isDict(raw) && keysAre(raw, [...BANDS])) {
    const values = BANDS.map((k) => raw[k]);
    if (values.every(validNumber) && values[0] <= values[1] && values[1] <= values[2]) return { low: raw.low, typical: raw.typical, high: raw.high };
  }
  return null;
}

/** Stable list scheduler; makespan is feasible, not guaranteed optimal. */
export function schedule(nodes: Dict[], edges: [string, string][], limit: number, durations: Record<string, number>): [Record<string, [number, number]>, number] {
  const byId = new Map<string, Dict>(nodes.map((n) => [n.operation_id, n]));
  const deps = new Map<string, Set<string>>();
  const children = new Map<string, Set<string>>();
  for (const key of byId.keys()) {
    deps.set(key, new Set());
    children.set(key, new Set());
  }
  for (const [before, after] of edges) {
    deps.get(after)!.add(before);
    children.get(before)!.add(after);
  }
  const order = new Map<string, number>(nodes.map((n, i) => [n.operation_id, i]));
  const byOrder = (a: string, b: string) => order.get(a)! - order.get(b)!;
  const ready: string[] = [...deps.entries()].filter(([, required]) => required.size === 0).map(([key]) => key).sort(byOrder);
  const scheduled = new Map<string, [number, number]>();
  const workerIntervals: [number, number, number][] = [];
  while (ready.length) {
    const key = ready.shift()!;
    const node = byId.get(key)!;
    let start = Math.max(0.0, ...[...deps.get(key)!].map((dep) => scheduled.get(dep)![1]));
    if (deps.get(key)!.size === 0) start = 0.0;
    const count = node.kind === "work" ? node.person_count : 0;
    const duration = durations[key];
    if (count) {
      for (;;) {
        const overlapping = workerIntervals.filter(([a, b]) => a < start + duration && start < b);
        const conflictTimes = [...new Set([start, ...overlapping.filter(([a]) => start <= a && a < start + duration).map(([a]) => a)])].sort((x, y) => x - y);
        const conflict = conflictTimes.find((point) => overlapping.filter(([a, b]) => a <= point && point < b).reduce((s, [, , c]) => s + c, 0) + count > limit);
        if (conflict === undefined) break;
        start = Math.min(...overlapping.filter(([a, b]) => a <= conflict && conflict < b).map(([, b]) => b));
      }
    }
    const finish = start + duration;
    scheduled.set(key, [start, finish]);
    if (count && duration) workerIntervals.push([start, finish, count]);
    const newlyReady = [...children.get(key)!].filter((child) => !scheduled.has(child) && !ready.includes(child) && [...deps.get(child)!].every((d) => scheduled.has(d)));
    ready.push(...newlyReady);
    ready.sort(byOrder);
  }
  let makespan = 0.0;
  for (const [, finish] of scheduled.values()) makespan = Math.max(makespan, finish);
  return [Object.fromEntries(scheduled), makespan];
}

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const version = get(scenario, "rule_version", RULE_VERSION);
  if (rulePack === null) {
    const result = runPipeline(scenarioInput);
    result.engine_id = ENGINE_ID;
    result.trace.push({ stage: "e09_schedule", mode: "shared_fixture_adapter", rule_version: version, note: "No explicit DAG supplied; common fixture calculation retained." });
    return result;
  }

  const trace: Dict[] = [{ stage: "input_snapshot", rule_version: version }];
  let issues: string[] = [];
  if (!isDict(rulePack)) return stop(version, ["rule_pack:object_required"], trace);
  let nodes = get(rulePack, "nodes");
  let rawEdges = get(rulePack, "edges");
  const limit = get(rulePack, "resource_limit");
  if (!pyIn(get(rulePack, "engine_id"), [null, ENGINE_ID])) issues.push("rule_pack:engine_id_mismatch");
  if (!pyEq(get(rulePack, "rule_version"), version)) issues.push("rule_pack:rule_version_mismatch");
  if (get(rulePack, "status", "approved") !== "approved") issues.push("rule_pack:approved_version_required");
  if (!isList(nodes) || !nodes.length) {
    issues.push("nodes:nonempty_list_required");
    nodes = [];
  }
  if (!isList(rawEdges)) {
    issues.push("edges:list_required");
    rawEdges = [];
  }
  if (typeof limit === "boolean" || !isInt(limit) || limit <= 0) issues.push("resource_limit:positive_integer_required");
  const seen = new Set<string>();
  const normalized: Dict[] = [];
  const durations = new Map<string, Dict | null>();
  nodes.forEach((raw: any, index: number) => {
    if (!isDict(raw)) {
      issues.push(`nodes[${index}]:object_required`);
      return;
    }
    const opId = get(raw, "operation_id");
    if (!isStr(opId) || !opId.trim()) {
      issues.push(`nodes[${index}]:operation_id_required`);
      return;
    }
    if (seen.has(opId)) {
      issues.push(`${opId}:duplicate_operation_id`);
      return;
    }
    seen.add(opId);
    const kind = get(raw, "kind", "work");
    if (!pyIn(kind, ["work", "wait"])) {
      issues.push(`${opId}:kind_must_be_work_or_wait`);
      return;
    }
    const count = get(raw, "person_count", kind === "work" ? 1 : 0);
    if (typeof count === "boolean" || !isInt(count) || count < 0 || (kind === "work" && count === 0)) issues.push(`${opId}:person_count_invalid`);
    else if (kind === "wait" && count !== 0) issues.push(`${opId}:wait_person_count_must_be_zero`);
    if (kind === "work" && (typeof limit === "boolean" || isInt(limit)) && count > Number(limit)) issues.push(`${opId}:worker_capacity_exceeded`);
    const rawDuration = get(raw, "duration_hours");
    const duration = rawDuration !== null ? rangeOf(rawDuration) : null;
    if (rawDuration !== null && duration === null) issues.push(`${opId}:duration_range_invalid`);
    else if (rawDuration === null && kind === "work") issues.push(`${opId}:required_person_hour_duration_unknown`);
    normalized.push({
      operation_id: opId, operation: get(raw, "operation", opId), kind, person_count: count, source: get(raw, "source"),
      reason: get(raw, "reason", "Explicit E09 process DAG."), status: get(raw, "status", "proposed"),
    });
    durations.set(opId, duration);
  });
  const edges: [string, string][] = [];
  rawEdges.forEach((edge: any, index: number) => {
    let before: any;
    let after: any;
    if (isDict(edge)) {
      before = get(edge, "before");
      after = get(edge, "after");
    } else if (isList(edge) && edge.length === 2) {
      [before, after] = edge;
    } else {
      issues.push(`edges[${index}]:before_after_required`);
      return;
    }
    for (const v of [before, after]) if (isList(v) || isDict(v)) throw new PyTypeError("unhashable type");
    if (!seen.has(before) || !seen.has(after)) issues.push(`edges[${index}]:missing_node_reference`);
    else if (before === after) issues.push(`edges[${index}]:self_cycle`);
    else edges.push([before, after]);
  });
  if (!issues.length) {
    const indegree = new Map<string, number>([...seen].map((k) => [k, 0]));
    for (const [, after] of edges) indegree.set(after, indegree.get(after)! + 1);
    const queue = normalized.filter((n) => indegree.get(n.operation_id) === 0).map((n) => n.operation_id);
    let visited = 0;
    const kids = new Map<string, string[]>([...seen].map((k) => [k, []]));
    for (const [before, after] of edges) kids.get(before)!.push(after);
    while (queue.length) {
      const current = queue.shift()!;
      visited += 1;
      for (const child of kids.get(current)!) {
        indegree.set(child, indegree.get(child)! - 1);
        if (indegree.get(child) === 0) queue.push(child);
      }
    }
    if (visited !== seen.size) issues.push("dag:cycle_detected");
  }
  if (issues.length) {
    trace.push({ stage: "validate", issues, input_sha256: sha256Hex(pyJsonDumps(rulePack, { sortKeys: true, defaultStr: true })) });
    return stop(version, issues, trace);
  }

  const missingWaits = normalized.filter((n) => n.kind === "wait" && durations.get(n.operation_id) === null).map((n) => n.operation_id);
  const personTotals: Dict = {};
  const elapsedTotals: Dict = {};
  const schedules: Dict = {};
  for (const band of BANDS) {
    const known: Record<string, number> = {};
    for (const [key, value] of durations) if (value !== null) known[key] = value![band];
    const personTotal = () => pySum(normalized.filter((n) => n.kind === "work").map((n) => known[n.operation_id] * n.person_count));
    if (missingWaits.length) {
      personTotals[band] = personTotal();
      elapsedTotals[band] = null;
      schedules[band] = null;
    } else {
      const [scheduled, makespan] = schedule(normalized, edges, limit, known);
      personTotals[band] = personTotal();
      elapsedTotals[band] = pyRound(makespan, 10);
      schedules[band] = Object.fromEntries(Object.entries(scheduled).map(([key, v]) => [key, { start: pyRound(v[0], 10), finish: pyRound(v[1], 10) }]));
    }
  }
  const rows = normalized.map((node) => {
    const duration = durations.get(node.operation_id)!;
    const work = node.kind === "work";
    return {
      operation_id: node.operation_id, operation: node.operation,
      hours: duration !== null && work ? Object.fromEntries(BANDS.map((k) => [k, pyRound(duration[k] * node.person_count, 10)])) : { low: 0.0, typical: 0.0, high: 0.0 },
      elapsed_hours: duration ? Object.fromEntries(BANDS.map((k) => [k, duration[k]])) : nullRange(),
      person_count: node.person_count, kind: node.kind, reason: node.reason,
      status: work && get(node, "billable") === false ? "nonbillable-work" : node.status, source: node.source,
    };
  });
  issues = missingWaits.map((key) => `${key}:elapsed_duration_unknown`);
  const labor = {
    person_hours: Object.fromEntries(Object.keys(personTotals).map((k) => [k, pyRound(personTotals[k], 10)])),
    elapsed_hours: { ...elapsedTotals },
    breakdown: rows, unknowns: issues,
  };
  const payloadHash = sha256Hex(pyJsonDumps({ scenario, rule_pack: rulePack }, { sortKeys: true, defaultStr: true }));
  trace.push({
    stage: "schedule", algorithm: "stable_list_scheduler", optimality: "not_guaranteed", resource_limit: limit,
    precedence: edges.map((e) => [...e]), schedules, input_sha256: payloadHash, rule_version: version,
  });
  return {
    engine_id: ENGINE_ID, rule_version: version, status: issues.length ? "partial" : "proposed", labor, trace,
    operation_keys: normalized.map((n) => n.operation_id), approvals: [], simulator_notice: SIMULATOR_NOTICE,
  };
}
