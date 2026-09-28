import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from moregan.processes import ProcessResult
from moregan.runtime import MoreGANRuntime, RiskClassifier
from moregan.workers import CommandWorker, WorkerCommand, WorkerContext
from moregan.workspaces import CheckoutFingerprint, WorkspaceCheckError


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()
        self.snapshots = Path(self.directory.name) / "snapshots"
        self.snapshots.mkdir()
        original_mkdtemp = tempfile.mkdtemp
        self.patch = patch("moregan.workspaces.tempfile.mkdtemp",
                           side_effect=lambda **kwargs: original_mkdtemp(dir=self.snapshots, **kwargs))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.context = WorkerContext(self.root, "workspace-test", "Change copy",
                                     RiskClassifier().classify("Change copy"), ["evaluator"])
        self.reply = "print('{\"stage\": \"evaluator\", \"verdict\": \"pass\", \"confidence\": 1}')"

    def worker(self, code=None, no_write=True, execution="auto", timeout=5, command=None):
        return CommandWorker(WorkerCommand("evaluator", command or [sys.executable, "-c", code or self.reply],
                                           timeout, no_write, "test", execution))

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def init_git(self):
        self.git("init")
        self.git("config", "user.name", "MoreGAN Test")
        self.git("config", "user.email", "test@example.com")
        (self.root / "tracked.txt").write_text("base\n")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "fixture")

    def assert_cleaned(self, result):
        self.assertEqual(list(self.snapshots.iterdir()), [])
        cleanup = next(item for item in result.evidence if item.kind == "workspace_cleanup")
        self.assertEqual(cleanup.name, "snapshot_removed")
        self.assertFalse(Path(cleanup.path).exists())

    def assert_violation(self, result, name):
        self.assertEqual(result.verdict, "fail")
        findings = [finding for finding in result.findings if finding.category == "no_write_violation"]
        self.assertEqual(len(findings), 1, result)
        self.assertIn(name, findings[0].description)
        self.assertIn("No files were restored", result.evidence[-1].summary)

    def test_isolated_success_allows_scratch_files_and_removes_snapshot(self):
        (self.root / "tracked.txt").write_text("user edit\n")
        code = "import pathlib; pathlib.Path('tracked.txt').write_text('scratch'); " + self.reply
        result = self.worker(code).run(self.context)
        self.assertEqual(result.verdict, "pass")
        self.assertEqual((self.root / "tracked.txt").read_text(), "user edit\n")
        self.assert_cleaned(result)
        self.assertTrue(any(item.kind == "workspace_integrity" for item in result.evidence))

    def test_isolated_provider_failures_and_invalid_payloads_remove_snapshot(self):
        for code in ("raise SystemExit(7)", "print('not JSON')", "print('{}')",
                     "import os; os.write(1, b'\\xff')"):
            with self.subTest(code=code):
                result = self.worker(code).run(self.context)
                self.assertEqual(result.verdict, "fail")
                self.assert_cleaned(result)
        result = self.worker(command=["definitely-not-a-moregan-worker"]).run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assert_cleaned(result)

    def test_isolated_timeout_removes_snapshot(self):
        code = "import pathlib, time; pathlib.Path('scratch').touch(); print('waiting', flush=True); time.sleep(60)"
        result = self.worker(code, timeout=1).run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("timed out", result.findings[0].description)
        self.assert_cleaned(result)

    def test_interruption_and_unexpected_error_remove_snapshot(self):
        for error in (KeyboardInterrupt, RuntimeError("unexpected")):
            with self.subTest(error=error):
                with patch.object(CommandWorker, "_run_command", side_effect=error):
                    with self.assertRaises(KeyboardInterrupt if error is KeyboardInterrupt else RuntimeError):
                        self.worker().run(self.context)
                self.assertEqual(list(self.snapshots.iterdir()), [])

    def test_partial_copy_failure_and_interruption_remove_allocated_directory(self):
        for error in (OSError("disk full"), KeyboardInterrupt):
            def copy(source, destination, **kwargs):
                destination.mkdir()
                (destination / "partial").touch()
                raise error
            with self.subTest(error=error), patch("moregan.workspaces.shutil.copytree", side_effect=copy):
                if error is KeyboardInterrupt:
                    with self.assertRaises(KeyboardInterrupt):
                        self.worker().run(self.context)
                else:
                    result = self.worker().run(self.context)
                    self.assertEqual(result.verdict, "fail")
                    self.assertIn("disk full", result.findings[0].description)
                    self.assert_cleaned(result)
                self.assertEqual(list(self.snapshots.iterdir()), [])

    def test_context_copy_failure_removes_snapshot(self):
        with patch.object(CommandWorker, "_context_pack_for_execution", side_effect=OSError("unreadable context")):
            result = self.worker().run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assert_cleaned(result)

    def test_cleanup_failure_is_reported_and_cannot_pass(self):
        with patch("moregan.workspaces.shutil.rmtree", side_effect=PermissionError("denied")):
            result = self.worker().run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("workspace_cleanup_failed", [item.category for item in result.findings])
        self.assertFalse(any(item.kind == "workspace_cleanup" for item in result.evidence))
        self.assertEqual(len(list(self.snapshots.iterdir())), 1)
        self.assertIn(str(self.snapshots), result.findings[0].description)

    def test_cleanup_failure_does_not_mask_interruption(self):
        with patch.object(CommandWorker, "_run_command", side_effect=KeyboardInterrupt):
            with patch("moregan.workspaces.shutil.rmtree", side_effect=PermissionError("denied")):
                with self.assertWarnsRegex(RuntimeWarning, "snapshot cleanup failed"):
                    with self.assertRaises(KeyboardInterrupt):
                        self.worker().run(self.context)

    def test_cleanup_handles_readonly_files_and_symlinks_without_touching_targets(self):
        victim = Path(self.directory.name) / "outside.txt"
        victim.write_text("keep")
        code = ("import pathlib; p = pathlib.Path('readonly'); p.write_text('copy'); p.chmod(0o400); "
                f"pathlib.Path('external').symlink_to({str(victim)!r}); " + self.reply)
        result = self.worker(code).run(self.context)
        self.assertEqual(result.verdict, "pass")
        self.assert_cleaned(result)
        self.assertEqual(victim.read_text(), "keep")

    def test_write_enabled_repository_worker_does_not_delete_checkout(self):
        code = "import pathlib; pathlib.Path('output').write_text('generated'); " + self.reply
        result = self.worker(code, no_write=False, execution="repository").run(self.context)
        self.assertEqual(result.verdict, "pass")
        self.assertEqual((self.root / "output").read_text(), "generated")
        self.assertFalse(any(item.kind in {"workspace_integrity", "workspace_cleanup"} for item in result.evidence))

    @unittest.skipUnless(os.name == "posix", "POSIX directory permissions")
    def test_cleanup_handles_unreadable_snapshot_directory(self):
        code = ("import pathlib; p = pathlib.Path('private'); p.mkdir(); "
                "(p / 'scratch').write_text('temporary'); p.chmod(0); " + self.reply)
        result = self.worker(code).run(self.context)
        self.assertEqual(result.verdict, "pass")
        self.assert_cleaned(result)

    def test_write_enabled_isolated_worker_also_cleans_up(self):
        result = self.worker(no_write=False, execution="isolated").run(self.context)
        self.assertEqual(result.verdict, "pass")
        self.assert_cleaned(result)

    def test_dirty_tracked_file_change_is_detected_even_with_unchanged_size_and_mtime(self):
        self.init_git()
        path = self.root / "tracked.txt"
        path.write_text("user\n")
        (self.root / "untouched.txt").write_text("user work")
        status = self.git("status", "--porcelain")
        code = ("import pathlib, os; p = pathlib.Path('tracked.txt'); s = p.stat(); "
                "p.write_text('evil\\n'); os.utime(p, ns=(s.st_atime_ns, s.st_mtime_ns)); " + self.reply)
        result = self.worker(code, execution="repository").run(self.context)
        self.assertEqual(self.git("status", "--porcelain"), status)
        self.assert_violation(result, "tracked.txt")
        self.assertEqual(path.read_text(), "evil\n")
        self.assertEqual((self.root / "untouched.txt").read_text(), "user work")

    def test_dirty_and_untracked_files_are_preserved_when_worker_only_reads(self):
        self.init_git()
        (self.root / "tracked.txt").write_text("user work")
        (self.root / "new.txt").write_text("untracked")
        before = CheckoutFingerprint.capture(self.root)
        for execution in ("repository", "isolated"):
            result = self.worker(execution=execution).run(self.context)
            self.assertEqual(result.verdict, "pass")
            self.assertEqual(CheckoutFingerprint.capture(self.root), before)

    def test_untracked_edits_deletes_creates_and_renames_are_detected(self):
        self.init_git()
        cases = {
            "edit": "p.write_text('changed')",
            "delete": "p.unlink()",
            "rename": "p.rename('renamed.txt')",
            "create": "pathlib.Path('added.txt').touch()",
        }
        for case, mutation in cases.items():
            with self.subTest(case=case):
                for name in ("new.txt", "renamed.txt", "added.txt"):
                    (self.root / name).unlink(missing_ok=True)
                (self.root / "new.txt").write_text("before")
                code = "import pathlib; p = pathlib.Path('new.txt'); " + mutation + "; " + self.reply
                result = self.worker(code, execution="repository").run(self.context)
                self.assert_violation(result, "added.txt" if case == "create" else "new.txt")

    def test_git_index_only_change_is_detected(self):
        self.init_git()
        (self.root / "tracked.txt").write_text("staged by worker")
        code = "import subprocess; subprocess.run(['git', 'add', 'tracked.txt'], check=True); " + self.reply
        result = self.worker(code, execution="repository").run(self.context)
        self.assert_violation(result, ".git/index")
        self.assertEqual((self.root / "tracked.txt").read_text(), "staged by worker")

    def test_git_head_only_change_and_unborn_repository_are_supported(self):
        self.git("init")
        self.assertEqual(self.worker(execution="repository").run(self.context).verdict, "pass")
        self.init_git()
        code = ("import subprocess; subprocess.run(['git', 'checkout', '-b', 'worker-branch'], check=True, "
                "capture_output=True); " + self.reply)
        result = self.worker(code, execution="repository").run(self.context)
        self.assert_violation(result, ".git/HEAD-ref")

    def test_non_git_workspace_is_checked(self):
        (self.root / "source.txt").write_text("before")
        code = "import pathlib; pathlib.Path('source.txt').write_text('after'); " + self.reply
        self.assert_violation(self.worker(code, execution="repository").run(self.context), "source.txt")

    def test_git_worktree_metadata_and_dirty_content_are_checked(self):
        self.init_git()
        worktree = Path(self.directory.name) / "worktree"
        self.git("worktree", "add", "--detach", str(worktree), "HEAD")
        self.assertTrue((worktree / ".git").is_file())
        before = CheckoutFingerprint.capture(worktree)
        (worktree / "tracked.txt").write_text("dirty worktree")
        self.assertEqual(CheckoutFingerprint.capture(worktree).changes_from(before), ["tracked.txt"])

    def test_binary_contents_and_newline_filenames_are_fingerprinted(self):
        self.init_git()
        path = self.root / "odd\nfile.bin"
        path.write_bytes(b"\x00\xffbefore")
        self.git("add", path.name)
        before = CheckoutFingerprint.capture(self.root)
        path.write_bytes(b"\x00\xffafter!")
        self.assertEqual(CheckoutFingerprint.capture(self.root).changes_from(before), [path.name])

    def test_each_invocation_owns_a_fresh_snapshot(self):
        worker = self.worker()
        first = worker.run(self.context)
        second = worker.run(self.context)
        self.assert_cleaned(first)
        self.assert_cleaned(second)
        first_path = next(item.path for item in first.evidence if item.kind == "execution_context")
        second_path = next(item.path for item in second.evidence if item.kind == "execution_context")
        self.assertNotEqual(first_path, second_path)

    def test_isolated_absolute_path_write_to_base_is_detected(self):
        path = self.root / "source.txt"
        path.write_text("before")
        code = f"import pathlib; pathlib.Path({str(path)!r}).write_text('after'); " + self.reply
        result = self.worker(code).run(self.context)
        self.assert_violation(result, "source.txt")
        self.assertEqual(path.read_text(), "after")
        self.assert_cleaned(result)

    def test_violations_are_recorded_even_after_provider_failure_or_timeout(self):
        path = self.root / "source.txt"
        for ending in ("raise SystemExit(7)", "print('invalid JSON')", "import time; time.sleep(60)"):
            with self.subTest(ending=ending):
                path.write_text("before")
                code = "import pathlib; pathlib.Path('source.txt').write_text('after'); " + ending
                result = self.worker(code, execution="repository", timeout=1).run(self.context)
                self.assert_violation(result, "source.txt")
                self.assertEqual(len(result.findings), 2)

    def test_integrity_failure_before_launch_does_not_execute_provider(self):
        with patch("moregan.workers.CheckoutFingerprint.capture", side_effect=WorkspaceCheckError("unreadable")):
            with patch.object(CommandWorker, "_run_command") as execute:
                result = self.worker().run(self.context)
        execute.assert_not_called()
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.findings[0].category, "no_write_check_failed")
        self.assertEqual(list(self.snapshots.iterdir()), [])

    def test_integrity_failure_after_execution_cannot_pass(self):
        before = CheckoutFingerprint.capture(self.root)
        with patch("moregan.workers.CheckoutFingerprint.capture", side_effect=[before, WorkspaceCheckError("unreadable")]):
            result = self.worker().run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.findings[0].category, "no_write_check_failed")
        self.assert_cleaned(result)

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_checkout_replaced_with_symlink_loop_returns_verification_failure(self):
        code = (f"import pathlib; p = pathlib.Path({str(self.root)!r}); "
                "p.rename(p.with_name('moved-checkout')); p.symlink_to(p); " + self.reply)
        result = self.worker(code).run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.findings[0].category, "no_write_check_failed")
        self.assert_cleaned(result)

    def test_git_inspection_failure_or_truncation_cannot_verify_clean(self):
        self.init_git()
        for result in (ProcessResult(124, timed_out=True, error_kind="timeout", reason="timed out"),
                       ProcessResult(0, stdout_truncated=True), ProcessResult(127, error_kind="not_found")):
            with self.subTest(result=result), patch("moregan.workspaces.run_bounded", return_value=result):
                with self.assertRaises(WorkspaceCheckError):
                    CheckoutFingerprint.capture(self.root)

    def test_scan_limits_fail_closed(self):
        (self.root / "source.txt").write_text("content")
        for name, value in (("MAX_SCAN_FILES", 0), ("MAX_SCAN_BYTES", 0), ("SCAN_TIMEOUT_SECONDS", -1)):
            with self.subTest(name=name), patch("moregan.workspaces." + name, value):
                with self.assertRaises(WorkspaceCheckError):
                    CheckoutFingerprint.capture(self.root)

    @unittest.skipUnless(os.name == "posix", "POSIX file modes and symlinks")
    def test_modes_and_symlink_targets_are_verified_without_following_links(self):
        source = self.root / "source.txt"
        source.write_text("content")
        outside = Path(self.directory.name) / "outside"
        outside.write_text("private")
        (self.root / "link").symlink_to(outside)
        before = CheckoutFingerprint.capture(self.root)
        outside.write_text("not covered")
        self.assertEqual(CheckoutFingerprint.capture(self.root), before)
        source.chmod(0o755)
        (self.root / "link").unlink()
        (self.root / "link").symlink_to(source)
        self.assertEqual(CheckoutFingerprint.capture(self.root).changes_from(before), ["link", "source.txt"])

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_internal_absolute_and_relative_snapshot_links_target_only_copy(self):
        for absolute in (False, True):
            with self.subTest(absolute=absolute):
                path = self.root / "source.txt"
                path.write_text("user work")
                link = self.root / "link"
                link.unlink(missing_ok=True)
                link.symlink_to(path if absolute else "source.txt")
                code = "import pathlib; pathlib.Path('link').write_text('scratch'); " + self.reply
                result = self.worker(code).run(self.context)
                self.assertEqual(result.verdict, "pass")
                self.assertEqual(path.read_text(), "user work")
                self.assert_cleaned(result)

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_external_snapshot_link_is_rejected_without_reading_target(self):
        outside = Path(self.directory.name) / "outside"
        outside.write_text("private")
        (self.root / "external").symlink_to(outside)
        with patch.object(CommandWorker, "_run_command") as execute:
            result = self.worker().run(self.context)
        execute.assert_not_called()
        self.assertEqual(result.verdict, "fail")
        self.assertIn("escapes", result.findings[0].description)
        self.assert_cleaned(result)
        self.assertEqual(outside.read_text(), "private")

    def test_tracked_ignored_files_are_verified_but_generated_artifacts_are_excluded(self):
        self.init_git()
        (self.root / "build").mkdir()
        tracked = self.root / "build/important.txt"
        tracked.write_text("before")
        (self.root / ".gitignore").write_text("build/\n")
        self.git("add", "-f", "build/important.txt")
        before = CheckoutFingerprint.capture(self.root)
        (self.root / ".moregan/runs/example").mkdir(parents=True)
        (self.root / ".moregan/runs/example/log").write_text("generated")
        self.assertEqual(CheckoutFingerprint.capture(self.root), before)
        tracked.write_text("after")
        self.assertEqual(CheckoutFingerprint.capture(self.root).changes_from(before), ["build/important.txt"])

    def test_submodule_index_entry_fails_closed(self):
        self.init_git()
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.git("rev-parse", "HEAD").strip() + ",nested")
        with self.assertRaisesRegex(WorkspaceCheckError, "Submodules"):
            CheckoutFingerprint.capture(self.root)

    def test_snapshot_storage_inside_checkout_is_rejected_and_removed(self):
        self.patch.stop()
        location = self.root / "allocated"
        location.mkdir()
        with patch("moregan.workspaces.tempfile.mkdtemp", return_value=str(location)):
            result = self.worker().run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("outside the repository", result.findings[0].description)
        self.assertFalse(location.exists())
        self.assertTrue(self.root.exists())

    def test_context_pack_is_copied_for_execution_and_original_is_preserved(self):
        pack = self.root / ".moregan/runs/run/context.json"
        pack.parent.mkdir(parents=True)
        pack.write_text('{"context": true}')
        self.context.context_pack_path = str(pack)
        code = ("import os, pathlib; p = pathlib.Path(os.environ['MOREGAN_CONTEXT_PACK']); "
                "p.relative_to(pathlib.Path.cwd()); assert p.read_text() == '{\"context\": true}'; " + self.reply)
        result = self.worker(code).run(self.context)
        self.assertEqual(result.verdict, "pass")
        self.assert_cleaned(result)
        self.assertEqual(pack.read_text(), '{"context": true}')
        self.assertTrue(any(item.kind == "context_pack" and item.path == str(pack) for item in result.evidence))

    def test_runtime_persists_violation_and_cleanup_evidence(self):
        path = self.root / "source.txt"
        path.write_text("user work")
        code = f"import pathlib; pathlib.Path({str(path)!r}).write_text('unexpected'); " + self.reply
        folder = self.root / ".moregan"
        folder.mkdir()
        (folder / "workers.yaml").write_text("workers:\n  - stage: evaluator\n"
                                             f"    command: {json.dumps([sys.executable, '-c', code])}\n"
                                             "    no_write: true\n")
        result = MoreGANRuntime(self.root, max_remediation_attempts=3).run("Change copy", run_checks=False)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.state["remediation_attempts"], 0)
        saved = json.loads((Path(result.trace_path) / "stages/evaluator.json").read_text())
        self.assertEqual(saved["findings"][0]["category"], "no_write_violation")
        self.assertTrue(any(item["name"] == "snapshot_removed" for item in saved["evidence"]))
        self.assertIn("worker.manual_review_required", (Path(result.trace_path) / "events.jsonl").read_text())
        self.assertEqual(list(self.snapshots.iterdir()), [])
        json.dumps(asdict(result), allow_nan=False)

    def test_runtime_does_not_remediate_integrity_or_cleanup_errors(self):
        folder = self.root / ".moregan"
        folder.mkdir()
        for category in ("no_write_check_failed", "workspace_cleanup_failed"):
            with self.subTest(category=category):
                payload = dict(stage="evaluator", verdict="fail", confidence=1, findings=[dict(
                    severity="high", category=category, description="Workspace failure", remediation="Inspect manually")])
                command = [sys.executable, "-c", f"print({json.dumps(payload)!r})"]
                (folder / "workers.yaml").write_text("workers:\n  - stage: evaluator\n"
                                                     f"    command: {json.dumps(command)}\n    no_write: false\n")
                result = MoreGANRuntime(self.root, max_remediation_attempts=3).run("Change copy", run_checks=False)
                self.assertEqual(result.status, "fail")
                self.assertEqual(result.state["remediation_attempts"], 0)
                self.assertEqual(sum(stage.stage == "generator" for stage in result.stages), 1)


if __name__ == "__main__":
    unittest.main()
