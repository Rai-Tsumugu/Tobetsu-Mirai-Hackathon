"""Real Git integration scenarios in disposable, locally configured repositories."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).with_name("team_git.py").resolve()
spec = importlib.util.spec_from_file_location("team_git", HELPER)
team = importlib.util.module_from_spec(spec)
spec.loader.exec_module(team)


class TeamGitScenarios(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teamgit-tests-")
        self.workspace = Path(self.temp.name).resolve()
        assert self.workspace.parent == Path(tempfile.gettempdir()).resolve()
        self.root = self.workspace / "student repo"
        self.root.mkdir()
        self.run_git(self.root, "init", "-b", "main")
        for name, value in (("user.name", "Sandbox Tester"), ("user.email", "test@example.invalid"),
                            ("commit.gpgsign", "false"), ("core.autocrlf", "false"),
                            ("core.hooksPath", str(self.root / ".git" / "hooks"))):
            self.run_git(self.root, "config", "--local", name, value)
        self.repo = team.Repo(self.root)

    def tearDown(self):
        # Cleanup is confined to this test's verified system-temp directory.
        assert self.workspace.parent == Path(tempfile.gettempdir()).resolve()
        assert self.workspace.name.startswith("teamgit-tests-")
        self.temp.cleanup()

    def run_git(self, root, *args):
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        return p.stdout

    def seed(self):
        (self.root / "student.txt").write_text("student's base\n", encoding="utf-8")
        (self.root / "feature.txt").write_text("feature base\n", encoding="utf-8")
        self.run_git(self.root, "add", "--", "student.txt", "feature.txt")
        self.run_git(self.root, "commit", "-m", "sandbox baseline")
        return self.repo.head()

    def start(self, task="feature", owner="session-b", paths=None):
        args = team.parser().parse_args(["start", "--repo", str(self.root), "--owner", owner,
                                        "--task", task, "--base", "HEAD", "--paths", *(paths or ["feature.txt"])])
        return team.do_start(self.repo, args)

    def command(self, task, name, *extra, owner=None):
        args = team.parser().parse_args([name, "--repo", str(self.root), "--owner", owner or task["owner"],
                                        "--task-id", task["id"], *extra])
        return team.do_task(self.repo, args)

    def checkpoint(self, task, dry=False):
        return self.command(task, "checkpoint", "--message", "feat: sandbox change", *( ["--dry-run"] if dry else []))

    def hook(self, name, body):
        file = self.root / ".git" / "hooks" / name
        file.write_bytes(("#!/bin/sh\n" + body + "\n").encode())
        file.chmod(0o755)
        return file

    def test_unborn_refuses_without_creating_records_or_commits(self):
        before = self.repo.snapshot()
        p = subprocess.run([sys.executable, "-B", str(HELPER), "status", "--repo", str(self.root)], capture_output=True)
        self.assertEqual(p.returncode, 0)
        self.assertIsNone(json.loads(p.stdout)["result"]["repository"]["head"])
        with self.assertRaisesRegex(team.GuardError, "initial commit"):
            self.start()
        self.assertEqual(self.repo.snapshot(), before)
        self.assertFalse(self.repo.registry.exists())

    def test_dirty_student_checkout_and_staged_work_survive_task_commit(self):
        baseline = self.seed()
        (self.root / "student.txt").write_text("student's staged progress\n", encoding="utf-8")
        self.run_git(self.root, "add", "--", "student.txt")
        (self.root / "student draft.txt").write_text("untracked progress", encoding="utf-8")
        before = self.run_git(self.root, "status", "--porcelain=v1", "-z")
        index = self.run_git(self.root, "write-tree")
        task = self.start()
        work = Path(task["worktree"])
        self.assertEqual((work / "student.txt").read_text(), "student's base\n")
        self.assertFalse((work / "student draft.txt").exists())
        (work / "feature.txt").write_text("new feature\n", encoding="utf-8")
        result = self.checkpoint(task)
        self.assertEqual(result["result"], "committed")
        self.assertEqual(self.run_git(self.root, "status", "--porcelain=v1", "-z"), before)
        self.assertEqual(self.run_git(self.root, "write-tree"), index)
        self.assertEqual(self.repo.head(), baseline)
        self.assertEqual(self.repo.branch(), "main")
        self.assertEqual((self.root / "student draft.txt").read_text(), "untracked progress")

    def test_disjoint_tasks_and_case_directory_overlap(self):
        self.seed()
        self.start()
        self.start(task="other", owner="session-c", paths=["student.txt"])
        with self.assertRaisesRegex(team.GuardError, "overlapping"):
            self.start(task="collision", owner="session-d")
        self.start(task="directory", owner="session-e", paths=["src/"])
        with self.assertRaisesRegex(team.GuardError, "overlapping"):
            self.start(task="nested", owner="session-f", paths=["src/new/file.txt"])
        if self.repo.casefold:
            with self.assertRaisesRegex(team.GuardError, "overlapping"):
                self.start(task="case", owner="session-g", paths=["FEATURE.txt"])

    def test_concurrent_claims_have_one_winner(self):
        self.seed()
        def attempt(owner):
            return subprocess.run([sys.executable, "-B", str(HELPER), "start", "--repo", str(self.root),
                                   "--owner", owner, "--task", owner, "--base", "HEAD", "--paths", "feature.txt"], capture_output=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(attempt, ["student-a", "student-b"]))
        self.assertEqual(sorted(p.returncode for p in outcomes), [0, 2])
        self.assertEqual(len(team.load_state(self.repo)["tasks"]), 1)

    def test_existing_task_reuses_by_resume_without_duplicate_branch(self):
        self.seed()
        task = self.start()
        with self.assertRaisesRegex(team.GuardError, "already exists"):
            self.start()
        resumed = self.command(task, "resume")
        self.assertEqual(resumed["worktree"], task["worktree"])
        self.assertEqual(len(team.load_state(self.repo)["tasks"]), 1)

    def test_foreign_staged_content_is_preserved(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "student.txt").write_text("another person's staged work\n")
        self.run_git(work, "add", "--", "student.txt")
        index = self.run_git(work, "write-tree")
        (work / "feature.txt").write_text("feature change\n")
        with self.assertRaisesRegex(team.GuardError, "Existing staged"):
            self.checkpoint(task)
        self.assertEqual(self.run_git(work, "write-tree"), index)
        self.assertEqual(team.Repo(work).head(), task["base"])

    def test_unclaimed_edits_and_wrong_owner_stop_without_staging(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "unknown.txt").write_text("student draft")
        with self.assertRaisesRegex(team.GuardError, "Unclaimed"):
            self.checkpoint(task)
        with self.assertRaisesRegex(team.GuardError, "another owner"):
            self.command(task, "claim", "--paths", "unknown.txt", owner="intruder")
        self.assertEqual(team.Repo(work).staged(), [])

    def test_exact_literal_unicode_and_space_paths(self):
        self.seed()
        files = ["[student].txt", "student.txt", "日本語 notes.txt"]
        task = self.start(paths=files)
        work = Path(task["worktree"])
        for name in files:
            (work / name).write_text("owned content\n", encoding="utf-8")
        preview = self.checkpoint(task, dry=True)
        self.assertEqual(set(preview["paths"]), set(files))
        self.assertEqual(team.Repo(work).staged(), [])
        commit = self.checkpoint(task)
        self.assertEqual(set(commit["paths"]), set(files))

    def test_hook_failure_and_targeted_recovery_preserve_files(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("owned draft\n")
        hook = self.hook("pre-commit", "exit 1")
        with self.assertRaises(team.GuardError):
            self.checkpoint(task)
        self.assertEqual(team.Repo(work).head(), task["base"])
        self.assertEqual(team.Repo(work).staged(), ["feature.txt"])
        self.command(task, "recover-index")
        self.assertEqual(team.Repo(work).staged(), [])
        self.assertEqual((work / "feature.txt").read_text(), "owned draft\n")
        hook.unlink()
        self.assertEqual(self.checkpoint(task)["result"], "committed")

    def test_recovery_refuses_a_changed_index(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("owned draft\n")
        self.hook("pre-commit", "exit 1")
        with self.assertRaises(team.GuardError):
            self.checkpoint(task)
        (work / "student.txt").write_text("foreign staged content\n")
        self.run_git(work, "add", "--", "student.txt")
        tree = self.run_git(work, "write-tree")
        with self.assertRaisesRegex(team.GuardError, "changed after"):
            self.command(task, "recover-index")
        self.assertEqual(self.run_git(work, "write-tree"), tree)

    def test_hook_tree_mutation_is_blocked_and_commit_retained(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("owned draft\n")
        self.hook("pre-commit", "printf 'hook change\\n' > injected.txt\ngit add -- injected.txt")
        with self.assertRaisesRegex(team.GuardError, "differed"):
            self.checkpoint(task)
        record = team.load_state(self.repo)["tasks"][task["id"]]
        self.assertEqual(record["status"], "blocked")
        self.assertNotEqual(team.Repo(work).head(), task["base"])
        self.assertEqual(self.run_git(work, "show", "HEAD:injected.txt"), b"hook change\n")
        with self.assertRaises(team.GuardError):
            self.command(task, "ready", "--summary", "done", "--verification", "unverified")

    def test_ready_release_and_resume_preserve_branches_and_worktrees(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("finished\n")
        with self.assertRaisesRegex(team.GuardError, "clean"):
            self.command(task, "ready", "--summary", "done", "--verification", "sandbox check")
        commit = self.checkpoint(task)["head"]
        ready = self.command(task, "ready", "--summary", "done", "--verification", "sandbox check passed")
        self.assertEqual(ready["status"], "ready")
        released = self.command(task, "release", "--reason", "completed")
        self.assertEqual(released["status"], "released")
        self.assertTrue(work.exists())
        self.assertEqual(self.run_git(self.root, "rev-parse", task["branch"]).decode().strip(), commit)
        second = self.start(task="followup", owner="session-c")
        with self.assertRaisesRegex(team.GuardError, "overlapping"):
            self.command(task, "resume")
        self.command(second, "release", "--reason", "cancelled")
        self.assertEqual(self.command(task, "resume")["status"], "active")

    def test_no_time_expiry_and_manual_head_move_refuses(self):
        self.seed()
        task = self.start()
        with team.Registry(self.repo) as reg:
            reg.state["tasks"][task["id"]]["updated_at"] = "2000-01-01T00:00:00Z"
            reg.save()
        with self.assertRaisesRegex(team.GuardError, "overlapping"):
            self.start(task="takeover", owner="session-c")
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("manual\n")
        self.run_git(work, "add", "--", "feature.txt")
        self.run_git(work, "commit", "-m", "manual commit")
        head = team.Repo(work).head()
        with self.assertRaisesRegex(team.GuardError, "HEAD changed"):
            self.checkpoint(task)
        self.assertEqual(team.Repo(work).head(), head)

    def test_traversal_git_paths_and_symlink_rejected(self):
        self.seed()
        for name in ("../escape.txt", ".git/config", "/tmp/escape", "C:/escape", "src/../escape", "src//file"):
            with self.assertRaises(team.GuardError, msg=name):
                self.start(task="bad", paths=[name])
        outside = self.workspace / "outside"
        outside.mkdir()
        link = self.root / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            return  # Windows may not allow symlink creation without Developer Mode.
        with self.assertRaisesRegex(team.GuardError, "Symlinks"):
            self.start(paths=["linked/file.txt"])

    def test_credentials_and_large_files_rejected_before_staging(self):
        self.seed()
        task = self.start(paths=[".env", "token.txt", "large.bin"])
        work = Path(task["worktree"])
        file = work / ".env"
        file.write_text("local-only setting\n")
        with self.assertRaisesRegex(team.GuardError, "credential file"):
            self.checkpoint(task)
        file.unlink()
        file = work / "token.txt"
        token = "ghp_" + "A" * 36
        file.write_text(token)
        with self.assertRaisesRegex(team.GuardError, "credential pattern") as error:
            self.checkpoint(task)
        self.assertNotIn(token, str(error.exception))
        file.unlink()
        (work / "large.bin").write_bytes(b"x" * (team.MAX_BLOB + 1))
        with self.assertRaisesRegex(team.GuardError, "limit"):
            self.checkpoint(task)
        self.assertEqual(team.Repo(work).staged(), [])

    def test_rename_requires_both_source_and_destination_claims(self):
        self.seed()
        task = self.start(paths=["renamed.txt"])
        work = Path(task["worktree"])
        (work / "feature.txt").rename(work / "renamed.txt")
        with self.assertRaisesRegex(team.GuardError, "Unclaimed"):
            self.checkpoint(task)
        self.command(task, "claim", "--paths", "feature.txt")
        self.assertEqual(set(self.checkpoint(task)["paths"]), {"feature.txt", "renamed.txt"})

    def test_corrupt_registry_fails_without_overwriting_it(self):
        self.seed()
        self.start()
        file = self.repo.registry / "state.json"
        file.write_bytes(b"{invalid json")
        with self.assertRaisesRegex(team.GuardError, "corrupt"):
            self.start(task="other", paths=["student.txt"])
        self.assertEqual(file.read_bytes(), b"{invalid json")

    def test_windows_case_claims_stay_exclusive_with_ignorecase_false(self):
        if os.name != "nt":
            self.skipTest("Windows filesystem scenario")
        self.seed()
        self.run_git(self.root, "config", "--local", "core.ignorecase", "false")
        self.repo = team.Repo(self.root)
        self.start()
        with self.assertRaisesRegex(team.GuardError, "overlapping"):
            self.start(task="same-file-case", owner="session-c", paths=["FEATURE.txt"])

    def test_verified_upstream_sync_excludes_inherited_student_changes(self):
        baseline = self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("student B feature\n")
        self.checkpoint(task)
        (self.root / "student.txt").write_text("student A completed progress\n")
        self.run_git(self.root, "add", "--", "student.txt")
        self.run_git(self.root, "commit", "-m", "student A completes task")
        target = self.repo.head()
        before = self.repo.snapshot()
        synced = self.command(task, "sync-base", "--target", "main")
        self.assertEqual(synced["base"], baseline)
        self.assertEqual(synced["review_base"], target)
        self.assertEqual((work / "student.txt").read_text(), "student A completed progress\n")
        self.assertEqual((work / "feature.txt").read_text(), "student B feature\n")
        self.assertEqual(self.repo.snapshot(), before)
        diff = team.names(self.run_git(work, "diff", target, "HEAD", "--name-only", "-z"))
        self.assertEqual(diff, ["feature.txt"])
        self.assertEqual(self.command(task, "ready", "--summary", "B feature", "--verification", "scenario passed")["status"], "ready")

    def test_conflicting_upstream_sync_can_be_resolved_and_recovered(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("student B feature\n")
        self.checkpoint(task)
        (self.root / "feature.txt").write_text("student A feature\n")
        self.run_git(self.root, "add", "--", "feature.txt")
        self.run_git(self.root, "commit", "-m", "student A update")
        target = self.repo.head()
        with self.assertRaises(team.GuardError):
            self.command(task, "sync-base", "--target", "main")
        record = team.load_state(self.repo)["tasks"][task["id"]]
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["sync_attempt"]["target"], target)
        (work / "feature.txt").write_text("student A feature\nstudent B feature\n")
        self.run_git(work, "add", "--", "feature.txt")
        self.run_git(work, "commit", "-m", "merge: preserve both student features")
        recovered = self.command(task, "recover-sync")
        self.assertEqual(recovered["status"], "active")
        self.assertEqual(recovered["review_base"], target)
        self.assertEqual((work / "feature.txt").read_text(), "student A feature\nstudent B feature\n")

    def test_checkpoint_crash_after_commit_recovers_without_duplicate(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("recoverable feature\n")
        code = (
            "import importlib.util, os\n"
            f"spec = importlib.util.spec_from_file_location('team_git', {str(HELPER)!r})\n"
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
            "original = module.Registry.save\ncalls = 0\n"
            "def crash(self):\n global calls\n calls += 1\n if calls == 3: os._exit(71)\n original(self)\n"
            "module.Registry.save = crash\n"
            f"args = module.parser().parse_args({['checkpoint', '--repo', str(self.root), '--owner', task['owner'], '--task-id', task['id'], '--message', 'feat: interrupted state save']!r})\n"
            "module.do_task(module.Repo(args.repo), args)\n"
        )
        child = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True)
        self.assertEqual(child.returncode, 71, child.stderr)
        head = team.Repo(work).head()
        self.assertNotEqual(head, task["base"])
        self.assertIn("attempt", team.load_state(self.repo)["tasks"][task["id"]])
        recovered = self.command(task, "recover-commit")
        self.assertEqual(recovered["last_head"], head)
        self.assertEqual(team.Repo(work).head(), head)
        self.assertEqual(len(recovered["checkpoints"]), 1)
        self.assertNotIn("attempt", recovered)

    def test_explicit_new_branch_and_existing_branch_protection(self):
        self.seed()
        args = team.parser().parse_args(["start", "--repo", str(self.root), "--owner", "session-b",
                                        "--task", "feature", "--base", "HEAD", "--branch", "student/feature", "--paths", "feature.txt"])
        task = team.do_start(self.repo, args)
        self.assertEqual(team.Repo(task["worktree"]).branch(), "student/feature")
        args.task = "other"
        args.paths = ["student.txt"]
        with self.assertRaisesRegex(team.GuardError, "already exists"):
            team.do_start(self.repo, args)

    def test_cancelled_task_cannot_recover_and_steal_new_claim(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("owned progress\n")
        self.hook("pre-commit", "exit 1")
        with self.assertRaises(team.GuardError):
            self.checkpoint(task)
        self.command(task, "release", "--reason", "cancelled")
        self.start(task="next", owner="session-c")
        with self.assertRaisesRegex(team.GuardError, "reacquired"):
            self.command(task, "recover-index")

    def test_credential_in_commit_message_is_rejected_without_staging(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("safe feature\n")
        token = "ghp_" + "B" * 36
        with self.assertRaisesRegex(team.GuardError, "credential pattern") as error:
            self.command(task, "checkpoint", "--message", "feat: " + token)
        self.assertNotIn(token, str(error.exception))
        self.assertEqual(team.Repo(work).staged(), [])

    def test_invalid_structured_task_record_is_preserved(self):
        self.seed()
        task = self.start()
        file = self.repo.registry / "state.json"
        data = json.loads(file.read_text())
        del data["tasks"][task["id"]]["checkpoints"]
        file.write_text(json.dumps(data))
        before = file.read_bytes()
        with self.assertRaisesRegex(team.GuardError, "corrupt"):
            self.command(task, "resume")
        self.assertEqual(file.read_bytes(), before)

    def test_recorded_merge_abort_can_resume_without_losing_feature(self):
        self.seed()
        task = self.start()
        work = Path(task["worktree"])
        (work / "feature.txt").write_text("student B feature\n")
        own_head = self.checkpoint(task)["head"]
        (self.root / "feature.txt").write_text("student A feature\n")
        self.run_git(self.root, "add", "--", "feature.txt")
        self.run_git(self.root, "commit", "-m", "student A update")
        with self.assertRaises(team.GuardError):
            self.command(task, "sync-base", "--target", "main")
        self.run_git(work, "merge", "--abort")
        recovered = self.command(task, "recover-sync", "--aborted")
        self.assertEqual(recovered["status"], "active")
        self.assertEqual(recovered["last_head"], own_head)
        self.assertEqual(recovered["review_base"], task["base"])
        self.assertEqual((work / "feature.txt").read_text(), "student B feature\n")

    def test_windows_ambiguous_device_and_alias_paths_refused(self):
        if os.name != "nt":
            self.skipTest("Windows filesystem scenario")
        self.seed()
        for name in ("NUL.txt", "feature.txt.", "feature.txt ", "COM1", "src/file?.txt", "src/evil\".txt"):
            with self.assertRaisesRegex(team.GuardError, "Windows"):
                self.start(paths=[name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
