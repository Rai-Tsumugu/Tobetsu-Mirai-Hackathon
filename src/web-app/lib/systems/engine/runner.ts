/* eslint-disable @typescript-eslint/no-explicit-any */
// 30 案の共通アダプタ。元: runner.py
import { type Dict, PyTypeError, PyValueError, deepcopy, get, isDict } from "./py";
import * as e01 from "./e01";
import * as e02 from "./e02";
import * as e03 from "./e03";
import * as e04 from "./e04";
import * as e05 from "./e05";
import * as e06 from "./e06";
import * as e07 from "./e07";
import * as e08 from "./e08";
import * as e09 from "./e09";
import * as e10 from "./e10";
import * as e11 from "./e11";
import * as e12 from "./e12";
import * as e13 from "./e13";
import * as e14 from "./e14";
import * as e15 from "./e15";
import * as e16 from "./e16";
import * as e17 from "./e17";
import * as e18 from "./e18";
import * as e19 from "./e19";
import * as e20 from "./e20";
import * as e21 from "./e21";
import * as e22 from "./e22";
import * as e23 from "./e23";
import * as e24 from "./e24";
import * as e25 from "./e25";
import * as e26 from "./e26";
import * as e27 from "./e27";
import * as e28 from "./e28";
import * as e29 from "./e29";
import * as e30 from "./e30";
import * as integrated from "./integrated";

export const ENGINE_IDS: string[] = Array.from({ length: 30 }, (_, i) => `e${String(i + 1).padStart(2, "0")}`);

type EngineModule = { run: (scenario: Dict, rulePack: Dict | null) => Dict };
const MODULES: Record<string, EngineModule> = {
  e01, e02, e03, e04, e05, e06, e07, e08, e09, e10, e11, e12, e13, e14, e15, e16, e17, e18, e19, e20, e21, e22, e23, e24, e25, e26, e27, e28, e29, e30, integrated,
};

/** Python の ModuleNotFoundError（API では 503）。 */
export class EngineNotInstalled extends Error {}

export function runEngine(engineId: string, scenarioInput: any, rulePack: Dict | null = null): Dict {
  if (!ENGINE_IDS.includes(engineId) && engineId !== "integrated") throw new PyValueError(`unknown engine_id: ${engineId}`);
  if (!isDict(scenarioInput)) throw new PyTypeError("scenario_input must be an object");
  const mod = MODULES[engineId];
  if (!mod) throw new EngineNotInstalled(engineId);
  const result = mod.run(deepcopy(scenarioInput), deepcopy(rulePack));
  if (!isDict(result)) throw new PyTypeError(`${engineId} must return an engine_result object`);
  if (!("scenario_id" in result)) result.scenario_id = get(scenarioInput, "scenario_id");
  for (const key of ["engine_id", "rule_version", "status", "labor", "trace", "operation_keys", "approvals"]) {
    if (!(key in result)) throw new PyValueError(`${engineId} engine_result is missing ${key}`);
  }
  return result;
}

export function compareEngines(scenarioInput: any, rulePack: Dict | null = null, engineIds: string[] = ENGINE_IDS): Dict[] {
  return engineIds.map((engineId) => {
    const result = runEngine(engineId, deepcopy(scenarioInput), deepcopy(rulePack));
    return { engine_id: engineId, labor: get(result, "labor"), status: get(result, "status"), rule_version: get(result, "rule_version"), trace: get(result, "trace", []) };
  });
}

export const registeredEngineIds = (): string[] => Object.keys(MODULES);

/** プロセス内で保持される公開済みルールの登録（E05/E06）を空にする。テスト用。 */
export function resetEngineState(): void {
  e05.resetPublished();
  e06.resetPublished();
}
