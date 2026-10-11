// 整備見積デモの API が返す JSON の形。サーバーと画面の両方から使う（DB には依存しない）。

export type Vehicle = {
  id: string;
  maker: string;
  model: string;
  model_code: string;
  years: number[];
  grades: string[];
  length_mm: number | null;
  width_mm: number | null;
  height_mm: number | null;
  powertrain: string | null;
  source_name: string;
  source_url: string | null;
  verified_at: string | null;
  note: string;
};

export type Job = {
  id: string;
  category: string;
  name: string;
  description: string;
  base: number;
};

/** 参考価格の候補。Simulator（架空）と Gemini 調査（AI抽出）で持つ項目が少し違う。 */
export type Source = {
  id: string;
  source_title: string;
  source_url: string | null;
  mode: "simulator" | "live";
  retrieved_at: string;
  currency: string;
  verified: boolean;
  labor_price: number | null;
  parts_price: number | null;
  total_price: number | null;
  tax_included: boolean | null;
  tax_rate?: number | null;
  vehicle_match_level: string;
  work_conditions: string;
  extraction_notes: string;
  normalized_labor: number | null;
  job_id?: string;
  vehicle_match?: "exact" | "similar" | "unknown";
  work_matches?: boolean | null;
  published_at?: string | null;
  evidence?: string;
};

export type CaseStatus = "unestimated" | "estimating" | "completed";

export type EstimateCase = {
  id: string;
  created_at: string;
  updated_at: string;
  latest_estimate_id: string | null;
  recipient_name: string;
  phone_memo: string;
  vehicle_id: string | null;
  title: string;
  vehicle_label: string;
  status: CaseStatus;
  amount: number | null;
  due_date: string | null;
  notes: string;
};

export type EstimateItem = {
  job_id: string;
  selected_source_ids: string[];
  labor_price: number;
  parts_price: number;
  conditions: string;
  adjustment_reason: string;
  name: string;
  category: string;
  calculated_labor_price: number | null;
  sources: Source[];
};

export type SavedEstimate = {
  id: string;
  created_at: string;
  status: "confirmed";
  mode: "simulator" | "live";
  winter_conditions: string[];
  research_id: string | null;
  search_suggestions: string;
  vehicle: Vehicle;
  year: number;
  grade: string;
  items: EstimateItem[];
  notes: string;
  labor_total: number;
  parts_total: number;
  tax_rate: number;
  subtotal: number;
  tax_amount: number;
  total_amount: number;
  case_id: string;
};

export type ResearchTarget = {
  vehicle_id: string;
  maker: string;
  model: string;
  model_code: string;
  year: number;
  grade: string;
  jobs: { id: string; name: string; description: string }[];
  winter_conditions?: string[];
};

/** Gemini 調査の結果（キャッシュに保存する形）。 */
export type ResearchRecord = {
  citations: { url: string; title: string }[];
  search_suggestions: string;
  warnings: string[];
  values: Record<string, Source[]>;
  context: ResearchTarget;
  kind: string;
  research_id: string;
  cached: boolean;
};
