# Operating the shared Git workflow

## Local helper

Run Python 3.10+ with the absolute path to `scripts/team_git.py`. It uses only the standard library and invokes Git with argument arrays, never a shell. Git must support `rev-parse --path-format` (2.31+). Replace the placeholders with verified values. The helper has no network commands.

```text
python <helper> status --repo <repo>
python <helper> start --repo <repo> --owner <session-owner> --task login-form --base <verified-base> --paths src/login.ts tests/login.test.ts
python <helper> resume --repo <repo> --owner <session-owner> --task-id <id>
python <helper> claim --repo <repo> --owner <session-owner> --task-id <id> --paths package.json package-lock.json
python <helper> checkpoint --repo <repo> --owner <session-owner> --task-id <id> --message "feat: add login validation" --dry-run
python <helper> checkpoint --repo <repo> --owner <session-owner> --task-id <id> --message "feat: add login validation"
python <helper> sync-base --repo <repo> --owner <session-owner> --task-id <id> --target <verified-upstream-ref>
python <helper> ready --repo <repo> --owner <session-owner> --task-id <id> --summary "Login validation added" --verification "npm test: 8 passed; browser check: passed"
python <helper> release --repo <repo> --owner <session-owner> --task-id <id> --reason completed
```

Use stable owner identifiers meaningful within the session, such as `codex-session-<id>`; do not invent a student's identity or Git author. Owner strings are declarations, not authenticated identities. Directory scopes end in `/`; prefer exact paths. The helper rejects absolute/traversal paths, `.git`, symlinks, and submodule scopes. A rename needs ownership of both the old and new paths. Paths with spaces must be separate quoted arguments. Shell quoting belongs to the caller; never interpolate untrusted text into shell commands.

`start` returns a task ID, branch, immutable base SHA, and absolute worktree path. A dirty source checkout is left in place, with its status recorded; its changes are not copied. Creation from a checkout with an interrupted merge/rebase/etc. is refused. Choose the base from the assignment and repository's actual branch configuration; do not assume `main` or that a cached remote ref is current. Fetch when the task calls for current upstream information, then inspect again. Avoid `pull` in somebody else's checkout.

For an explicitly requested new branch, pass `start --branch <name>`. Existing branches are never replaced: find/resume their registered task when ownership is established. If a requested existing branch has no task record or is occupied by another checkout, inspect it and prepare an isolated alternative or an explicitly authorized ownership handoff; do not silently use a different branch or override Git's checkout protection.

Records live in `<git-common-dir>/codex-collaboration/state.json`. Linked worktrees share this record and an OS lock. Worktrees live outside the source tree in a sibling `.codex-worktrees/<repo>-<clone-id>/<task-id>` directory. `status` is read-only and does not create a registry. Mutation commands serialize for up to ten seconds and then fail; no stale lock file is deleted. The OS releases the lock when a process dies. The file may remain normally.

Records retain owner, scopes, source/original base/review base/last HEAD, branch/worktree, timestamps, checkpoint hashes, and handoff evidence. States include `preparing`, `active`, `ready`, `blocked`, `setup-failed`, and `released`. Every unreleased task holds claims, including interrupted/failed tasks. Old timestamps do not establish abandonment. `resume` returns the same worktree and reacquires a released task's scopes only if they do not overlap; it never adopts changed HEADs or another owner automatically. Designated handoff recipients need explicit task/session authorization to use the recorded owner identifier; an ID alone is not permission.

The registry is local and uncommitted. Across different clones/computers, establish task ownership and dependency order in the assigned issue/PR when writing there is authorized. Worktree isolation protects local files, but the registry cannot detect a teammate in another clone. Shared interfaces and dependency lockfiles need coordination even when files are isolated.

## Automatic action policy

| Operation | Default within an implementation task |
| --- | --- |
| Inspect local state or assigned issue/PR | Proceed |
| Claim files; create/reuse a local task worktree/branch | Proceed |
| Local coherent checkpoint of reviewed, owned changes | Proceed; respect an explicit no-commit request |
| Fetch to verify a needed remote base | Proceed when upstream inspection is relevant |
| Push, create/update PR, post issue comment | Only when requested or already authorized |
| Merge or deploy | Prepare/review/check first; perform only with authorization for that action |
| Force push, history rewrite, branch/worktree deletion | No automatic operation; use a separately scoped explicit instruction |
| Change protection, install hooks/CI, alter credentials/config | Separate task; do not silently install |

Do not repeat an approval question when session authorization covers the action. Unknown ownership, an unknown baseline, or a changed target can require clarification; routine Git mechanics do not.

## Checkpoints, failures, and recovery

Before checkpointing, inspect actual diff/content, generated files, credentials, and task gates. The helper requires unchanged recorded HEAD/branch, no interrupted operation/index lock, and no pre-existing staged entries. It rejects changes outside claims, unresolved conflicts, symlinks/gitlinks, selected credential filenames/patterns, and files over 10 MiB. Example/template filenames are allowed but their contents are scanned. This heuristic does not certify absence of secrets; use a documented project scanner when available.

Dry run checks working files without staging. The real checkpoint also scans staged blobs, records attempted paths/tree, runs normal hooks, and verifies a single direct-child commit with the expected tree and a clean index. Working files changed by hooks may remain uncommitted; report/review them. Record actual check results in handoffs. WIP checkpoints preserve local progress and must not be labelled ready.

| Condition | Response |
| --- | --- |
| Existing staged work, unclaimed edits, or changed branch/HEAD | Inspect ownership/history; preserve it; do not expand claims to absorb unexplained changes |
| Missing author, signing key, or credentials | Report the missing capability; do not forge an author, disable signing, or expose tokens |
| Hook failure | Preserve work/index, fix the cause, inspect the recorded attempt before recovery |
| Interrupted stage/commit | Inspect registry, status, reflog, and HEAD; do not duplicate a commit to hide uncertainty |
| Git created exactly the recorded checkpoint, but state save was interrupted | `recover-commit --repo ... --owner ... --task-id ...` verifies parent, recorded tree, branch, owned diff, and clean index, then records the existing commit without duplicating it |
| Recorded index retained after a failed attempt | `recover-index --repo ... --owner ... --task-id ...` unstages only the recorded attempt when tree/HEAD still match, preserving working files |
| Index changed after the attempt | Recovery refuses; review exact staged hunks/ownership before a targeted manual action |
| Hook changes committed tree/HEAD, or state save fails after commit | Preserve the commit; review actual history/content before repair/publication; never reset automatically |
| Missing/corrupt record, missing/moved worktree, or failed setup | Preserve files/refs; inspect worktree list, status, and evidence before repair. Do not guess an owner or edit records to skip checks |
| Claim held by idle/crashed session | Inspect its work, then use an explicit handoff/cancellation or dependency ordering; never expire by time |
| Cancellation | Stop editing and document the remaining state, then use `release --reason cancelled` under that authorization; files/refs remain |

The helper cannot infer ownership of unrelated manual commits. If recorded HEAD diverges, inspect the recorded attempt and use the matching recovery command only when its checks establish the operation. Otherwise use an explicitly authorized repair/handoff; do not rewrite state just to make the helper proceed. Refs, reflog, files, and the recorded attempt are evidence. Recovery from uncertainty is more conservative than routine operation.

## Empty repository and uncommitted student work

With no committed base, `start` refuses before creating a branch/task record. Enumerate existing files, identify owners, and prepare a narrow initial-commit candidate. The first commit establishes the common baseline and needs agreement about exactly which existing files belong in it. Obtain that missing decision while doing authorized nonoverlapping work in place. Untracked files do not imply ownership; never stage the whole directory.

After baseline authorization, recheck status/index, stage only agreed files, run applicable checks/normal hooks, create the initial commit, verify its file list/hash, then begin isolated work. Do not synthesize an empty root commit or orphan history to evade a missing baseline. If another session creates the baseline, inspect it rather than initializing again.

For a student's existing uncommitted edits, agree files/hunks and destination first. Apply only an owned patch to a clean task worktree after a dry run, handling binary/renames as needed; do not remove the original. Mixed ownership in one file needs hunk review or sequencing. Do not commit somebody else's draft as a shortcut.

## Remote publication and integration

Before an authorized push, review task history and the whole review-base-to-HEAD diff, including WIP commits. Check secrets in history as well as current files. Verify the intended remote repository, target/task branches, current remote state, and authorization. These task records are not remote locks. Push normally and verify remote SHA. State branch dependencies and use the agreed base.

For an authorized PR, use a focused title, link the assigned issue when known, and describe final behavior/actual checks. Use structured arguments or an exact body file. Keep local paths/session IDs out of public text. Verify PR URL, head/base, diff, draft/open state, and CI results. Keep failed or unchecked results as a draft and explain what remains.

When upstream advances, inspect both sides and use `sync-base --target <verified-ref>` from a clean, active task. It merges only into this task's branch, preserves the original base, and advances `review_base` after checking the owned diff against the target. This excludes inherited upstream changes from ownership/PR-diff checks. The target must descend from the previous review base; do not hide task edits by choosing an arbitrary ref as the baseline. Recheck gates after integration. Do not auto-rebase published/shared history.

If a merge conflicts or a hook fails, `sync_attempt` and work remain for review. Coordinate interfaces and resolve the recorded merge in the same task worktree with exact paths and normal Git hooks; then `recover-sync --repo ... --owner ... --task-id ...` verifies the recorded target, merge parents, clean index/worktree, and owned target-to-HEAD diff before continuing. Preserve both contributors' intent; never erase unknown work with whole-side `ours`/`theirs`. Run relevant checks after resolution. Regenerate lockfiles only after dependency intent is understood. A deliberate `git merge --abort` is limited to this task's own recorded merge and needs authorization to discard any resolution edits; after inspecting restored files/HEAD, `recover-sync --aborted` records the verified abort without changing files or refs. Do not edit records to conceal uncertain history.

Merge authorization applies to a verified PR/head/target. Recheck reviews, protections, required CI, and intervening changes. Never bypass required gates. Confirm merge state; deployment is a separate action. Release claims when editing has stopped and integration/handoff is established. Branch/worktree removal is separate cleanup; preserve pending/unpushed work.

## Environment and student-facing operation

- Worktrees do not copy `.env`, ignored output, installed dependencies, untracked instructions, or secrets. Read original task instructions; transfer instruction files only when authorized. Prefer separate dependency/build directories. Do not copy credentials automatically.
- Isolate dev-server ports and mutable databases/test data. Do not kill a teammate's process, reuse a shared port, run destructive migrations, or change a shared service because Git files are isolated.
- Submodules, symlinks, LFS, large/binary assets, generated code, sparse checkout, and unusual hooks need project-specific ownership/verification before a manual alternative. Do not auto-install LFS, disable sparse checkout, or relocate worktrees.
- Attend to Windows case collisions, filename length, CRLF, Unicode, and case-only renames. The helper uses literal pathspecs, conservative case folding on Windows, and filesystem/config detection elsewhere. `core.ignorecase=false` cannot bypass protection on Windows. Avoid unrelated file normalization.
- If Python/Git or required tools are missing, use inspected exact-path operations in an isolated task worktree with the same constraints; otherwise preserve work and report the concrete blocker. No automatic installation or timer service is included.
- Explain what changed, where progress is saved, checks performed, and review/push/merge status in simple terms. Ask a decision only when it changes ownership, baseline, or an authorized external action; prepare evidence and a recommendation first.

The guarantee is limited to cooperating tasks leaving each other's checkouts, index, task refs, and uncommitted work intact while recording/checking their own work. Direct edits of the same worktree, malicious hooks, filesystem failure, and separate clones need protections outside this skill. Propose GitHub rulesets/required review/CI as a separate task if server enforcement is needed.

Primary Git references: [linked worktrees](https://git-scm.com/docs/git-worktree), [commits](https://git-scm.com/docs/git-commit), and [hooks](https://git-scm.com/docs/githooks). Worktrees have separate HEAD/index but share repository objects and most refs; this workflow also tracks task branch ownership.
