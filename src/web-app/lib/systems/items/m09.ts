// M09: CSV列対応ウィザード（m09.py の移植）。列を共通品目項目へ対応づけ、候補を隔離してから人が承認する。
import { DEMO_DATE, ITEM_FIELDS, ValidationError, textValue, type Json, type Store } from "./core";
import { approveRows, stageRows } from "./importing";
import { get, has, isDict, isInt, pyStrip } from "./py";

const DEMO_HEADERS = ["商品コード", "品名", "分類", "単位", "単価", "価格区分", "出所", "確認日"];
const DEMO_CSV = [
  DEMO_HEADERS.join(","),
  `demo-m09-paint,架空デモ塗料,塗料,ml,95,仕入,simulator:架空値,${DEMO_DATE}`,
  `demo-m09-thinner,架空デモ溶剤,溶剤,L,480,仕入,simulator:架空値,${DEMO_DATE}`,
].join("\n");
const DEMO_FIELD_MAP: Record<string, string> = Object.fromEntries(ITEM_FIELDS.map((field, index) => [field, DEMO_HEADERS[index]]));

export const SPEC = {
  idea_id: "M09",
  title: "CSV列対応ウィザード",
  description: "CSV列を共通品目項目へ対応づけ、行ごとの検品後に選択候補だけを人が承認します。",
  defaults: {
    action: "stage",
    csv_text: DEMO_CSV,
    source: "simulator:架空値",
    source_key: "demo-m09-csv",
    field_map: DEMO_FIELD_MAP,
  },
};

const EXTRA = "__extra_columns__";

/** csv.Error 相当。 */
class CsvError extends Error {}

/** StringIO(text, newline='') の行分割（\r\n / \n / \r で区切り、改行文字は残す）。 */
function splitLines(text: string): string[] {
  const lines: string[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      lines.push(text.slice(start, i + 1));
      start = i + 1;
    }
  }
  if (start < text.length) lines.push(text.slice(start));
  return lines;
}

const FIELD_LIMIT = 131072;

/** csv.reader(excel 方言, strict=True) の状態機械（_csv.c の parse_process_char）。 */
function* csvReader(text: string): Generator<string[]> {
  const lines = splitLines(text);
  let lineIndex = 0;
  type State = "START_RECORD" | "START_FIELD" | "IN_FIELD" | "IN_QUOTED_FIELD" | "QUOTE_IN_QUOTED_FIELD" | "EAT_CRNL";
  for (;;) {
    const fields: string[] = [];
    let field = "";
    let fieldLen = 0;
    let state: State = "START_RECORD";
    const addChar = (c: string) => {
      if (fieldLen >= FIELD_LIMIT) throw new CsvError(`field larger than field limit (${FIELD_LIMIT})`);
      field += c;
      fieldLen += 1;
    };
    const saveField = () => {
      fields.push(field);
      field = "";
      fieldLen = 0;
    };
    const process = (c: string | null) => {
      switch (state) {
        case "START_RECORD":
          if (c === null) return;
          if (c === "\n" || c === "\r") {
            state = "EAT_CRNL";
            return;
          }
          state = "START_FIELD";
        // fallthrough
        case "START_FIELD":
          if (c === "\n" || c === "\r" || c === null) {
            saveField();
            state = c === null ? "START_RECORD" : "EAT_CRNL";
          } else if (c === '"') {
            state = "IN_QUOTED_FIELD";
          } else if (c === ",") {
            saveField();
          } else {
            addChar(c);
            state = "IN_FIELD";
          }
          return;
        case "IN_FIELD":
          if (c === "\n" || c === "\r" || c === null) {
            saveField();
            state = c === null ? "START_RECORD" : "EAT_CRNL";
          } else if (c === ",") {
            saveField();
            state = "START_FIELD";
          } else {
            addChar(c);
          }
          return;
        case "IN_QUOTED_FIELD":
          if (c === null) return;
          if (c === '"') state = "QUOTE_IN_QUOTED_FIELD";
          else addChar(c);
          return;
        case "QUOTE_IN_QUOTED_FIELD":
          if (c === '"') {
            addChar(c);
            state = "IN_QUOTED_FIELD";
          } else if (c === ",") {
            saveField();
            state = "START_FIELD";
          } else if (c === "\n" || c === "\r" || c === null) {
            saveField();
            state = c === null ? "START_RECORD" : "EAT_CRNL";
          } else {
            throw new CsvError(`',' expected after '"'`);
          }
          return;
        case "EAT_CRNL":
          if (c === "\n" || c === "\r") return;
          if (c === null) {
            state = "START_RECORD";
            return;
          }
          throw new CsvError("new-line character seen in unquoted field - do you need to open the file with newline=''?");
      }
    };
    do {
      if (lineIndex >= lines.length) {
        if (fieldLen !== 0 || (state as State) === "IN_QUOTED_FIELD") {
          throw new CsvError("unexpected end of data");
        }
        return;
      }
      const line = lines[lineIndex];
      lineIndex += 1;
      for (const c of line) process(c);
      process(null);
    } while ((state as State) !== "START_RECORD");
    yield fields;
  }
}

/** csv.DictReader(restkey='__extra_columns__', restval=None) の見出しと行。 */
function dictReader(text: string): { headers: () => string[] | null; rows: () => Json[] } {
  const reader = csvReader(text);
  let fieldnames: string[] | null | undefined;
  const headers = () => {
    if (fieldnames === undefined) {
      const next = reader.next();
      fieldnames = next.done ? null : next.value;
    }
    return fieldnames;
  };
  const rows = () => {
    const names = headers() ?? [];
    const out: Json[] = [];
    for (const row of reader) {
      if (row.length === 0) continue;
      const record: Json = {};
      names.forEach((name, index) => {
        if (index < row.length) record[name] = row[index];
      });
      if (names.length < row.length) record[EXTRA] = row.slice(names.length);
      else if (names.length > row.length) for (const name of names.slice(row.length)) record[name] = null;
      out.push(record);
    }
    return out;
  };
  return { headers, rows };
}

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "stage");
  if (action === "stage") return stage(payload, store);
  if (action === "approve") return approve(payload, store);
  throw new ValidationError("action: stage または approve を指定してください");
}

async function stage(payload: Json, store: Store): Promise<Json> {
  const csvText = get(payload, "csv_text");
  if (typeof csvText !== "string" || !pyStrip(csvText)) {
    throw new ValidationError("csv_text: CSV本文が必要です");
  }
  if (new TextEncoder().encode(csvText).length > 1_000_000) {
    throw new ValidationError("csv_text: CSVは1MB以下にしてください");
  }
  const source = textValue(get(payload, "source", "simulator:架空値"), "source");
  const sourceKey = textValue(get(payload, "source_key", source), "source_key");
  if ([...sourceKey].length > 128) {
    throw new ValidationError("source_key: 128文字以下にしてください");
  }

  let fieldMap: Record<string, string>;
  let rawRows: Json[];
  try {
    const reader = dictReader(csvText);
    const headers = reader.headers();
    if (!headers || headers.length === 0) {
      throw new ValidationError("csv_text: ヘッダー行が必要です");
    }
    if (headers.some((header) => typeof header !== "string" || !pyStrip(header))) {
      throw new ValidationError("csv_text: 空の列名は使用できません");
    }
    if (headers.length !== new Set(headers).size) {
      throw new ValidationError("csv_text: 重複した列名があります");
    }
    if (headers.includes(EXTRA)) {
      throw new ValidationError("csv_text: 予約済み列名が含まれています");
    }
    fieldMap = validateFieldMap(get(payload, "field_map"), headers);
    rawRows = reader.rows();
  } catch (error) {
    if (error instanceof CsvError) {
      throw new ValidationError(`csv_text: CSV形式を確認してください (${error.message})`);
    }
    throw error;
  }

  if (rawRows.length === 0 || rawRows.length > 1000) {
    throw new ValidationError("csv_text: 1〜1000件の明細が必要です");
  }

  // 対応づけていない列は保存前に落とす。余分なセルがある行は必須項目を欠けさせて隔離する。
  const mappedRows = rawRows.map((rawRow) => {
    const row: Json = { ...rawRow };
    if (has(rawRow, EXTRA)) {
      row[has(fieldMap, "item_id") ? fieldMap.item_id : "item_id"] = null;
    }
    return row;
  });

  const existingVersions = await store.records("import_mapping", sourceKey);
  const mappingVersion = existingVersions.length > 0 ? (existingVersions[existingVersions.length - 1].version as number) + 1 : 1;
  let staged: Awaited<ReturnType<typeof stageRows>> | undefined;
  let mapping: Json | undefined;
  await store.transaction(async () => {
    staged = await stageRows(store, mappedRows, source, fieldMap);
    mapping = await store.put("import_mapping", { source_key: sourceKey, field_map: fieldMap, version: mappingVersion }, sourceKey);
  });

  return {
    status: staged!.status,
    source_key: sourceKey,
    mapping_version: mappingVersion,
    mapping_record_id: mapping!.record_id,
    field_map: fieldMap,
    staged_rows: staged!.staged_rows,
    preview_count: staged!.staged_rows.length,
    quarantined_count: staged!.staged_rows.filter((row) => row.status === "quarantined").length,
    items: [],
  };
}

function validateFieldMap(fieldMapInput: unknown, headers: string[]): Record<string, string> {
  let fieldMap = fieldMapInput;
  if (fieldMap === null || fieldMap === undefined) {
    fieldMap = Object.fromEntries(ITEM_FIELDS.filter((field) => headers.includes(field)).map((field) => [field, field]));
  }
  if (!isDict(fieldMap) || Object.keys(fieldMap).some((target) => !(ITEM_FIELDS as readonly string[]).includes(target))) {
    throw new ValidationError("field_map: 共通品目項目への列対応を確認してください");
  }
  const normalized: Record<string, string> = {};
  for (const [target, columnInput] of Object.entries(fieldMap)) {
    const column = textValue(columnInput, `field_map.${target}`);
    if (!headers.includes(column)) {
      throw new ValidationError(`field_map.${target}: CSVに存在する列を選択してください`);
    }
    normalized[target] = column;
  }
  // 項目ごとに元の列がちょうど1つ決まるまで保存しない。
  const resolved = ITEM_FIELDS.map((field) => (has(normalized, field) ? normalized[field] : field));
  if (resolved.some((column) => !headers.includes(column))) {
    throw new ValidationError("field_map: 品目ID・品名・分類・単位・単価・価格区分・出所・確認日の列対応が必要です");
  }
  if (new Set(resolved).size !== ITEM_FIELDS.length) {
    throw new ValidationError("field_map: 同じCSV列を複数の項目に割り当てられません");
  }
  return normalized;
}

async function approve(payload: Json, store: Store): Promise<Json> {
  const mappingVersion = get(payload, "mapping_version");
  if (mappingVersion !== null) {
    if (typeof mappingVersion === "boolean" || !isInt(mappingVersion) || Number(mappingVersion) < 1) {
      throw new ValidationError("mapping_version: 正の版番号が必要です");
    }
    const sourceKey = textValue(get(payload, "source_key"), "source_key");
    const mappings = await store.records("import_mapping", sourceKey);
    if (mappings.length === 0 || Number(mappings[mappings.length - 1].version) !== Number(mappingVersion)) {
      throw new ValidationError("mapping_version: 現在の列対応版を確認してください");
    }
  }
  const result: Json = await approveRows(store, get(payload, "candidate_ids"), get(payload, "confirmed_by"));
  result.mapping_version = mappingVersion;
  return result;
}
