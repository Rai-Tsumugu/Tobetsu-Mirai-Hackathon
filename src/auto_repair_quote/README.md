# 整備見積 統合版

30案のうち、設計書が推奨する **P01 + P07 + P14** を中心に、価格検証、3帯比較、担当者確定、電話説明、保存履歴、印刷をつないだSimulatorです。全ての価格・税設定・匿名IDは架空です。

## 起動

リポジトリのルートから実行します。Python 3.10以上、Node.js 20.19以上を使います。

```sh
python3 -m venv src/auto_repair_quote/.venv
src/auto_repair_quote/.venv/bin/pip install -r src/auto_repair_quote/requirements.lock
npm ci --prefix src/auto_repair_quote
npm run build --prefix src/auto_repair_quote
src/auto_repair_quote/.venv/bin/python -m uvicorn src.auto_repair_quote.api:app --host 127.0.0.1 --port 8879
```

ブラウザで <http://127.0.0.1:8879> を開きます。APIと画面を同じサーバーから配信します。SQLiteはこのフォルダの `quotes.sqlite3` に保存し、Git管理から除外します。別のDBを使う場合は `AUTO_REPAIR_QUOTE_DB` を指定してください。

## 採用した機能

| 使う場面 | 採用案 | 統合した動作 |
| --- | --- | --- |
| 作業の選択 | P19・P20・P22 | 承認済みプリセットを検索し、不足条件を確認 |
| 金額計算 | P01〜P07・P09 | 請求人時と品目を同じ帯で積算、掛率・値引き・最低工賃・税を検証 |
| 比較と判断 | P08・P10・P11・P14・P23 | 3帯と根拠を表示し、人が帯と確定額を選択 |
| 保存と説明 | P12・P18・P27・P28・P30 | 確定額を固定し、電話要約・伝達記録・印刷・JSON出力へ共有 |
| 中断・再見積 | P15・P17・P21・P26・P29 | 下書き再開、旧版保持、差分と追加変更の了承記録 |

電話概算（P16）、価格比較（P24）、複数作業の統合比較（P25）は補助機能として保持します。複数見積の重複費目は自動控除せず、承認した候補だけを対象にします。

`workflow.py` が統合処理、`main.tsx` が統合画面です。`p01.py`〜`p30.py` は各案の独立モジュールとして保持しています。API・Python・画面の独自変数は `snake_case`、帯は `low / typical / high` を共通で使います。

## デモの操作

1. 作業を選び、人時・時間単価を確認して試算します。
2. 3帯の内訳と根拠を比べ、帯を明示的に選びます。自動で標準帯を選びません。
3. 担当者IDを確認して保存します。金額を上書きする場合は理由が必要です。
4. 顧客向け説明を読み、伝えた金額・条件を記録します。見積票は印刷またはJSONで出力できます。
5. 条件変更は新しい版として作ります。保存済みの旧版と通信記録は残ります。

「下書き・履歴・追加変更」の補助パネルで中断・再開と過去版を扱います。保存版を開くと、その版の入力・価格根拠を表示します。入力を変更すると以前の試算・選択・説明を解除し、新しい試算を求めます。

## 統合API

- `POST /api/workflow/preview`：`{"inputs": ...}` を受け、一度の計算結果から `quote / summary / band_comparison / questions / can_confirm / next_action` を生成します。保存は行いません。
- `POST /api/quotes/confirm`：サーバーで再計算・担当者確認後、入力と結果の確定スナップショットを保存します。
- `GET /api/workflow/{quote_id}?quote_version=1`：保存された指定版から説明・帳票・その版だけの通信/変更記録を返します。価格を再計算しません。

見積保存と通信/変更記録の複合処理はトランザクションで実行し、検証が失敗した場合は途中の新規保存も取り消します。

## 検証

```sh
src/auto_repair_quote/.venv/bin/python -m src.auto_repair_quote.run_tests
npm run build --prefix src/auto_repair_quote
```

`test_workflow.py` は入力不足、手動確定額の説明・通信・帳票一致、旧版保持、版別イベント分離、失敗時の保存取り消しを確認します。個別案のテストとAPIテストも同じコマンドで実行します。

画面操作の確認は `requirements-dev.txt` のPlaywrightを使います。

```sh
src/auto_repair_quote/.venv/bin/pip install -r src/auto_repair_quote/requirements-dev.txt
src/auto_repair_quote/.venv/bin/python -m playwright install chromium
```

デモサーバー起動後、次のコマンドで選択・手動額・通信・JSON・印刷・新版・旧版・電話概算・入力不足・スマホ表示・通信失敗からの復帰を検証できます。架空の見積を保存するため、テスト専用DBを指定して起動してください。

```sh
AUTO_REPAIR_QUOTE_DB=src/auto_repair_quote/browser_test.sqlite3 src/auto_repair_quote/.venv/bin/python -m uvicorn src.auto_repair_quote.api:app --host 127.0.0.1 --port 8879
# 別のターミナルで実行
src/auto_repair_quote/.venv/bin/python src/auto_repair_quote/smoke_browser.py --channel chromium
```

インストール済みGoogle Chromeを使う場合は `--channel chrome` を指定します。スクリーンショット・PDF・JSONは一時フォルダへ出力します。

## 適用範囲

実価格の取得、外部システム接続、認証、実車での検証は含みません。人時エンジン・時間単価・価格マスタは現在、共通契約に沿った架空fixtureを使用しています。`labor_rate.basis` は適用する円/人時と一致する根拠を受け取り、原価の集計自体は別システムの責務です。

帳票は見積票です。手動確定額の税配分は未確認として表示し、請求書として再計算しません。氏名・電話番号・音声は入力せず、匿名IDを使います。既知の電話番号・メール形式は拒否しますが、自由記述の完全な匿名化は保証しません。
