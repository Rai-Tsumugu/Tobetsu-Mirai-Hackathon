#!/usr/bin/env python3
"""Local, cooperating task ownership and exact-path Git checkpoints. No network."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time
import uuid

MAX_BLOB = 10 * 1024 * 1024
OP_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge",
              "rebase-apply", "BISECT_LOG", "sequencer", "index.lock")
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(rb"(?im)(?:password|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\"']?[^\s\"'<>$]{20,}"),
)


class GuardError(Exception):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git(path, *args, check=True, input_data=None):
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        env.pop(key, None)
    result = subprocess.run(
        ["git", "--no-optional-locks", "--literal-pathspecs", "-C", str(path), *args],
        input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    if check and result.returncode:
        raise GuardError("Git command failed; inspect locally without exposing credentials.",
                         command=args[0], returncode=result.returncode)
    return result


def out(path, *args):
    return git(path, *args).stdout.decode("utf-8", "surrogateescape").strip()


def names(data):
    return [p.decode("utf-8", "surrogateescape") for p in data.split(b"\0") if p]


class Repo:
    def __init__(self, path):
        path = Path(path).resolve(strict=True)
        self.root = Path(out(path, "rev-parse", "--show-toplevel")).resolve()
        self.common = Path(out(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
        self.registry = self.common / "codex-collaboration"
        case = git(self.root, "config", "--bool", "core.ignorecase", check=False)
        try:
            filesystem_folds = (self.root / ".git").samefile(self.root / ".GIT")
        except OSError:
            filesystem_folds = False
        # core.ignorecase=false does not make a Windows/macOS filesystem sensitive.
        self.casefold = os.name == "nt" or filesystem_folds or case.stdout.strip() == b"true"

    def head(self):
        p = git(self.root, "rev-parse", "--verify", "HEAD^{commit}", check=False)
        return p.stdout.decode().strip() if p.returncode == 0 else None

    def branch(self):
        p = git(self.root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        return p.stdout.decode("utf-8", "surrogateescape").strip() if p.returncode == 0 else None

    def operations(self):
        return [name for name in OP_MARKERS if Path(out(
            self.root, "rev-parse", "--path-format=absolute", "--git-path", name)).exists()]

    def assert_idle(self):
        ops = self.operations()
        if ops:
            raise GuardError("An interrupted or concurrent Git operation needs review.", operations=ops)
        if git(self.root, "ls-files", "-u", "-z").stdout:
            raise GuardError("Unresolved index conflicts need review.")

    def staged(self):
        return names(git(self.root, "diff", "--cached", "--name-only", "--no-renames", "-z").stdout)

    def changed(self):
        tracked = names(git(self.root, "diff", "HEAD", "--name-only", "--no-renames", "-z").stdout)
        untracked = names(git(self.root, "ls-files", "--others", "--exclude-standard", "-z").stdout)
        return sorted(set(tracked + untracked))

    def snapshot(self):
        return {"root": str(self.root), "head": self.head(), "branch": self.branch(),
                "operations": self.operations(), "status": out(self.root, "status", "--short", "--branch")}


class Registry:
    """Serialize cooperating mutations with an OS lock, not a timestamp lease."""
    def __init__(self, repo):
        self.repo = repo
        self.file = repo.registry / "state.json"
        self.handle = None
        self.state = None

    def __enter__(self):
        if self.repo.registry.resolve() != self.repo.registry:
            raise GuardError("Registry directory is redirected; preserve and review its location.")
        self.repo.registry.mkdir(parents=True, exist_ok=True)
        if (self.repo.registry / "mutex.lock").is_symlink():
            raise GuardError("Registry lock is a symlink; preserve and review it.")
        self.handle = open(self.repo.registry / "mutex.lock", "a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                self.handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    raise GuardError("Another cooperating Git operation holds the registry lock.")
                time.sleep(0.05)
        try:
            self.state = load_state(self.repo)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def save(self):
        self.state["updated_at"] = now()
        with tempfile.NamedTemporaryFile(dir=self.repo.registry, suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            f.write((json.dumps(self.state, ensure_ascii=True, indent=2) + "\n").encode())
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(temporary, self.file)
        finally:
            if temporary.exists():
                temporary.unlink()

    def __exit__(self, *_):
        if self.handle and not self.handle.closed:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def load_state(repo):
    file = repo.registry / "state.json"
    if not file.exists():
        return {"version": 1, "common": str(repo.common), "tasks": {}}
    try:
        state = json.loads(file.read_text(encoding="utf-8"))
        if state["version"] != 1 or Path(state["common"]).resolve() != repo.common or not isinstance(state["tasks"], dict):
            raise ValueError("Invalid registry")
        required = {"id", "owner", "task", "scopes", "status", "branch", "worktree", "base", "last_head", "checkpoints"}
        for task_id, task in state["tasks"].items():
            if not isinstance(task, dict) or not required <= task.keys() or task_id != task["id"]:
                raise ValueError("Invalid task")
            if not isinstance(task["scopes"], list) or not all(isinstance(p, str) for p in task["scopes"]):
                raise ValueError("Invalid scopes")
            if (task["status"] not in ("preparing", "active", "ready", "blocked", "setup-failed", "released") or
                    not isinstance(task["checkpoints"], list)):
                raise ValueError("Invalid task state")
        return state
    except (ValueError, KeyError, TypeError) as exc:
        raise GuardError("Registry is corrupt or from another clone; preserve and review it.") from exc


def key(repo, path):
    return path.casefold() if repo.casefold else path


def inside(path, root):
    return path == root or root in path.parents


def normalize_scope(repo, value):
    value = value.replace("\\", "/")
    parts = PurePosixPath(value).parts
    if (not value or value.startswith("/") or ":" in value or "\0" in value or
            any(p in ("", ".", "..") or p.casefold() == ".git" for p in value.rstrip("/").split("/"))):
        raise GuardError("Scopes must be safe relative paths, with '/' for directories.", path=value)
    if os.name == "nt":
        reserved = {"con", "prn", "aux", "nul", "conin$", "conout$"}
        reserved.update(f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10))
        if any(p.endswith((".", " ")) or p.split(".")[0].casefold() in reserved or
               any(ord(c) < 32 or c in '<>\"|?*' for c in p) for p in parts):
            raise GuardError("Windows device names and ambiguous path aliases are not supported.", path=value)
    normalized = "/".join(parts) + ("/" if value.endswith("/") else "")
    validate_path(repo, normalized.rstrip("/"))
    if (repo.root / normalized).is_dir() and not normalized.endswith("/"):
        raise GuardError("A directory scope must end in '/'.", path=normalized)
    return normalized


def covers(repo, scope, path):
    scope, path = key(repo, scope), key(repo, path)
    return path.startswith(scope) if scope.endswith("/") else path == scope


def overlap(repo, first, second):
    return (covers(repo, first, second.rstrip("/")) or
            covers(repo, second, first.rstrip("/")) or key(repo, first.rstrip("/")) == key(repo, second.rstrip("/")))


def check_claims(repo, state, scopes, exclude=None):
    for task_id, task in state["tasks"].items():
        if task_id == exclude or task["status"] == "released":
            continue
        clashes = [(a, b) for a in scopes for b in task["scopes"] if overlap(repo, a, b)]
        if clashes:
            raise GuardError("Another task owns overlapping files; coordinate before editing.",
                             task_id=task_id, owner=task["owner"], overlaps=clashes)


def validate_path(repo, value):
    current = repo.root
    for part in value.split("/"):
        current = current / part
        if current.is_symlink() or (current.exists() and (
                not inside(current.resolve(), repo.root) or current.resolve() != current)):
            raise GuardError("Symlinks or path escapes need a project-specific workflow.", path=value)
        if current != repo.root and (current / ".git").exists():
            raise GuardError("Nested repositories/submodules need a separate workflow.", path=value)
    if not inside(current.resolve(), repo.root):
        raise GuardError("Path escaped the task worktree.", path=value)


def check_tree_scopes(repo, revision, scopes):
    for entry in git(repo.root, "ls-tree", "-r", "-z", revision).stdout.split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode = meta.split()[0]
        name = path.decode("utf-8", "surrogateescape")
        if mode in (b"160000", b"120000") and any(
                overlap(repo, scope, name) or covers(repo, name + "/", scope.rstrip("/")) for scope in scopes):
            raise GuardError("Claim touches a submodule or symlink; use a separate reviewed workflow.", path=name)


def task_for(registry, args):
    task = registry.state["tasks"].get(args.task_id)
    if not task:
        raise GuardError("Unknown task ID.")
    if task["owner"] != args.owner:
        raise GuardError("Task belongs to another owner; explicit handoff is required.", owner=task["owner"])
    return task


def task_repo(registry, task, allow_changed_head=False):
    repo = Repo(task["worktree"])
    if repo.root != Path(task["worktree"]).resolve() or repo.common != registry.repo.common:
        raise GuardError("Task worktree does not match its recorded clone.")
    repo.assert_idle()
    if repo.branch() != task["branch"] or (not allow_changed_head and repo.head() != task["last_head"]):
        raise GuardError("Task branch or HEAD changed; inspect history before reconciliation.",
                         expected_branch=task["branch"], expected_head=task["last_head"],
                         actual_branch=repo.branch(), actual_head=repo.head())
    return repo


def owned_changes(repo, task):
    files = repo.changed()
    unknown = [p for p in files if not any(covers(repo, s, p) for s in task["scopes"])]
    if unknown:
        raise GuardError("Unclaimed changes are present; establish ownership before proceeding.", paths=unknown)
    for name in files:
        normalize_scope(repo, name)
    return files


def scan_blob(name, data):
    lower = name.casefold()
    leaf = lower.rsplit("/", 1)[-1]
    env_example = leaf in (".env.example", ".env.sample", ".env.template")
    if ((leaf == ".env" or leaf.startswith(".env.")) and not env_example or
            leaf in ("id_rsa", "id_ed25519", "credentials.json") or
            leaf.endswith((".pem", ".key", ".p12", ".pfx", ".jks")) or
            lower.endswith(".aws/credentials") or leaf.startswith("secrets.")):
        raise GuardError("Potential credential file requires explicit review outside auto-checkpointing.", path=name)
    if len(data) > MAX_BLOB:
        raise GuardError("File exceeds the 10 MiB automatic checkpoint limit; review asset handling.", path=name)
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        raise GuardError("Potential credential pattern found; inspect locally. No secret is printed.", path=name)


def scan_working(repo, files):
    for name in files:
        file = repo.root / name
        if file.is_file():
            if file.stat().st_size > MAX_BLOB:
                raise GuardError("File exceeds the automatic checkpoint limit.", path=name)
            scan_blob(name, file.read_bytes())


def scan_staged(repo, files):
    entries = git(repo.root, "ls-files", "--stage", "-z", "--", *files).stdout
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode, oid, stage = meta.split()
        name = path.decode("utf-8", "surrogateescape")
        if mode in (b"120000", b"160000") or stage != b"0":
            raise GuardError("Symlink, gitlink, or conflict in staged content.", path=name)
        if int(out(repo.root, "cat-file", "-s", oid.decode())) > MAX_BLOB:
            raise GuardError("Staged blob exceeds the automatic checkpoint limit.", path=name)
        scan_blob(name, git(repo.root, "cat-file", "blob", oid.decode()).stdout)


def do_start(repo, args):
    repo.assert_idle()
    if not repo.head():
        raise GuardError("No initial commit. Agree the exact baseline and ownership before creating worktrees.")
    if out(repo.root, "rev-parse", "--show-superproject-working-tree"):
        raise GuardError("Submodule tasks require a project-specific workflow.")
    if not args.owner.strip() or not args.task.strip():
        raise GuardError("Owner and task must be nonempty.")
    base = out(repo.root, "rev-parse", "--verify", "--end-of-options", args.base + "^{commit}")
    scopes = sorted(set(normalize_scope(repo, p) for p in args.paths))
    check_tree_scopes(repo, base, scopes)
    with Registry(repo) as reg:
        for existing in reg.state["tasks"].values():
            if existing["owner"] == args.owner and existing["task"] == args.task and existing["status"] != "released":
                raise GuardError("This task already exists; resume it instead of duplicating work.", task_id=existing["id"], worktree=existing["worktree"])
        check_claims(repo, reg.state, scopes)
        task_id = uuid.uuid4().hex[:12]
        slug = re.sub(r"[^a-z0-9-]+", "-", args.task.lower()).strip("-")[:36] or "task"
        branch = args.branch or "codex/" + slug + "-" + task_id
        if branch.startswith("-") or git(repo.root, "check-ref-format", "--branch", branch, check=False).returncode:
            raise GuardError("Invalid requested task branch name.")
        if git(repo.root, "show-ref", "--verify", "--quiet", "refs/heads/" + branch, check=False).returncode == 0:
            raise GuardError("Requested branch already exists; inspect ownership and resume its task rather than replacing it.", branch=branch)
        source = Repo(repo.common.parent) if (repo.common.parent / ".git").is_dir() else repo
        clone_id = hashlib.sha256(str(repo.common).encode()).hexdigest()[:8]
        parent = source.root.parent / ".codex-worktrees" / (source.root.name + "-" + clone_id)
        if parent.resolve() != parent or inside(parent, source.root):
            raise GuardError("Worktree destination is redirected or inside the source checkout.")
        parent.mkdir(parents=True, exist_ok=True)
        worktree = parent / task_id
        task = {"id": task_id, "owner": args.owner, "task": args.task, "scopes": scopes,
                "status": "preparing", "branch": branch, "worktree": str(worktree),
                "base": base, "review_base": base, "last_head": base, "source": repo.snapshot(),
                "created_at": now(), "updated_at": now(), "checkpoints": []}
        reg.state["tasks"][task_id] = task
        reg.save()
        try:
            git(repo.root, "worktree", "add", "-b", branch, str(worktree), base)
            task["status"] = "active"
        except Exception:
            task["status"] = "setup-failed"
            reg.save()
            raise
        reg.save()
        return task


def do_checkpoint(reg, task, args):
    if task["status"] != "active":
        raise GuardError("Only an active task can checkpoint; review/resume its recorded state.")
    repo = task_repo(reg, task)
    if repo.staged():
        raise GuardError("Existing staged changes must be reviewed; no automatic restaging.", paths=repo.staged())
    if task.get("attempt") or task.get("sync_attempt"):
        raise GuardError("A previous checkpoint attempt needs recovery/review first.")
    files = owned_changes(repo, task)
    scan_working(repo, files)
    if not files:
        return {"task_id": task["id"], "result": "no-changes", "head": repo.head()}
    if args.dry_run:
        return {"task_id": task["id"], "result": "preview", "paths": files, "head": repo.head()}
    if not args.message.strip() or "\0" in args.message:
        raise GuardError("A meaningful, nonempty commit message is required.")
    scan_blob("commit-message", args.message.encode("utf-8"))
    old = repo.head()
    task["attempt"] = {"head": old, "paths": files, "started_at": now(), "tree": None}
    reg.save()
    try:
        git(repo.root, "add", "--", *files)
        staged = repo.staged()
        if set(staged) != set(files):
            raise GuardError("Staged paths differ from reviewed working changes; inspect concurrent edits/filters.")
        tree = out(repo.root, "write-tree")
        task["attempt"]["tree"] = tree
        reg.save()
        scan_staged(repo, files)
        task_repo(reg, task)
        if out(repo.root, "write-tree") != tree:
            raise GuardError("Index changed immediately before commit; review concurrent edits.")
        git(repo.root, "commit", "-F", "-", input_data=args.message.encode("utf-8"))
        new = repo.head()
        if (repo.branch() != task["branch"] or
                out(repo.root, "rev-list", "--parents", "-n", "1", new).split() != [new, old] or
                out(repo.root, "rev-parse", "HEAD^{tree}") != tree or repo.staged()):
            task["status"] = "blocked"
            task["observed_head"] = new
            reg.save()
            raise GuardError("Commit differed from its attempt; preserve it and review hooks/history before publication.", observed_head=new)
        task["last_head"] = new
        task["updated_at"] = now()
        task["checkpoints"].append({"head": new, "message": args.message, "at": now(), "paths": files})
        task.pop("attempt", None)
        reg.save()
        return {"task_id": task["id"], "result": "committed", "head": new, "paths": files,
                "remaining_changes": repo.changed()}
    except Exception:
        task["updated_at"] = now()
        if repo.head() != old and task.get("attempt"):
            task["status"] = "blocked"
            task["observed_head"] = repo.head()
        reg.save()
        raise


def review_diff(repo, task, base, revision):
    files = names(git(repo.root, "diff", base, revision, "--name-only", "--no-renames", "-z").stdout)
    unknown = [p for p in files if not any(covers(repo, s, p) for s in task["scopes"])]
    if unknown:
        raise GuardError("Task diff contains unowned paths relative to the review base.", paths=unknown)
    check_tree_scopes(repo, revision, task["scopes"])
    entries = git(repo.root, "ls-tree", "-r", "-z", revision, "--", *files).stdout if files else b""
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode, kind, oid = meta.split()
        name = path.decode("utf-8", "surrogateescape")
        if mode in (b"120000", b"160000") or kind != b"blob":
            raise GuardError("Nonregular object in the owned diff.", path=name)
        if int(out(repo.root, "cat-file", "-s", oid.decode())) > MAX_BLOB:
            raise GuardError("Owned committed blob exceeds the automatic limit.", path=name)
        scan_blob(name, git(repo.root, "cat-file", "blob", oid.decode()).stdout)
    return files


def recover_commit(reg, task):
    attempt = task.get("attempt")
    if not attempt or not attempt.get("tree") or task.get("sync_attempt"):
        raise GuardError("No complete checkpoint attempt can be reconciled automatically.")
    work = task_repo(reg, task, allow_changed_head=True)
    head = work.head()
    if (out(work.root, "rev-list", "--parents", "-n", "1", head).split() != [head, attempt["head"]] or
            out(work.root, "rev-parse", "HEAD^{tree}") != attempt["tree"] or work.staged()):
        raise GuardError("HEAD/index does not match the recorded checkpoint; preserve for manual review.")
    files = review_diff(work, task, attempt["head"], head)
    owned_changes(work, task)
    task["checkpoints"].append({"head": head, "message": out(work.root, "show", "-s", "--format=%B", head),
                                 "at": now(), "paths": files, "recovered": True})
    task.update(last_head=head, status="active", updated_at=now())
    task.pop("attempt")
    task.pop("observed_head", None)
    reg.save()
    return task


def finish_sync(reg, task, aborted=False):
    attempt = task.get("sync_attempt")
    if not attempt:
        raise GuardError("No recorded upstream merge to recover.")
    work = task_repo(reg, task, allow_changed_head=True)
    head, old, target = work.head(), attempt["head"], attempt["target"]
    if aborted:
        if head != old or work.changed() or work.staged():
            raise GuardError("Aborted merge recovery needs the recorded original HEAD and clean files/index.")
        review_diff(work, task, task.get("review_base", task["base"]), head)
        task.setdefault("syncs", []).append({"head": head, "target": target, "aborted": True, "at": now()})
        task.update(status="active", updated_at=now())
        task.pop("sync_attempt")
        task.pop("observed_head", None)
        reg.save()
        return task
    parents = out(work.root, "rev-list", "--parents", "-n", "1", head).split()
    ff = git(work.root, "merge-base", "--is-ancestor", old, target, check=False).returncode == 0
    already = git(work.root, "merge-base", "--is-ancestor", target, old, check=False).returncode == 0
    if not ((ff and head == target) or (already and head == old) or parents == [head, old, target]):
        raise GuardError("Merge HEAD/parents differ from the recorded target; preserve and review history.")
    if work.changed() or work.staged():
        raise GuardError("Finish resolving the merge with normal hooks; recovery needs clean files/index.")
    review_diff(work, task, target, head)
    task.setdefault("syncs", []).append({"head": head, "target": target, "previous_head": old, "at": now()})
    task.update(last_head=head, review_base=target, status="active", updated_at=now())
    task.pop("sync_attempt")
    task.pop("observed_head", None)
    reg.save()
    return task


def do_sync(reg, task, args):
    if task["status"] != "active" or task.get("attempt") or task.get("sync_attempt"):
        raise GuardError("Only an active, recovered task can integrate upstream.")
    work = task_repo(reg, task)
    if work.changed() or work.staged():
        raise GuardError("Checkpoint or review pending work before integrating upstream.")
    target = out(work.root, "rev-parse", "--verify", "--end-of-options", args.target + "^{commit}")
    base = task.get("review_base", task["base"])
    if git(work.root, "merge-base", "--is-ancestor", base, target, check=False).returncode:
        raise GuardError("Target does not advance the recorded review base; verify the intended upstream.")
    review_diff(work, task, base, work.head())
    check_tree_scopes(work, target, task["scopes"])
    task["sync_attempt"] = {"head": work.head(), "target": target, "started_at": now()}
    reg.save()
    try:
        # Override only ambiguous local merge policies; preserve normal hooks/signing.
        git(work.root, "merge", "--no-edit", "--no-squash", "--ff", target)
        return finish_sync(reg, task)
    except Exception:
        task["status"] = "blocked"
        task["observed_head"] = work.head()
        reg.save()
        raise


def do_task(repo, args):
    with Registry(repo) as reg:
        task = task_for(reg, args)
        if task["status"] == "released" and args.command not in ("resume", "release"):
            raise GuardError("Released ownership must be reacquired by resume before further work.")
        if args.command == "checkpoint":
            return do_checkpoint(reg, task, args)
        if args.command == "sync-base":
            return do_sync(reg, task, args)
        if args.command == "recover-sync":
            return finish_sync(reg, task, aborted=args.aborted)
        if args.command == "recover-commit":
            return recover_commit(reg, task)
        if args.command == "release" and args.reason == "cancelled":
            task.update(status="released", released_at=now(), release_reason=args.reason)
            reg.save()
            return task
        work = task_repo(reg, task)
        if args.command == "claim":
            if task["status"] != "active":
                raise GuardError("Only active tasks can expand ownership.")
            scopes = sorted(set(task["scopes"] + [normalize_scope(work, p) for p in args.paths]))
            check_tree_scopes(work, work.head(), scopes)
            check_claims(work, reg.state, scopes, task["id"])
            task["scopes"] = scopes
        elif args.command == "resume":
            if task["status"] not in ("active", "ready", "released") or task.get("attempt") or task.get("sync_attempt"):
                raise GuardError("Interrupted/blocked setup or checkpoint needs recovery before resume.")
            check_claims(work, reg.state, task["scopes"], task["id"])
            task["status"] = "active"
        elif args.command == "recover-index":
            attempt = task.get("attempt")
            if not attempt or not attempt.get("tree"):
                raise GuardError("No fully recorded staged attempt; inspect manually without discarding work.")
            if out(work.root, "write-tree") != attempt["tree"] or work.head() != attempt["head"]:
                raise GuardError("Index/HEAD changed after the attempt; automatic recovery refused.")
            git(work.root, "restore", "--staged", "--", *attempt["paths"])
            task.pop("attempt")
        elif args.command == "ready":
            if task["status"] != "active" or task.get("attempt") or task.get("sync_attempt"):
                raise GuardError("Only an active, recovered task can become ready.")
            if work.changed() or work.staged():
                raise GuardError("A ready handoff requires a clean task worktree/index.")
            review_diff(work, task, task.get("review_base", task["base"]), work.head())
            if not args.summary.strip() or not args.verification.strip():
                raise GuardError("Outcome and concrete verification evidence are required.")
            task.update(status="ready", handoff={"summary": args.summary, "verification": args.verification, "head": work.head(), "at": now()})
        elif args.command == "release":
            if task["status"] != "ready" or work.changed() or work.staged():
                raise GuardError("Release requires a clean ready handoff; explicit cancellation uses --reason cancelled.")
            task.update(status="released", released_at=now(), release_reason=args.reason)
        task["updated_at"] = now()
        reg.save()
        return task


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="Inspect clone/task state without creating records")
    status.add_argument("--repo", required=True)
    start = commands.add_parser("start", help="Claim paths and create an isolated task worktree")
    start.add_argument("--repo", required=True)
    start.add_argument("--owner", required=True)
    start.add_argument("--task", required=True)
    start.add_argument("--base", required=True)
    start.add_argument("--branch", help="Explicit new task branch; existing branches are never replaced")
    start.add_argument("--paths", nargs="+", required=True)
    for name in ("resume", "claim", "checkpoint", "recover-index", "recover-commit", "sync-base", "recover-sync", "ready", "release"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--repo", required=True)
        cmd.add_argument("--owner", required=True)
        cmd.add_argument("--task-id", required=True)
        if name == "claim":
            cmd.add_argument("--paths", nargs="+", required=True)
        if name == "sync-base":
            cmd.add_argument("--target", required=True)
        if name == "recover-sync":
            cmd.add_argument("--aborted", action="store_true", help="Record a verified prior merge abort; does not abort or discard files")
        if name == "checkpoint":
            cmd.add_argument("--message", required=True)
            cmd.add_argument("--dry-run", action="store_true")
        if name == "ready":
            cmd.add_argument("--summary", required=True)
            cmd.add_argument("--verification", required=True)
        if name == "release":
            cmd.add_argument("--reason", choices=("completed", "handed-off", "cancelled"), required=True)
    return cli


def main():
    args = parser().parse_args()
    try:
        repo = Repo(args.repo)
        if args.command == "status":
            result = {"repository": repo.snapshot(), "tasks": load_state(repo)["tasks"],
                      "worktrees": out(repo.root, "worktree", "list", "--porcelain")}
        elif args.command == "start":
            result = do_start(repo, args)
        else:
            result = do_task(repo, args)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True, indent=2))
        return 0
    except GuardError as exc:
        print(json.dumps({"ok": False, "error": str(exc), **exc.details}, ensure_ascii=True, indent=2))
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": "Filesystem/process failure; preserve work and inspect recorded state.",
                          "type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
