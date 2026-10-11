-- 工数見積もり（src/30-algorithm/integrated）のデータ。
-- 過去の実績・工場パラメータ・補正表・今回の入力・計算結果を分けて持つ。

-- 工場パラメータ（しきい値・加点表・状態の分岐・単価の経費など）。
-- 項目の種類が多く、エンジンが版ごと丸ごと読むので、版単位の jsonb で持つ。
CREATE TABLE shop_parameter_sets (
  version      text PRIMARY KEY CHECK (btrim(version) <> ''),
  params       jsonb NOT NULL CHECK (jsonb_typeof(params) = 'object'),
  is_current   boolean NOT NULL DEFAULT false,
  adopted_by   text REFERENCES staff,
  is_simulator boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX shop_parameter_sets_one_current ON shop_parameter_sets (is_current) WHERE is_current;

-- 補正表。v1 は整備士の暫定値、v2 以降は実績から作った候補。
-- 候補は自動で使わず、整備士が承認したときだけ adopted にする（同時に1つだけ）。
CREATE TABLE labor_rate_tables (
  rate_table_code text PRIMARY KEY CHECK (btrim(rate_table_code) <> ''),
  label           text,
  status          text NOT NULL CHECK (status IN ('candidate', 'adopted', 'retired')),
  derived_from    text,
  approved_by     text REFERENCES staff,
  approved_at     timestamptz,
  is_simulator    boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'adopted' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE UNIQUE INDEX labor_rate_tables_one_adopted ON labor_rate_tables (status) WHERE status = 'adopted';

CREATE TABLE labor_rate_entries (
  rate_table_code text NOT NULL REFERENCES labor_rate_tables ON DELETE CASCADE,
  operation_code  text NOT NULL REFERENCES operations,
  per_unit        text,
  hours_low       numeric NOT NULL CHECK (hours_low >= 0),
  hours_typical   numeric NOT NULL,
  hours_high      numeric NOT NULL,
  sample_count    integer CHECK (sample_count >= 0),
  PRIMARY KEY (rate_table_code, operation_code),
  CHECK (hours_low <= hours_typical AND hours_typical <= hours_high)
);

-- 自工場の作業実績。見積もり人時と実作業人時の差、原因タグを持つ。
CREATE TABLE work_records (
  record_code      text PRIMARY KEY CHECK (btrim(record_code) <> ''),
  vehicle_ref      text REFERENCES vehicles,
  performed_month  date NOT NULL CHECK (extract(day FROM performed_month) = 1),
  body_class       text,
  drive            text,
  age_years        integer CHECK (age_years >= 0),
  odometer_km      integer CHECK (odometer_km >= 0),
  brake_rust_grade smallint CHECK (brake_rust_grade BETWEEN 0 AND 3),
  estimated_hours  numeric NOT NULL CHECK (estimated_hours >= 0),
  actual_hours     numeric NOT NULL CHECK (actual_hours >= 0),
  is_same_vehicle  boolean NOT NULL DEFAULT false,
  is_simulator     boolean NOT NULL DEFAULT false,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE work_record_jobs (
  record_code text NOT NULL REFERENCES work_records ON DELETE CASCADE,
  job_code    text NOT NULL REFERENCES jobs,
  PRIMARY KEY (record_code, job_code)
);

-- 原因タグ（固着対応・ボルト折れ…）ごとの人時。count は本数・か所数（入庫1回単位のタグは NULL）。
CREATE TABLE work_record_tags (
  record_code text NOT NULL REFERENCES work_records ON DELETE CASCADE,
  tag         text NOT NULL CHECK (btrim(tag) <> ''),
  hours       numeric NOT NULL CHECK (hours >= 0),
  count       integer CHECK (count > 0),
  PRIMARY KEY (record_code, tag)
);

-- 工程ログ（作業中に工程ごとに記録した人数と時間）。
-- 待機（融解待ち・浸透待ちなど）は作業者を拘束しないので 0 人で記録し、人時には入れない。
CREATE TABLE process_logs (
  record_code text NOT NULL REFERENCES work_records ON DELETE CASCADE,
  seq         integer NOT NULL CHECK (seq >= 1),
  step        text NOT NULL,
  persons     integer NOT NULL CHECK (persons >= 0),
  hours       numeric NOT NULL CHECK (hours >= 0),
  is_wait     boolean NOT NULL DEFAULT false,
  PRIMARY KEY (record_code, seq),
  CHECK (is_wait OR persons >= 1)
);

-- 同一車両の過去の観察。車両マスタに登録がない過去分もあるので vehicle_key でも引ける。
CREATE TABLE vehicle_observations (
  observation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vehicle_key    text NOT NULL,
  vehicle_ref    text REFERENCES vehicles,
  record_code    text REFERENCES work_records,
  observed_month date NOT NULL CHECK (extract(day FROM observed_month) = 1),
  odometer_km    integer CHECK (odometer_km >= 0),
  observed       jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(observed) = 'object'),
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX vehicle_observations_key ON vehicle_observations (vehicle_key, observed_month);

-- 他工場の匿名実績（集計値だけ）。見積もりには直接足さず、参照幅として示す。
CREATE TABLE peer_benchmarks (
  shop_code      text NOT NULL,
  metric         text NOT NULL,
  operation_code text REFERENCES operations,
  median_hours   numeric NOT NULL CHECK (median_hours >= 0),
  sample_count   integer NOT NULL CHECK (sample_count >= 1),
  is_simulator   boolean NOT NULL DEFAULT false,
  PRIMARY KEY (shop_code, metric)
);

-- 今回の見積もり入力。観察項目は入れ子が深く、エンジンの入力形式そのままで持つ。
-- 電子車検証の使用者欄などの個人情報は inputs に入れない。
CREATE TABLE estimate_cases (
  case_id      text PRIMARY KEY CHECK (btrim(case_id) <> ''),
  vehicle_ref  text REFERENCES vehicles,
  intake_date  date NOT NULL,
  inputs       jsonb NOT NULL CHECK (jsonb_typeof(inputs) = 'object'),
  created_by   text REFERENCES staff,
  is_simulator boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE case_jobs (
  case_id  text NOT NULL REFERENCES estimate_cases ON DELETE CASCADE,
  job_code text NOT NULL REFERENCES jobs,
  PRIMARY KEY (case_id, job_code)
);

-- 工数エンジンの計算結果。どの版のパラメータ・補正表・基準工数で出したかを残す。
-- 経過時間（待機を含む）は表示用で、請求するのは人時だけ。
CREATE TABLE man_hour_estimates (
  estimate_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id               text NOT NULL REFERENCES estimate_cases,
  parameter_version     text NOT NULL REFERENCES shop_parameter_sets,
  rate_table_code       text NOT NULL REFERENCES labor_rate_tables,
  catalog_version       text,
  person_hours_low      numeric NOT NULL CHECK (person_hours_low >= 0),
  person_hours_typical  numeric NOT NULL,
  person_hours_high     numeric NOT NULL,
  elapsed_hours_low     numeric CHECK (elapsed_hours_low >= 0),
  elapsed_hours_typical numeric,
  elapsed_hours_high    numeric,
  result                jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
  created_by            text REFERENCES staff,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CHECK (person_hours_low <= person_hours_typical AND person_hours_typical <= person_hours_high),
  CHECK (elapsed_hours_low <= elapsed_hours_typical AND elapsed_hours_typical <= elapsed_hours_high)
);
CREATE INDEX man_hour_estimates_case ON man_hour_estimates (case_id, created_at);
CREATE TRIGGER man_hour_estimates_append_only
  BEFORE UPDATE OR DELETE ON man_hour_estimates
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
