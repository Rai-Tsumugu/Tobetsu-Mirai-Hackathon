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

## データベース

NeonのPostgreSQLへ `@neondatabase/serverless` で接続します。サーバー側コードから `lib/db.ts` の `getDatabase()` を使ってください。接続文字列は `.env.local` とVercelの環境変数 `DATABASE_URL` に設定し、ソースコードへ書かないでください。テーブル構成はアプリの機能要件が決まってから追加します。

## Vercel

GitリポジトリをImportするときはRoot Directoryを `src/web-app` に設定します。`.vercel/` の作成とデプロイは、アカウント・チーム選択後に行います。VercelのProject Settingsで `DATABASE_URL` をDevelopment、Preview、Productionの必要な環境へ登録してください。
