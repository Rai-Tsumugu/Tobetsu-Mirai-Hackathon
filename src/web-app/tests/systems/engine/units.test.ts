/* eslint-disable @typescript-eslint/no-explicit-any */
// 各案の公開関数（パーサ・検証など）を、元の Python 関数の出力（golden/units.json）と照合する。
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { pyErrorName } from "../../../lib/systems/engine/py";
import { parseToAst } from "../../../lib/systems/engine/e03";
import { normalize } from "./normalize";

const FUNCS: Record<string, (...args: any[]) => any> = {
  "e03.parse_to_ast": parseToAst,
};

const units: { fn: string; args: any[]; expected: any }[] = JSON.parse(readFileSync(path.join(__dirname, "golden", "units.json"), "utf8"));

describe("golden: functions", () => {
  units.forEach((u, i) => {
    const fn = FUNCS[u.fn];
    if (!fn) return;
    it(`${u.fn} #${i}`, () => {
      let actual: any;
      try {
        actual = fn(...structuredClone(u.args));
      } catch (e) {
        actual = { error: pyErrorName(e) };
      }
      expect(normalize(actual)).toEqual(normalize(u.expected));
    });
  });
});
