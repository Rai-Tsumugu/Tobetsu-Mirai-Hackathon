# ハッカソンで使うSkill一覧

このファイルを、本リポジトリで使うSkillの一覧と利用手順の入口とする。UIはFigma Design、発表資料はFigma Slidesを使う。

## リポジトリに配置したSkill

以下の8つを `.agents/skills/` に配置している。リポジトリを共有するとSkillの指示・付属ファイルも共有できる。外部サービスへの接続や実行ツールは、各メンバーの環境で準備する。

| 優先・位置づけ | Skill | 使う場面 | 入力 | 主な成果物 |
|---|---|---|---|---|
| 1 | [tobetsu-interview](../.agents/skills/tobetsu-interview/SKILL.md) | ヒアリング準備・回答整理 | 共有メモ、事業者の回答 | 質問、根拠付きの課題一覧、未確認事項 |
| 2 | [tobetsu-mvp](../.agents/skills/tobetsu-mvp/SKILL.md) | テーマ選択・1日の開発範囲決定 | 課題、データ、環境、残り時間 | 最小仕様、3人の担当、受入条件、時間配分 |
| 3 | [github-collaboration](../.agents/skills/github-collaboration/SKILL.md) | ファイル編集・実装・引き継ぎ | Gitの状態、作業対象、担当 | 作業の分離、担当範囲の記録、コミット、レビューへの引き継ぎ |
| 4 | [tobetsu-business-data](../.agents/skills/tobetsu-business-data/SKILL.md) | A・B・Cのデータ処理 | 売上・出店・天候、原価・見積もり、文字起こし | 再計算可能な結果、会話記録、根拠と確認結果 |
| 5 | [tobetsu-prototype](../.agents/skills/tobetsu-prototype/SKILL.md) | FigmaでのUI設計、コード実装、実演確認 | MVP仕様、対象Figma画面、処理結果 | Figma DesignのUI、実アプリ、検証・実演手順 |
| 6 | [tobetsu-pitch](../.agents/skills/tobetsu-pitch/SKILL.md) | 約3分の発表準備 | 課題、試作、効果の根拠 | 発表原稿、Figma Slides、想定質疑、PoC案 |
| UI設計・実装を補助 | [frontend-design](../.agents/skills/frontend-design/SKILL.md) | 見た目・レイアウト・操作文言の検討 | 利用者、画面の目的、既存デザイン | 配色、文字、配置、UIの設計・改善。指定済みFigmaデザインを尊重する |
| 動作確認を補助 | [webapp-testing](../.agents/skills/webapp-testing/SKILL.md) | ローカルWebアプリの操作検証 | 起動方法、対象画面、期待結果 | Playwrightによる操作・結果確認、スクリーンショット、ログ |

優先順位は事前に準備する順序。Git協業は編集開始時に使い、発表の骨子は開発と並行して作る。

## Figmaの作業で使うSkill

次のSkillは、現在の環境のFigmaプラグインから提供されている。ファイルをこのリポジトリへコピーしたものではない。ほかのメンバーも同じ作業を行う場合は、Figmaプラグインと対象ファイルへのアクセスを確認する。

| Skill | 使用する場面 |
|---|---|
| `figma:figma-create-new-file` | 新しいFigma Design・Slidesファイルを作る前 |
| `figma:figma-use` | Figmaを読み書きするuse_figmaツールの呼び出し前 |
| `figma:figma-generate-design` | Figma Designに画面や複数の要素からなるUIを作るとき |
| `figma:figma-design-to-code` | Figmaの画面をコードへ実装するとき、get_design_contextの呼び出し前 |
| `figma:figma-use-slides` | Figma Slidesで発表資料を作成・編集するとき |

`tobetsu-prototype`と`tobetsu-pitch`が、作業内容に応じてこれらの専門Skillを使う手順を定めている。Figma上の操作プロトタイプ、実アプリの動作確認、Googleサービスとの実接続はそれぞれ記録する。

## 自動選択と明示的な呼び出し

Codexは依頼とSkillの説明が合う場合に、Skillを選んで指示を読む。本リポジトリの8つは自動選択の対象。Git協業はAGENTS.mdでも、実装・引き継ぎ・Issue／PR対応時に使うよう指定している。

すべてのSkillが毎回実行されたり、工程が順番に自動実行されたりする仕組みではない。使用するSkillを指定したい場合は、次のように依頼する。

| 依頼例 | Skill |
|---|---|
| `$tobetsu-interview 共有メモから、事業者に聞く質問を整理してください。` | 課題・質問整理 |
| `$tobetsu-mvp 課題P1を、3人で16時の発表に間に合う範囲へ絞ってください。` | 開発範囲の決定 |
| `$github-collaboration 今回の実装の作業範囲とGit作業を準備してください。` | Git協業 |
| `$tobetsu-business-data 売上CSVから、出店場所ごとの営業1時間当たり売上を比較してください。` | データ分析 |
| `$tobetsu-prototype MVP仕様からFigmaでUIを作り、その画面を実装・検証してください。` | UI・試作 |
| `$tobetsu-pitch 試作と検証結果から、約3分の原稿とFigma Slidesを作ってください。` | 発表 |
| `$frontend-design この入力画面の配置と操作文言を検討してください。` | 画面の設計補助 |
| `$webapp-testing 起動済みの試作で、入力から結果表示まで確認してください。` | ブラウザ検証 |

## 実行環境と準備状況

- **Figma**：UIと発表資料の作成先として決定済み。対象ファイルとメンバーのアクセスは、実際の作成時に確認する。現在の準備ではFigmaファイルやスライドをまだ作成していない。
- **Playwright**：このPCではuvの管理環境に `1.63.0` と対応Chromiumを準備し、起動・入力・クリック・結果確認・スクリーンショット作成が成功した。実アプリの検証はこれから行う。
- **Google**：使用する具体的なサービスと事前設定は未確認。サービスが決まった後に必要なツールやSkillを選ぶ。
- **事業者データ**：提供範囲・形式・利用条件を確認する。例示データと実データを区別する。

Skillの管理には、現在のCodex環境にある`skill-creator`と`skill-installer`を使える。表計算などの作業は、利用可能なSpreadsheet・Google SheetsのSkillを必要に応じて使う。これらも上の8つとは別に、実行環境側で提供される。

## 詳細と出所

- [ハッカソンの共有メモ](hackathon-memo.md)
- [開発・発表の進め方とSkill設計](hackathon-skills-design.md)
- [外部Skillの導入記録とPlaywrightの再実行手順](skill-installation.md)
- [CodexのSkill公式説明](https://learn.chatgpt.com/docs/build-skills)

`frontend-design`と`webapp-testing`はAnthropicの公開リポジトリから、コミット `dbd4588f9e1033efb41dad4bef2f7947c8993d44` の内容を導入した。各フォルダーにライセンスを含めている。ハッカソン専用の5つはこのプロジェクト向けに作成した指示中心のSkill。
