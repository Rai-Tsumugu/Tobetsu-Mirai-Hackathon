// m21.py の移植: 承認済み配合版（M05 と同じ形）と確認済み価格から必要量を比例計算し、スナップショット保存する。
import { Decimal } from "./decimal";
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, textValue, type Json, type Store } from "./core";
import { get, isDict, isInt, pyEqual, pyStr, truthy, uuidHex } from "./py";

export const SPEC = {
  idea_id: "M21",
  title: "配合量の比例計算",
  description: "M05の承認済み配合版と確認済み価格を使い、必要量を計算してスナップショット保存します。",
  defaults: {
    action: "register_formula",
    formula_id: "demo-m21-blue",
    code: "SIM-M21-BLUE",
    version: 1,
    status: "approved",
    confirmed_by: "架空デモ担当",
    formula_lines: [{ item_id: "demo-paint", ratio: "1", unit: "ml" }],
  } as Json,
};

export const FORMULA_NAMESPACE = "formula";
export const SNAPSHOT_NAMESPACE = "formula_quantity_snapshot";
export const APPROVAL_NAMESPACE = "formula_quantity_approval";

const ONE = Decimal.parse("1");

/** M05 互換の配合登録、計算、スナップショットの承認・取得。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "calculate");
  if (action === "register_formula") return registerFormula(payload, store);
  if (action === "calculate") return calculate(payload, store);
  if (action === "approve_snapshot") return approveSnapshot(payload, store);
  if (action === "get_snapshot") {
    const snapshotId = textValue(get(payload, "snapshot_id"), "snapshot_id");
    return { snapshot: await store.latest(SNAPSHOT_NAMESPACE, snapshotId), simulator: true };
  }
  throw new ValidationError("action: register_formula / calculate / approve_snapshot / get_snapshot を選択してください");
}

function validVersion(version: unknown): boolean {
  return isInt(version) && Number(version) >= 1;
}

async function registerFormula(payload: Json, store: Store): Promise<Json> {
  const formulaId = textValue(get(payload, "formula_id"), "formula_id");
  const code = textValue(get(payload, "code"), "code");
  const version = get(payload, "version");
  if (!validVersion(version)) {
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
  for (const [index, line] of rawLines.entries()) {
    if (!isDict(line)) {
      throw new ValidationError(`formula_lines[${index}]: 構成を確認してください`);
    }
    const itemId = textValue(get(line, "item_id"), `formula_lines[${index}].item_id`);
    if (seenItems.has(itemId)) {
      throw new ValidationError("formula_lines: 同じ品目は1行にまとめてください");
    }
    seenItems.add(itemId);
    const ratio = decimalValue(get(line, "ratio"), `formula_lines[${index}].ratio`, { positive: true });
    if (ratio.gt(1)) {
      throw new ValidationError(`formula_lines[${index}].ratio: 1以下で入力してください`);
    }
    const unit = textValue(get(line, "unit"), `formula_lines[${index}].unit`);
    lines.push({ item_id: itemId, ratio: ratio.toString(), unit });
    ratioTotal = ratioTotal.add(ratio, { prec: 80 });
  }
  if (!ratioTotal.eq(ONE)) {
    throw new ValidationError("配合比率不整合: 比率の合計を1にしてください");
  }

  const formula = {
    formula_id: formulaId,
    code,
    version,
    status,
    confirmed_by: confirmer,
    formula_lines: lines,
    source: "simulator:架空レシピ",
  };
  await store.transaction(() => store.put(FORMULA_NAMESPACE, formula, formulaId));
  return { formula, simulator: true };
}

async function getFormula(payload: Json, store: Store): Promise<Json> {
  const formulaId = textValue(get(payload, "formula_id"), "formula_id");
  const version = get(payload, "version");
  let rows: Json[] = await store.records(FORMULA_NAMESPACE, formulaId);
  if (version !== null) {
    if (!validVersion(version)) {
      throw new ValidationError("version: 1以上の整数が必要です");
    }
    rows = rows.filter((row) => pyEqual(get(row, "version"), version));
  }
  if (rows.length === 0) {
    throw new ValidationError("formula: 指定した配合版がありません");
  }
  const formula = rows[rows.length - 1];
  if (get(formula, "status") !== "approved" || !truthy(get(formula, "confirmed_by"))) {
    throw new ValidationError("未承認配合: 担当者の承認が必要です");
  }
  const lines = get(formula, "formula_lines");
  if (!Array.isArray(lines) || lines.length === 0) {
    throw new ValidationError("配合構成不整合: 構成を確認してください");
  }
  let ratioTotal = Decimal.parse("0");
  for (const [index, line] of lines.entries()) {
    if (!isDict(line)) {
      throw new ValidationError("配合構成不整合: 構成を確認してください");
    }
    textValue(get(line, "item_id"), `formula_lines[${index}].item_id`);
    textValue(get(line, "unit"), `formula_lines[${index}].unit`);
    ratioTotal = ratioTotal.add(decimalValue(get(line, "ratio"), `formula_lines[${index}].ratio`, { positive: true }));
  }
  if (!ratioTotal.eq(ONE)) {
    throw new ValidationError("配合比率不整合: 比率の合計を1にしてください");
  }
  return formula;
}

async function calculate(payload: Json, store: Store): Promise<Json> {
  const formula = await getFormula(payload, store);
  const totalQty = decimalValue(get(payload, "total_qty"), "total_qty", { positive: true });
  const unit = textValue(get(payload, "unit"), "unit");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const calculatedLines: Json[] = [];
  let totalCost = Decimal.parse("0");
  let simulator = pyStr(get(formula, "source", "")).startsWith("simulator:");
  const ctx = { prec: 80 };
  for (const line of formula.formula_lines as Json[]) {
    if (get(line, "unit") !== unit) {
      throw new ValidationError("単位不一致: 配合構成と必要総量の単位が一致しません");
    }
    const ratio = decimalValue(get(line, "ratio"), "ratio", { positive: true });
    const quantity = totalQty.mul(ratio, ctx);
    const price = await store.getPrice(line.item_id as string, "仕入", { as_of: asOf, unit });
    const item = price.item;
    simulator = simulator || item.source.startsWith("simulator:");
    if (item.category !== "塗料" && item.category !== "溶剤") {
      throw new ValidationError("配合構成品は塗料または溶剤を指定してください");
    }
    const unitPrice = decimalValue(item.unit_price, "unit_price");
    if (unitPrice.isZero()) {
      throw new ValidationError("価格未確認: 0円の価格では計算できません");
    }
    const lineCost = quantity.mul(unitPrice, ctx);
    totalCost = totalCost.add(lineCost, ctx);
    calculatedLines.push({
      item_id: item.item_id,
      name: item.name,
      ratio: ratio.toString(),
      quantity: quantity.toString(),
      unit,
      unit_price: unitPrice.toString(),
      price_type: item.price_type,
      price_version_id: price.price_version_id,
      line_cost: lineCost.toString(),
    });
  }

  const snapshotId = uuidHex();
  const snapshot = {
    snapshot_id: snapshotId,
    formula_id: formula.formula_id,
    formula_code: formula.code,
    formula_version: formula.version,
    formula_confirmed_by: formula.confirmed_by,
    formula_source: formula.source,
    total_qty: totalQty.toString(),
    unit,
    as_of: asOf,
    lines: calculatedLines,
    total_cost: totalCost.toString(),
    currency: "JPY",
    status: "needs_human_confirmation",
    confirmed_by: null,
    simulator,
  };
  await store.put(SNAPSHOT_NAMESPACE, snapshot, snapshotId);
  return {
    snapshot,
    simulator: snapshot.simulator,
    notice: "数量・価格の計算候補です。承認されるまで見積確定には使用できません。",
  };
}

async function approveSnapshot(payload: Json, store: Store): Promise<Json> {
  const snapshotId = textValue(get(payload, "snapshot_id"), "snapshot_id");
  const confirmer = approvedBy(payload);
  const snapshot = await store.latest(SNAPSHOT_NAMESPACE, snapshotId);
  if (get(snapshot, "status") !== "needs_human_confirmation") {
    throw new ValidationError("snapshot: 承認待ちの計算結果ではありません");
  }
  const approval = {
    snapshot_id: snapshotId,
    confirmed_by: confirmer,
    status: "approved",
    formula_id: snapshot.formula_id,
    formula_version: snapshot.formula_version,
  };
  const approvedSnapshot = { ...snapshot, status: "approved", confirmed_by: confirmer };
  await store.transaction(async () => {
    await store.put(APPROVAL_NAMESPACE, approval, snapshotId);
    await store.put(SNAPSHOT_NAMESPACE, approvedSnapshot, snapshotId);
  });
  return { snapshot: approvedSnapshot, approval, simulator: snapshot.simulator };
}
