# Repository instructions for Codex

This is a shared hackathon repository. Multiple people and ChatGPT/Codex sessions may work here at the same time.

- Use `$github-collaboration` when starting implementation work, preparing a handoff, or handling a GitHub issue or pull request in this repository.
- Check the current branch and working tree before changing files. Preserve other contributors' uncommitted work; do not overwrite, reset, clean, or include it in your changes.
- Keep changes scoped to the assigned task. Coordinate before editing files another contributor is actively changing.
- Report what changed, what was verified, and what remains unverified. Do not claim that a PR was created, merged, or deployed unless its state was checked.

Project-specific build and test commands are not established yet. Use the commands documented by the project once they are added.

## コミット・プッシュ・PR作成

- ユーザーから依頼された変更が完了し、必要な確認を終えたら、明示的なコミット依頼がなくても対象の変更だけをコミットする。
- この方針は、共通運用ルールの「明示的依頼がない限りコミットしない」より優先する。ユーザーがコミットしないよう指示した場合は、その指示に従う。
- ステージングは個別ファイルを指定し、他の作業者の変更や機密ファイルを含めない。フックはスキップしない。
- コミットメッセージは Conventional Commits に従い、本文に変更が必要な理由を記載する。HEREDOC 形式で渡し、末尾に `Co-Authored-By: Codex <noreply@anthropic.com>` を付ける。
- プッシュ・PR作成は引き続きユーザーの明示的な依頼がある場合のみ行う。
