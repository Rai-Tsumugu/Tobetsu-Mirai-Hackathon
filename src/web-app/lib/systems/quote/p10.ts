// P10: 金額を変えずに、見積行ごとの出所バッジを付ける。
import { casefold, deepcopy, get, isDict, isInt, isList, pyStr, QuoteError, truthy, type Obj } from "./pyrt";

export function source_badges(quote: unknown): Obj[] {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  const lines = get(quote, "lines", []);
  if (!isList(lines)) throw new QuoteError("quote.lines must be a list");
  const badges: Obj[] = [];
  lines.forEach((line, index) => {
    if (!isDict(line)) throw new QuoteError(`quote.lines.${index} must be an object`);
    let snapshot = get(line, "snapshot");
    snapshot = isDict(snapshot) ? snapshot : {};
    let sourceSystem = get(line, "source_system");
    let sourceRef = get(line, "source_ref");
    let updatedAt: unknown = null;
    let priceType: unknown = null;
    let fictional = isSimulator(sourceSystem);
    let label = "出所未確認";
    let status = "unconfirmed";

    if (get(line, "kind") === "labor") {
      let rate = get(snapshot, "labor_rate");
      rate = isDict(rate) ? rate : {};
      let basis = get(rate, "basis");
      basis = isList(basis) ? basis : [];
      const effectiveFrom = get(rate, "effective_from");
      updatedAt = nonempty(effectiveFrom) ? effectiveFrom : null;
      priceType = "工賃";
      const hasBasis = (basis as unknown[]).some(
        (entry) => isDict(entry) && nonempty(get(entry, "label")) && get(entry, "value") !== null,
      );
      fictional = fictional || (basis as unknown[]).some((entry) => isDict(entry) && pyStr(get(entry, "label", "")).includes("架空"));
      if (hasBasis && truthy(updatedAt)) {
        label = fictional ? "架空の工賃設定" : "工賃設定";
        status = fictional ? "fictional" : "available";
      } else {
        label = "工賃根拠・適用日未確認";
      }
    } else {
      priceType = get(snapshot, "price_type");
      updatedAt = get(snapshot, "updated_at");
      const itemSource = get(snapshot, "source");
      if (truthy(itemSource)) sourceSystem = itemSource;
      fictional = fictional || isSimulator(itemSource);
      sourceRef = get(snapshot, "item_id", sourceRef);
      if (contractSource(sourceSystem, itemSource, snapshot)) {
        label = "契約条件未確認";
        status = "contract_unconfirmed";
      } else if (nonempty(sourceSystem) && nonempty(sourceRef) && nonempty(updatedAt) && truthy(priceType)) {
        label = fictional ? "架空データ（Simulator）" : "価格根拠あり";
        status = fictional ? "fictional" : "available";
      } else {
        label = "価格の出所・取得日未確認";
        status = "unconfirmed";
      }
    }
    badges.push({
      line_id: deepcopy(get(line, "line_id")),
      source_system: deepcopy(sourceSystem),
      source_ref: deepcopy(sourceRef),
      updated_at: deepcopy(updatedAt),
      price_type: deepcopy(priceType),
      fictional,
      label,
      status,
    });
  });
  return badges;
}

export function apply(quote: unknown, inputs: unknown = null): Obj {
  if (!isDict(quote)) throw new QuoteError("quote must be an object");
  if (inputs !== null && !isDict(inputs)) throw new QuoteError("inputs must be an object when provided");
  const result = deepcopy(quote);
  result.source_badges = source_badges(result);
  return result;
}

function isSimulator(value: unknown): boolean {
  return typeof value === "string" && ["simulator", "fictional", "架空"].includes(casefold(value.trim()));
}

function contractSource(system: unknown, source: unknown, snapshot: Obj): boolean {
  const text = [system, source].filter((value) => value !== null && value !== undefined).map((value) => casefold(pyStr(value))).join(" ");
  if (["contract", "契約", "external", "外部"].some((token) => text.includes(token))) {
    return get(snapshot, "contract_terms_confirmed") !== true;
  }
  return false;
}

function nonempty(value: unknown): boolean {
  return value !== null && value !== undefined && (typeof value === "string" || isInt(value)) && pyStr(value).trim() !== "";
}
