# M01–M30 共通実装契約

実装所有範囲は `src/auto_repair_items/`。ユーザー承認により既存の
`src/auto_repair_engine/` 担当と分離する。既存共同作業ヘルパーは確保範囲の
縮小コマンドを持たないため、既存の広い `src/` 記録は変更せず、本範囲の
明示的な引き継ぎと個別ファイルのステージングで調整する。他領域を編集しない。

- 全変数・関数・JSONキーは `snake_case`。IDは `item_id` / `price_version_id`。
- 各案は `mXX.py`。公開API `run(payload: dict, store: Store) -> dict`。
- `SPEC = {'idea_id':'MXX','title':日本語名,'description':日本語説明,'defaults':dict}`。
  defaultsはブラウザフォームとデモに使う、必ず架空で1回実行できるデータ。
- 共通 `core.py`: `Store`, `ValidationError`, `decimal_value`, `text_value`,
  `date_value`, `approved_by`, `validate_item`, `demo_item`, `DEMO_DATE`。
- `Store.put(namespace, record, record_id=None)` は追記し、`records(namespace, record_id=None)`
  は一覧、`latest(namespace, record_id)` は最終版。record_idを返す。
- `Store.add_price(item, confirmed_by, supplier_id='', valid_from=None, valid_until=None,
  status='approved', reason='初回登録', **metadata)` は新しい価格版を返す。
  `price_versions(item_id=None, price_type=None, supplier_id=None)` は履歴。
  `get_price(item_id, price_type='販売', as_of=DEMO_DATE, supplier_id=None, unit=None)` は
  承認・期限・単位を検証し価格版を返す。返り値の `item` は8項目の共通契約。
- `with store.transaction():` で複数保存を原子的に行う。保存値にDecimalは使用可。
- 数値は `Decimal`。保存・JSONは十進文字列。float演算・暗黙丸めは禁止。
- 人の確定は `confirmed_by`、変更理由は `reason`。価格未確認を0円にしない。
- すべての自動候補は提案。外部通信、実OCR、実PDF抽出はSimulatorで代替し
  `simulator` / 未接続 / 架空値を明示。Excelは可能なら実XLSX固定1シート読取。
- 未確認の価格、単位、期限、条件は `ValidationError` で停止。指数から価格更新禁止。
- 個人情報はホワイトリストの品目情報だけ保存。原伝票全文は保存しない。
- 各案の所有ファイルは `mXX.py` と `tests/test_mXX.py` のみ。他案・coreは変更禁止。
- テスト実行: `PYTHONPATH=src python3 -m unittest discover -s src/auto_repair_items/tests -v`。
- reviewerは `reviews/mXX_check1.md` または `reviews/mXX_check2.md` のみ編集可。
  読み取りで検査・実行し、不具合は実装担当へ返す。合格前にPASSと記載しない。

## M23 / M27 / M30 見積内部参照

- namespace `quote_snapshot`、record_id `quote_id`。
- snapshot: `quote_id`, `lines`, `confirmed_by`, `created_at`。
- line: `quote_line_id`, `item_id`, `name`, `category`, `quantity`, `unit`,
  `unit_price_snapshot`, `price_type`, `price_version_id`, `source_snapshot`,
  `updated_at`, `supplier_id`, `conditions`, `line_total`。
- `conditions` は取引条件のみ。推奨キー: `freight_basis`, `freight_amount`,
  `tax_basis`, `delivery_days`, `currency`, `transaction_conditions`。
  `checked_at` 等の鮮度メタデータは価格比較の取引条件に混ぜない。
- `core.price_conditions(version)` で条件表記を統一する。仕入先レコードの
  flatメタデータと `metadata.conditions` にある同じ条件を共通化し、
  `currency` は明示的にJPYを保持する。比較するsnapshot側も同じ正規化を使う。
- M23実使用量は `item_usage` namespaceへ、過去の見積行を変更しない。
- M27は比較結果だけを返し、見積スナップショットを書き換えない。
- M30は同じ `quote_id` の保存を拒否し、価格・数量・版・出所を固定する。
