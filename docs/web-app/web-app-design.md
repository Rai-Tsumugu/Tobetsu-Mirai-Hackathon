# Webアプリの設計・開発環境

`src/web-app/` に置くハッカソン用Webアプリの技術構成、起動方法、Vercelへの接続方針を記録する。機能・画面の詳細はテーマとMVP決定後に追記する。

## 現在の前提

- ハッカソンのテーマ（A・B・C）とMVPは未決定。現時点では業務機能、実データ、外部APIを仮定しない。
- アプリのルートはリポジトリ内の `src/web-app/`。
- Next.js App Router、TypeScript、Tailwind CSSを使う。Next.jsはVercelで追加設定なしに扱える。
- データベースはNeonのPostgreSQLを採用し、`@neondatabase/serverless` でNext.jsのサーバー側から接続する。接続文字列は `DATABASE_URL` としてローカルの `.env.local` とVercelの環境変数に設定し、Gitには含めない。テーマ、保存データ、利用者、権限が決まってから必要なテーブルとアクセス制御を設計する。
- サーバー側処理が必要になった時点でNext.jsのRoute HandlerやServer Actionを検討する。認証、Google連携、生成AI、課金機能は要件確定まで導入しない。

## ディレクトリ

```text
src/web-app/
├── app/
│   ├── api/health/db/route.ts # Neon接続確認API
│   ├── globals.css            # グローバルスタイル
│   ├── layout.tsx             # 共通レイアウトとページメタデータ
│   └── page.tsx               # 初期画面
├── lib/db.ts                  # サーバー側Neon接続
├── public/                 # 静的アセット
├── .env.example            # DATABASE_URLの共有用ひな形（値は空）
├── package.json            # 開発・ビルド・起動スクリプト
└── package-lock.json       # npm依存関係の固定
```

## ローカル開発

Node.js 20.9以上を使用する。依存関係を導入し、`.env.example` を `.env.local` へコピーして `DATABASE_URL` を設定した後、次のコマンドを `src/web-app/` で実行する。

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

ブラウザーで `http://localhost:3000` を開く。確認用ビルドと本番モードの起動は次の通り。

Neon Project dashboardから取得した接続文字列を `src/web-app/.env.local` の `DATABASE_URL` に設定する。DB接続は `http://localhost:3000/api/health/db` で確認できる。未設定または接続失敗の場合はHTTP 503を返す。

```powershell
npm run build
npm run start
```

## Vercel接続

VercelでGitリポジトリをImportする場合、Root Directoryに `src/web-app` を指定する。Framework PresetはNext.js、Install CommandとBuild Commandは自動検出を使う。NeonのPostgreSQLはVercel Marketplace連携で接続し、接続情報はVercelの環境変数で管理する。Next.jsはVercel上で標準サポートされるため、機能要件が増えるまでは `vercel.json` を置かない。

ローカルのVercelプロジェクト紐付け（`.vercel/`）とデプロイは、利用アカウント・チームを確認してから行う。環境変数を追加するときは秘密値をGitへ入れず、`.env.example` にはキー名と説明だけを記載し、値はローカルの `.env.local` とVercelのProject Settingsに登録する。

## 機能設計で追記すること

テーマとMVPが決まったら、画面の目的と利用者、入力・結果・エラー状態、データの出典、外部サービス/API、環境変数、受け入れ条件、実演手順をこの文書へ追記する。模擬データと実データ、操作プロトタイプとアプリ実装、ローカル動作と公開環境の状態を区別して記録する。

## 参照

- [Next.js Installation](https://nextjs.org/docs/app/getting-started/installation)
- [Next.js on Vercel](https://vercel.com/docs/frameworks/full-stack/nextjs)
- [Neon on Vercel Marketplace](https://vercel.com/marketplace/neon)

## 現在の依存監査メモ

2026-10-11に `npm audit` を実行したところ、開発依存の `eslint-config-next` から辿られる `braces` 等にHigh advisoryが5件報告された。`npm audit --omit=dev` は脆弱性0件。本番依存には報告がない。`npm audit fix --force` は `eslint-config-next` を14系へ下げる提案となるため適用していない。開発依存の互換性を確認してから個別に更新する。

## Vercelプレビュー確認記録

2026-10-11、Vercel CLI 63.1.2から `--target=preview` を明示してデプロイ。Next.jsのリモートビルドが成功し、デプロイID `dpl_3uZtwKeScdLSUKtFWmnfbHjyxE8v` は `Ready`、targetは `preview`。Preview URLは <https://web-mji2saisr-adachitakato628-7410.vercel.app>。デプロイ保護はVercel Authenticationのため、表示にはVercelログインが必要。

初回のCLI操作では一時デプロイにログインが必要となり、Vercel CLIが初回デプロイを自動でproductionに割り当てた。Production URLは <https://web-app-hazel-omega.vercel.app>。こちらもVercel Authenticationで保護されている。続けてpreview targetを明示したデプロイを作成済み。productionデプロイの削除・変更は未実施。
