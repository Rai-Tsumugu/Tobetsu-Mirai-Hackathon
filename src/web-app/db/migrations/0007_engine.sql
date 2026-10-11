-- 工数エンジン30案（src/auto_repair_engine）の保存先。元の SQLite（store.py）の表に対応する。
-- 他システムとは独立した engine_ 接頭辞の表で、既存のスキーマ（0002〜0005）には触れない。
-- 本文（body）は元の body_json に当たる。body_hash は正準 JSON の SHA-256 で、
-- 版の不変性と冪等キーの内容比較（同じキーで内容が変われば拒否）に使う。

-- 承認済みルールの版。同じ (engine_id, rule_version) の内容は変えられない（新しい版を作る）。
CREATE TABLE engine_rule_packs (
  engine_id      text NOT NULL CHECK (btrim(engine_id) <> ''),
  rule_version   text NOT NULL CHECK (btrim(rule_version) <> ''),
  body           jsonb NOT NULL CHECK (jsonb_typeof(body) = 'object'),
  body_hash      text NOT NULL,
  approved_by    text,
  effective_from text,
  status         text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (engine_id, rule_version)
);

-- 保存した見積（サーバーで再計算した結果）。
CREATE TABLE engine_estimates (
  estimate_id  text PRIMARY KEY CHECK (btrim(estimate_id) <> ''),
  scenario_id  text NOT NULL,
  engine_id    text NOT NULL,
  rule_version text NOT NULL,
  status       text NOT NULL,
  body         jsonb NOT NULL CHECK (jsonb_typeof(body) = 'object'),
  body_hash    text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  seq          bigint GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX engine_estimates_created ON engine_estimates (created_at DESC, seq DESC);

-- 冪等キー。同じキーで内容（body_hash）が違う保存は拒否する。
CREATE TABLE engine_estimate_idempotency (
  idempotency_key text PRIMARY KEY CHECK (btrim(idempotency_key) <> ''),
  estimate_id     text NOT NULL,
  body_hash       text NOT NULL
);

-- 観察イベント（追記のみ）。
CREATE TABLE engine_observation_events (
  event_id     text PRIMARY KEY CHECK (btrim(event_id) <> ''),
  scenario_id  text NOT NULL,
  operation_id text,
  event_type   text NOT NULL,
  body         jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  seq          bigint GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX engine_observation_events_scenario ON engine_observation_events (scenario_id, created_at, seq);

-- 実績の訂正（追記のみ。古い記録は更新しない）。
CREATE TABLE engine_estimate_revisions (
  revision_id            text PRIMARY KEY CHECK (btrim(revision_id) <> ''),
  estimate_id            text NOT NULL,
  supersedes_revision_id text,
  reason                 text NOT NULL CHECK (btrim(reason) <> ''),
  body                   jsonb NOT NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  seq                    bigint GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX engine_estimate_revisions_estimate ON engine_estimate_revisions (estimate_id, created_at, seq);

-- オフラインで作った版固定のスナップショット（E29）。版が違えば version_conflict のまま残す。
CREATE TABLE engine_offline_snapshots (
  snapshot_id text PRIMARY KEY CHECK (btrim(snapshot_id) <> ''),
  scenario_id text NOT NULL,
  rule_version text NOT NULL,
  body        jsonb NOT NULL,
  sync_status text NOT NULL DEFAULT 'pending',
  created_at  timestamptz NOT NULL DEFAULT now(),
  seq         bigint GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX engine_offline_snapshots_pending ON engine_offline_snapshots (sync_status, created_at, seq);

-- 見積・観察イベント・訂正は追記専用（既存の forbid_mutation を使う）。
CREATE TRIGGER engine_estimates_append_only BEFORE UPDATE OR DELETE ON engine_estimates
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER engine_estimate_idempotency_append_only BEFORE UPDATE OR DELETE ON engine_estimate_idempotency
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER engine_observation_events_append_only BEFORE UPDATE OR DELETE ON engine_observation_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER engine_estimate_revisions_append_only BEFORE UPDATE OR DELETE ON engine_estimate_revisions
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER engine_rule_packs_append_only BEFORE UPDATE OR DELETE ON engine_rule_packs
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
