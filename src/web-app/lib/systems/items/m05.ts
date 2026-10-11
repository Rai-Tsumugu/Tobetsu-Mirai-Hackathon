// M05: 塗料配合構成マスタ（m05.py の移植）。架空で人が承認した配合を保存し、金額候補を計算する。
import { Decimal } from "./decimal";
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, textValue, type Json, type Store } from "./core";
import { get, isDict, isInt } from "./py";

export const SPEC = {
  idea_id: "M05",
  title: "塗料配合構成マスタ",
  description: "配合を版管理し、承認済み構成品の単位と仕入単価から基準量の金額候補を計算します。",
  defaults: {
    action: "save_formula",
    formula_id: "demo-metallic-blue",
    code: "SIM-BLUE-01",
    version: 1,
    status: "approved",
    confirmed_by: "架空デモ担当",
    formula_lines: [{ item_id: "demo-paint", ratio: "1", unit: "ml" }],
    base_qty: "100",
    unit: "ml",
    as_of: DEMO_DATE,
  },
};

/**
 * 配合の保存・取得・承認・計算。比率は基準量に対する割合で、合計がちょうど1でなければならない。
 * 金額は承認済み仕入価格による候補で、塗装の指示や実際の見積ではない。
 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "calculate");
  if (action === "save_formula") {
    const formula = buildFormula(payload);
    return store.transaction(async () => {
      await store.put("formula", formula, formula.formula_id);
      if (formula.status !== "approved") {
        return { formula, simulator: true };
      }
      return calculate(formula, payload, store);
    });
  }
  if (action === "get_formula" || action === "calculate") {
    const formula = await getFormula(payload, store);
    if (action === "get_formula") {
      requireApproved(formula);
      return { formula, simulator: true };
    }
    return calculate(formula, payload, store);
  }
  if (action === "approve_formula") {
    const formulaId = textValue(get(payload, "formula_id"), "formula_id");
    const current = await store.latest("formula", formulaId);
    const confirmer = approvedBy(payload);
    if (current.status === "approved") {
      throw new ValidationError("配合はすでに承認済みです");
    }
    const approved = { ...current, status: "approved", confirmed_by: confirmer };
    await store.put("formula", approved, formulaId);
    return { formula: approved, simulator: true };
  }
  throw new ValidationError("action: save_formula / get_formula / calculate / approve_formula を選択してください");
}

function buildFormula(payload: Json): Json & { formula_id: string; status: string } {
  const formulaId = textValue(get(payload, "formula_id"), "formula_id");
  const code = textValue(get(payload, "code"), "code");
  const version = get(payload, "version");
  if (!isInt(version) || Number(version) < 1) {
    throw new ValidationError("version: 1以上の整数が必要です");
  }
  const status = get(payload, "status", "pending");
  if (status !== "approved" && status !== "pending") {
    throw new ValidationError("status: approved または pending を指定してください");
  }
  const confirmer = approvedBy(payload);
  const rawLines = get(payload, "formula_lines");
  if (!Array.isArray(rawLines) || rawLines.length === 0 || rawLines.length > 100) {
    throw new ValidationError("formula_lines: 1〜100件の構成が必要です");
  }

  const lines: Json[] = [];
  const seenItems = new Set<string>();
  let ratioTotal = Decimal.parse("0");
  for (const [index, rawLine] of rawLines.entries()) {
    if (!isDict(rawLine)) {
      throw new ValidationError(`formula_lines[${index}]: 構成を確認してください`);
    }
    const itemId = textValue(get(rawLine, "item_id"), `formula_lines[${index}].item_id`);
    if (seenItems.has(itemId)) {
      throw new ValidationError("formula_lines: 同じ品目は1行にまとめてください");
    }
    seenItems.add(itemId);
    const ratio = decimalValue(get(rawLine, "ratio"), `formula_lines[${index}].ratio`, { positive: true });
    if (ratio.gt(1)) {
      throw new ValidationError(`formula_lines[${index}].ratio: 1以下で入力してください`);
    }
    const unit = textValue(get(rawLine, "unit"), `formula_lines[${index}].unit`);
    lines.push({ item_id: itemId, ratio: ratio.toString(), unit });
    ratioTotal = ratioTotal.add(ratio);
  }
  if (!ratioTotal.eq(Decimal.parse("1"))) {
    throw new ValidationError("配合比率不整合: 比率の合計を1にしてください");
  }

  return {
    formula_id: formulaId,
    code,
    version,
    status,
    confirmed_by: confirmer,
    formula_lines: lines,
    source: "simulator:架空レシピ",
  };
}

async function getFormula(payload: Json, store: Store): Promise<Json> {
  const formulaId = textValue(get(payload, "formula_id"), "formula_id");
  if (get(payload, "version") === null) {
    return store.latest("formula", formulaId);
  }
  const version = payload.version;
  if (!isInt(version) || Number(version) < 1) {
    throw new ValidationError("version: 1以上の整数が必要です");
  }
  const matches = (await store.records("formula", formulaId)).filter((record) => get(record, "version") === Number(version));
  if (matches.length === 0) {
    throw new ValidationError("formula: 指定した版がありません");
  }
  return matches[matches.length - 1];
}

function requireApproved(formula: Json): void {
  if (get(formula, "status") !== "approved") {
    throw new ValidationError("未承認配合: 担当者の承認が必要です");
  }
}

async function calculate(formula: Json, payload: Json, store: Store): Promise<Json> {
  requireApproved(formula);
  const unit = textValue(get(payload, "unit"), "unit");
  const baseQty = decimalValue(get(payload, "base_qty"), "base_qty", { positive: true });
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");

  const calculatedLines: Json[] = [];
  let total = Decimal.parse("0");
  // 比率と数量はそれぞれ28桁まで。積と和を丸めずに保つため精度80で計算する。
  const ctx = { prec: 80 };
  for (const formulaLine of formula.formula_lines as Json[]) {
    if (formulaLine.unit !== unit) {
      throw new ValidationError("単位不一致: 配合構成と基準量の単位が一致しません");
    }
    const ratio = decimalValue(formulaLine.ratio, "ratio", { positive: true });
    const quantity = ratio.mul(baseQty, ctx);
    const priceVersion = await store.getPrice(formulaLine.item_id as string, "仕入", { as_of: asOf, unit: formulaLine.unit as string });
    const item = priceVersion.item;
    if (item.category !== "塗料" && item.category !== "溶剤") {
      throw new ValidationError("配合構成品は塗料または溶剤を指定してください");
    }
    const lineTotal = decimalValue(item.unit_price, "unit_price").mul(quantity, ctx);
    total = total.add(lineTotal, ctx);
    calculatedLines.push({
      item_id: item.item_id,
      name: item.name,
      ratio: ratio.toString(),
      quantity: quantity.toString(),
      unit: item.unit,
      unit_price: decimalValue(item.unit_price, "unit_price").toString(),
      price_version_id: priceVersion.price_version_id,
      line_total: lineTotal.toString(),
    });
  }

  return {
    formula,
    base_qty: baseQty.toString(),
    unit,
    as_of: asOf,
    lines: calculatedLines,
    total_cost: total.toString(),
    currency: "JPY",
    confirmed_by: formula.confirmed_by,
    simulator: true,
    notice: "架空価格による金額候補です。塗着率・廃棄分を含まず、実塗装には使用できません。",
  };
}
