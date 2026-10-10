---
name: github-collaboration
description: Manage task branches, isolated worktrees, file ownership, local checkpoint commits, and review handoffs in this shared hackathon repository. Use automatically for implementation, interrupted work, and GitHub issue or PR work, including when a student asks only for a feature or fix without mentioning Git.
---

# GitHub collaboration

Take care of routine Git management as part of the requested implementation. Students should be able to ask for a feature or fix without choosing Git commands. Preserve every contributor's work and keep the result recoverable and reviewable. Explain exceptional decisions in ordinary Japanese when the user writes Japanese.

## Boundaries and authority

- A scoped implementation request authorizes creating a local task branch/worktree and making local commits containing that task's owned changes. Follow an explicit request to avoid commits or to use a named branch.
- Pushing, creating/updating a PR, posting issue comments, merging, and deployment require authorization in the current task or existing session. A request to create a PR includes pushing its task branch. Reading a GitHub issue does not authorize posting to it. Never force push automatically.
- Do not rewrite another person's history, switch their checkout, stash their work, delete their branch/worktree, bypass hooks, change global Git configuration, or include their changes in a commit. Never use blanket staging (`git add .`, `git add -A`, `git commit -a`) in a shared checkout.
- Isolation and the helper's ownership checks cover cooperating sessions in one local clone. Separate clones/computers, direct Git commands, external editors, and arbitrary hooks can bypass them. Never promise universal exclusion, backup, or a permanently running service. GitHub protection and CI are separate enforcement; configure them only when requested.

## Start automatically

1. Read repository instructions and the task. Inspect the branch, status, worktrees, interrupted Git operations, and current local ownership records. Inspect a named issue/PR live. Determine the intended base and narrowly scoped files; preserve facts, assumptions, and assigned ownership.
2. Read [references/workflow.md](references/workflow.md) for the helper commands and exception handling. Run `scripts/team_git.py status --repo <absolute-repo>` (Python 3.10+ and Git required).
3. Reuse this task's recorded worktree on resume. For new work, call `start` with a stable session owner, task name, explicit base commit/ref, and exact files or directory scopes. It creates a unique `codex/<task>-<id>` branch, an isolated worktree, and a shared task record. Record the returned absolute worktree path and task ID in the session. Run all subsequent edits, builds, and Git commands in that worktree.
4. Run `claim` before expanding the files to edit. Another live task's overlapping claim blocks the helper, including shared lockfiles and directory scopes. Resolve ownership or sequence the work through an already authorized channel; do useful nonoverlapping work meanwhile. Do not take over an old claim because its timestamp is old.
5. If the base has no commit, ownership is unclear, or isolation cannot be created, preserve the existing checkout and follow the reference's specific fallback. Do not manufacture a base, move uncommitted files, or initialize a commit containing unknown work.

The helper uses an OS lock and atomic records in the Git common directory, shared across linked worktrees. No repository files, global hooks, credentials, or remote settings are installed by the helper. It fails with an explanation and retains recoverable state after partial operations.

## Implement and checkpoint

- Keep changes coherent and task scoped. A fresh worktree contains committed base files; it does not contain the student's uncommitted edits. If those edits are needed, establish their ownership and transfer only the agreed changes after checking both copies.
- Preserve project tool versions, dependency locks, line endings, and generated-file conventions. Avoid unrelated formatting. Use the documented checks and distinguish checks passed, failed, and unavailable. Do not invent build commands or install dependencies in another person's environment.
- Create a checkpoint after a coherent, reviewed milestone, before a long interruption, and at completion. Do not commit every save or on a timer. Incomplete work can have a clearly labelled local `wip:` checkpoint after a meaningful review; report failed/unrun checks and keep it unready for integration.
- Use `checkpoint --dry-run`, review the proposed diff/content, then `checkpoint` with a meaningful message. The helper validates ownership, HEAD/branch, staged changes, conflicts, path escapes, simple credential patterns, and file size before committing exact paths. It preserves hooks and verifies the resulting commit. A heuristic scan does not prove absence of secrets; review actual content before committing or publishing.
- Unexpected staged changes or HEAD movement stop the helper. Use `sync-base` for verified upstream updates, rather than an unrecorded manual merge. Hook failure retains work and staged files; inspect the recorded attempt and follow recovery instructions. Do not unstage someone else's work or bypass a failing hook. Hooks that alter the commit tree cause a blocked result; review and repair before publishing.
- Save progress in the local task record at each checkpoint. When stopping with uncommitted work, report its path and state. A local commit/worktree is not an off-device backup; report whether a permitted push was actually performed.

## Review and handoff

1. Review task history and the full review-base-to-task diff, final status, and required checks. The original base remains recorded; verified upstream updates advance the review base. Confirm that only assigned changes are included. Resolve failures or state exactly why a result remains a draft.
2. Use `ready` only when task gates pass; provide a short outcome and concrete verification record. It requires a clean worktree and retains ownership while integration is pending. If checks cannot run, retain an active task or prepare an explicitly labelled draft; do not claim it is ready.
3. When remote work is authorized, follow the publication/integration section of the reference: verify the remote/base, push the task branch normally, inspect PR contents and CI, and confirm actual state. Coordinate competing changes through review. Merge and deployment remain distinct actions with their own authorization and evidence.
4. Release claims only after the owner has stopped editing and integration or an explicit handoff/cancellation permits release. `release` retains branches, commits, and worktrees. Do not delete recovery material as routine cleanup.
5. Tell the student what was completed, the branch/worktree and commit, checks performed, uncommitted work, and the next needed decision in a short explanation. Do not make the student perform routine Git steps that the agent is authorized to handle.

For interruptions, conflicts, credentials, hooks, multiple clones, submodules/LFS, and repository bootstrap, read the relevant parts of [references/workflow.md](references/workflow.md). The helper is a cooperating workflow, not an access-control system.
