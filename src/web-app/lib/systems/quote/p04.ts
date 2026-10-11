// P04: 承認済みの仕入掛率を1回だけ掛け、品目単価をスナップショットする。
import { BANDS, make_line, money_range, multiply_ranges, number, range_value, type Band } from "./common";
import { dateFromIso, deepcopy, get, isDict, isList, item, nonemptyStrOrInt, pyIn, PyError, pyStr, QuoteError, setdefault, truthy, type Obj } from "./pyrt";

const CATEGORIES = ["部品", "塗料", "溶剤", "消耗品"];
const PRICE_TYPES = ["仕入", "販売"];
const LINE_PREFIX = "item-price:";

export function selling_price(entry: unknown): Record<Band, number> {
  if (!isDict(entry)) throw new QuoteError("item must be an object");
  const priceType = get(entry, "price_type");
  if (!pyIn(priceType, PRICE_TYPES)) throw new QuoteError("price_type must be 仕入 or 販売");
  const base = finiteRange(money_range(get(entry, "unit_price")));
  if (priceType === "販売") return base;
  const markup = get(entry, "markup");
  if (!isDict(markup)) throw new QuoteError("purchase price requires an approved markup");
  if (!nonemptyStrOrInt(get(markup, "approved_by")) || !nonemptyStrOrInt(get(markup, "reason"))) {
    throw new QuoteError("purchase markup requires approved_by and reason");
  }
  const factor = finiteRange(money_range(get(markup, "value")));
  return finiteRange(multiply_ranges(base, factor));
}

export function apply(quote: unknown, inputs: unknown): Obj {
  if (!isDict(quote) || !isDict(inputs)) throw new QuoteError("quote and inputs must be objects");
  const items = get(inputs, "items");
  if (!isList(items)) throw new QuoteError("items must be a list");

  const prepared: [Obj, Record<Band, number>][] = [];
  const seen = new Set<string>();
  items.forEach((entry, index) => {
    if (!isDict(entry)) throw new QuoteError(`items.${index} must be an object`);
    let itemId = get(entry, "item_id");
    if (!nonemptyStrOrInt(itemId)) throw new QuoteError(`items.${index}.item_id is required`);
    itemId = pyStr(itemId);
    if (seen.has(itemId)) throw new QuoteError(`duplicate item_id: ${itemId}`);
    seen.add(itemId);
    if (!pyIn(get(entry, "category"), CATEGORIES)) throw new QuoteError(`items.${index}.category is invalid`);
    if (!pyIn(get(entry, "price_type"), PRICE_TYPES)) throw new QuoteError(`items.${index}.price_type is invalid`);
    const unit = get(entry, "unit");
    const quantityUnit = get(entry, "quantity_unit");
    if (!nonemptyStrOrInt(unit) || !nonemptyStrOrInt(quantityUnit) || unitKey(unit) !== unitKey(quantityUnit)) {
      throw new QuoteError(`items.${index}.quantity_unit must match unit`);
    }
    const quantity = range_value(get(entry, "quantity_range"));
    const finalPrice = selling_price(entry);
    const amount = multiply_ranges(
      { low: quantity.low.toString(), typical: quantity.typical.toString(), high: quantity.high.toString() },
      finalPrice,
    );
    for (const field of ["source", "updated_at"]) {
      if (!nonemptyStrOrInt(get(entry, field))) throw new QuoteError(`items.${index}.${field} is required`);
    }
    validateDate(entry.updated_at, index);
    prepared.push([entry, amount]);
  });

  const result = deepcopy(quote);
  const lines = setdefault(result, "lines", []);
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");
  const itemIds = new Set(prepared.map(([entry]) => pyStr(entry.item_id)));
  const kept = lines.filter(
    (line) => !(isDict(line) && get(line, "line_id") === lineId(get(line, "source_ref")) && itemIds.has(pyStr(get(line, "source_ref")))),
  );
  lines.splice(0, lines.length, ...kept);

  for (const [entry, amount] of prepared) {
    const itemId = pyStr(entry.item_id);
    const basePrice = money_range(entry.unit_price);
    const markupSnapshot = get(entry, "price_type") === "仕入" ? deepcopy(get(entry, "markup")) : null;
    const finalPrice = selling_price(entry);
    const snapshot = {
      item_id: itemId,
      price_type: entry.price_type,
      base_price: basePrice,
      final_unit_price: finalPrice,
      markup: markupSnapshot,
      source: entry.source,
      updated_at: entry.updated_at,
    };
    const category = entry.category;
    lines.push(
      make_line({
        line_id: lineId(itemId),
        kind: category === "部品" ? "parts" : "materials",
        category,
        description: pyStr(truthy(get(entry, "name")) ? get(entry, "name") : itemId),
        quantity_range: entry.quantity_range,
        unit: pyStr(entry.unit).trim(),
        unit_price_range: finalPrice,
        amount,
        source_system: pyStr(entry.source),
        source_ref: itemId,
        snapshot,
        reason: reason(entry),
      }),
    );
  }
  return result;
}

function lineId(itemId: unknown): string {
  return `${LINE_PREFIX}${pyStr(itemId)}`;
}

function finiteRange(value: Record<Band, number>): Record<Band, number> {
  const parsed = { low: value.low, typical: value.typical, high: value.high };
  for (const band of BANDS) number(parsed[band]);
  return parsed;
}

function reason(entry: Obj): string {
  if (get(entry, "price_type") === "販売") return "登録済み販売単価 × 同一帯の数量（掛率なし）";
  const markup = item(entry, "markup");
  return `仕入単価 × 承認済み掛率 ${pyStr(item(markup, "value"))}（${pyStr(item(markup, "approved_by"))}: ${pyStr(item(markup, "reason"))}）`;
}

function unitKey(value: unknown): string {
  return typeof value === "string" ? value.split(/\s+/).join("") : "";
}

function validateDate(value: unknown, index: number): void {
  if (typeof value !== "string") throw new QuoteError(`items.${index}.updated_at must be an ISO date`);
  try {
    dateFromIso(value);
  } catch (error) {
    if (error instanceof PyError) throw new QuoteError(`items.${index}.updated_at must be an ISO date`);
    throw error;
  }
}
