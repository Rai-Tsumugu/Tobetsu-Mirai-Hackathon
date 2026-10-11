// 整備見積デモの架空の初期データ（src/app-demo/backend/app.py の MODELS・JOBS・sources_for）。
// 車種・型式は要件書の例示。年式の選択肢・仕様・参考価格はすべてデモ用の架空値で、実車への適合を示さない。
import type { Queryable, Transaction } from "@/lib/db/queryable";
import type { Job, Source, Vehicle } from "./types";

/** [メーカー, 車種, 型式, 仕様] のサンプル9車種。並び順は車両一覧の表示順。 */
export const MODELS: readonly (readonly [string, string, string, string])[] = [
  ["ホンダ", "シビック", "FL4", "e:HEV（デモ仕様）"],
  ["ホンダ", "シビック", "FL1", "ガソリン（デモ仕様）"],
  ["トヨタ", "プリウス", "ZVW50", "ハイブリッド（デモ仕様）"],
  ["トヨタ", "プリウス", "MXWH60", "ハイブリッド（デモ仕様）"],
  ["トヨタ", "アクア", "NHP10", "ハイブリッド（デモ仕様）"],
  ["トヨタ", "アクア", "MXPK11", "ハイブリッド（デモ仕様）"],
  ["スズキ", "ジムニー", "JB64W", "4WD（デモ仕様）"],
  ["ホンダ", "N-BOX", "JF3", "軽自動車（デモ仕様）"],
  ["ホンダ", "N-BOX", "JF5", "軽自動車（デモ仕様）"],
];

export const JOBS: readonly Job[] = [
  { id: "brake", category: "ブレーキ", name: "フロントブレーキパッド交換", description: "前輪左右・パッド持込なし", base: 6000 },
  { id: "oil", category: "消耗品", name: "エンジンオイル交換", description: "オイル交換のみ・フィルター別", base: 2000 },
  { id: "battery", category: "電装", name: "補機バッテリー交換", description: "補機用・バッテリー持込なし", base: 4000 },
  { id: "filter", category: "消耗品", name: "エアコンフィルター交換", description: "フィルター交換のみ", base: 1500 },
  { id: "bumper", category: "外装", name: "フロントバンパー交換", description: "脱着交換・塗装と補修は別", base: 16000 },
];

/** サンプル車両1件分の data（年式は2015〜2026年、仕様はデモ仕様と「その他（要確認）」）。 */
export function sampleVehicle([maker, model, code, grade]: readonly [string, string, string, string]): Vehicle {
  return {
    id: code,
    maker,
    model,
    model_code: code,
    years: Array.from({ length: 12 }, (_, i) => 2015 + i),
    grades: [grade, "その他（要確認）"],
    length_mm: null,
    width_mm: null,
    height_mm: null,
    powertrain: "未確認",
    source_name: "simulator",
    source_url: null,
    verified_at: null,
    note: "年式の選択肢・仕様はデモ用です。実車への適合・諸元は未確認です。",
  };
}

/**
 * Simulator の参考価格（架空の4件、毎回同じ）。
 * A=基準−1,000円（税抜）、B=基準×1.1（税込。税抜換算は円未満切り捨て）、C=基準+2,000円（税抜）、
 * D=総額のみ・別仕様（比較対象外）。
 */
export function simulatorSources(job: Job): Source[] {
  const base = job.base;
  // int(Decimal(base) * Decimal('1.1')) と、税抜換算の (price / 1.1) の切り捨てを整数で計算する。
  const prices: [string, number][] = [
    ["A", base - 1000],
    ["B", Math.trunc((base * 11) / 10)],
    ["C", base + 2000],
    ["D", base * 4],
  ];
  return prices.map(([label, price], i) => ({
    id: `${job.id}-${i}`,
    source_title: `サンプル整備記録 ${label}`,
    source_url: null,
    mode: "simulator",
    retrieved_at: "2026-10-11",
    currency: "JPY",
    verified: false,
    labor_price: i < 3 ? price : null,
    parts_price: i < 3 ? null : base * 2,
    total_price: i < 3 ? null : base * 4,
    tax_included: i === 1,
    vehicle_match_level: i < 3 ? "型式一致（架空）" : "別仕様（架空）",
    work_conditions: i < 3 ? job.description : "別仕様・追加工程あり・工賃内訳不明",
    extraction_notes: "サンプル／実価格ではない",
    normalized_labor: i === 1 ? Math.floor((price * 10) / 11) : i < 3 ? price : null,
  }));
}

/** 作業マスタを入れる（登録済みは変えない）。見積もり保存の前にも呼び、参照先を必ず用意する。 */
export async function ensureRepairJobs(db: Queryable): Promise<void> {
  await db.query(
    `INSERT INTO demo_repair_jobs (id, data)
     SELECT x->>'id', x FROM json_array_elements($1::json) AS x
     ON CONFLICT (id) DO NOTHING`,
    [JSON.stringify(JOBS)],
  );
}

/** サンプル車両と作業を入れる。何度実行しても同じ状態になる（登録済みのものは変えない）。 */
export async function seedDemo(db: Transaction): Promise<void> {
  for (const model of MODELS) {
    const vehicle = sampleVehicle(model);
    await db.query("INSERT INTO demo_vehicles (id, data) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING", [
      vehicle.id,
      JSON.stringify(vehicle),
    ]);
  }
  await ensureRepairJobs(db);
}
