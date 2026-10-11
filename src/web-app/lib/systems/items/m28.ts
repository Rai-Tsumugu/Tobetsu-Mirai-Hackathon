// M28: 掛率ルールの版管理と、人の承認後だけの販売価格登録（m28.py の移植）。
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, textValue, type Json, type PriceVersion, type Store } from "./core";
import { Decimal } from "./decimal";
import { get, isDict, maxBy, pyEqual, truthy, uuidHex } from "./py";

export const SPEC = {
  idea_id: "M28",
  title: "掛率ルールの版管理",
  description: "カテゴリ・仕入先・適用日ごとの掛率を版管理し、販売価格候補を人の承認後にだけ登録します。",
  defaults: {
    action: "record_rule",
    rule_id: "demo-markup",
    category: "塗料",
    supplier_id: "demo-supplier",
    effective_from: DEMO_DATE,
    multiplier: "1.5",
    confirmed_by: "架空デモ担当",
    reason: "架空デモ用のルール登録",
  },
};

export const RULES = "markup_rule";
export const PROPOSALS = "markup_proposal";

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "propose");
  if (action === "record_rule") {
    keys(payload, ["action", "rule_id", "category", "supplier_id", "effective_from", "multiplier", "confirmed_by", "reason"]);
    return { rule: await recordRule(payload, store) };
  }
  if (action === "list_rules") {
    keys(payload, ["action", "rule_id"]);
    const rules = await store.records(RULES, get(payload, "rule_id") as string | null);
    return { rules, simulator: rules.some((rule) => truthy(get(rule, "simulator"))) };
  }
  if (action === "propose") {
    keys(payload, ["action", "item_id", "purchase_price_version_id", "rule_id", "as_of", "reason", "confirmed_by"]);
    return propose(payload, store);
  }
  if (action === "approve") {
    keys(payload, ["action", "proposal_id", "confirmed_by", "reason"]);
    return approve(payload, store);
  }
  if (action === "list_proposals") {
    keys(payload, ["action"]);
    return { proposals: await store.records(PROPOSALS), simulator: false };
  }
  throw new ValidationError("action: record_rule / list_rules / propose / approve / list_proposals を選択してください");
}

function keys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

async function recordRule(payload: Json, store: Store): Promise<Json> {
  const ruleId = textValue(get(payload, "rule_id"), "rule_id");
  const category = textValue(get(payload, "category"), "category");
  if (!["部品", "塗料", "溶剤", "消耗品"].includes(category)) {
    throw new ValidationError("category: 選択値を確認してください");
  }
  const supplierId = textValue(get(payload, "supplier_id"), "supplier_id");
  const effectiveFrom = dateValue(get(payload, "effective_from"), "effective_from");
  const multiplier = decimalValue(get(payload, "multiplier"), "multiplier", { positive: true });
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason"), "reason");
  const previous = await store.records(RULES, ruleId);
  if (previous.length > 0) {
    const latest = previous[previous.length - 1];
    if ((latest.effective_from as string) > effectiveFrom) {
      throw new ValidationError("effective_from: 既存ルールより前の日付です");
    }
    if (!pyEqual([latest.category, latest.supplier_id], [category, supplierId])) {
      throw new ValidationError("rule_id: ルールの対象カテゴリ・仕入先は変更できません");
    }
  }
  const record: Json = {
    rule_id: ruleId,
    version: previous.length + 1,
    category,
    supplier_id: supplierId,
    effective_from: effectiveFrom,
    multiplier: multiplier.toString(),
    confirmed_by: confirmer,
    reason,
  };
  await store.put(RULES, record, ruleId);
  return record;
}

async function propose(payload: Json, store: Store): Promise<Json> {
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const purchaseId = textValue(get(payload, "purchase_price_version_id"), "purchase_price_version_id");
  const ruleId = textValue(get(payload, "rule_id"), "rule_id");
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const reason = textValue(get(payload, "reason"), "reason");
  const purchase = await priceById(store, itemId, purchaseId, "仕入");
  const item = purchase.item;
  const purchaseSupplier = get(purchase as unknown as Json, "supplier_id", "");
  const eligible = (await store.records(RULES, ruleId)).filter(
    (r) => r.category === item.category && r.supplier_id === purchaseSupplier && (r.effective_from as string) <= asOf,
  );
  if (eligible.length === 0) {
    throw new ValidationError("掛率ルール: 対象カテゴリ・仕入先・適用日の承認済みルールがありません");
  }
  const rule = maxBy(
    eligible.map((entry, index) => ({ entry, index })),
    (pair) => [pair.entry.effective_from as string, pair.index],
  ).entry;
  if (purchase.status !== "approved" || purchase.valid_from > asOf || (purchase.valid_until !== null && asOf > purchase.valid_until)) {
    throw new ValidationError("仕入価格版: 指定日で有効な承認済み価格が必要です");
  }
  await ensureNoSales(store, itemId);
  const candidateAmount = Decimal.parse(item.unit_price).mul(Decimal.parse(rule.multiplier as string));
  const candidate = {
    ...item,
    unit_price: candidateAmount.toString(),
    price_type: "販売",
    source: `simulator:markup:${ruleId}:v${rule.version}`,
    updated_at: asOf,
  };
  const proposalId = uuidHex();
  const proposal: Json = {
    proposal_id: proposalId,
    item_id: itemId,
    category: item.category,
    supplier_id: purchaseSupplier,
    as_of: asOf,
    purchase_price_version_id: purchaseId,
    purchase_unit_price: item.unit_price,
    rule_id: ruleId,
    rule_version: rule.version,
    multiplier: rule.multiplier,
    candidate,
    reason,
    status: "pending",
    simulator: item.source.startsWith("simulator:"),
  };
  await store.put(PROPOSALS, proposal, proposalId);
  return {
    proposal,
    items: [candidate],
    price_saved: false,
    notice: "販売価格候補です。人が承認するまで価格マスタへ保存されません。",
  };
}

async function approve(payload: Json, store: Store): Promise<Json> {
  const proposalId = textValue(get(payload, "proposal_id"), "proposal_id");
  const confirmer = approvedBy(payload);
  const reason = textValue(get(payload, "reason"), "reason");
  const proposal = await store.latest(PROPOSALS, proposalId);
  if (proposal.status !== "pending") {
    throw new ValidationError("proposal: 承認待ちの候補ではありません");
  }
  await ensureNoSales(store, proposal.item_id as string);
  const purchase = await priceById(store, proposal.item_id as string, proposal.purchase_price_version_id as string, "仕入");
  const ruleVersions = (await store.records(RULES, proposal.rule_id as string)).filter((r) => pyEqual(r.version, proposal.rule_version));
  if (ruleVersions.length === 0 || !pyEqual(ruleVersions[0].multiplier, proposal.multiplier)) {
    throw new ValidationError("掛率ルール版: 提案時の版を確認できません");
  }
  const candidate = proposal.candidate;
  const version = await store.addPrice(candidate, confirmer, {
    supplier_id: proposal.supplier_id,
    valid_from: proposal.as_of,
    reason,
    markup_rule_id: proposal.rule_id,
    markup_rule_version: proposal.rule_version,
    purchase_price_version_id: purchase.price_version_id,
    proposal_id: proposalId,
    multiplier: proposal.multiplier,
    target_category: proposal.category,
    applied_on: proposal.as_of,
  });
  const approved: Json = {
    ...proposal,
    status: "approved",
    approved_by: confirmer,
    approval_reason: reason,
    sales_price_version_id: version.price_version_id,
  };
  await store.put(PROPOSALS, approved, proposalId);
  return { proposal: approved, price_version: version, items: [version.item], price_saved: true };
}

async function priceById(store: Store, itemId: string, priceVersionId: string, priceType: string): Promise<PriceVersion> {
  for (const version of await store.priceVersions(itemId, priceType)) {
    if (version.price_version_id === priceVersionId) return version;
  }
  throw new ValidationError(`${priceType}価格版: 品目に紐づく指定版がありません`);
}

async function ensureNoSales(store: Store, itemId: string): Promise<void> {
  // 販売価格は品目単位。別の仕入先でも、販売価格がある品目へ掛率を再適用しない。
  const existing = (await store.priceVersions(itemId, "販売")).filter((v) => v.status === "approved");
  if (existing.length > 0) {
    throw new ValidationError("販売価格が既にあるため、掛率を再適用できません");
  }
}
