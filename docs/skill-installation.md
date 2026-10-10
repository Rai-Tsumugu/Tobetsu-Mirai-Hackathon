# 追加Skillの導入記録

## 導入したもの

プロジェクトで使う全Skillの一覧は [Skill一覧](skills.md) を参照する。

- [webapp-testing](../.agents/skills/webapp-testing/SKILL.md)：ローカルWebアプリの操作、結果確認、スクリーンショット、ログ確認。
- [frontend-design](../.agents/skills/frontend-design/SKILL.md)：画面の構成、文字、色、操作文言の設計。

導入元は [anthropics/skills](https://github.com/anthropics/skills)、参照コミットは `dbd4588f9e1033efb41dad4bef2f7947c8993d44`。Codexのskill-installer付属スクリプトで、上記2フォルダーをリポジトリの `.agents/skills/` に導入した。配布元のLICENSE.txtと、webapp-testingの補助スクリプト・例を含めて保存している。

初回コミット時に、webapp-testingのSKILL.mdにあった1行の末尾空白を除去した。指示の内容と付属スクリプトは変更していない。

両Skillはこのリポジトリでの自動選択対象となる。導入後、次のユーザーターンから利用可能。呼び出しを指定する場合は `$webapp-testing`、`$frontend-design` を使う。別のメンバーの環境ではSkillファイルと必要なツールの両方を用意する。

## このPCの実行環境

確認時点でNode.js `v24.14.1`、Python `3.11.9`、uvが利用可能。Playwright `1.63.0` はuvの管理環境に準備した。通常のPython環境に直接インストールしたものではない。

対応するChromiumとHeadless Shellを、このWindowsユーザーのPlaywrightブラウザキャッシュに導入した。Chromiumの確認時の版は `153.0.8010.12`。ブラウザ等のバイナリやPythonの依存パッケージはリポジトリに含めない。

再準備する場合、リポジトリのルートから実行する。

```powershell
uv run --no-project --with playwright==1.63.0 python -m playwright install chromium
```

Playwrightを使うPythonスクリプトも、同じ環境で実行する。次の `path/to/check.py` は、実際に作成した検証スクリプトのパスへ置き換える。

```powershell
uv run --no-project --with playwright==1.63.0 python path/to/check.py
```

起動補助スクリプトの使い方を確認する場合：

```powershell
uv run --no-project --with playwright==1.63.0 python .agents/skills/webapp-testing/scripts/with_server.py --help
```

アプリの起動コマンドとポートは、実装する技術と他の作業の状態を確認してから指定する。

参考：[Playwright公式導入手順](https://playwright.dev/python/docs/intro)

## 今回確認した範囲

- 新規2Skill：skill-creator付属の形式検証に合格。
- with_server.py：`--help` が正常終了。
- Playwright：Chromiumのheadless起動、例示HTMLへの文字入力、ボタン操作、結果のassertion、スクリーンショット作成が成功。
- 例示HTMLは依存ツールの確認用。ハッカソンのアプリや事業者データの動作検証ではない。
- 開発サーバーの起動・停止、Googleサービスとの接続、実アプリの受入確認は未実施。

## 次に用意するもの

現時点で追加必須のSkillはない。開発テーマと環境が決まった後に、必要なサービスに合わせて選ぶ。

1. Googleの具体的なサービス、3人の利用可能なアカウント、必要な権限、API利用・実行方法。現時点ではサービス未確定のため、クラウドの設定や課金設定は行っていない。
2. 事業者データの提供範囲・形式・利用条件。未提供ならデモ用の例示データを準備し、実データと区別する。
3. MVPの受入条件と実演手順。正常入力と代表的な失敗入力、結果の確認方法を先に決める。
4. チームの担当と、各端末での起動確認。今回のツール準備と確認は、このPCについてのもの。

導入時は初回コミット前のため、ローカルの未コミットファイルとして保存した。その後、ユーザーからここまでの内容のコミット・プッシュを依頼された。現在の保存・公開状態はGitの履歴とリモートの状態で確認する。
