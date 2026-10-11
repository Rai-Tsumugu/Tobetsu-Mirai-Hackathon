// Python 版エンジンの出力（result_example.json / .md）と、TypeScript 版の出力が一致することを確かめる。
// 期待値は src/30-algorithm/integrated/estimator.py が出したファイルで、ここでは再計算していない。
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { estimate, toMarkdown } from "../../../lib/systems/man-hours/estimator";
import { loadJsonData } from "../../../lib/systems/man-hours/json-data";

const GOLDEN = join(__dirname, "../../../../30-algorithm/integrated");

describe("Python 版との一致", () => {
  const data = loadJsonData();
  const result = estimate(data.case, data.params, data.catalog, data.records);

  it("計算結果が一致する（-0.0 と 0.0 の違いも含む）", () => {
    const expected = JSON.parse(readFileSync(join(GOLDEN, "result_example.json"), "utf-8"));
    expect(result).toEqual(expected);
  });

  it("Markdown が一致する", () => {
    expect(toMarkdown(result)).toBe(readFileSync(join(GOLDEN, "result_example.md"), "utf-8"));
  });
});
