// m19.py の移植: 部位と仕上げから人が確認した材料候補を示し、選択を記録する。
import { ValidationError, approvedBy, textValue, type Json, type Store, type StoredRecord } from "./core";
import { get, isDict, truthy } from "./py";

export const SPEC = {
  idea_id: "M19",
  title: "パネル・部位材料辞書",
  description: "部位と仕上げから材料候補を表示し、人が適合を確認して選択します。",
  defaults: {
    action: "list",
    panel_id: "front_door",
    finish_type: "metallic",
  } as Json,
};

export const NAMESPACE = "panel_material";
export const SELECTION_NAMESPACE = "panel_material_selection";

/** 辞書の記録、候補の一覧、人の選択の記録。 */
export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "list");
  if (action === "record") {
    checkKeys(payload, ["action", "panel_id", "finish_type", "item_id", "applicability", "source", "confirmed_by"]);
    return record(payload, store);
  }
  if (action === "list") {
    checkKeys(payload, ["action", "panel_id", "finish_type"]);
    return list(payload, store);
  }
  if (action === "select") {
    checkKeys(payload, ["action", "panel_id", "finish_type", "item_id", "application_condition", "confirmed_by"]);
    return select(payload, store);
  }
  throw new ValidationError("action: record / list / select を選択してください");
}

function checkKeys(payload: Json, allowed: string[]): void {
  if (Object.keys(payload).some((key) => !allowed.includes(key))) {
    throw new ValidationError("payload: 指定できない項目があります");
  }
}

function key(payload: Json): [string, string] {
  return [textValue(get(payload, "panel_id"), "panel_id"), textValue(get(payload, "finish_type"), "finish_type")];
}

async function record(payload: Json, store: Store): Promise<Json> {
  const [panelId, finishType] = key(payload);
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const applicability = textValue(get(payload, "applicability"), "applicability");
  const source = textValue(get(payload, "source"), "source");
  const confirmer = approvedBy(payload);
  const row = {
    panel_id: panelId,
    finish_type: finishType,
    item_id: itemId,
    applicability,
    source,
    confirmed_by: confirmer,
    simulator: source.startsWith("simulator:"),
  };
  const saved = await store.put(NAMESPACE, row);
  return { status: "saved", panel_material_id: saved.record_id, candidate: row };
}

async function matchingRows(store: Store, panelId: string, finishType: string): Promise<StoredRecord[]> {
  return (await store.records(NAMESPACE)).filter((row) => row.panel_id === panelId && row.finish_type === finishType);
}

async function list(payload: Json, store: Store): Promise<Json> {
  const [panelId, finishType] = key(payload);
  let rows = await matchingRows(store, panelId, finishType);
  if (rows.length === 0 && panelId === "front_door" && finishType === "metallic") {
    await record(
      {
        panel_id: panelId,
        finish_type: finishType,
        item_id: "demo-metallic-paint",
        applicability: "架空デモ用。実車・工程への適合は未確認",
        source: "simulator:架空材料辞書",
        confirmed_by: "架空デモ担当",
      },
      store,
    );
    rows = await matchingRows(store, panelId, finishType);
  }
  const candidates = rows.map((row) => ({
    item_id: row.item_id,
    applicability: row.applicability,
    source: row.source,
    confirmed_by: row.confirmed_by,
    simulator: row.simulator,
  }));
  const result: Json = {
    panel_id: panelId,
    finish_type: finishType,
    candidates,
    simulator: rows.some((row) => truthy(row.simulator)),
  };
  if (candidates.length === 0) {
    result.unknowns = ["panel_id/finish_type の材料候補辞書が未登録"];
  }
  return result;
}

async function select(payload: Json, store: Store): Promise<Json> {
  const [panelId, finishType] = key(payload);
  const itemId = textValue(get(payload, "item_id"), "item_id");
  const condition = textValue(get(payload, "application_condition"), "application_condition");
  const confirmer = approvedBy(payload);
  const candidates = (await matchingRows(store, panelId, finishType)).filter((row) => row.item_id === itemId);
  if (candidates.length === 0) {
    throw new ValidationError("候補未登録: 選択前に辞書を確認してください");
  }
  const candidate = candidates[candidates.length - 1];
  const selection = {
    panel_id: panelId,
    finish_type: finishType,
    item_id: itemId,
    application_condition: condition,
    source: candidate.source,
    confirmed_by: confirmer,
  };
  const saved = await store.put(SELECTION_NAMESPACE, selection);
  return { status: "selected", selection_id: saved.record_id, selection, simulator: truthy(candidate.simulator) };
}
