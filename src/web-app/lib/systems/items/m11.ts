// M11: PDF伝票領域指定取込（m11.py の移植）。指定領域から架空の明細候補を作る Simulator。
import { Decimal } from "./decimal";
import { DEMO_DATE, ValidationError, approvedBy, decimalValue, textValue, type Json, type Store } from "./core";
import { approveRows, stageRows } from "./importing";
import { get, isDict, isInt, pyEqual, utcNowIso } from "./py";

export const SPEC = {
  idea_id: "M11",
  title: "PDF伝票領域指定取込",
  description: "人が指定したページ領域からSimulatorの架空明細候補を作り、選択承認した行だけ価格マスタへ登録します。",
  defaults: {
    action: "sample",
    confirmed_by: "架空デモ担当",
  },
};

const SAMPLE_ROWS: Json[] = [
  {
    item_id: "demo-m11-paint",
    name: "架空サンプル塗料",
    category: "塗料",
    unit: "ml",
    unit_price: "95",
    price_type: "仕入",
    source: "simulator:架空PDF明細",
    updated_at: DEMO_DATE,
  },
];
const MAX_PAGE = 10000;
const REGION_KEYS = ["x", "y", "width", "height"] as const;

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "stage");
  if (action === "approve") {
    const batchId = textValue(get(payload, "import_batch_id"), "import_batch_id");
    const batch = await store.latest("import_batch", batchId);
    const ids = get(payload, "candidate_ids");
    const batchIds = batch.candidate_ids as unknown[];
    if (!Array.isArray(ids) || ids.some((candidateId) => !batchIds.some((known) => pyEqual(known, candidateId)))) {
      throw new ValidationError("candidate_ids: このPDF候補から承認対象を選択してください");
    }
    const result: Json = await approveRows(store, ids, approvedBy(payload));
    result.import_batch_id = batchId;
    result.simulator = true;
    return result;
  }
  if (action !== "stage" && action !== "sample") {
    throw new ValidationError("action: stage / sample / approve を指定してください");
  }

  let documentId: string;
  let page: unknown;
  let pageWidth: Decimal;
  let pageHeight: Decimal;
  let region: Record<string, Decimal>;
  if (action === "sample") {
    documentId = "demo-m11-pdf";
    page = 1;
    pageWidth = Decimal.parse("612");
    pageHeight = Decimal.parse("792");
    region = { x: Decimal.parse("36"), y: Decimal.parse("120"), width: Decimal.parse("540"), height: Decimal.parse("240") };
  } else {
    documentId = documentReference(get(payload, "source_document_id"));
    page = pageNumber(get(payload, "page"));
    pageWidth = decimalValue(get(payload, "page_width"), "page_width", { positive: true });
    pageHeight = decimalValue(get(payload, "page_height"), "page_height", { positive: true });
    region = regionBounds(get(payload, "region"), pageWidth, pageHeight);
    // 抽出は意図的に Simulator。PDF のバイト列は読まず保存しない。
  }

  const source = "simulator:未接続のPDF抽出、架空値";
  const rows = SAMPLE_ROWS.map((row) => ({ ...row, source }));
  const staged = await stageRows(store, rows, source);
  const regionText = Object.fromEntries(Object.entries(region).map(([key, value]) => [key, value.toString()]));
  const batch = await store.put("import_batch", {
    source_document_id: documentId,
    document_type: "pdf",
    page,
    page_width: pageWidth.toString(),
    page_height: pageHeight.toString(),
    region: regionText,
    candidate_ids: staged.staged_rows.map((row) => row.record_id),
    imported_at: utcNowIso(),
    simulator: true,
    extraction_connected: false,
  });
  return {
    status: "人の確認待ち",
    source_document_id: documentId,
    page,
    region: { ...regionText },
    import_batch_id: batch.record_id,
    staged_rows: staged.staged_rows,
    items: [],
    simulator: true,
    extraction_connected: false,
  };
}

function documentReference(value: unknown): string {
  const text = textValue(value, "source_document_id");
  if ([...text].length > 128 || [...text].some((char) => char.codePointAt(0)! < 32)) {
    throw new ValidationError("source_document_id: 参照IDは128文字以下で指定してください");
  }
  return text;
}

function pageNumber(value: unknown): unknown {
  if (typeof value === "boolean" || !isInt(value) || !(Number(value) >= 1 && Number(value) <= MAX_PAGE)) {
    throw new ValidationError("page: 1〜10000の整数を指定してください");
  }
  return value;
}

function regionBounds(value: unknown, pageWidth: Decimal, pageHeight: Decimal): Record<string, Decimal> {
  const keys = isDict(value) ? Object.keys(value) : [];
  if (!isDict(value) || keys.length !== REGION_KEYS.length || !REGION_KEYS.every((key) => keys.includes(key))) {
    throw new ValidationError("region: x / y / width / height を指定してください");
  }
  const bounds: Record<string, Decimal> = {};
  for (const key of REGION_KEYS) {
    bounds[key] = decimalValue(value[key], `region.${key}`, { positive: key === "width" || key === "height" });
  }
  if (bounds.x.add(bounds.width).gt(pageWidth) || bounds.y.add(bounds.height).gt(pageHeight)) {
    throw new ValidationError("region: ページ範囲内の領域を指定してください");
  }
  return bounds;
}
