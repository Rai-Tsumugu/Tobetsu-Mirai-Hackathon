-- 部品・材料単価（src/auto_repair_items）の30案と統合ワークスペースが使う追記記録。
-- 単価の版は item_prices、見積は quotes / quote_versions / quote_lines、実使用量は material_usages、
-- 単位換算は unit_conversions に入れる（0004・0005）。ここでは既存の列に入りきらないものだけを持つ。

-- 元の Store.records(namespace, record_id, payload) と同じ追記記録。
-- 30案それぞれの形（価格イベント、更新待ち、仕入先の選択、配合の版、取込候補、掛率・端数規約など）を
-- そのまま JSON で持つ。payload は json 型にして、キーの順序を保存時のまま残す。
-- 見積スナップショット・実使用量・単位換算も同じ形でここに残し、既存の表へは同時に写す。
CREATE TABLE items_records (
  seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  namespace  text NOT NULL CHECK (btrim(namespace) <> ''),
  record_id  text NOT NULL CHECK (btrim(record_id) <> ''),
  payload    json NOT NULL CHECK (json_typeof(payload) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX items_records_lookup ON items_records (namespace, record_id, seq);
CREATE TRIGGER items_records_append_only
  BEFORE UPDATE OR DELETE ON items_records
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- 単価の版の元の形（共通8項目の品目、更新日時の原表記、取引条件などの metadata）。
-- item_prices の列は検索・制約用で、ここは画面と30案が読む版の全体。
CREATE TABLE items_price_payloads (
  price_version_id uuid PRIMARY KEY REFERENCES item_prices,
  payload          json NOT NULL CHECK (json_typeof(payload) = 'object'),
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER items_price_payloads_append_only
  BEFORE UPDATE OR DELETE ON items_price_payloads
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
