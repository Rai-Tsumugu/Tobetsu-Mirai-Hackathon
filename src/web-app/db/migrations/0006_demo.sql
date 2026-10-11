-- 整備見積デモ（src/app-demo）の保存先。元の SQLite（demo.sqlite3）の各テーブルに1つずつ対応する。
-- 元は1行を JSON 文字列で持ち、画面とAPIはその JSON をそのまま返していたので、同じ形を data 列に持つ。
-- キーの順序と元の文字列表現を保つため jsonb ではなく json にする。
-- 値はすべて架空のデモデータ。ほかのシステムのテーブルとは参照し合わない。

-- 車両。サンプル9車種（seed）と、画面から手入力した暫定登録。
-- 一覧は登録順（元の SQLite の rowid 順）に返すので、順序用の連番を持つ。
CREATE TABLE demo_vehicles (
  id         text PRIMARY KEY CHECK (btrim(id) <> ''),
  position   bigint GENERATED ALWAYS AS IDENTITY,
  data       json NOT NULL CHECK (json_typeof(data) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX demo_vehicles_position ON demo_vehicles (position);

-- 作業（ブレーキパッド交換など5件）。見積明細から参照する。
CREATE TABLE demo_repair_jobs (
  id   text PRIMARY KEY CHECK (btrim(id) <> ''),
  data json NOT NULL CHECK (json_typeof(data) = 'object')
);

-- 見積もり案件。ID（CASE-…）はサーバーで発行し、編集しても変えない。
-- created_at は data の created_at と同じ時刻（一覧の並べ替えに使う）。
CREATE TABLE demo_cases (
  id         text PRIMARY KEY CHECK (btrim(id) <> ''),
  created_at timestamptz NOT NULL,
  data       json NOT NULL CHECK (json_typeof(data) = 'object')
);
CREATE INDEX demo_cases_created ON demo_cases (created_at DESC, id DESC);

-- 保存した見積もり。保存した行は書き換えず、再保存は新しい行になる（案件の最新見積もりだけ差し替わる）。
-- search_text は履歴検索用（メーカー・車種・型式・年式・仕様・作業名を空白でつないだもの）。
CREATE TABLE demo_estimates (
  id          text PRIMARY KEY CHECK (btrim(id) <> ''),
  created_at  timestamptz NOT NULL,
  search_text text NOT NULL,
  data        json NOT NULL CHECK (json_typeof(data) = 'object')
);
CREATE INDEX demo_estimates_created ON demo_estimates (created_at DESC);

-- 見積もりの明細（作業ごと）。
CREATE TABLE demo_estimate_items (
  id            text PRIMARY KEY CHECK (btrim(id) <> ''),
  estimate_id   text NOT NULL REFERENCES demo_estimates (id),
  repair_job_id text NOT NULL REFERENCES demo_repair_jobs (id),
  data          json NOT NULL CHECK (json_typeof(data) = 'object')
);
CREATE INDEX demo_estimate_items_estimate ON demo_estimate_items (estimate_id);

-- 明細ごとに表示した参考価格の候補（採用・除外の両方）。
CREATE TABLE demo_price_sources (
  id      text PRIMARY KEY CHECK (btrim(id) <> ''),
  item_id text NOT NULL REFERENCES demo_estimate_items (id),
  data    json NOT NULL CHECK (json_typeof(data) = 'object')
);
CREATE INDEX demo_price_sources_item ON demo_price_sources (item_id);

-- 明細が採用した候補。
CREATE TABLE demo_selected_sources (
  item_id   text NOT NULL REFERENCES demo_estimate_items (id),
  source_id text NOT NULL REFERENCES demo_price_sources (id),
  PRIMARY KEY (item_id, source_id)
);

-- Gemini による工賃調査の結果。同じ条件（cache_key）は24時間再利用し、見積もり保存時に research_id で照合する。
-- サーバーレスでは関数のインスタンスが分かれるため、メモリではなくここに持つ。
CREATE TABLE demo_research_cache (
  id         text PRIMARY KEY CHECK (btrim(id) <> ''),
  cache_key  text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  data       json NOT NULL CHECK (json_typeof(data) = 'object')
);
CREATE INDEX demo_research_cache_key ON demo_research_cache (cache_key, created_at);

-- Gemini を最後に呼び出した時刻（1行だけ）。新しい検索は10秒以上の間隔を空ける。
-- 元はプロセス内の変数だったが、インスタンスをまたいで守るため DB に持つ。
CREATE TABLE demo_gemini_throttle (
  id              smallint PRIMARY KEY CHECK (id = 1),
  last_request_at timestamptz NOT NULL
);
