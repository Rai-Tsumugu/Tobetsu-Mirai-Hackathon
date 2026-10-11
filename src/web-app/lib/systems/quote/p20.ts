// P20: 承認済みの作業名・略称を検索する（作業は選ばない）。
import { casefold, get, isDict, isList, pyEq, squash, type Obj } from "./pyrt";

function hasText(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

function normalize(value: string): string {
  return squash(casefold(value.normalize("NFKC")));
}

function approvedAliases(job: Obj): string[] {
  const rawAliases = get(job, "aliases", []);
  if (!isList(rawAliases)) return [];
  const approved: string[] = [];
  for (const raw of rawAliases) {
    if (!isDict(raw)) continue;
    const alias = get(raw, "alias");
    if (!hasText(get(raw, "approved_by"))) continue;
    if (hasText(alias)) approved.push(alias.trim());
  }
  return approved;
}

function isApprovedJob(job: unknown): job is Obj {
  return isDict(job) && hasText(get(job, "approved_by"));
}

function result(job: Obj): Obj {
  return {
    job_id: get(job, "job_id"),
    job_ref: get(job, "job_ref"),
    preset_id: get(job, "preset_id"),
    name: get(job, "name"),
    aliases: approvedAliases(job),
    source: get(job, "source"),
    approved_by: get(job, "approved_by"),
  };
}

export function search_jobs(jobs: unknown, query: unknown = ""): Obj[] {
  if (!isList(jobs) || typeof query !== "string") return [];
  const needle = normalize(query);
  const matches: Obj[] = [];
  for (const job of jobs) {
    if (!isApprovedJob(job)) continue;
    const name = get(job, "name");
    const terms = [...(hasText(name) ? [name] : []), ...approvedAliases(job)];
    if (!needle || terms.some((term) => normalize(term).includes(needle))) matches.push(result(job));
  }
  return matches;
}

export function select_job(jobs: unknown, job_id: unknown): Obj | null {
  if (!isList(jobs) || job_id === null) return null;
  const matches = jobs.filter((job) => isDict(job) && pyEq(get(job, "job_id"), job_id));
  return matches.length === 1 && isApprovedJob(matches[0]) ? result(matches[0]) : null;
}
