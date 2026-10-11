# 当別未来フェス Webアプリ

アプリ本体です。設計と未確定事項は [`docs/web-app-design.md`](../../docs/web-app-design.md) を参照してください。

## 開発環境

Node.js 20.9以上が必要です。`src/web-app/` で次を実行します。

```bash
npm install
npm run dev
```

ブラウザーで [http://localhost:3000](http://localhost:3000) を開きます。

## コマンド

- `npm run dev` — 開発サーバー
- `npm run build` — 本番ビルド
- `npm run start` — ビルド済みアプリの起動
- `npm run lint` — ESLint

## Vercel

GitリポジトリをImportするときはRoot Directoryを `src/web-app` に設定します。`.vercel/` の作成とデプロイは、アカウント・チーム選択後に行います。

環境変数が必要になった場合は `.env.example` にキー名だけを記録し、値は `.env.local` またはVercel Project Settingsへ登録します。
