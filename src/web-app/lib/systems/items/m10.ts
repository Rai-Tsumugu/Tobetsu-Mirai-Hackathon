// M10: Excel単一シート取込（m10.py の移植）。固定8列・1シートの XLSX を候補として隔離する。
import { DEMO_DATE, ITEM_FIELDS, ValidationError, approvedBy, textValue, type Json, type Store } from "./core";
import { approveRows, stageRows } from "./importing";
import { get, isDict } from "./py";
import { BadZipFile, XmlParseError, find, findall, itertext, parseXml, readZip, type XmlElement, type ZipEntry } from "./xlsx";

export const SPEC = {
  idea_id: "M10",
  title: "Excel単一シート取込",
  description: "固定8列の1シートXLSXを候補として隔離し、人が確認した行だけ価格マスタへ登録します。",
  defaults: {
    action: "sample",
    confirmed_by: "架空デモ担当",
  },
};

export const MAX_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024;
const MAX_ZIP_ENTRIES = 100;
const MAX_ROWS = 1000;
const MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships";

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "stage");
  if (action === "approve") {
    const batchId = textValue(get(payload, "import_batch_id"), "import_batch_id");
    const result: Json = await approveRows(store, get(payload, "candidate_ids"), approvedBy(payload));
    result.import_batch_id = batchId;
    return result;
  }
  let entries: ZipEntry[];
  let fileName: string;
  let source: string;
  if (action === "sample") {
    entries = sampleEntries();
    fileName = "架空サンプル.xlsx";
    source = "simulator:架空値、架空Excelサンプル";
  } else if (action === "stage") {
    fileName = safeFileName(get(payload, "file_name"));
    const bytes = decodeFile(get(payload, "file_base64"));
    try {
      entries = readZip(bytes);
    } catch (error) {
      if (error instanceof BadZipFile) throw new ValidationError("XLSX: 正しいExcelファイルではありません");
      throw error;
    }
    source = `excel:${fileName}`;
  } else {
    throw new ValidationError("action: stage / sample / approve を指定してください");
  }

  const rows = readXlsx(entries);
  const staged = await stageRows(store, rows, source, Object.fromEntries(ITEM_FIELDS.map((field) => [field, field])));
  const batch = await store.put("import_batch", {
    file_name: fileName,
    source,
    row_count: rows.length,
    staged_count: staged.staged_rows.length,
    simulator: action === "sample",
  });
  return {
    status: "人の確認待ち",
    import_batch_id: batch.record_id,
    file_name: fileName,
    row_count: rows.length,
    staged_rows: staged.staged_rows,
    items: [],
    simulator: action === "sample",
  };
}

function safeFileName(value: unknown): string {
  const name = textValue(value, "file_name");
  if (name.includes("/") || name.includes("\\") || name === "." || name === ".." || !name.toLowerCase().endsWith(".xlsx")) {
    throw new ValidationError("file_name: .xlsx形式のファイル名を指定してください");
  }
  return name;
}

function decodeFile(input: unknown): Uint8Array {
  if (typeof input !== "string" || !input || input.length > Math.floor((MAX_FILE_BYTES * 4) / 3) + 8) {
    throw new ValidationError("file_base64: サイズ上限内のXLSXデータが必要です");
  }
  let value = input;
  if (value.startsWith("data:")) {
    const comma = value.indexOf(",");
    const header = comma < 0 ? value : value.slice(0, comma);
    if (comma < 0 || !header.toLowerCase().includes(";base64")) {
      throw new ValidationError("file_base64: base64形式を確認してください");
    }
    value = value.slice(comma + 1);
  }
  // base64.b64decode(validate=True): 標準の文字だけ、末尾の正しいパディング。
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new ValidationError("file_base64: base64形式を確認してください");
  }
  const data = new Uint8Array(Buffer.from(value, "base64"));
  if (data.length === 0 || data.length > MAX_FILE_BYTES) {
    throw new ValidationError("file_base64: ファイルは5MB以下にしてください");
  }
  return data;
}

function xml(data: Uint8Array, label: string): XmlElement {
  // DTD / entity 宣言は XLSX に不要なので拒否する。
  const upper = Buffer.from(data).toString("latin1").toUpperCase();
  if (upper.includes("<!DOCTYPE") || upper.includes("<!ENTITY")) {
    throw new ValidationError(`${label}: DTD / entity は使用できません`);
  }
  try {
    return parseXml(data);
  } catch (error) {
    if (error instanceof XmlParseError) throw new ValidationError(`${label}: XLSX内のXMLを読み取れません`);
    throw error;
  }
}

function posixNormpath(path: string): string {
  if (path === "") return ".";
  const absolute = path.startsWith("/");
  const parts: string[] = [];
  for (const part of path.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (parts.length > 0 && parts[parts.length - 1] !== "..") parts.pop();
      else if (!absolute) parts.push("..");
      continue;
    }
    parts.push(part);
  }
  const joined = parts.join("/");
  return absolute ? `/${joined}` : joined || ".";
}

function posixJoin(a: string, b: string): string {
  if (b.startsWith("/")) return b;
  if (a === "" || a.endsWith("/")) return a + b;
  return `${a}/${b}`;
}

function posixDirname(path: string): string {
  const index = path.lastIndexOf("/") + 1;
  let head = path.slice(0, index);
  if (head && head !== "/".repeat(head.length)) head = head.replace(/\/+$/, "");
  return head;
}

function lstripSlash(value: string): string {
  return value.replace(/^\/+/, "");
}

function readXlsx(entries: ZipEntry[]): Json[] {
  if (entries.length > MAX_ZIP_ENTRIES || entries.reduce((total, entry) => total + entry.file_size, 0) > MAX_UNCOMPRESSED_BYTES) {
    throw new ValidationError("XLSX: 展開サイズまたはファイル数の上限を超えています");
  }
  const names = entries.map((entry) => entry.filename);
  if (names.length !== new Set(names).size || names.some((name) => name.startsWith("/") || name.split("/").includes(".."))) {
    throw new ValidationError("XLSX: ZIP内のパスを確認してください");
  }
  if (names.some((name) => name.toLowerCase().endsWith(".xlsm") || name.toLowerCase().endsWith(".bin") || name.toLowerCase().includes("vbaproject"))) {
    throw new ValidationError("XLSX: マクロを含むファイルは取り込めません");
  }
  const required = ["[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"];
  if (!required.every((name) => names.includes(name))) {
    throw new ValidationError("XLSX: 必須構成が不足しています");
  }
  const read = (name: string): Uint8Array => {
    // ZipFile.read は同名があれば最後のものを読む（ここでは重複を先に拒否済み）。
    const entry = entries.filter((candidate) => candidate.filename === name).pop()!;
    return entry.read();
  };
  const contents = xml(read("[Content_Types].xml"), "Content_Types");
  if (contents.children.some((node) => (node.attrib.ContentType ?? "").toLowerCase().includes("macroenabled"))) {
    throw new ValidationError("XLSX: マクロ有効形式は取り込めません");
  }
  for (const name of names) {
    if (!name.endsWith(".rels")) continue;
    const root = xml(read(name), name);
    for (const rel of findall(root, `{${PKG_REL_NS}}Relationship`)) {
      if (rel.attrib.TargetMode === "External") {
        throw new ValidationError("XLSX: 外部リンクを含むファイルは取り込めません");
      }
      const target = rel.attrib.Target ?? "";
      if (!target || target.startsWith("http:") || target.startsWith("https:") || target.startsWith("//") || target.includes("?") || target.includes("#")) {
        throw new ValidationError("XLSX: 安全でないリンク先を含んでいます");
      }
      const relDir = posixDirname(name.slice(0, -5));
      const resolvedTarget = posixNormpath(posixJoin(relDir, lstripSlash(target)));
      if (resolvedTarget === ".." || resolvedTarget.startsWith("../")) {
        throw new ValidationError("XLSX: ZIP外を指すリンク先は使用できません");
      }
    }
  }

  const workbook = xml(read("xl/workbook.xml"), "workbook");
  const sheets = findall(workbook, `.//{${MAIN_NS}}sheet`);
  if (sheets.length !== 1) {
    throw new ValidationError("XLSX: ワークシートは1枚だけにしてください");
  }
  const sheetRelId = sheets[0].attrib[`{${DOC_REL_NS}}id`] ?? null;
  const relRoot = xml(read("xl/_rels/workbook.xml.rels"), "workbook relationships");
  const sheetRel = findall(relRoot, `{${PKG_REL_NS}}Relationship`).find((rel) => (rel.attrib.Id ?? null) === sheetRelId) ?? null;
  if (sheetRel === null || !(sheetRel.attrib.Type ?? "").includes("worksheet")) {
    throw new ValidationError("XLSX: 対象シートを特定できません");
  }
  const target = sheetRel.attrib.Target ?? "";
  const sheetPath = target.startsWith("/") ? lstripSlash(target) : posixNormpath(posixJoin("xl", target));
  if (sheetPath.startsWith("../") || !names.includes(sheetPath)) {
    throw new ValidationError("XLSX: 対象シートのパスが不正です");
  }

  let shared: string[] = [];
  if (names.includes("xl/sharedStrings.xml")) {
    const sharedRoot = xml(read("xl/sharedStrings.xml"), "shared strings");
    shared = findall(sharedRoot, `{${MAIN_NS}}si`).map((node) => itertext(node));
  }
  const root = xml(read(sheetPath), "worksheet");
  if (find(root, `.//{${MAIN_NS}}mergeCells`) !== null) {
    throw new ValidationError("XLSX: 結合セルは取り込めません");
  }
  if (find(root, `.//{${MAIN_NS}}hyperlinks`) !== null) {
    throw new ValidationError("XLSX: ハイパーリンクを含むファイルは取り込めません");
  }
  const dataRows = findall(root, `.//{${MAIN_NS}}sheetData/{${MAIN_NS}}row`);
  if (dataRows.length === 0 || dataRows.length > MAX_ROWS + 1) {
    throw new ValidationError("XLSX: ヘッダーと1〜1000件のデータ行が必要です");
  }
  const rows: Json[] = [];
  for (const [rowIndex, rowNode] of dataRows.entries()) {
    const values = new Map<number, string>();
    for (const cell of findall(rowNode, `{${MAIN_NS}}c`)) {
      const address = cell.attrib.r ?? "";
      const match = /^([A-Z]+)/.exec(address);
      if (!match) {
        throw new ValidationError("XLSX: セル位置を読み取れません");
      }
      const column = columnIndex(match[1]);
      if (values.has(column)) {
        throw new ValidationError("XLSX: 同じ行に重複セルがあります");
      }
      if (find(cell, `{${MAIN_NS}}f`) !== null) {
        throw new ValidationError("XLSX: 数式セルは取り込めません");
      }
      if (column >= ITEM_FIELDS.length) {
        throw new ValidationError("XLSX: 8列を超えるデータは取り込めません");
      }
      values.set(column, cellValue(cell, shared));
    }
    if (rowIndex === 0) {
      const header = ITEM_FIELDS.map((_, index) => values.get(index) ?? "");
      if (header.some((value, index) => value !== ITEM_FIELDS[index]) || values.size !== ITEM_FIELDS.length) {
        throw new ValidationError("XLSX: 1行目は共通8項目の固定ヘッダーにしてください");
      }
      continue;
    }
    if (values.size === 0 || [...values.values()].every((value) => value === "")) continue;
    rows.push(Object.fromEntries(ITEM_FIELDS.map((field, index) => [field, values.get(index) ?? ""])));
  }
  if (rows.length === 0) {
    throw new ValidationError("XLSX: データ行がありません");
  }
  return rows;
}

function columnIndex(letters: string): number {
  let value = 0;
  for (const letter of letters) value = value * 26 + letter.charCodeAt(0) - 65 + 1;
  return value - 1;
}

function cellValue(cell: XmlElement, shared: string[]): string {
  const kind = cell.attrib.t ?? null;
  const valueNode = find(cell, `{${MAIN_NS}}v`);
  if (kind === "inlineStr") {
    const inline = find(cell, `{${MAIN_NS}}is`);
    return inline !== null ? itertext(inline) : "";
  }
  if (valueNode === null || !valueNode.text) return "";
  const value = valueNode.text;
  if (kind === "s") {
    // int(value): 前後の空白・符号・"_" 区切りを許す。負の添字は Python では末尾から数える。
    const text = value.replace(/^[\s]+|[\s]+$/g, "");
    if (!/^[+-]?\d+(?:_\d+)*$/.test(text)) throw new ValidationError("XLSX: shared string index が不正です");
    let index = Number(text.replace(/_/g, ""));
    if (index < 0) index += shared.length;
    if (index < 0 || index >= shared.length) throw new ValidationError("XLSX: shared string index が不正です");
    return shared[index];
  }
  if (kind === "b") {
    throw new ValidationError("XLSX: 真偽値セルは取り込めません");
  }
  return value;
}

function xmlEscape(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

/** 架空の小さなブック（_sample_xlsx と同じ内容）。ZIP に固めずに読み取りへ渡す。 */
function sampleEntries(): ZipEntry[] {
  const sample = ["demo-m10-thinner", "架空サンプルシンナー", "溶剤", "ml", "35", "仕入", "simulator:架空値", DEMO_DATE];
  const inline = (ref: string, val: string) => `<c r="${ref}" t="inlineStr"><is><t>${xmlEscape(val)}</t></is></c>`;
  const headerCells = ITEM_FIELDS.map((value, i) => inline(`${String.fromCharCode(65 + i)}1`, value)).join("");
  const cells = sample.map((value, i) => inline(`${String.fromCharCode(65 + i)}2`, value)).join("");
  const worksheet =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    `<sheetData><row r="1">${headerCells}</row><row r="2">${cells}</row></sheetData></worksheet>`;
  const workbook =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
    '<sheets><sheet name="Items" sheetId="1" r:id="rId1"/></sheets></workbook>';
  const rels =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
    "</Relationships>";
  const rootRels =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
    "</Relationships>";
  const types =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
    "</Types>";
  const files: [string, string][] = [
    ["[Content_Types].xml", types],
    ["_rels/.rels", rootRels],
    ["xl/workbook.xml", workbook],
    ["xl/_rels/workbook.xml.rels", rels],
    ["xl/worksheets/sheet1.xml", worksheet],
  ];
  return files.map(([filename, content]) => {
    const bytes = new TextEncoder().encode(content);
    return { filename, file_size: bytes.length, read: () => bytes };
  });
}
