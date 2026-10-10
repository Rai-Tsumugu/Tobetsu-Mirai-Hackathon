# ハッカソンのSkill一覧・設計・導入手順

本リポジトリのSkill一覧、開発・発表の進め方、導入記録と環境の再準備手順をこの1ファイルにまとめる。UIはFigma Design、発表資料はFigma Slidesを使う。

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

## 開発・発表の進め方

チーム共有メモを基にした準備案。イベントの最新案内や事業者本人の回答が得られたら、当日の判断を更新する。目的は3人で課題を選び、使える試作を作り、約3分で価値と確認状況を伝えること。

1. **課題整理**：tobetsu-interviewで質問と課題仮説を用意し、事業者の回答と未確認事項を整理する。
2. **MVP決定**：tobetsu-mvpで入力・出力・3人の担当・受入条件・時間配分・代替デモを決める。
3. **作業準備**：github-collaborationでGitの状態と担当ファイルを確認し、作業を分離する。
4. **データ処理**：tobetsu-business-dataで入力を検証し、根拠を追える計算・分析・会話記録を用意する。
5. **UI・試作**：tobetsu-prototypeでFigma DesignのUIを作り、コードと処理を接続して実演を確認する。
6. **発表**：tobetsu-pitchで約3分の原稿とFigma Slidesを用意し、検証結果とPoC案を伝える。

各工程へ成果物を渡し、Skillに定めた完了条件で状態を確認する。各工程を完全に終えてから次へ進む必要はない。Git協業は編集時点から使い、発表の骨子はMVP選択後から開発と並行して作る。

既存のGit協業Skillを再利用し、ハッカソン専用5つは指示中心のSkillとしている。不要なスクリプト、サービス接続、追加アカウント設定を含めない。表計算・画面実装・発表資料の既存Skillは該当作業で利用可能な場合に使い、ない場合にも設計やローカル処理を進められるようにする。

## FigmaでのUI・発表資料作成

1. MVPを決め、入力・結果・必要なエラー状態を整理する。
2. Figma Designで編集可能な画面と共通部品を作り、中心の操作を確認する。
3. 対象画面のデザイン情報を取得し、プロジェクトの開発環境に合わせてコードと処理を実装する。
4. 実アプリの見た目と操作・計算結果を確認する。
5. Figma Slidesへ、課題、UI、実演、効果の根拠をまとめる。発表の骨子は開発と並行して用意する。

Figma上の操作プロトタイプと実アプリの動作確認は別に記録する。新しいファイルを作る前にはfigma-create-new-fileを読む。画面作成でfigma-useとfigma-generate-design、実装でfigma-design-to-code、スライド作成でfigma-useとfigma-use-slidesを使う。アカウントの接続・対象ファイルの権限・メンバーのアクセスは実際の作成時に確認する。

## テーマごとの最小候補

以下は選択済みの開発方針ではなく、ヒアリング後に比較する候補。

| テーマ | 最小候補 | 事前に必要な確認 | 当日確認する例 |
|---|---|---|---|
| A | 写真とメニュー情報からSNS投稿の下書き | 店の口調、必要な情報、投稿確認の担当 | 入力した情報と下書きが一致し、店長が修正できる |
| A | 材料単価と使用量から原価・売価試算 | 数量単位、税、費用範囲、粗利率 | 手計算と一致し、単価不明や率の範囲外を扱える |
| B | 出店・売上・天候の条件別比較 | データ項目・期間、場所と観測地点、営業時間 | 結合漏れを示し、集計と原データが一致する |
| C | 概算の会話から条件付きの確認メモ | 利用できる文字起こし、概算と正式見積もりの区別 | 金額・条件を発言に追跡でき、曖昧さが残る |
| A・C | 現場の文字起こしから教育資料の下書き | 利用可能な音声・文字起こし、確認責任者 | 手順の根拠が分かり、確認前の下書きと表示する |

テーマ専用の準備は、次のブランチに配置している。各ブランチには共通8Skillに加えて、専用Skillとデータ仕様・出典資料がある。テーマの採用は未確定。

| テーマ | ブランチ | 専用Skill | 準備資料のパス |
|---|---|---|---|
| A：飲食店のDX | `theme/a-restaurant-dx` | `tobetsu-restaurant-dx` | `docs/theme-a/README.md` |
| B：キッチンカー | `theme/b-kitchen-car` | `tobetsu-kitchen-car-analysis` | `docs/theme-b/README.md` |
| C：整備工場など | `theme/c-workshop-ops` | `tobetsu-workshop-ops` | `docs/theme-c/README.md` |

専用Skillは対応するブランチの `.agents/skills/<Skill名>/SKILL.md` を読む。共通文書を更新したら、テーマ固有の成果を保持して各テーマブランチにも取り込み、コミット・公開状態を確認する。

## イベント情報の扱い

説明メモによる予定は10:00集合、10:30頃から開発、16:00頃から発表、17:00終了。開催日と具体的な集合場所は未確認。開発基盤はGoogleを使用する予定だがサービスは未確認。Airレジ・freeeの利用からデータ連携権限を推定しない。

17時以降のメインステージは対象チーム・開始時刻が未確認。最優秀成果のPoCは予定、クーポンは検討中で配布対象・条件が未確認。主催者への質問やメール送信は、この設計の作成に含まれない。

## 外部Skillの導入記録

`frontend-design`と`webapp-testing`の導入元は [anthropics/skills](https://github.com/anthropics/skills)、参照コミットは `dbd4588f9e1033efb41dad4bef2f7947c8993d44`。Codexのskill-installer付属スクリプトで、リポジトリの `.agents/skills/` に導入した。配布元のLICENSE.txtと、webapp-testingの補助スクリプト・例を含めて保存している。

初回コミット時に、webapp-testingのSKILL.mdにあった1行の末尾空白を除去した。指示の内容と付属スクリプトは変更していない。別のメンバーの環境ではSkillファイルと必要なツールの両方を用意する。

## 実行環境と再準備手順

導入時に、このPCでNode.js `v24.14.1`、Python `3.11.9`、uvが利用可能であることを確認した。Playwright `1.63.0` はuvの管理環境に準備した。通常のPython環境に直接インストールしたものではない。

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

アプリの起動コマンドとポートは、実装する技術と他の作業の状態を確認してから指定する。参考：[Playwright公式導入手順](https://playwright.dev/python/docs/intro)

## 確認方法と準備時の検証記録

Skillの形式、名前とフォルダー名、参照先、成果物の受け渡し、境界事例を確認する。形式検証はヒアリングや開発の成功を保証しない。当日の事業者データ、アカウント、実演環境での評価は別途行う。

- 専用Skillの作成時：skill-creator付属の形式検証で新規5件が合格し、当時の設計書の相対リンク6件が実在することを確認した。既存のGit協業ファイル5件とAGENTS.mdは作成前後のSHA256が一致した。
- 追加Skillの導入時：新規2Skillの形式検証に合格し、with_server.pyの `--help` が正常終了した。
- Playwrightの導入時：Chromiumのheadless起動、例示HTMLへの文字入力、ボタン操作、結果のassertion、スクリーンショット作成が成功した。
- 初回コミット時：共通8Skillの形式と文書リンクを確認し、Git協業の27件のテストが通過した。
- 例示HTMLは依存ツールの確認用。ハッカソンのアプリや事業者データの動作検証ではない。
- 開発サーバーの起動・停止、Googleサービスとの接続、実アプリの受入確認、実データを用いたSkillの実行評価、発表練習は未実施。

## 次に用意するもの

現時点で追加必須のSkillはない。開発テーマと環境が決まった後に、必要なサービスに合わせて選ぶ。

1. Googleの具体的なサービス、3人の利用可能なアカウント、必要な権限、API利用・実行方法。サービス未確定のため、クラウドの設定や課金設定は行っていない。
2. 事業者データの提供範囲・形式・利用条件。未提供ならデモ用の例示データを準備し、実データと区別する。
3. MVPの受入条件と実演手順。正常入力と代表的な失敗入力、結果の確認方法を先に決める。
4. チームの担当と、各端末での起動確認。ツールの準備と確認は、このPCについてのもの。

## 関連資料

- [ハッカソンの共有メモ](hackathon-memo.md)
- [CodexのSkill公式説明](https://learn.chatgpt.com/docs/build-skills)

ハッカソン専用の5つはこのプロジェクト向けに作成した指示中心のSkill。Skillの指示本体は `.agents/skills/*/SKILL.md` にあり、本書はチームが使う一覧・設計・導入手順をまとめた文書である。保存・公開状態はGitの履歴とリモートの状態で確認する。
