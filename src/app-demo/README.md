# 整備見積ワークベンチ

要件書 `docs/app-demo/auto_repair_estimate_requirements.md` のPhase 1を実演する、外部API不要のSimulatorと、参考金額の比較でGeminiを使う工賃調査モードのデモです。React / TypeScript / Tailwind CSS、FastAPI、SQLiteで構成しています。

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

VIN読み取り、網羅的な車両マスター、メーカー資料の人による検証、認証、PDF、工程重複の自動控除は未実装です。公開・本番運用用の構成ではありません。

実施した確認の詳細は [VERIFICATION.md](VERIFICATION.md) を参照してください。

## GeminiのWeb検索（無料枠プロジェクト）

2026-10-11、差し替えたキーで `gemini-2.5-flash` のGoogle検索に成功しました。旧キーでは同じモデルが404でした。無料枠の有無と、そのプロジェクトがモデルを利用できるかは別の条件です。
1. Google AI Studioで**無料枠のプロジェクト**のAPIキーを発行します。アプリは請求先やプランを変更しません。既に有料プランのプロジェクトのキーでは、そのプロジェクトの料金条件が適用されます。
2. このディレクトリに `.env` を作成して次の1行を記載します。既存のファイルは上書きせず編集してください。

```dotenv
GEMINI_API_KEY=手元のAPIキー
```

`.env` はGit管理から除外します。フロントエンドへキーを渡しません。

3. `.venv/bin/python -m pip install -r backend/requirements.txt` で依存関係を入れ、バックエンドを再起動します。`.env` の変更は再起動後に反映されます。
4. 車検証を確認し、メーカー・車種・型式・年式・仕様を手入力します。登録済み車両の検索も利用できます。型式をAIで特定する機能・APIは廃止しました。
5. 作業を選び、「AIで工賃を調査（Gemini）」を選びます。
6. 「参考価格を比較する」で入力した車両・作業条件をもとに工賃を検索します。出典を開いて金額・条件を確認した候補だけを採用し、工賃・部品代を調整して保存します。

### 呼び出しと根拠の扱い

- モデルは `gemini-2.5-flash` 固定。Google SearchとURL Contextで調査し、別の呼び出しでJSONへ構造化します。通常は1操作で最大2回の生成呼び出し（検索は最初の1回）。500/502/503/504の一時障害だけ、1秒後に1回再試行します。429や400/404、通信タイムアウトは自動再試行せず、有料モデルへも切り替えません。
- 同一条件の調査はSQLiteに24時間キャッシュ。検索ボタンを押した場合だけ外部通信します。新しい検索は10秒以上の間隔を必要とします。
- APIが返した参照URLと一致する候補だけを保持し、根拠の短い抜粋を表示。AI抽出は人による検証前なので `verified=false`、車両の `verified_at=null` のまま保存します。検索連携が返す関連検索候補も隔離したiframeで表示します。
- 車両情報は利用者が入力・確認します。登録済み検索はSQLite内だけで行い、AIや外部APIには問い合わせません。以前のAI車両データ・見積もり履歴は保持します。
- 工賃・税区分・税込の場合の税率・車両と作業の一致条件が確認できる候補だけを中央値計算に使います。税率を現在の10%と推定して過去の税込料金を逆算しません。候補は初期状態ですべて除外し、利用者が出典を確認して採用します。
- 検索結果が0件でも架空データを補いません。工賃の手入力・調整理由を入力して続行できます。部品代は引き続き手入力です。
- Web調査IDと条件をサーバーで照合して保存し、履歴の根拠や採用状況を復元します。既存のSimulator履歴も読み出せます。テーブル追加だけで既存データを保持します。
- キー未設定は503、呼び出し制限は429、通信・回答形式の不具合は502として画面で案内します。無料枠のプロジェクトの呼び出し制限はGoogle AI Studioで確認してください。

公式資料：[料金](https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash)、[検索連携](https://ai.google.dev/gemini-api/docs/generate-content/google-search)、[URL Context](https://ai.google.dev/gemini-api/docs/generate-content/url-context)。

### Geminiを呼ばないブラウザ検証

`backend/check_live_browser.py --mock-server` は検証専用の模擬Google応答を返します。本番アプリには模擬応答を組み込みません。Playwright、Chromium、ビルドが必要です。

このリポジトリのルートから：

```bash
cd src/app-demo
npm run build
.venv/bin/python ../../.agents/skills/webapp-testing/scripts/with_server.py --server 'REPAIR_DB_PATH=/tmp/repair-live-check.sqlite3 .venv/bin/python backend/check_live_browser.py --mock-server' --port 8019 -- .venv/bin/python backend/check_live_browser.py
```

8019番と専用の一時DBを使います。車両検索、諸元・出典表示、不明な税区分と別仕様の除外、候補の採用、保存・再表示・再利用、スマートフォン幅を確認します。
