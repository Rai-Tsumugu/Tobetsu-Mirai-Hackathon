export type Band = 'low' | 'typical' | 'high';
export type RangeValue = Record<Band, number | null>;
export type QuoteLine = {
  line_id: string;
  kind: string;
  category: string | null;
  description: string;
  quantity_range: RangeValue;
  unit: string;
  unit_price_range: RangeValue;
  amount: RangeValue;
  source_system: string;
  source_ref: string | null;
  reason: string;
  status: string;
  snapshot: Record<string, unknown>;
};
export type Quote = {
  quote_id: string;
  quote_version: number;
  status: string;
  lines: QuoteLine[];
  subtotal: RangeValue;
  tax: RangeValue;
  total: RangeValue;
  final_amount?: number | null;
  reasons: string[];
  conditions: Array<{ text: string; status: string }>;
  selected_band: Band | null;
  confirmed_by: string | null;
  override_reason: string | null;
  issues?: Array<{ code: string; path: string; message: string }>;
  [key: string]: unknown;
};
export type WorkflowPreview = {
  quote: Quote;
  summary: { text: string; [key: string]: unknown };
  band_comparison: unknown;
  questions: {
    questions: Array<{ field: string; prompt: string; detail: string; status: string }>;
    status: string;
    can_calculate: boolean;
  };
  next_action: string;
  can_confirm: boolean;
};
export type WorkflowSnapshot = {
  quote: Quote;
  summary: { text?: string; [key: string]: unknown };
  document: Record<string, unknown> | string | null;
  communications: unknown[];
  changes: unknown[];
  next_action: string;
};
export const bands: Band[] = ['low', 'typical', 'high'];
export const band_labels: Record<Band, string> = {
  low: '低い条件',
  typical: '標準条件',
  high: '追加条件',
};
