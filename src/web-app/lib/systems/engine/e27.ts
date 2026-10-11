/* eslint-disable @typescript-eslint/no-explicit-any */
// E27 のサーバー側（ブラウザの純関数と同じ結果になるか検証する）。 元: e27.py
import { type Dict, deepcopy, get, isDict, pyEq, pyIn, pyJsonDumps, sha256Hex } from "./py";
import * as e07 from "./e07";

export const ENGINE_ID = "e27_browser_pure_function";
export const RULE_VERSION = "e27-browser-pure-v1";
const nullRange = () => ({ low: null, typical: null, high: null });

/** Recompute from the immutable snapshot and reject a mismatched browser proposal. */
export function run(scenarioInput: any, rulePack: any = null): Dict {
  const scenario: Dict = isDict(scenarioInput) ? deepcopy(scenarioInput) : {};
  const result = e07.run(scenario, null);
  result.engine_id = ENGINE_ID;
  result.rule_version = get(scenario, "rule_version", RULE_VERSION);
  if (rulePack !== null && !isDict(rulePack)) {
    result.status = "missing-required";
    result.labor = { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: ["rule_pack:object_required"] };
  }
  let proposal: any = isDict(rulePack) ? get(rulePack, "client_proposal") : null;
  if (isDict(rulePack) && !pyIn(get(rulePack, "rule_version"), [null, result.rule_version])) proposal = { rule_version_mismatch: true };
  const expected = get(result, "labor");
  if (
    proposal !== null &&
    (!isDict(proposal) || !isDict(get(proposal, "labor")) || !pyEq(get(proposal, "rule_version"), result.rule_version) ||
      (get(proposal, "status") !== null && !pyEq(get(proposal, "status"), get(result, "status"))) ||
      !pyEq(get(get(proposal, "labor", {}), "person_hours"), get(expected, "person_hours")) ||
      !pyEq(get(get(proposal, "labor", {}), "elapsed_hours"), get(expected, "elapsed_hours")))
  ) {
    result.status = "missing-required";
    result.labor = { person_hours: nullRange(), elapsed_hours: nullRange(), breakdown: [], unknowns: ["browser_proposal:server_parity_validation_failed"] };
  }
  const payload = pyJsonDumps(scenarioInput, { sortKeys: true, ensureAscii: false, defaultStr: true });
  result.trace.unshift({ stage: "browser_parity", input_sha256: sha256Hex(payload), client_proposal_checked: proposal !== null, server_recomputed: true });
  return result;
}
