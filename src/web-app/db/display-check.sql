CREATE TABLE IF NOT EXISTS db_display_check (
  id integer PRIMARY KEY,
  label text NOT NULL,
  value integer NOT NULL,
  unit text NOT NULL
);

INSERT INTO db_display_check (id, label, value, unit)
VALUES (1, '表示確認用サンプル', 1234, '件')
ON CONFLICT (id) DO UPDATE
SET label = EXCLUDED.label,
    value = EXCLUDED.value,
    unit = EXCLUDED.unit;
