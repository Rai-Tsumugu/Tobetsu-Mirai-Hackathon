-- 見積（src/auto_repair_quote と、auto_repair_items の見積時価格スナップショット）。
-- 両システムの見積を1つの表にまとめ、工数の計算結果と単価の版を見積行から参照する。
-- 帯は low / typical / high。金額・数量は帯ごとに列を持つ（単一値の見積は3帯に同じ値を入れる）。

-- 承認済みの作業プリセット（見積の作業選択）。内容を変えるときは新しい版を作る。
CREATE TABLE job_presets (
  preset_id           text NOT NULL CHECK (btrim(preset_id) <> ''),
  version             integer NOT NULL CHECK (version >= 1),
  job_code            text NOT NULL REFERENCES jobs,
  name                text NOT NULL,
  aliases             jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(aliases) = 'array'),
  required_conditions jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(required_conditions) = 'array'),
  inputs              jsonb NOT NULL CHECK (jsonb_typeof(inputs) = 'object'),
  default_quantity    numeric NOT NULL DEFAULT 1 CHECK (default_quantity > 0),
  rate_ref            text,
  item_codes          text[] NOT NULL DEFAULT '{}',
  source              text NOT NULL,
  approved_by         text NOT NULL REFERENCES staff,
  updated_on          date NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (preset_id, version)
);

-- 見積の見出し。origin は作成元のシステム（quote=整備見積、items=材料の見積時価格）。
CREATE TABLE quotes (
  quote_id     text PRIMARY KEY CHECK (btrim(quote_id) <> ''),
  origin       text NOT NULL CHECK (origin IN ('quote', 'items')),
  customer_ref text REFERENCES customers,
  vehicle_ref  text REFERENCES vehicles,
  job_code     text REFERENCES jobs,
  case_id      text REFERENCES estimate_cases,
  is_simulator boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quotes_customer ON quotes (customer_ref);
CREATE INDEX quotes_vehicle ON quotes (vehicle_ref);

-- 見積の版。保存した版は変えない。条件を変えたら新しい版を作る（旧版は残る）。
-- snapshot は保存時点の見積全体で、価格を再計算せずにそのまま再表示するために持つ。
CREATE TABLE quote_versions (
  quote_id             text NOT NULL REFERENCES quotes,
  version_no           integer NOT NULL CHECK (version_no >= 1),
  parent_version_no    integer,
  status               text NOT NULL CHECK (status IN ('calculated', 'proposed', 'confirmed', 'blocked')),
  selected_band        text CHECK (selected_band IN ('low', 'typical', 'high')),
  subtotal_low         numeric NOT NULL CHECK (subtotal_low >= 0),
  subtotal_typical     numeric NOT NULL,
  subtotal_high        numeric NOT NULL,
  tax_low              numeric NOT NULL CHECK (tax_low >= 0),
  tax_typical          numeric NOT NULL,
  tax_high             numeric NOT NULL,
  total_low            numeric NOT NULL CHECK (total_low >= 0),
  total_typical        numeric NOT NULL,
  total_high           numeric NOT NULL,
  final_amount         numeric CHECK (final_amount >= 0),
  override_reason      text,
  confirmed_by         text REFERENCES staff,
  man_hour_estimate_id uuid REFERENCES man_hour_estimates,
  as_of                date,
  inputs               jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(inputs) = 'object'),
  snapshot             jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
  created_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (quote_id, version_no),
  FOREIGN KEY (quote_id, parent_version_no) REFERENCES quote_versions (quote_id, version_no),
  CHECK (parent_version_no IS NULL OR parent_version_no < version_no),
  CHECK (subtotal_low <= subtotal_typical AND subtotal_typical <= subtotal_high),
  CHECK (tax_low <= tax_typical AND tax_typical <= tax_high),
  CHECK (total_low <= total_typical AND total_typical <= total_high),
  -- 確定は担当者と帯を人が選んだときだけ。自動で標準帯を選ばない。
  CHECK (status <> 'confirmed' OR (confirmed_by IS NOT NULL AND selected_band IS NOT NULL)),
  CHECK (final_amount IS NULL OR selected_band IS NOT NULL),
  -- 確定額を帯の合計から変えるときは理由が必要。
  CHECK (
    final_amount IS NULL
    OR final_amount = CASE selected_band
      WHEN 'low' THEN total_low WHEN 'typical' THEN total_typical ELSE total_high END
    OR btrim(coalesce(override_reason, '')) <> ''
  )
);
CREATE TRIGGER quote_versions_append_only
  BEFORE UPDATE OR DELETE ON quote_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- 見積行。工賃は工数の結果、部品・材料は単価の版を参照する。
CREATE TABLE quote_lines (
  quote_id           text NOT NULL,
  version_no         integer NOT NULL,
  line_id            text NOT NULL CHECK (btrim(line_id) <> ''),
  position           integer NOT NULL CHECK (position >= 1),
  kind               text NOT NULL CHECK (kind IN ('labor', 'parts', 'materials', 'adjustment', 'discount')),
  category           text,
  description        text NOT NULL,
  unit               text NOT NULL,
  quantity_low       numeric NOT NULL CHECK (quantity_low >= 0),
  quantity_typical   numeric NOT NULL,
  quantity_high      numeric NOT NULL,
  unit_price_low     numeric NOT NULL CHECK (unit_price_low >= 0),
  unit_price_typical numeric NOT NULL,
  unit_price_high    numeric NOT NULL,
  amount_low         numeric NOT NULL CHECK (amount_low >= 0),
  amount_typical     numeric NOT NULL,
  amount_high        numeric NOT NULL,
  source_system      text NOT NULL,
  source_ref         text,
  item_code          text REFERENCES items,
  price_version_id   uuid REFERENCES item_prices,
  reason             text NOT NULL DEFAULT '',
  status             text NOT NULL,
  snapshot           jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(snapshot) = 'object'),
  PRIMARY KEY (quote_id, version_no, line_id),
  UNIQUE (quote_id, version_no, position),
  FOREIGN KEY (quote_id, version_no) REFERENCES quote_versions,
  CHECK (quantity_low <= quantity_typical AND quantity_typical <= quantity_high),
  CHECK (unit_price_low <= unit_price_typical AND unit_price_typical <= unit_price_high),
  CHECK (amount_low <= amount_typical AND amount_typical <= amount_high)
);
CREATE INDEX quote_lines_price ON quote_lines (price_version_id) WHERE price_version_id IS NOT NULL;
CREATE TRIGGER quote_lines_append_only
  BEFORE UPDATE OR DELETE ON quote_lines
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- 顧客に伝えた金額・条件の記録（電話説明など）。版を参照し、追記だけ。
CREATE TABLE quote_communications (
  communication_id text PRIMARY KEY CHECK (btrim(communication_id) <> ''),
  quote_id         text NOT NULL,
  version_no       integer NOT NULL,
  payload          jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  recorded_by      text REFERENCES staff,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (quote_id, version_no) REFERENCES quote_versions
);
CREATE INDEX quote_communications_quote ON quote_communications (quote_id, version_no, created_at);
CREATE TRIGGER quote_communications_append_only
  BEFORE UPDATE OR DELETE ON quote_communications
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- 再見積・追加変更の記録（どの版からどの版へ、顧客の了承）。追記だけ。
CREATE TABLE quote_change_events (
  event_id     text PRIMARY KEY CHECK (btrim(event_id) <> ''),
  quote_id     text NOT NULL,
  from_version integer,
  to_version   integer NOT NULL,
  payload      jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (quote_id, to_version) REFERENCES quote_versions (quote_id, version_no),
  FOREIGN KEY (quote_id, from_version) REFERENCES quote_versions (quote_id, version_no)
);
CREATE INDEX quote_change_events_quote ON quote_change_events (quote_id, created_at);
CREATE TRIGGER quote_change_events_append_only
  BEFORE UPDATE OR DELETE ON quote_change_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- 入力途中の下書き。保存前なので上書きできる。
CREATE TABLE quote_drafts (
  draft_id   text PRIMARY KEY CHECK (btrim(draft_id) <> ''),
  quote_id   text REFERENCES quotes,
  step       integer NOT NULL DEFAULT 0 CHECK (step >= 0),
  payload    jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- 見積行に対する実使用量。見積の数量・単価は変えず、理由付きで別に記録する。
CREATE TABLE material_usages (
  usage_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_id           text NOT NULL,
  version_no         integer NOT NULL,
  line_id            text NOT NULL,
  estimated_quantity numeric NOT NULL CHECK (estimated_quantity >= 0),
  actual_quantity    numeric NOT NULL CHECK (actual_quantity >= 0),
  difference         numeric GENERATED ALWAYS AS (actual_quantity - estimated_quantity) STORED,
  unit               text NOT NULL,
  reason             text NOT NULL CHECK (btrim(reason) <> ''),
  confirmed_by       text NOT NULL REFERENCES staff,
  is_simulator       boolean NOT NULL DEFAULT false,
  recorded_at        timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (quote_id, version_no, line_id) REFERENCES quote_lines
);
CREATE INDEX material_usages_line ON material_usages (quote_id, version_no, line_id);
CREATE TRIGGER material_usages_append_only
  BEFORE UPDATE OR DELETE ON material_usages
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
