// m22.py の移植: 工程に対応する材料候補を示し、人が品目・数量・単位を確定した後だけスナップショットを作る。
import { Decimal } from "./decimal";
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, textValue, type Json, type Store } from "./core";
import { get, isDict, pyEqual, truthy, uuidHex } from "./py";

export const SPEC = {
  idea_id: "M22",
  title: "工程別材料候補",
  description: "①の工程に対応する材料候補を提示し、人が品目・数量・単位を確定した後だけ④向けsnapshotを作ります。",
  defaults: {
    action: "register_rule",
    operation_id: "rust-treatment",
    item_id: "demo-m22-paint",
    required_when: "架空: 塗装工程を選択した場合",
    quantity_rule: "架空: 人が数量を入力",
    evidence: "simulator:架空デモ用の仮定",
    confirmed_by: "架空デモ担当",
  } as Json,
};

export const RULE_NAMESPACE = "operation_material";
export const SUGGESTION_NAMESPACE = "operation_material_suggestion";
export const SNAPSHOT_NAMESPACE = "operation_material_quantity_snapshot";

/** 工程と材料の対応の登録、工数からの候補提示、見積行の確定。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "suggest");
  if (action === "register_rule") {
    checkKeys(payload, ["action", "operation_id", "item_id", "required_when", "quantity_rule", "evidence", "confirmed_by"]);
    return registerRule(payload, store);
  }
  if (action === "suggest") {
    checkKeys(payload, ["action", "labor", "proposed_rules"]);
    return suggest(payload, store);
  }
  if (action === "confirm_selection") {
    checkKeys(payload, ["action", "suggestion_id", "operation_id", "item_id", "quantity", "unit", "price_type", "as_of", "confirmed_by"]);
    return confirmSelection(payload, store);
  }
  if (action === "get_snapshot") {
    checkKeys(payload, ["action", "snapshot_id"]);
    const snapshotId = textValue(get(payload, "snapshot_id"), "snapshot_id");
    return { snapshot: await store.latest(SNAPSHOT_NAMESPACE, snapshotId) };
  }
  throw new ValidationError("action: register_rule / suggest / confirm_selection / get_snapshot を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

async function registerRule(payload: Json, store: Store): Promise<Json> {
  const operationId = textValue(get(payload, "operation_id"), "operation_id");
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const requiredWhen = textValue(get(payload, "required_when"), "required_when");
  const quantityRule = textValue(get(payload, "quantity_rule"), "quantity_rule");
  const evidence = textValue(get(payload, "evidence"), "evidence");
  const confirmer = approvedBy(payload);
  const rule = {
    operation_id: operationId,
    item_id: itemId,
    required_when: requiredWhen,
    quantity_rule: quantityRule,
    evidence,
    confirmed_by: confirmer,
    status: "approved",
  };
  const saved = await store.put(RULE_NAMESPACE, rule);
  return { status: "saved", rule_id: saved.record_id, rule, simulator: evidence.startsWith("simulator:") };
}

function validLabor(payload: Json): { operation_id: string; status: string }[] {
  const labor = get(payload, "labor");
  if (!isDict(labor) || !Array.isArray(get(labor, "breakdown"))) {
    throw new ValidationError("labor.breakdown: 工程一覧を確認してください");
  }
  const breakdown = labor.breakdown as unknown[];
  if (breakdown.length > 100) {
    throw new ValidationError("labor.breakdown: 工程数が多すぎます");
  }
  const operations: { operation_id: string; status: string }[] = [];
  const seen = new Set<string>();
  for (const [index, row] of breakdown.entries()) {
    if (!isDict(row)) {
      throw new ValidationError(`labor.breakdown[${index}]: 工程を確認してください`);
    }
    const operationId = textValue(get(row, "operation"), `labor.breakdown[${index}].operation`);
    const status = textValue(get(row, "status"), `labor.breakdown[${index}].status`);
    if (!seen.has(operationId)) {
      operations.push({ operation_id: operationId, status });
      seen.add(operationId);
    }
  }
  return operations;
}

async function suggest(payload: Json, store: Store): Promise<Json> {
  const operations = validLabor(payload);
  const proposalRules = get(payload, "proposed_rules", []);
  if (!Array.isArray(proposalRules) || proposalRules.length > 100) {
    throw new ValidationError("proposed_rules: 候補辞書を確認してください");
  }
  // 提案はこの呼び出しの中だけで使い、対応表や品目には書かない。
  const proposed: Json[] = [];
  for (const [index, row] of proposalRules.entries()) {
    if (!isDict(row)) {
      throw new ValidationError(`proposed_rules[${index}]: 候補を確認してください`);
    }
    proposed.push({
      operation_id: textValue(get(row, "operation_id"), `proposed_rules[${index}].operation_id`),
      item_id: textValue(get(row, "item_id"), `proposed_rules[${index}].item_id`),
      required_when: textValue(get(row, "required_when"), `proposed_rules[${index}].required_when`),
      quantity_rule: textValue(get(row, "quantity_rule"), `proposed_rules[${index}].quantity_rule`),
      evidence: textValue(get(row, "evidence"), `proposed_rules[${index}].evidence`),
      confirmed_by: textValue(get(row, "confirmed_by"), `proposed_rules[${index}].confirmed_by`),
      status: "proposed",
    });
  }
  const candidates: Json[] = [];
  const unknowns: Json[] = [];
  for (const operation of operations) {
    const operationId = operation.operation_id;
    if (operation.status !== "confirmed" && operation.status !== "conditional") {
      unknowns.push({
        operation_id: operationId,
        question: "この工程の実施有無・状態を人が確認してください。材料候補は追加していません。",
      });
      continue;
    }
    const matching: Json[] = (await store.records(RULE_NAMESPACE)).filter(
      (row) => pyEqual(get(row, "operation_id"), operationId) && get(row, "status") === "approved" && truthy(get(row, "confirmed_by")),
    );
    matching.push(...proposed.filter((row) => row.operation_id === operationId));
    if (matching.length === 0) {
      unknowns.push({ operation_id: operationId, question: "この工程で使う材料候補と根拠を登録・確認してください。" });
    }
    for (const row of matching) {
      candidates.push({
        operation_id: operationId,
        operation_status: operation.status,
        item_id: row.item_id,
        required_when: row.required_when,
        quantity_rule: row.quantity_rule,
        evidence: row.evidence,
        mapping_status: row.status,
        mapping_confirmed_by: row.confirmed_by,
      });
    }
  }
  const suggestionId = uuidHex();
  const suggestion = { suggestion_id: suggestionId, candidates, unknowns, labor_operation_count: operations.length };
  await store.put(SUGGESTION_NAMESPACE, suggestion, suggestionId);
  return { suggestion, simulator: candidates.some((row) => (row.evidence as string).startsWith("simulator:")) };
}

async function confirmSelection(payload: Json, store: Store): Promise<Json> {
  const suggestionId = textValue(get(payload, "suggestion_id"), "suggestion_id");
  const operationId = textValue(get(payload, "operation_id"), "operation_id");
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const quantity = decimalValue(get(payload, "quantity"), "quantity", { positive: true });
  const unit = textValue(get(payload, "unit"), "unit");
  const priceType = get(payload, "price_type", "販売");
  const confirmer = approvedBy(payload);
  const asOf = dateValue(get(payload, "as_of", DEMO_DATE), "as_of");
  const suggestion = await store.latest(SUGGESTION_NAMESPACE, suggestionId);
  const matches = (suggestion.candidates as Json[]).filter((row) => row.operation_id === operationId && row.item_id === itemId);
  if (matches.length === 0) {
    throw new ValidationError("候補未確認: 提示された工程・品目から選択してください");
  }
  const candidate = matches[matches.length - 1];
  const version = await store.getPrice(itemId, priceType, { as_of: asOf, unit });
  const item = { ...version.item };
  // 人が入れた数量を、承認済みの品目・価格版に結びつける。
  const snapshotId = uuidHex();
  const amount = quantity.mul(Decimal.parse(item.unit_price));
  const snapshot = {
    snapshot_id: snapshotId,
    idea_id: "M22",
    operation_id: operationId,
    operation_status: candidate.operation_status,
    item,
    quantity: quantity.toString(),
    unit,
    price_version_id: version.price_version_id,
    candidate_rule: candidate,
    confirmed_by: confirmer,
    as_of: asOf,
    candidate_amount: amount.toString(),
    currency: "JPY",
    status: "confirmed_for_quote_review",
    labor_cost_included: false,
  };
  await store.put(SNAPSHOT_NAMESPACE, snapshot, snapshotId);
  return {
    status: snapshot.status,
    snapshot_id: snapshotId,
    material_snapshot: snapshot,
    items: [item],
    quantity_snapshot_ref: snapshotId,
    simulator: item.source.startsWith("simulator:") || (candidate.evidence as string).startsWith("simulator:"),
  };
}
