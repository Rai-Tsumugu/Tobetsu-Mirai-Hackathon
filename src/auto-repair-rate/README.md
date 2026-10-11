# Auto Repair Rate Simulator

③時間単価の共通スケルトンです。React + TypeScript のスマートフォン向け画面、FastAPI + Pydantic API、SQLite追記履歴で構成し、外部ネットワークに接続しません。

## 共通契約

- APIのフィールド名はsnake_case。`RateProposal`、`RateCalculation`、`RateVersion` がR01〜R30共通の入出力です。
- 期間レートの分母は `period_total_person_hours * u_period` のみです。案件専用の `job_person_hours` low/typical/high と `hours_basis` は別に扱います。`total_person_hours` 基準では `job_billable_ratio` を案件時間に一度だけ適用し、`billable_person_hours` 基準ではそのまま通します。案件比率は期間レート分母に入りません。案件基準や必要な比率が不明なら案件時間だけを出しません。
- 必須費用、時間、割合が不明、または分母が0なら `candidate_yen_per_person_hour` はnullで `blocked`。不明値は0に補完しません。
- `labor_rate` は明示的な人の承認後だけ存在し、形は `{ "yen_per_person_hour", "effective_from", "basis": [{"label", "value", "unit"}] }` です。候補値自体は承認前でも `calculation` に表示できます。
- `RateVersion` とSQLite提案・承認・履歴行は `rate_scope` と `rate_type` を `labor_rate` の外側に持ちます。`rate_scope` は `factory_standard` または `category:<id>`、`season:<id>`、`customer:<id>`、`worker:<pseudonymous-id>` のみです。`rate_type` は `customer` / `internal` です。これらの列は履歴の範囲と用途を示し、標準 `labor_rate` の形を変えません。
- 承認日や有効期間は同じ `rate_scope` の顧客向け単価内でだけ競合判定します。`internal` 候補は共通の `labor_rate` として承認できません。工場標準として見積に使う場合は `factory_standard/customer` の承認済み値だけを参照します。冬季やカテゴリ単価はそれぞれの明示スコープに分離します。
- 旧SQLiteデータベースにはスコープ列を `ALTER TABLE ADD COLUMN` で追加します。既存の行は `factory_standard/customer` として読み取られ、既存の承認履歴・`labor_rate` の形は維持します。
- 部品・材料など別請求費用は `billing_class=separately_billed_item` かつ `included_in_labor_pool=false` として保存し、画面で除外表示します。根拠・出所・記録日、状態、算定条件、承認者・理由を保存します。
- `proposals`、`approvals` と `labor_rate_history` を分けています。提案と承認履歴は追加保存し、適用日を遡った重複や同一提案の再承認を拒否します。レート履歴は更新しません。有効終了日は次の適用開始日から読み出し時に導出します。
- R方式は `backend/modules/R01.py` など独立ファイルに置き、`MODULE_ID` とFastAPI `router` を公開すると `/api/auto-repair-rate/{MODULE_ID}` へ自動登録されます。ルーターのAPI関数は入力値からそのR方式の計算関数をサーバー内で呼び、共通型 `RateCalculation` を受け取って `store.create_proposal(proposal, module_calculation=calculation)` で保存します。クライアントから計算済み候補を受け取るエンドポイントは作らないでください。共通モデルと計算は `backend/models.py`、`backend/shared.py` にあります。

## API

- `POST /api/auto-repair-rate/proposals` — `{ "proposal": RateProposal }` を保存し候補または停止理由を返す
- `GET /api/auto-repair-rate/proposals/{proposal_id}` — 提案・承認結果を取得
- `POST /api/auto-repair-rate/proposals/{proposal_id}/approval` — `approved_yen_per_person_hour`, `effective_from`, `approved_by`, `approval_reason` を受け、人の承認を記録
- `GET /api/auto-repair-rate/labor-rates` — 有効日順の追記単価履歴
- `GET /api/auto-repair-rate/labor-rates/active?as_of=YYYY-MM-DD` — 指定日現在の承認済み `factory_standard/customer` 単価。未来日も `as_of` で指定できます。
- `GET /api/auto-repair-rate/modules` — 登録されたR方式一覧

SQLiteの保存先は `AUTO_REPAIR_RATE_DB` で変更できます。画面の初期値はすべて明示的に架空デモ値として表示しています。実工場の値やレビュー実績を含みません。

## 起動

このフォルダで初回に `python3 -m venv .venv`、次に `.venv/bin/python -m pip install -r requirements.txt` を実行し、`.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000` でAPIを起動します。別のターミナルで `cd frontend && npm install && npm run dev` を起動します。Viteは `/api` だけをローカルFastAPIへ転送します。API/SQLiteの契約テストはこのフォルダ直下から `.venv/bin/python -m pytest -s backend/tests`、UI型確認は `cd frontend && npm run build` で実行します。
