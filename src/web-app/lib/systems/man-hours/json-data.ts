// 同梱データ（元の Python 版の data/ をそのまま読む。コピーは持たない）。
// 工場パラメータ・実績・基準工数・例の入力。DB が使えないときの入力と、テストの入力に使う。
import caseJson from "../../../../30-algorithm/integrated/data/case_example.json";
import catalogJson from "../../../../30-algorithm/integrated/data/job_catalog.json";
import recordsJson from "../../../../30-algorithm/integrated/data/records.json";
import paramsJson from "../../../../30-algorithm/integrated/data/shop_params.json";
import type { Obj } from "./python-compat";

export type EngineData = { case: Obj; params: Obj; catalog: Obj; records: Obj };

/** 呼び出し側が書き換えても同梱の JSON に影響しないよう、複製して返す。 */
function copy<T>(value: T): T {
  return structuredClone(value);
}

export function loadJsonData(): EngineData {
  return { case: copy(caseJson), params: copy(paramsJson), catalog: copy(catalogJson), records: copy(recordsJson) };
}

/** 基準工数。DB の jobs には工程名などの全項目がないので、同梱の JSON を使う。 */
export function loadCatalog(): Obj {
  return copy(catalogJson);
}

/** 辞書のキー順の基準にする同梱データ（key-order.ts）。 */
export const REFERENCE_PARAMS: Obj = paramsJson;
export const REFERENCE_RECORDS: Obj = recordsJson;
export const REFERENCE_CASE: Obj = caseJson;
