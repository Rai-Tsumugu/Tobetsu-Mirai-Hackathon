-- 3システム（工数・品目単価・見積）が共有するもの。
-- 個人情報は持たない。顧客・車両は匿名の参照IDだけで扱う。

-- 追記専用テーブルの UPDATE / DELETE を止める。訂正は新しい行（版）で記録する。
CREATE FUNCTION forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% は追記専用です。訂正は新しい行で記録してください', TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END
$$;

-- 確定・承認・記録を行う担当者。確認者の列はすべてここを参照する。
CREATE TABLE staff (
  staff_code   text PRIMARY KEY CHECK (btrim(staff_code) <> ''),
  display_name text NOT NULL CHECK (btrim(display_name) <> ''),
  is_simulator boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE customers (
  customer_ref text PRIMARY KEY CHECK (btrim(customer_ref) <> ''),
  is_simulator boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- vehicle_key は工数エンジンが同一車両の照合に使うキー（型式/初度登録年月）。
-- 手入力させず、電子車検証の型式と初度登録年月から作る。
CREATE TABLE vehicles (
  vehicle_ref            text PRIMARY KEY CHECK (btrim(vehicle_ref) <> ''),
  model_code             text,
  first_registered_month date CHECK (extract(day FROM first_registered_month) = 1),
  vehicle_key            text GENERATED ALWAYS AS (
    model_code || '/' || (extract(year FROM first_registered_month))::int::text
      || '-' || lpad((extract(month FROM first_registered_month))::int::text, 2, '0')
  ) STORED,
  model_name             text,
  drive                  text,
  body_class             text,
  attributes             jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(attributes) = 'object'),
  is_simulator           boolean NOT NULL DEFAULT false,
  created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX vehicles_vehicle_key ON vehicles (vehicle_key);

-- 工程（リフトアップ、固着対応など）。基準工数・補正表・実績タグが共通で参照する。
CREATE TABLE operations (
  operation_code text PRIMARY KEY CHECK (btrim(operation_code) <> ''),
  name           text NOT NULL,
  per_unit       text
);

-- 作業。工数エンジンの基準工数（J1, J2…）と見積のプリセット（JOB-…）を同じ表で持つ。
-- 見積だけで使う作業は基準人時を持たないので base_labor_hours は任意。
CREATE TABLE jobs (
  job_code         text PRIMARY KEY CHECK (btrim(job_code) <> ''),
  name             text NOT NULL,
  base_labor_hours numeric CHECK (base_labor_hours >= 0),
  basis_unit       text,
  basis_source     text,
  catalog_version  text,
  work_areas       text[] NOT NULL DEFAULT '{}',
  attributes       jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(attributes) = 'object'),
  is_simulator     boolean NOT NULL DEFAULT false,
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- 作業に含まれる工程。shared=true の工程（リフト等）は複数作業で1回だけ計上する。
CREATE TABLE job_operations (
  job_code       text NOT NULL REFERENCES jobs ON DELETE CASCADE,
  operation_code text NOT NULL REFERENCES operations,
  position       integer NOT NULL,
  hours          numeric NOT NULL CHECK (hours >= 0),
  shared         boolean NOT NULL DEFAULT false,
  PRIMARY KEY (job_code, operation_code),
  UNIQUE (job_code, position)
);
