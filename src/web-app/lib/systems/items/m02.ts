// M02: 容量・入数単位変換（m02.py の移植）。承認済みの包装単位の価格と数量を基準単位へ換算する。
import { Decimal } from "./decimal";
import { DEMO_DATE, ValidationError, approvedBy, decimalValue, textValue, type Json, type Store } from "./core";
import { get, has, isDict } from "./py";

export const SPEC = {
  idea_id: "M02",
  title: "容量・入数単位変換",
  description: "根拠を確認した包装単位の価格と数量を基準単位へ換算します。",
  defaults: {
    item_id: "demo-paint",
    source_unit: "ml",
    base_unit: "ml",
    factor: "1",
    evidence: "simulator:架空値、同一単位のデモ換算",
    quantity: "1",
    price_type: "仕入",
    confirmed_by: "架空デモ担当",
    as_of: DEMO_DATE,
  },
};

// 同じ次元の単位。包装単位（箱・缶・セット）は個数として数え、factor が何基準単位を含むかを記録する。
const UNIT_DIMENSIONS: Record<string, string> = {
  個: "count",
  本: "count",
  缶: "count",
  箱: "count",
  セット: "count",
  ml: "volume",
  L: "volume",
  g: "mass",
  kg: "mass",
};

function conversionId(itemId: string, sourceUnit: string, baseUnit: string): string {
  return `${itemId}|${sourceUnit}|${baseUnit}`;
}

function validateUnits(sourceUnit: string, baseUnit: string): void {
  if (!has(UNIT_DIMENSIONS, sourceUnit) || !has(UNIT_DIMENSIONS, baseUnit)) {
    throw new ValidationError("unit: 対応する単位を選択してください");
  }
  if (UNIT_DIMENSIONS[sourceUnit] !== UNIT_DIMENSIONS[baseUnit]) {
    throw new ValidationError("unit: 次元が異なる単位は換算できません");
  }
}

/**
 * 承認済み価格と数量を基準単位で返す。factor は元の単位1つに含まれる基準単位の数。
 * 保存済みの承認価格は source_unit 建てでなければならない。
 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const sourceUnit = textValue(get(payload, "source_unit"), "source_unit");
  const baseUnit = textValue(get(payload, "base_unit"), "base_unit");
  validateUnits(sourceUnit, baseUnit);
  const factor = decimalValue(get(payload, "factor"), "factor", { positive: true });
  if (sourceUnit === baseUnit && !factor.eq(Decimal.parse("1"))) {
    throw new ValidationError("factor: 同一単位の換算係数は1です");
  }
  const evidence = textValue(get(payload, "evidence"), "evidence");
  const quantity = decimalValue(get(payload, "quantity"), "quantity");
  const confirmedBy = approvedBy(payload);
  const priceType = textValue(get(payload, "price_type", "販売"), "price_type");
  const asOf = textValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const id = conversionId(itemId, sourceUnit, baseUnit);

  // 登録済みの換算と条件が違えば止める。新しい係数・根拠は人が改めて確認する。
  const existing = await store.records("unit_conversion", id);
  if (existing.length > 0) {
    const previous = existing[existing.length - 1];
    if (previous.factor !== factor.toString() || previous.evidence !== evidence) {
      throw new ValidationError("換算根拠が登録済み内容と異なります: 再確認してください");
    }
  }
  const version = await store.getPrice(itemId, priceType, { as_of: asOf, unit: sourceUnit });
  const sourceItem = version.item;
  const sourcePrice = decimalValue(sourceItem.unit_price, "unit_price");
  // decimal_value は28桁までなので、60桁あれば積は正確で、割り切れない除算を検出できる。
  const normalizedQuantity = quantity.mul(factor, { prec: 60 });
  const normalizedPrice = sourcePrice.div(factor, { prec: 60 });
  const exactPrice = normalizedPrice.mul(factor, { prec: 60 }).eq(sourcePrice);
  if (!exactPrice) {
    throw new ValidationError("単価を有限桁で正確に表せません: 丸め規則を確認してください");
  }
  const normalizedItem = { ...sourceItem, unit: baseUnit, unit_price: normalizedPrice.toString() };

  if (existing.length === 0) {
    await store.transaction(() =>
      store.put(
        "unit_conversion",
        {
          item_id: itemId,
          source_unit: sourceUnit,
          base_unit: baseUnit,
          factor: factor.toString(),
          evidence,
          confirmed_by: confirmedBy,
        },
        id,
      ),
    );
  }

  return {
    item: normalizedItem,
    items: [normalizedItem],
    source_quantity: quantity.toString(),
    source_unit: sourceUnit,
    quantity: normalizedQuantity.toString(),
    unit: baseUnit,
    source_unit_price: sourcePrice.toString(),
    unit_price: normalizedPrice.toString(),
    price_type: priceType,
    price_version_id: version.price_version_id,
    conversion: { factor: factor.toString(), evidence, confirmed_by: confirmedBy },
  };
}
