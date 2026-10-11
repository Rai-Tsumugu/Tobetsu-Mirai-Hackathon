-- 接続・数値表示の検証用（/db-check が読む）。業務データではない。
-- db/display-check.sql と同じ内容で、マイグレーションからも作れるようにする。
CREATE TABLE IF NOT EXISTS db_display_check (
  id integer PRIMARY KEY,
  label text NOT NULL,
  value integer NOT NULL,
  unit text NOT NULL
);

INSERT INTO db_display_check (id, label, value, unit)
VALUES (1, '表示確認用サンプル', 1234, '件')
ON CONFLICT (id) DO NOTHING;
