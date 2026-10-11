// M13: 卸提供JSONコネクタ（m13.py の移植）。ローカル fixture の仕入候補を、人の承認後だけ保存する。
import { DEMO_DATE, ValidationError, approvedBy, dateValue, decimalValue, textValue, type Json, type Store } from "./core";
import { approveRows, stageRows } from "./importing";
import { get, isDict, pyEqual, utcNowIso } from "./py";

export const SPEC = {
  idea_id: "M13",
  title: "卸提供JSONコネクタ",
  description:
    "利用許諾と品番対応を確認したローカルJSON fixtureから仕入候補を作り、人の承認後だけ保存します。実API未接続のSimulatorです。",
  defaults: {
    action: "sample",
    confirmed_by: "架空デモ担当",
  },
};

export const DEMO_FEED = {
  mode: "fixture",
  source: "simulator:架空卸fixture",
  terms_status: "approved",
  schema_version: "1",
  offers: [
    {
      supplier_part_number: "DEMO-PAINT-01",
      unit_price: "95",
      currency: "JPY",
      updated_at: DEMO_DATE,
    },
  ],
};
export const DEMO_MAPPING = [
  {
    supplier_part_number: "DEMO-PAINT-01",
    item_id: "demo-m13-paint",
    name: "架空サンプル塗料",
    category: "塗料",
    unit: "ml",
  },
];

const hasControl = (text: string) => [...text].some((char) => char.codePointAt(0)! < 32);

export async function run(payload: unknown, store: Store): Promise<Json> {
  if (!isDict(payload)) {
    throw new ValidationError("payload: 入力を確認してください");
  }
  const action = get(payload, "action", "stage");
  if (action === "approve") {
    const batchId = textValue(get(payload, "import_batch_id"), "import_batch_id");
    const batch = await store.latest("import_batch", batchId);
    const candidateIds = get(payload, "candidate_ids");
    if (
      !Array.isArray(candidateIds) ||
      candidateIds.length === 0 ||
      candidateIds.some((candidateId) => !(batch.candidate_ids as unknown[]).some((known) => pyEqual(known, candidateId)))
    ) {
      throw new ValidationError("candidate_ids: この卸fixtureの候補から選択してください");
    }
    const result: Json = await approveRows(store, candidateIds, approvedBy(payload));
    result.import_batch_id = batchId;
    result.simulator = true;
    result.api_connected = false;
    return result;
  }

  if (action !== "sample" && action !== "stage") {
    throw new ValidationError("action: sample / stage / approve を指定してください");
  }
  const [feed, mapping] = action === "sample" ? [DEMO_FEED, DEMO_MAPPING] : [get(payload, "feed"), get(payload, "part_number_mapping")];

  const [source, schemaVersion, offers] = validateFeed(feed);
  const mappingByPart = validateMapping(mapping);
  const offerParts = offers.map((offer) => offer.supplier_part_number);
  if (offerParts.length !== new Set(offerParts).size) {
    throw new ValidationError("offers: 仕入先品番の重複を解消してください");
  }
  if (offerParts.some((partNumber) => !mappingByPart.has(partNumber))) {
    throw new ValidationError("part_number_mapping: 全仕入先品番の対応づけが必要です");
  }

  const rows = offers.map((offer) => {
    const partNumber = offer.supplier_part_number;
    const mapped = mappingByPart.get(partNumber)!;
    return {
      item_id: mapped.item_id,
      name: mapped.name,
      category: mapped.category,
      unit: mapped.unit,
      unit_price: offer.unit_price,
      price_type: "仕入",
      source: `simulator:未接続fixture:${source}:schema-${schemaVersion}:part-${partNumber}`,
      updated_at: offer.updated_at,
    };
  });

  let staged: Awaited<ReturnType<typeof stageRows>> | undefined;
  let batch: Json | undefined;
  await store.transaction(async () => {
    staged = await stageRows(store, rows, source);
    batch = await store.put("import_batch", {
      source,
      schema_version: schemaVersion,
      terms_status: "approved",
      candidate_ids: staged.staged_rows.map((row) => row.record_id),
      imported_at: utcNowIso(),
      simulator: true,
      api_connected: false,
      mode: "fixture",
    });
  });
  return {
    status: "人の確認待ち",
    import_batch_id: batch!.record_id,
    staged_rows: staged!.staged_rows,
    items: [],
    simulator: true,
    api_connected: false,
    source,
    schema_version: schemaVersion,
  };
}

type Offer = { supplier_part_number: string; unit_price: string; updated_at: string };

function validateFeed(feed: unknown): [string, string, Offer[]] {
  if (!isDict(feed)) {
    throw new ValidationError("feed: 卸提供JSON fixtureが必要です");
  }
  const mode = textValue(get(feed, "mode"), "mode");
  if (mode !== "fixture") {
    throw new ValidationError("mode: live接続は未許諾・未実装のため利用できません");
  }
  const source = textValue(get(feed, "source"), "source");
  if ([...source].length > 120 || hasControl(source)) {
    throw new ValidationError("source: 120文字以下で指定してください");
  }
  if (get(feed, "terms_status") !== "approved") {
    throw new ValidationError("terms_status: 利用許諾の確認が必要です");
  }
  const schemaVersion = textValue(get(feed, "schema_version"), "schema_version");
  if (schemaVersion !== "1") {
    throw new ValidationError("schema_version: 対応するfixture schemaは1です");
  }
  const offers = get(feed, "offers");
  if (!Array.isArray(offers) || offers.length === 0 || offers.length > 1000) {
    throw new ValidationError("offers: 1〜1000件の候補が必要です");
  }
  const normalized: Offer[] = [];
  offers.forEach((offer, zeroIndex) => {
    const index = zeroIndex + 1;
    if (!isDict(offer)) {
      throw new ValidationError(`offers[${index}]: fixtureの行を確認してください`);
    }
    const partNumber = textValue(get(offer, "supplier_part_number"), `offers[${index}].supplier_part_number`);
    if ([...partNumber].length > 128 || hasControl(partNumber)) {
      throw new ValidationError(`offers[${index}].supplier_part_number: 128文字以下で指定してください`);
    }
    let unitPrice = textValue(get(offer, "unit_price"), `offers[${index}].unit_price`);
    // 共通の Decimal 検査を通し、十進文字列のまま保持する。
    unitPrice = decimalValue(unitPrice, `offers[${index}].unit_price`, { positive: true }).toString();
    if (get(offer, "currency") !== "JPY") {
      throw new ValidationError(`offers[${index}].currency: JPY以外は自動換算できません`);
    }
    let updatedAt = textValue(get(offer, "updated_at"), `offers[${index}].updated_at`);
    updatedAt = dateValue(updatedAt, `offers[${index}].updated_at`);
    normalized.push({ supplier_part_number: partNumber, unit_price: unitPrice, updated_at: updatedAt });
  });
  return [source, schemaVersion, normalized];
}

type LocalItem = { item_id: string; name: string; category: string; unit: string };

function validateMapping(mapping: unknown): Map<string, LocalItem> {
  if (!Array.isArray(mapping) || mapping.length === 0 || mapping.length > 1000) {
    throw new ValidationError("part_number_mapping: 品番対応づけが必要です");
  }
  const mappingByPart = new Map<string, LocalItem>();
  mapping.forEach((entry, zeroIndex) => {
    const index = zeroIndex + 1;
    if (!isDict(entry)) {
      throw new ValidationError(`part_number_mapping[${index}]: 対応づけを確認してください`);
    }
    const partNumber = textValue(get(entry, "supplier_part_number"), `part_number_mapping[${index}].supplier_part_number`);
    if (mappingByPart.has(partNumber)) {
      throw new ValidationError("part_number_mapping: 仕入先品番の重複を解消してください");
    }
    const localItem: LocalItem = {
      item_id: textValue(get(entry, "item_id"), `part_number_mapping[${index}].item_id`),
      name: textValue(get(entry, "name"), `part_number_mapping[${index}].name`),
      category: textValue(get(entry, "category"), `part_number_mapping[${index}].category`),
      unit: textValue(get(entry, "unit"), `part_number_mapping[${index}].unit`),
    };
    if (!["部品", "塗料", "溶剤", "消耗品"].includes(localItem.category)) {
      throw new ValidationError(`part_number_mapping[${index}].category: 選択値を確認してください`);
    }
    mappingByPart.set(partNumber, localItem);
  });
  return mappingByPart;
}
