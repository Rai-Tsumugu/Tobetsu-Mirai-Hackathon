// importing.py の移植: M09〜M13 の取込候補の隔離と承認。品目の項目だけを保存する。
import { ITEM_FIELDS, ValidationError, textValue, validateItem, type Item, type Json, type PriceVersion, type Store, type StoredRecord } from "./core";
import { get, has, isDict } from "./py";

/**
 * field_map は共通項目名 → 元の列名。不備のある行はエラー付きで隔離する。
 * 原文・個人情報・対応づけていない列は保存しない。
 */
export async function stageRows(
  store: Store,
  rows: unknown,
  sourceInput: unknown,
  fieldMap: unknown = null,
): Promise<{ staged_rows: StoredRecord[]; status: string; items: Item[] }> {
  const source = textValue(sourceInput, "source");
  if (!Array.isArray(rows) || rows.length === 0 || rows.length > 1000) {
    throw new ValidationError("rows: 1〜1000行の品目情報が必要です");
  }
  if (
    fieldMap !== null &&
    fieldMap !== undefined &&
    (!isDict(fieldMap) ||
      Object.entries(fieldMap).some(([key, value]) => !(ITEM_FIELDS as readonly string[]).includes(key) || typeof value !== "string"))
  ) {
    throw new ValidationError("field_map: 共通品目項目への列対応を確認してください");
  }
  const map = (fieldMap ?? null) as Record<string, string> | null;
  const useMap = map !== null && Object.keys(map).length > 0;
  const stagedRows: StoredRecord[] = [];
  await store.transaction(async () => {
    for (const [index, row] of rows.entries()) {
      const errors: string[] = [];
      let item: Item | null = null;
      if (!isDict(row)) {
        errors.push("行は品目項目の集合で指定してください");
      } else {
        const candidate: Json = {};
        for (const key of ITEM_FIELDS) {
          const column = useMap ? (has(map!, key) ? map![key] : key) : key;
          candidate[key] = get(row, column);
        }
        if (candidate.source === null || candidate.source === undefined || candidate.source === "") {
          candidate.source = source;
        }
        try {
          item = validateItem(candidate);
        } catch (error) {
          if (!(error instanceof ValidationError)) throw error;
          errors.push(error.message);
        }
      }
      const staged = await store.put("staging_row", {
        row_number: index + 1,
        item,
        source,
        status: errors.length > 0 ? "quarantined" : "pending",
        errors,
      });
      stagedRows.push(staged);
    }
  });
  return { staged_rows: stagedRows, status: "人の確認待ち", items: [] };
}

export async function approveRows(
  store: Store,
  candidateIdsInput: unknown,
  confirmedByInput: unknown,
): Promise<{ items: Item[]; price_version_ids: string[]; status: string }> {
  const confirmedBy = textValue(confirmedByInput, "confirmed_by");
  if (!Array.isArray(candidateIdsInput) || candidateIdsInput.length === 0) {
    throw new ValidationError("candidate_ids: 候補IDを選択してください");
  }
  const candidateIds = candidateIdsInput.map((candidateId) => textValue(candidateId, "candidate_id"));
  if (candidateIds.length !== new Set(candidateIds).size) {
    throw new ValidationError("candidate_ids: 重複のない候補IDを選択してください");
  }
  const versions: PriceVersion[] = [];
  await store.transaction(async () => {
    for (const rawId of candidateIds) {
      const candidateId = textValue(rawId, "candidate_id");
      const row = await store.latest("staging_row", candidateId);
      if (row.status !== "pending" || row.item === null || row.item === undefined) {
        throw new ValidationError("取込不備の行は承認できません");
      }
      if ((await store.records("import_approval", candidateId)).length > 0) {
        throw new ValidationError("この候補はすでに承認されています");
      }
      const version = await store.addPrice(row.item, confirmedBy, { reason: "取込候補を人が確認" });
      await store.put(
        "import_approval",
        { candidate_id: candidateId, price_version_id: version.price_version_id, confirmed_by: confirmedBy },
        candidateId,
      );
      versions.push(version);
    }
  });
  return {
    items: versions.map((version) => version.item),
    price_version_ids: versions.map((version) => version.price_version_id),
    status: "承認済み",
  };
}
