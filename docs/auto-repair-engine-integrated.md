# 整備工賃エンジン統合 Simulator ガイド

## 統合版の使い方

このローカル Simulator の主な使い方は、**統合版を選び、架空の整備 scenario を検査・計算し、内訳と根拠を確認してから保存すること**です。実装は `src/auto_repair_engine/integrated.py`、API は `src/auto_repair_engine/api.py`、画面は `src/auto_repair_engine/web/index.html` にあります。初期選択は「統合版（推奨）」です。

統合版は次の機能を実際に組み合わせています。

| ID | 統合で担うこと | 現在の画面/API |
|---|---|---|
| E13 | schema と入力質問、入力後の再評価 | schema/evaluate は API。画面は架空 fixture と条件幅チェックを使う |
| E06 | 架空の承認済み基準版 | 統合版で既定使用。呼び出し側が E02 互換の承認 pack を渡す経路もある |
| E07 | 必須値検証、正規化、集計、監査 | 入力不足で停止し、人時と経過時間を分ける |
| E21 | 根拠付き追加工程の承認検査 | `rule_pack.evidence_additions` を渡す API 利用で有効。画面に追加工程の編集フォームはない |
| E18 | breakdown を再計算する trace tree | 統合版の適用行が labor を再現することを検証し、結果と一緒に返す |
| E28 | 保存時のサーバー再計算、冪等保存 | 画面/API。計算提案とサーバー再計算が違えば拒否し、同じ idempotency key の重複保存を防ぐ |
| E29 | 端末内 offline snapshot と版固定 | 画面は端末内キュー保存まで。版衝突の同期・選択フォームは未接続 |

リポジトリには E01〜E30 の比較用候補もあります。画面の「全方式を比較」は同じ架空入力を30案へ渡す評価操作です。日常の統合フローでは使わず、比較したい場合だけ実行します。

## 起動と確認

## 起動と確認

Python 3.9 以降を用意し、リポジトリのルートから次を実行します。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r src/auto_repair_engine/requirements.txt
PYTHONPATH=src python -m auto_repair_engine.api
```

ブラウザで `http://127.0.0.1:8000/` を開きます。API の `GET /api/health` はローカル simulator と架空データであることを返し、`GET /api/engines` は利用可能な engine ID 一覧を返します。`GET /api/fixture` は標準架空 fixture、`GET /api/fixture?approved_rotor=true` は条件幅を架空承認した fixture を返します。

保存先は macOS で `~/Library/Application Support/AutoRepairEngine/auto_repair_simulator.sqlite3`、その他の環境では `~/.local/share/auto-repair-engine/auto_repair_simulator.sqlite3` です。`AUTOREPAIR_DB` 環境変数または `create_app(db_path=...)` で保存先を変更できます。

## 画面での統合フロー

1. 初期選択「統合版（推奨）」のまま、架空 fixture を使います。「架空のローター固着条件幅を『人が承認済み』として試す」をオンにすると、fixture に事前記録された架空承認の条件幅を含めて計算します。実際の承認操作ではありません。
2. 「この方式で計算」を押し、person-hours / elapsed-hours の幅、unknowns、各 breakdown 行を確認します。「方式固有のtrace」を開くと、段階検証と E18 の計算根拠を確認できます。未確認必須値は null の範囲で停止します。
3. 保存する場合は確認者、確定する工賃、修正理由を入力し、「確認した工賃で見積もりを保存」を押します。サーバーが統合版を再計算し、結果の一致、人時範囲、時給を検証して SQLite に保存します。画面は冪等キーを付けて送信します。
4. 「保存済み見積もりを再読込」で保存記録を確認します。「端末内にoffline snapshotを保存」は scenario と rule_version を IndexedDB に保存します。版衝突の人手解決 UI と同期処理は現行画面に接続されていません。

画面には E13 の質問に沿った自由な scenario 編集欄や E21 追加工程の登録欄はありません。質問フォーム評価や根拠付き追加工程を含む統合入力は API から呼び出します。

## API と比較候補

統合入力向けの `GET /api/integrated/schema?job_id=front_brake_service` は E13 schema を返し、`POST /api/integrated/evaluate` は `{scenario_input, answers}` を受け取って適用済み入力、エラー、残質問、承認記録を返します。`POST /api/engines/integrated/calculate` は `{scenario_input, rule_pack?}` を受けます。`rule_pack` には任意で `approved_rule_pack`, `evidence_additions`, `client_proposal` を渡せます。

`POST /api/estimates` は `{engine_id: "integrated", scenario_input, idempotency_key, final_labor_amount, actor, adjustment_reason, client_proposal?}` を受け、統合版の再計算後に保存します。読み戻しは `GET /api/estimates` / `GET /api/estimates/{estimate_id}`、観察イベントは `POST /api/scenarios/{scenario_id}/events` です。`POST /api/compare` は E01〜E30 の候補比較専用です。必須観察・承認不足は `missing-required` または保存時409、形式不正は422になります。

## 数値と停止ルール

JSON は `scenario_input`, `rule_pack`, `engine_id`, `rule_version`, `operation_id`, `person_count`, `duration_hours` など snake_case の共通キーを使います。人時の `person_hours` と経過時間の `elapsed_hours` は low / typical / high の幅で扱います。待機は実作業の人時へ加えず、確認済みの待機時間だけを経過時間に加算します。洗浄など非請求扱いの実作業も人時からは除きません。必須値が未知なら範囲を null にして停止します。

架空の共通承認 fixture は person-hours が 1.88 / 2.13 / 2.38、elapsed-hours が 2.53 / 2.78 / 3.03 です。標準 fixture の rotor 関連性は未確認なので、承認済み fixture と同じ結果にはなりません。画面の金額確定では person-hours の全幅と labor_rate が必要です。

## テストと確認範囲

Python suite とブラウザ関数の Node test は次のコマンドで実行できます。

```sh
PYTHONPATH=src python3 -m unittest discover -s src -t src -p 'test_*.py'
node --experimental-strip-types --test src/auto_repair_engine/browser.test.mjs
```

ブラウザ関数の型付きソース実行には Node 24 の native type stripping が使われます。UI 手動操作はこのガイド作成時点で実施確認していません。実データ、価格 API、実車画像・音声、外部 AI は接続していません。架空 fixture の計算一致は工場の実績値や見積精度の検証を意味しません。
