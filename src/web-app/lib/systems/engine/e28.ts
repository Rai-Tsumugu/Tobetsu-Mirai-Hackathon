/* eslint-disable @typescript-eslint/no-explicit-any */
// E28: server-side recomputation and idempotent save policy. 元: e28.py
import { type Dict, deepcopy, get, isDict, pyEq, truthy } from "./py";
import * as e07 from "./e07";

export const ENGINE_ID = "e28_server_recompute";
export const RULE_VERSION = "e28-server-recompute-v1";
const nullRange = () => ({ low: null, typical: null, high: null });

export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const version = get(scenario, "rule_version", RULE_VERSION);
  const pack: Dict = isDict(rulePack) ? deepcopy(rulePack) : {};
  const result = e07.run(scenario);
  result.engine_id = ENGINE_ID;
  result.rule_version = version;
  const proposal = get(pack, "client_proposal");
  const issues: string[] = [];
  if (rulePack !== null && !isDict(rulePack)) issues.push("rule_pack:object_required");
  if (truthy(pack) && !pyEq(get(pack, "rule_version"), version)) issues.push("rule_pack:version_mismatch");
  if (proposal !== null) {
    if (!isDict(proposal) || !pyEq(get(proposal, "rule_version"), version) || (get(proposal, "status") !== null && !pyEq(get(proposal, "status"), get(result, "status")))) {
      issues.push("client_proposal:version_mismatch");
    } else if (
      !isDict(get(proposal, "labor")) || !pyEq(get(proposal.labor, "person_hours"), get(result.labor, "person_hours")) ||
      !pyEq(get(proposal.labor, "elapsed_hours"), get(result.labor, "elapsed_hours"))
    ) {
      issues.push("client_proposal:server_recomputation_mismatch");
    }
  }
  if (issues.length) {
    result.status = "missing-required";
    result.labor = { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: issues };
  }
  result.trace.unshift({ stage: "server_recompute", client_proposal_checked: proposal !== null, mismatch_rejected: issues.length > 0, rule_version: version });
  return result;
}
