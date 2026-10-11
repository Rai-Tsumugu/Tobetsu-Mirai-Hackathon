# DB 設計

工数見積もり（`src/30-algorithm/integrated`）、部品・材料単価（`src/auto_repair_items`）、整備見積（`src/auto_repair_quote`）の3システムのデータを、Neon PostgreSQL の1つのスキーマにまとめる。値はすべて各システムの Simulator と同じ架空値で、実在の価格・人時ではない。

3システムは、それぞれ SQLite に JSON を丸ごと保存していた（`records(namespace, payload)`、`quote_versions(snapshot)` など）。ここでは列に分けて制約を DB で検査し、システムをまたぐ参照（見積行 → 単価の版、見積の版 → 工数の計算結果）を外部キーでつなぐ。

## 方針

- **金額・数量・人時は `numeric`**。浮動小数点を通さず、丸めない。TypeScript 側でも文字列のまま扱う（`"1.5"`）。
- **帯は low / typical / high の3列**。`low <= typical <= high` を CHECK 制約で検査する。単一値の見積は3帯に同じ値を入れる。
- **記録は追記だけ**。単価の版、見積の版と行、顧客への説明、変更の記録、実使用量、工数の計算結果は、トリガーで UPDATE / DELETE を止める。訂正は新しい行（版）で記録する。
- **人の確認が要るところは DB でも止める**。たとえば次の場合は保存しない。
  - 確定の版に、担当者と帯の選択がない
  - 確定額を帯の合計から変えたのに、理由がない
  - 採用中の補正表が2つになる
  - 承認した取込候補に、単価の版がない
- **個人情報は持たない**。顧客・車両は匿名の参照ID（`customer_ref` / `vehicle_ref`）だけで扱う。
- 形が深く入れ子になっていて、エンジンがまとめて読むもの（工場パラメータ、今回の観察、見積の保存時スナップショット）は `jsonb` で持つ。

## テーブル

| 領域 | テーブル | 中身 |
|---|---|---|
| 共有 | `staff` | 確定・承認・記録をする担当者。確認者の列はここを参照する |
| | `customers` / `vehicles` | 匿名の顧客・車両。`vehicles.vehicle_key`（型式/初度登録年月）は自動で作る |
| | `operations` / `jobs` / `job_operations` | 工程、作業（基準人時）、作業に含まれる工程。工数と見積の両方が使う |
| 工数 | `shop_parameter_sets` | 工場パラメータの版（jsonb）。現行は1つ |
| | `labor_rate_tables` / `labor_rate_entries` | 補正表（v1 は暫定値、v2 以降は実績からの候補）。承認したものだけ採用する |
| | `work_records` / `work_record_jobs` / `work_record_tags` / `process_logs` | 作業実績、原因タグごとの人時、工程ログ（待機は 0 人） |
| | `vehicle_observations` / `peer_benchmarks` | 同一車両の過去の観察、他工場の匿名の集計値 |
| | `estimate_cases` / `case_jobs` / `man_hour_estimates` | 今回の入力と、どの版のパラメータ・補正表で出したかを含む計算結果 |
| 品目単価 | `suppliers` / `items` / `item_prices` | 品目と単価の版（仕入／販売・仕入先・有効期間・承認状態） |
| | `unit_conversions` / `paint_codes` / `formulas` / `formula_components` | 単位換算、塗料コードの正規化、配合（版） |
| | `import_mappings` / `import_batches` / `import_candidates` | 取込の列対応 → バッチ → 候補行 → 承認 |
| 見積 | `job_presets` | 承認済みの作業プリセット（版） |
| | `quotes` / `quote_versions` / `quote_lines` | 見積の見出し・版・行。両システムの見積をまとめ、行から単価の版を参照する |
| | `quote_communications` / `quote_change_events` / `quote_drafts` | 顧客への説明、再見積の記録、下書き（下書きだけ上書きできる） |
| | `material_usages` | 見積行に対する実使用量と差 |
| その他 | `db_display_check` | `/db-check` の表示確認用（業務データではない） |
| | `schema_migrations` | 適用済みのマイグレーション |

DDL は [`migrations/`](migrations/) にある。各テーブルの意味はファイル中のコメントに書いた。

## 旧データとの対応

| 旧（SQLite） | 新 |
|---|---|
| items `prices(payload)` | `items` + `item_prices` |
| items `records`: `quote_snapshot` | `quotes`（origin=items）+ `quote_versions` + `quote_lines` |
| items `records`: `item_usage` | `material_usages` |
| items `records`: `import_batch` / `staging_row` / `import_approval` / `import_mapping` | `import_batches` / `import_candidates` / `import_mappings` |
| items `records`: `formula` / `unit_conversion` / `paint_code` | `formulas` / `unit_conversions` / `paint_codes` |
| quote `quote_versions(snapshot)` | `quotes`（origin=quote）+ `quote_versions` + `quote_lines`。snapshot も残す |
| quote `communications` / `change_events` / `drafts` | `quote_communications` / `quote_change_events` / `quote_drafts` |
| quote `price_history` | `item_prices` |
| 工数 `data/*.json` | `shop_parameter_sets`、`labor_rate_*`、`work_*`、`process_logs`、`vehicle_observations`、`peer_benchmarks`、`jobs`、`estimate_cases` |

まだ移していないもの（items の `price_event`・`freshness_queue`・`supplier_price_selection`）は、単価の版の履歴と `priceInventory()` で代わりになるか、画面を作るときに決める。

## DB 層（`lib/db/`）

| ファイル | 役割 |
|---|---|
| `index.ts` | 入口。`import { withDatabase, items } from "@/lib/db"` |
| `client.ts` | `getDatabase()`（HTTP の単発クエリ）、`withDatabase()` / `withTransaction()`（1リクエストの間だけプールを開く） |
| `queryable.ts` | ドライバーに依存しない接続の型と `transaction()`（入れ子はセーブポイント） |
| `repositories/*.ts` | 領域ごとの読み書き。`masters` / `manHours` / `items` / `quotes` |
| `migrate.ts` / `seed.ts` | マイグレーションの適用、架空のデモデータ |

```ts
import { items, withDatabase } from "@/lib/db";

const price = await withDatabase((db) =>
  items.getEffectivePrice(db, "demo-paint", "販売", { asOf: "2026-10-11" }),
);
```

入力の不備は `DataValidationError`（画面にそのまま出せる日本語）で返す。0 や既定値で黙って置き換えない。

## コマンド

`src/web-app/` で実行する。接続先は環境変数 `DATABASE_URL`（なければ `.env.local`）。

```bash
npm run db:migrate   # 未適用のマイグレーションを適用（適用済みのファイルが書き換えられていたら止める）
npm run db:seed      # 架空のデモデータ（何度実行しても同じ状態）
npm run typecheck
TEST_DATABASE_URL=postgres://postgres@localhost:5432/postgres npm test
```

テストは `TEST_DATABASE_URL` のサーバーに使い捨てのデータベースを作って実行し、終わったら消す。`TEST_DATABASE_URL` がなければスキップする。

マイグレーションは追加していく。適用済みのファイルは書き換えず、変更は新しい番号のファイルで行う。
