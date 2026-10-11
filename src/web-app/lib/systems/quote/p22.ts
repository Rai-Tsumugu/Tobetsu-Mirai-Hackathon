// P22: 計算前に電話で確認する質問の一覧を作る。
import { BANDS } from "./common";
import { validate_inputs } from "./p03";
import { deepcopy, get, has, isDict, isList, PyError, pyFloat, ValueErr, type Obj } from "./pyrt";

function pathValue(value: unknown, path: string): unknown {
  let current = value;
  for (const part of path ? path.split(".") : []) {
    if (isDict(current)) {
      if (!has(current, part)) return null;
      current = current[part];
    } else if (isList(current) && /^\d+$/.test(part)) {
      const index = Number(part);
      if (index >= current.length) return null;
      current = current[index];
    } else {
      return null;
    }
  }
  return current;
}

function approval(inputs: unknown): [Set<string>, Obj | null] {
  const value = isDict(inputs) ? get(inputs, "conditional_approval") : null;
  if (!isDict(value)) return [new Set(), null];
  const approvedBy = get(value, "approved_by");
  const reason = get(value, "reason");
  const fields = get(value, "fields");
  const range = get(value, "range");
  if (
    typeof approvedBy !== "string" || !approvedBy.trim() ||
    typeof reason !== "string" || !reason.trim() ||
    !isList(fields) || !fields.length ||
    fields.some((path) => typeof path !== "string" || !path.trim()) ||
    new Set(fields).size !== fields.length ||
    !isDict(range) ||
    BANDS.some((band) => !has(range, band))
  ) {
    return [new Set(), null];
  }
  const normalized: Record<string, number> = {};
  for (const band of BANDS) {
    const entry = range[band];
    if (typeof entry === "boolean") return [new Set(), null];
    let parsed: number;
    try {
      parsed = pyFloat(entry);
    } catch (error) {
      if (error instanceof PyError) return [new Set(), null];
      throw error;
    }
    if (!Number.isFinite(parsed) || parsed < 0) return [new Set(), null];
    normalized[band] = parsed;
  }
  if (!(normalized.low <= normalized.typical && normalized.typical <= normalized.high)) return [new Set(), null];
  return [
    new Set(fields as string[]),
    { approved_by: approvedBy, reason, range: Object.fromEntries(BANDS.map((band) => [band, range[band]])) },
  ];
}

export function question_guide(inputs: unknown, required_fields: unknown = null): Obj {
  const issues = validate_inputs(inputs);
  const hardErrorPaths = new Set(issues.filter((entry) => entry.code !== "unresolved_unknowns").map((entry) => entry.path));
  const missing = new Map<string, string>();
  for (const entry of issues) {
    const path = entry.path || "inputs";
    if (path && !missing.has(path)) missing.set(path, entry.message);
  }
  const paths = isList(required_fields) ? required_fields : [];
  for (const path of paths) {
    if (typeof path !== "string" || !path.trim()) continue;
    const value = pathValue(inputs, path);
    if ((value === null || value === "") && !missing.has(path)) missing.set(path, "required value is missing");
  }
  const [coveredPaths, approvalRecord] = approval(inputs);
  const questions: Obj[] = [];
  let blocked = false;
  let conditional = false;
  for (const [path, message] of missing) {
    const covered = approvalRecord !== null && coveredPaths.has(path) && !hardErrorPaths.has(path);
    conditional = conditional || covered;
    blocked = blocked || !covered;
    const question: Obj = {
      field: path,
      prompt: `${path}について確認してください。`,
      answer: deepcopy(pathValue(inputs, path)),
      status: covered ? "conditional" : "unanswered",
      source_ref: path,
    };
    if (covered) question.conditional_approval = deepcopy(approvalRecord);
    else question.detail = message;
    questions.push(question);
  }
  const status = blocked ? "blocked" : conditional ? "conditional" : "ready";
  return { questions, status, can_calculate: !blocked };
}

function setPath(target: unknown, path: unknown, value: unknown): void {
  const parts = typeof path === "string" ? path.split(".") : [];
  if (!parts.length || parts.some((part) => !part)) throw new ValueErr("answer field must be a non-empty dotted path");
  let current = target;
  for (const part of parts.slice(0, -1)) {
    if (isDict(current)) {
      if (!has(current, part)) current[part] = {};
      current = current[part];
    } else if (isList(current) && /^\d+$/.test(part)) {
      const index = Number(part);
      if (index >= current.length) throw new ValueErr(`answer path does not exist: ${path}`);
      current = current[index];
    } else {
      throw new ValueErr(`answer path does not exist: ${path}`);
    }
  }
  const leaf = parts[parts.length - 1];
  if (isDict(current)) current[leaf] = deepcopy(value);
  else if (isList(current) && /^\d+$/.test(leaf) && Number(leaf) < current.length) current[Number(leaf)] = deepcopy(value);
  else throw new ValueErr(`answer path does not exist: ${path}`);
}

export function answers_to_inputs(inputs: unknown, answers: unknown): Obj {
  if (!isDict(inputs)) throw new ValueErr("inputs must be an object");
  if (!isDict(answers)) throw new ValueErr("answers must be a mapping of dotted paths to values");
  const result = deepcopy(inputs);
  for (const [path, answer] of Object.entries(answers)) setPath(result, path, answer);
  return result;
}
