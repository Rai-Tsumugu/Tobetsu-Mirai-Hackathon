-- 部品・材料単価（src/auto_repair_items）のデータ。
-- 金額・数量は numeric で持ち、丸めない。単価は版を追記していき、上書きしない。

CREATE TABLE suppliers (
  supplier_code text PRIMARY KEY CHECK (btrim(supplier_code) <> ''),
  name          text NOT NULL,
  is_simulator  boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- 品目。名称・分類・基準単位は単価の更新で変えない（単価の版が単位で品目を参照する）。
CREATE TABLE items (
  item_code    text PRIMARY KEY CHECK (btrim(item_code) <> ''),
  name         text NOT NULL CHECK (btrim(name) <> ''),
  category     text NOT NULL CHECK (category IN ('部品', '塗料', '溶剤', '消耗品')),
  base_unit    text NOT NULL CHECK (btrim(base_unit) <> ''),
  is_simulator boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (item_code, base_unit)
);

-- 単価の版。仕入／販売、仕入先、有効期間ごとに追記する。
-- 適用する版は「承認済み・valid_from が基準日以前」のうち valid_from が最も新しく、同日なら後に追記したもの。
CREATE TABLE item_prices (
  price_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  seq              bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  item_code        text NOT NULL,
  unit             text NOT NULL,
  price_type       text NOT NULL CHECK (price_type IN ('仕入', '販売')),
  supplier_code    text REFERENCES suppliers,
  unit_price       numeric NOT NULL CHECK (unit_price >= 0),
  currency         text NOT NULL DEFAULT 'JPY' CHECK (currency ~ '^[A-Z]{3}$'),
  valid_from       date NOT NULL,
  valid_until      date CHECK (valid_until >= valid_from),
  status           text NOT NULL CHECK (status IN ('approved', 'pending')),
  source           text NOT NULL CHECK (btrim(source) <> ''),
  reason           text NOT NULL CHECK (btrim(reason) <> ''),
  updated_on       date NOT NULL,
  checked_on       date,
  conditions       jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(conditions) = 'object'),
  confirmed_by     text NOT NULL REFERENCES staff,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (item_code, unit) REFERENCES items (item_code, base_unit)
);
CREATE INDEX item_prices_lookup ON item_prices (item_code, price_type, supplier_code, valid_from DESC, seq DESC);
CREATE TRIGGER item_prices_append_only
  BEFORE UPDATE OR DELETE ON item_prices
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- 塗料コードの正規化（メーカー表記の揺れ → 正規コード）。
CREATE TABLE paint_codes (
  maker           text NOT NULL DEFAULT '',
  raw_code        text NOT NULL CHECK (btrim(raw_code) <> ''),
  normalized_code text NOT NULL CHECK (btrim(normalized_code) <> ''),
  item_code       text REFERENCES items,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (maker, raw_code)
);

-- 単位換算。item_code が NULL の行はすべての品目に共通の換算。
CREATE TABLE unit_conversions (
  conversion_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_code     text REFERENCES items,
  from_unit     text NOT NULL,
  to_unit       text NOT NULL,
  factor        numeric NOT NULL CHECK (factor > 0),
  confirmed_by  text NOT NULL REFERENCES staff,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (from_unit <> to_unit),
  UNIQUE NULLS NOT DISTINCT (item_code, from_unit, to_unit)
);

-- 塗料の配合。配合を変えるときは新しい版を作る。
CREATE TABLE formulas (
  formula_code  text NOT NULL CHECK (btrim(formula_code) <> ''),
  version       integer NOT NULL CHECK (version >= 1),
  item_code     text REFERENCES items,
  base_quantity numeric NOT NULL CHECK (base_quantity > 0),
  base_unit     text NOT NULL,
  confirmed_by  text NOT NULL REFERENCES staff,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (formula_code, version)
);

CREATE TABLE formula_components (
  formula_code        text NOT NULL,
  version             integer NOT NULL,
  component_item_code text NOT NULL REFERENCES items,
  quantity            numeric NOT NULL CHECK (quantity > 0),
  unit                text NOT NULL,
  PRIMARY KEY (formula_code, version, component_item_code),
  FOREIGN KEY (formula_code, version) REFERENCES formulas ON DELETE CASCADE
);

-- CSV・Excel・PDF 取込。列の対応 → 取込バッチ → 候補行 → 人の承認 → 単価の版。
CREATE TABLE import_mappings (
  mapping_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_key text NOT NULL CHECK (btrim(source_key) <> ''),
  version    integer NOT NULL CHECK (version >= 1),
  field_map  jsonb NOT NULL CHECK (jsonb_typeof(field_map) = 'object'),
  created_by text REFERENCES staff,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_key, version)
);

CREATE TABLE import_batches (
  batch_id   text PRIMARY KEY CHECK (btrim(batch_id) <> ''),
  source     text NOT NULL,
  source_key text,
  mapping_id uuid REFERENCES import_mappings,
  created_by text REFERENCES staff,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- 候補行は承認か却下で一度だけ状態が変わる。承認した行は作った単価の版を指す。
CREATE TABLE import_candidates (
  candidate_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id         text NOT NULL REFERENCES import_batches ON DELETE CASCADE,
  row_number       integer NOT NULL CHECK (row_number >= 1),
  raw              jsonb NOT NULL,
  parsed           jsonb,
  issues           jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(issues) = 'array'),
  status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  decided_by       text REFERENCES staff,
  decided_at       timestamptz,
  price_version_id uuid REFERENCES item_prices,
  UNIQUE (batch_id, row_number),
  CHECK ((status = 'pending') = (decided_by IS NULL AND decided_at IS NULL)),
  CHECK ((status = 'approved') = (price_version_id IS NOT NULL))
);
