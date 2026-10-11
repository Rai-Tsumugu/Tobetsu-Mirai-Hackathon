// pipeline.py: 帯を保ったまま見積を計算する正の経路（P03→P01/P02→P04→P07→P05→P06→P07→P09→P11→P10→P08）。
import { BANDS, new_quote, _json_number } from "./common";
import * as p01 from "./p01";
import * as p02 from "./p02";
import * as p03 from "./p03";
import * as p04 from "./p04";
import * as p05 from "./p05";
import * as p06 from "./p06";
import * as p07 from "./p07";
import * as p08 from "./p08";
import * as p09 from "./p09";
import * as p10 from "./p10";
import * as p11 from "./p11";
import { deepcopy, Dec, get, has, isDict, isList, PyError, truthy, uuid4Hex, ValueErr, type Obj } from "./pyrt";

export function json_ready(value: unknown): unknown {
  if (value instanceof Dec) return _json_number(value);
  if (isDict(value)) {
    const result: Obj = {};
    for (const key of Object.keys(value)) result[key] = json_ready(value[key]);
    return result;
  }
  if (isList(value)) return value.map(json_ready);
  return value;
}

function nullBands(quote: Obj): void {
  for (const field of ["subtotal", "tax", "total"]) quote[field] = { low: null, typical: null, high: null };
}

export function calculate(rawInputs: unknown): Obj {
  if (!isDict(rawInputs)) throw new ValueErr("inputs must be an object");
  const inputs = deepcopy(rawInputs);
  let quote = new_quote({}, {}, []);
  const items = get(inputs, "items");
  Object.assign(quote, {
    quote_id: truthy(get(inputs, "quote_id")) ? inputs.quote_id : "Q-" + uuid4Hex().slice(0, 10),
    quote_version: get(inputs, "quote_version", 1),
    customer_ref: get(inputs, "customer_ref"),
    vehicle_ref: get(inputs, "vehicle_ref"),
    job_ref: get(inputs, "job_ref"),
    selected_band: null,
    conditions: [],
    fictional: isList(items) && items.every((entry) => isDict(entry) && get(entry, "source") === "simulator"),
  });
  quote.metadata.input_snapshot = deepcopy(inputs);
  if (get(inputs, "parent_version") !== null) quote.parent_version = inputs.parent_version;
  quote = p03.apply(quote, inputs);
  if (quote.status === "blocked") {
    nullBands(quote);
    return json_ready(quote) as Obj;
  }
  try {
    quote = p01.apply(quote, inputs);
    const labor = get(inputs, "labor", {});
    if (truthy(isDict(labor) ? get(labor, "breakdown") : null)) quote = p02.apply(quote, inputs);
    quote = p04.apply(quote, inputs);
    quote = p07.apply(quote, inputs);
    if (get(inputs, "discount") !== null) quote = p05.apply(quote, inputs);
    quote = p06.apply(quote, inputs);
    quote = p07.apply(quote, inputs);
    quote = p09.apply(quote, inputs);
    quote = p11.apply(quote, inputs);
    quote = p10.apply(quote, inputs);
    quote = p08.apply(quote);
  } catch (error) {
    // ValueError / TypeError / KeyError をまとめて「計算できない」状態にする。
    if (!(error instanceof PyError || error instanceof TypeError)) throw error;
    Object.assign(quote, { status: "blocked", issues: [{ code: "calculation_blocked", path: "inputs", message: error.message }] });
    nullBands(quote);
  }
  return json_ready(quote) as Obj;
}

export { has };
