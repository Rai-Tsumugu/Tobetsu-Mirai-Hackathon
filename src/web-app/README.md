# 当別未来フェス Webアプリ

アプリ本体です。設計と未確定事項は [`web-app-design.md`](../../docs/web-app/web-app-design.md) を参照してください。

## 開発環境

Node.js 20.9以上が必要です。`src/web-app/` で次を実行します。

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

NeonのProject dashboardからPostgreSQL接続文字列を取得し、`.env.local` の `DATABASE_URL` に設定してください。このファイルはGitに追加しないでください。

ブラウザーで [http://localhost:3000](http://localhost:3000) を開きます。DB接続は [http://localhost:3000/api/health/db](http://localhost:3000/api/health/db) で確認できます。接続できると `{"status":"connected"}` を返します。

## コマンド

- `npm run dev` — 開発サーバー
- `npm run build` — 本番ビルド
- `npm run start` — ビルド済みアプリの起動
- `npm run lint` — ESLint
- `npm run typecheck` — 型チェック
- `npm test` — DB層の結合テスト（`TEST_DATABASE_URL` が必要）
- `npm run db:migrate` — マイグレーションの適用
- `npm run db:seed` — 架空のデモデータの投入

## データベース

NeonのPostgreSQLへ `@neondatabase/serverless` で接続します。接続文字列は `.env.local` とVercelの環境変数 `DATABASE_URL` に設定し、ソースコードへ書かないでください。

工数見積もり・部品材料単価・整備見積の3システムのデータを1つのスキーマにまとめています。テーブル設計、DB層（`lib/db/`）の使い方、マイグレーションの手順は [`db/README.md`](db/README.md) を参照してください。サーバー側コードからは `@/lib/db` の `withDatabase()` と各リポジトリ（`masters` / `manHours` / `items` / `quotes`）を使います。単発のクエリには従来どおり `getDatabase()` も使えます。

### 数値表示の検証

1. `npm run db:migrate`（または Neon SQL Editorで `db/display-check.sql`）を実行します。検証用テーブルに `1234` のサンプル値が1件入ります。
2. `npm run dev` を起動し、[http://localhost:3000/db-check](http://localhost:3000/db-check) を開きます。未接続なら画面確認用の `1,234 件` がサンプル表示されます。
3. `.env.local` を設定してSQLを実行後、Neonから読み込んだ `1,234 件` と `DATABASE CONNECTED` が表示されればDB読出し確認も完了です。

検証用データはアプリの業務データではありません。不要になったら `db_display_check` テーブルを削除できます。

## Vercel

GitリポジトリをImportするときはRoot Directoryを `src/web-app` に設定します。`.vercel/` の作成とデプロイは、アカウント・チーム選択後に行います。VercelのProject Settingsで `DATABASE_URL` をDevelopment、Preview、Productionの必要な環境へ登録してください。
