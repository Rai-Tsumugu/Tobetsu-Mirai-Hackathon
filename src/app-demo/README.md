# 整備見積ワークベンチ

要件書 `docs/app-demo/auto_repair_estimate_requirements.md` のPhase 1を実演する、外部API不要のSimulatorです。React / TypeScript / Tailwind CSS、FastAPI、SQLiteで構成しています。

## 起動

このREADMEがある `src/app-demo` で実行します。初回の依存関係インストールには通信が必要です。インストール後は外部通信・APIキーなしで動作します。Node.js 20.19以上または22.12以上、Python 3.10以上を使用してください。

```bash
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

ターミナル1（バックエンド）：

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8017
```

ターミナル2（フロントエンド）：

```bash
npm run dev
```

ブラウザで http://127.0.0.1:5177 を開きます。Viteが `/api` を8017番のFastAPIへ転送します。ポートが使用中の場合は既存プロセスを停止せず、ポートと `frontend/vite.config.ts` の転送先をそろえて変更してください。

ビルド後はFastAPIだけでも配信できます。`npm run build` を実行した後にバックエンドを起動し、http://127.0.0.1:8017 を開いてください。

## 3分のデモ手順

1. `FL4` または `シビック` で検索し、シビックFL4を選択。
2. 年式 `2023年` と `e:HEV（デモ仕様）` を選択。
3. `フロントブレーキパッド交換` を選択し、参考価格を比較。
4. 架空の4件を確認。Aは工賃5,000円（税抜）、Bは6,600円（税込→税抜6,000円）、Cは8,000円（税抜）。Dは総額のみ・別仕様のため比較対象外。
5. 初期の中央値6,000円から、Cを除外して5,500円へ変わることを確認。
6. 金額確定で工賃7,000円、部品代12,000円、調整理由を入力。消費税1,900円、税込合計20,900円を確認して保存。
7. ページを再読み込みし、`保存した見積もり` を開く。型式・年式・作業で検索し、当時の条件と採用根拠を確認。
8. 履歴から `この条件で見積もりを作る` で再利用。元の見積もりは更新せず、新規見積もりとして保存します。

車両の手入力・暫定登録、複数作業の同時選択、候補の全除外からの手入力も操作できます。工賃の調整・手入力には理由が必須です。部品代は手入力（初期値0円）です。

## データと計算

- 参考価格はすべて固定の架空データ。出所は `simulator`、参照日は `2026-10-11`、実在する出典URLは持ちません。
- 車種・型式の候補は要件書の例示に基づきます。年式の選択肢と仕様はデモ用で、メーカー資料との照合は未実施です。実在の販売年式範囲・適合情報として使えません。寸法・駆動方式・検証日時は未確認として保持します。
- 採用した工賃のみを税抜で中央値計算。税込工賃の税抜換算と中央値の円未満は切り捨て。工賃と部品代と総額を混ぜません。採用0件は算出値 `null`。
- 消費税は合算した税抜額の10%を切り捨て。サーバー側で候補、中央値、税額、合計を再計算し、フロントが送った合計は受け付けません。
- SQLiteは `demo.sqlite3` に自動作成。`REPAIR_DB_PATH` 環境変数で保存先を変更できます。車両、作業、見積明細、参照候補、採用関係を関連テーブルへ保存し、当時の条件をJSONスナップショットでも保持します。DBと依存環境はGit管理対象外です。
- 概算は正式な修理費用の保証ではありません。適合・条件・価格を担当者が確認してください。個人情報の入力は想定していません。

## 検証

```bash
npm run build
.venv/bin/python -m unittest discover -s backend -p 'test_*.py' -v
```

バックエンドのテストは一時SQLiteを使用し、検索・仕様の明示、決定的な候補、税込換算、採用除外、中央値、手入力、端数、改ざん拒否、複数作業、DB再オープン後の永続性・根拠関係を検証します。デモのDBは変更しません。

ブラウザ検証には追加でPlaywrightとChromiumを用意します。

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
```

フロントエンド・バックエンドを起動したうえで：

```bash
.venv/bin/python backend/check_browser.py
```

既存Chromeを使う場合は `PLAYWRIGHT_CHROMIUM_EXECUTABLE` にChrome実行ファイルの絶対パスを設定できます。

ブラウザ確認は実際のデモDBに1件の検証見積もりを保存します。専用DBで確認したい場合は、バックエンド起動時に `REPAIR_DB_PATH=/tmp/repair-check.sqlite3` を指定してください。スクリーンショットは `/tmp/repair-demo-desktop.png` と `/tmp/repair-demo-mobile.png` に出力します。

## 対象外

Live API、Gemini、VIN読み取り、メーカー諸元の照合、認証、PDF、工程重複の自動控除は未実装です。公開・本番運用用の構成ではありません。

実施した確認の詳細は [VERIFICATION.md](VERIFICATION.md) を参照してください。
