/* eslint-disable @typescript-eslint/no-explicit-any */
// 元の Python 実装の出力（golden/generate.py で生成）と TS 版の出力が一致することを確かめる。
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { pyErrorName } from "../../../lib/systems/engine/py";
import { registeredEngineIds, resetEngineState, runEngine } from "../../../lib/systems/engine/runner";
import { normalize } from "./normalize";

const dir = path.join(__dirname, "golden");
const variants = JSON.parse(readFileSync(path.join(dir, "variants.json"), "utf8"));

const files = readdirSync(dir).filter((f) => /^cases-.*\.json$/.test(f)).sort();
const registered = new Set([...registeredEngineIds(), "integrated"]);

describe("golden: engines", () => {
  for (const file of files) {
    const engineId = file.replace(/^cases-|\.json$/g, "");
    if (!registered.has(engineId)) continue;
    const cases: any[] = JSON.parse(readFileSync(path.join(dir, file), "utf8"));
    describe(engineId, () => {
      for (const c of cases) {
        it(c.name, () => {
          const scenario = c.variant ? variants[c.variant] : c.scenario_input;
          resetEngineState();
          let actual: any;
          try {
            actual = runEngine(c.engine_id, structuredClone(scenario), structuredClone(c.rule_pack));
          } catch (e) {
            actual = { error: pyErrorName(e) };
          }
          expect(normalize(actual)).toEqual(normalize(c.expected));
        });
      }
    });
  }
});
