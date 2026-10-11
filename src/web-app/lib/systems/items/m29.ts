// M29: 承認済みの端数処理規約を版で保存し、見積行と税区分ごとの合計に適用する（m29.py の移植）。
import { ValidationError, approvedBy, decimalValue, textValue, type Json, type Store } from "./core";
import { Decimal, InvalidOperation, decimalSum, type Rounding } from "./decimal";
import { compareStrings, get, isDict, isInt, uuidHex } from "./py";

export const SPEC = {
  idea_id: "M29",
  title: "端数処理規約",
  description: "承認済みの丸め規則を版保存し、見積行と税区分ごとの合計に適用します。",
  defaults: {
    action: "quote_demo",
    quote_id: "demo-m29-quote",
    line_rule_id: "demo-m29-line-rule",
    tax_rule_id: "demo-m29-tax-rule",
    confirmed_by: "架空デモ担当",
    tax_rates: { "demo-tax": "0.1" },
    lines: [
      { quote_line_id: "demo-m29-line-1", name: "架空デモ材料A", quantity: "1", unit_price: "1.005", tax_category: "demo-tax" },
      { quote_line_id: "demo-m29-line-2", name: "架空デモ材料B", quantity: "1", unit_price: "1.005", tax_category: "demo-tax" },
    ],
  },
};

export const RULE_NAMESPACE = "rounding_rule";
export const QUOTE_NAMESPACE = "quote_snapshot";
const ROUNDING_MODES: Record<string, Rounding> = {
  half_up: "ROUND_HALF_UP",
  down: "ROUND_DOWN",
  up: "ROUND_CEILING",
  floor: "ROUND_FLOOR",
};
const STAGES = ["line", "tax_category_total"];

type Rule = { id: string; rounding_rule_version_id: string; stage: string; mode: string; decimal_places: number; confirmed_by: string };

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "quote");
  if (action === "save_rule") {
    return saveRule(payload, store);
  }
  if (action === "quote_demo") {
    await seedDemoRules(store);
    return quote(payload, store, true);
  }
  if (action === "quote") {
    return quote(payload, store, false);
  }
  throw new ValidationError("action: save_rule / quote / quote_demo を選択してください");
}

function ruleFields(payload: Json): [string, string, string, number] {
  const ruleId = textValue(get(payload, "id"), "id");
  const stage = textValue(get(payload, "stage"), "stage");
  const mode = textValue(get(payload, "mode"), "mode");
  if (!STAGES.includes(stage)) {
    throw new ValidationError("stage: line / tax_category_total を選択してください");
  }
  if (!Object.prototype.hasOwnProperty.call(ROUNDING_MODES, mode)) {
    throw new ValidationError("mode: half_up / down / up / floor を選択してください");
  }
  const places = get(payload, "decimal_places");
  if (!isInt(places) || !(Number(places) >= 0 && Number(places) <= 6)) {
    throw new ValidationError("decimal_places: 0〜6の整数を指定してください");
  }
  return [ruleId, stage, mode, Number(places)];
}

async function saveRule(payload: Json, store: Store): Promise<Json> {
  const [ruleId, stage, mode, decimalPlaces] = ruleFields(payload);
  const confirmer = approvedBy(payload);
  const version = {
    id: ruleId,
    stage,
    mode,
    decimal_places: decimalPlaces,
    confirmed_by: confirmer,
    rounding_rule_version_id: uuidHex(),
  };
  const saved = await store.put(RULE_NAMESPACE, version, ruleId);
  return { status: "saved", rounding_rule: saved, simulator: false };
}

/** 架空の規約は quote_demo を選んだときだけ作る。 */
async function seedDemoRules(store: Store): Promise<void> {
  for (const [ruleId, stage] of [
    ["demo-m29-line-rule", "line"],
    ["demo-m29-tax-rule", "tax_category_total"],
  ]) {
    if ((await store.records(RULE_NAMESPACE, ruleId)).length === 0) {
      await saveRule({ id: ruleId, stage, mode: "half_up", decimal_places: 2, confirmed_by: "架空デモ担当" }, store);
    }
  }
}

async function loadRule(store: Store, ruleIdInput: unknown, expectedStage: string): Promise<Rule> {
  const ruleId = textValue(ruleIdInput, `${expectedStage}_rule_id`);
  const rule = await store.latest(RULE_NAMESPACE, ruleId);
  // 保存済みの値も検査し直し、不正な記録を見積に使わない。
  const [, stage, mode, decimalPlaces] = ruleFields({ ...rule, id: ruleId });
  if (stage !== expectedStage) {
    throw new ValidationError(`${ruleId}: 対象stageが一致しません`);
  }
  const confirmer = textValue(get(rule, "confirmed_by"), "rounding_rule.confirmed_by");
  const versionId = textValue(get(rule, "rounding_rule_version_id"), "rounding_rule.version_id");
  return { id: ruleId, rounding_rule_version_id: versionId, stage, mode, decimal_places: decimalPlaces, confirmed_by: confirmer };
}

function round(value: Decimal, rule: Rule): Decimal {
  const quantum = Decimal.fromInt(1).scaleb(-rule.decimal_places);
  return value.quantize(quantum, ROUNDING_MODES[rule.mode]);
}

async function quote(payload: Json, store: Store, simulator: boolean): Promise<Json> {
  const quoteId = textValue(get(payload, "quote_id"), "quote_id");
  const confirmer = approvedBy(payload);
  const lineRule = await loadRule(store, get(payload, "line_rule_id"), "line");
  const taxRule = await loadRule(store, get(payload, "tax_rule_id"), "tax_category_total");
  const lines = get(payload, "lines");
  if (!Array.isArray(lines) || lines.length === 0) {
    throw new ValidationError("lines: 見積行を1件以上指定してください");
  }
  const taxRates = get(payload, "tax_rates");
  if (!isDict(taxRates) || Object.keys(taxRates).length === 0) {
    throw new ValidationError("tax_rates: 人が指定した架空税率設定が必要です");
  }
  const rates = new Map<string, Decimal>();
  for (const [taxCategory, rawRate] of Object.entries(taxRates)) {
    const category = textValue(taxCategory, "tax_category");
    const rate = decimalValue(rawRate, `tax_rates.${category}`);
    if (rate.gt(1)) {
      throw new ValidationError(`tax_rates.${category}: 税率は0〜1の十進比率で指定してください`);
    }
    rates.set(category, rate);
  }

  const quoteLines: Json[] = [];
  const categoryBases = new Map<string, Decimal>();
  const seenLineIds = new Set<string>();
  for (const [index, line] of lines.entries()) {
    if (!isDict(line)) {
      throw new ValidationError(`lines[${index}]: 見積行を確認してください`);
    }
    const lineId = textValue(get(line, "quote_line_id"), `lines[${index}].quote_line_id`);
    if (seenLineIds.has(lineId)) {
      throw new ValidationError("quote_line_id: 重複しています");
    }
    seenLineIds.add(lineId);
    const name = textValue(get(line, "name"), `lines[${index}].name`);
    const quantity = decimalValue(get(line, "quantity"), `lines[${index}].quantity`);
    const unitPrice = decimalValue(get(line, "unit_price"), `lines[${index}].unit_price`);
    const taxCategory = textValue(get(line, "tax_category"), `lines[${index}].tax_category`);
    if (!rates.has(taxCategory)) {
      throw new ValidationError(`lines[${index}].tax_category: 税率の指定がありません`);
    }
    let unrounded: Decimal;
    let rounded: Decimal;
    try {
      unrounded = quantity.mul(unitPrice);
      rounded = round(unrounded, lineRule);
    } catch (error) {
      if (error instanceof InvalidOperation) throw new ValidationError(`lines[${index}]: 金額の桁数を確認してください`);
      throw error;
    }
    categoryBases.set(taxCategory, (categoryBases.get(taxCategory) ?? Decimal.parse("0")).add(unrounded));
    quoteLines.push({
      quote_line_id: lineId,
      name,
      quantity: quantity.toString(),
      unit_price: unitPrice.toString(),
      unrounded_line_total: unrounded.toString(),
      line_total: rounded.toString(),
      tax_category: taxCategory,
      rounding_rule: { ...lineRule },
    });
  }

  const taxGroups: Json[] = [];
  for (const taxCategory of [...categoryBases.keys()].sort(compareStrings)) {
    const base = categoryBases.get(taxCategory)!;
    const rate = rates.get(taxCategory)!;
    const unroundedTax = base.mul(rate);
    let taxAmount: Decimal;
    try {
      taxAmount = round(unroundedTax, taxRule);
    } catch (error) {
      if (error instanceof InvalidOperation) throw new ValidationError(`${taxCategory}: 税額の桁数を確認してください`);
      throw error;
    }
    taxGroups.push({
      tax_category: taxCategory,
      tax_rate: rate.toString(),
      unrounded_taxable_total: base.toString(),
      unrounded_tax: unroundedTax.toString(),
      tax: taxAmount.toString(),
      rounding_rule: { ...taxRule },
    });
  }
  const subtotal = decimalSum(quoteLines.map((line) => Decimal.parse(line.line_total as string)));
  const taxTotal = decimalSum(taxGroups.map((group) => Decimal.parse(group.tax as string)));
  const quoteRecord: Json = {
    quote_id: quoteId,
    lines: quoteLines,
    subtotal: subtotal.toString(),
    tax: taxTotal.toString(),
    total: subtotal.add(taxTotal).toString(),
    tax_groups: taxGroups,
    confirmed_by: confirmer,
    rounding_rules: { line: { ...lineRule }, tax_category_total: { ...taxRule } },
    tax_rate_source: "human_supplied_fictional_configuration",
    simulator,
  };
  const saved = await store.put(QUOTE_NAMESPACE, quoteRecord, quoteId);
  return {
    status: "quoted",
    quote: saved,
    simulator,
    notice: "税率は人が指定した架空設定です。法令・会計適合性を示すものではありません。",
  };
}
