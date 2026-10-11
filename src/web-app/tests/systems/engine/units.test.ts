/* eslint-disable @typescript-eslint/no-explicit-any */
// 各案の公開関数（パーサ・検証など）を、元の Python 関数の出力（golden/units.json）と照合する。
import { describe, expect, it } from "vitest";
import { pyErrorName } from "../../../lib/systems/engine/py";
import { parseToAst } from "../../../lib/systems/engine/e03";
import { deductOnce, replaceOnce } from "../../../lib/systems/engine/e10";
import { resetEngineState } from "../../../lib/systems/engine/runner";
import { golden } from "./fixtures";
import { normalize } from "./normalize";

const FUNCS: Record<string, (...args: any[]) => any> = {
  "e03.parse_to_ast": parseToAst,
  "e10.deduct_once": (ledger, key, amount, owners, reason) => deductOnce(ledger, key, amount, { owners, reason }),
  "e10.replace_once": (ledger, key, rkey, owners, oldHours, replacementHours, reason) =>
    replaceOnce(ledger, key, rkey, { owners, old_hours: oldHours, replacement_hours: replacementHours, reason }),
};

const units: { fn: string; args: any[]; expected: any }[] = golden("units.json");

describe("golden: functions", () => {
  units.forEach((u, i) => {
    const fn = FUNCS[u.fn];
    if (!fn) return;
    it(`${u.fn} #${i}`, () => {
      resetEngineState();
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
