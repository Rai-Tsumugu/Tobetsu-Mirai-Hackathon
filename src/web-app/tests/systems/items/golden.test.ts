// 元の Python（src/auto_repair_items）の出力と TS 版の出力のゴールデン照合。
// 入力: golden/scenarios/<name>.json、期待値: golden/<name>.json（generate.py で作る）。
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { comparable, GOLDEN_DIR, loadGolden, runScenario } from "./harness";

const names = readdirSync(path.join(GOLDEN_DIR, "scenarios"))
  .filter((file) => file.endsWith(".json"))
  .map((file) => file.replace(/\.json$/, ""))
  .filter((name) => existsSync(path.join(GOLDEN_DIR, `${name}.json`)))
  .sort();

describe("auto_repair_items ゴールデン照合", () => {
  for (const name of names) {
    describe(name, () => {
      const golden = loadGolden(name);
      for (const scenario of golden.scenarios) {
        it(scenario.name, async () => {
          const outcomes = await runScenario(scenario.steps, scenario.expected);
          const { expected, actual } = comparable(outcomes);
          for (let i = 0; i < expected.length; i += 1) {
            expect(actual[i], `${name} / ${scenario.name} / step ${i} (${scenario.steps[i].op})`).toEqual(expected[i]);
          }
        });
      }
    });
  }
});
