// DB を使わない部分のゴールデン照合（golden/pure.json は golden/generate.py が元の Python から作る）。
import { describe, expect, it } from "vitest";
import { PRICES_SCHEMA, extractPrices, generationSchema, publicUrl } from "../../../lib/systems/demo/gemini";
import { HttpError, pyDumps } from "../../../lib/systems/demo/py";
import { JOBS, simulatorSources } from "../../../lib/systems/demo/seed";
import { medianInt, researchCacheKey } from "../../../lib/systems/demo/service";
import type { ResearchTarget } from "../../../lib/systems/demo/types";
import golden from "./golden/pure.json";
import { Normalizer, ordered } from "./normalize";

describe("整備見積デモ: 計算・抽出のゴールデン照合", () => {
  it("作業マスタと Simulator の架空候補（税込の税抜換算を含む）が元と同じ", () => {
    expect(ordered(JOBS)).toBe(ordered(golden.jobs));
    for (const job of JOBS) {
      expect(ordered(simulatorSources(job)), job.id).toBe(ordered(golden.simulator[job.id as keyof typeof golden.simulator]));
    }
  });

  it.each(golden.public_url)("public_url($url) = $result", ({ url, result }) => {
    expect(publicUrl(url)).toBe(result);
  });

  it("extract_prices の採用・除外・税抜換算・警告が元と同じ（全ケースを順に）", () => {
    const normalizer = new Normalizer();
    for (const c of golden.extract) {
      const result = { data: c.data, citations: c.citations, warnings: [] as string[] };
      let output: unknown;
      try {
        output = { groups: normalizer.value(extractPrices(result, c.job_ids)), warnings: result.warnings };
      } catch (error) {
        if (!(error instanceof HttpError)) throw error;
        output = { status: error.status, detail: error.detail, warnings: result.warnings };
      }
      expect(ordered(output), c.name).toBe(ordered(c.output));
    }
  });

  it("Gemini に渡すスキーマ（範囲の制約を外したもの）が元と同じ", () => {
    expect(ordered(PRICES_SCHEMA)).toBe(ordered(golden.schema));
    expect(ordered(generationSchema(PRICES_SCHEMA))).toBe(ordered(golden.generation_schema));
  });

  it("調査キャッシュのキーとプロンプトに入れる JSON が元と同じ", () => {
    const target = golden.cache.target as ResearchTarget;
    expect(pyDumps(target)).toBe(golden.cache.dumps);
    expect(researchCacheKey("prices", target)).toBe(golden.cache.key);
  });

  it.each(golden.median)("中央値 $values → $result", ({ values, result }) => {
    expect(medianInt(values)).toBe(result);
  });
});
