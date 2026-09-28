import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from moregan import processes
from moregan.adapters import AgentAdapterScaffolder
from moregan.agent_worker import AgentWorkerRunner, build_parser
from moregan.processes import (
    MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, ProcessCleanupInterrupted, ProcessResult, run_bounded, supervised_adapter,
)
from moregan.runtime import MoreGANRuntime, RiskClassifier
from moregan.workers import CommandWorker, WorkerCommand, WorkerConfigError, WorkerConfigLoader, WorkerContext
from moregan.workspaces import WorkerWorkspace


class ProviderExecutionFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()
        self.prompt = self.root / "prompt.md"
        self.prompt.write_text("Review carefully.", encoding="utf-8")
        self.context = WorkerContext(self.root, "test", "Change copy", RiskClassifier().classify("Change copy"), [], attempt=2)
        self.payload = dict(stage="evaluator", verdict="pass", confidence=1)
        self.reply = f"print({json.dumps(self.payload)!r}, flush=True)"

    def run_adapter(self, adapter, code, output=MAX_OUTPUT_BYTES, prompt=MAX_INPUT_BYTES, timeout=1):
        command = [sys.executable, "-c", code]
        if adapter == "command":
            worker = CommandWorker(WorkerCommand("evaluator", command, timeout, False, "test", "repository", output, prompt))
            return worker.run(self.context)
        with patch.dict(os.environ, {f"MOREGAN_{adapter.upper()}_COMMAND": json.dumps(command), "MOREGAN_ATTEMPT": "2"}):
            return AgentWorkerRunner(adapter, "evaluator", self.prompt, self.root, timeout, output, prompt).run()


class ProviderExecutionTests(ProviderExecutionFixture, unittest.TestCase):
    def test_output_limits_reject_whitespace_plus_valid_json_at_every_boundary(self):
        code = "import sys; sys.stdin.read(); sys.stdout.write(' ' * 4096); " + self.reply
        for adapter in ("command", "codex", "claude"):
            with self.subTest(adapter=adapter):
                result = self.run_adapter(adapter, code, output=512)
                self.assertEqual(result.verdict, "fail")
                self.assertIn("exceeded 512 bytes", result.findings[0].description)
                self.assertTrue(any("error_kind=output_limit" in item.summary for item in result.evidence))
                self.assertEqual(result.attempt, 2)
                json.dumps(asdict(result), allow_nan=False)

    def test_invalid_utf8_inside_otherwise_valid_json_fails(self):
        raw = json.dumps(dict(self.payload, evidence=[dict(kind="test", name="test", summary="TEXT")])).encode().replace(b"TEXT", b"bad\xff")
        code = f"import sys; sys.stdin.read(); sys.stdout.buffer.write({raw!r})"
        for adapter in ("command", "codex", "claude"):
            with self.subTest(adapter=adapter):
                result = self.run_adapter(adapter, code)
                self.assertEqual(result.verdict, "fail")
                self.assertIn("UTF-8", result.findings[0].description)

    def test_large_stderr_is_bounded_advisory_and_does_not_deadlock(self):
        code = "import sys, os; sys.stdin.read()\nfor _ in range(128): os.write(2, b'x' * 65536)\n" + self.reply
        for adapter in ("command", "codex", "claude"):
            with self.subTest(adapter=adapter):
                result = self.run_adapter(adapter, code, timeout=5)
                self.assertEqual(result.verdict, "pass")
                self.assertTrue(any("stderr_bytes=8388608; stderr_truncated=True" in item.summary for item in result.evidence))

    def test_strict_limit_stops_continuous_output_with_bounded_memory(self):
        tracemalloc.start()
        try:
            result = run_bounded([sys.executable, "-c", "import os\nwhile True: os.write(1, b'x' * 65536)"],
                                 self.root, strict_stdout=True, max_output_bytes=1024, timeout_seconds=5)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(result.error_kind, "output_limit")
        self.assertLessEqual(result.stdout_bytes, 1024 + 65536)
        self.assertLess(peak, 2 * 1024 * 1024)
        self.assertEqual(len(result.stdout_tail), 1024)

    def test_exact_output_limit_is_accepted_and_multibyte_utf8_preserved(self):
        raw = json.dumps(dict(self.payload, evidence=[dict(kind="test", name="test", summary="\u00e9")]), ensure_ascii=False).encode()
        result = run_bounded([sys.executable, "-c", f"import os; os.write(1, {raw!r})"], self.root,
                             strict_stdout=True, max_output_bytes=len(raw))
        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(result.error_kind)
        self.assertEqual(result.stdout_tail.encode(), raw)
        self.assertFalse(result.stdout_truncated)

    def test_prompt_delivery_and_both_output_streams_progress_together(self):
        data = b"request" * 100000
        code = ("import sys, os\n"
                "os.write(1, b'o' * 131072)\nos.write(2, b'e' * 131072)\n"
                f"assert sys.stdin.buffer.read() == {data[:7]!r} * 100000\n")
        result = run_bounded([sys.executable, "-c", code], self.root, input_bytes=data, timeout_seconds=5)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout_bytes, 131072)
        self.assertEqual(result.stderr_bytes, 131072)

    def test_blocked_stdin_obeys_deadline_and_keeps_partial_output(self):
        start = time.monotonic()
        result = run_bounded([sys.executable, "-c", "import time; print('started', flush=True); time.sleep(60)"],
                             self.root, input_bytes=b"x" * MAX_INPUT_BYTES, timeout_seconds=1)
        self.assertTrue(result.timed_out)
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(result.stdout_tail, "started\n")

    def test_provider_wrappers_also_bound_blocked_prompt_delivery(self):
        self.prompt.write_text("x" * (MAX_INPUT_BYTES // 2))
        for adapter in ("codex", "claude"):
            with self.subTest(adapter=adapter):
                start = time.monotonic()
                result = self.run_adapter(adapter, "import time; time.sleep(60)")
                self.assertEqual(result.verdict, "fail")
                self.assertIn("timed out", result.findings[0].description)
                self.assertLess(time.monotonic() - start, 4)

    def test_early_stdin_close_cannot_pass_with_partial_prompt(self):
        code = "import os, time; os.close(0); print('{}', flush=True); time.sleep(5)"
        result = run_bounded([sys.executable, "-c", code], self.root, input_bytes=b"x" * MAX_INPUT_BYTES,
                             strict_stdout=True, timeout_seconds=2)
        self.assertEqual(result.error_kind, "input_delivery")

    def test_input_limits_are_validated_before_launch(self):
        for kwargs in (dict(input_bytes="text"), dict(input_bytes=b"x" * (MAX_INPUT_BYTES + 1)),
                       dict(input_bytes=b"xx", max_input_bytes=1), dict(max_input_bytes=True),
                       dict(max_input_bytes=MAX_INPUT_BYTES + 1)):
            with self.subTest(kwargs=str(kwargs)[:80]), patch("moregan.processes.subprocess.Popen") as launch:
                with self.assertRaises(ValueError):
                    run_bounded(["provider"], self.root, **kwargs)
                launch.assert_not_called()

    def test_oversize_template_and_runtime_context_fail_before_launch(self):
        for adapter in ("codex", "claude"):
            for content, request in (("x" * 2000, ""), ("small", "x" * 2000), ("\u00e9" * 600, "")):
                with self.subTest(adapter=adapter, length=len(content)), patch.dict(os.environ, {"MOREGAN_REQUEST": request}):
                    self.prompt.write_text(content, encoding="utf-8")
                    with patch("moregan.agent_worker.run_bounded") as launch:
                        result = self.run_adapter(adapter, "pass", prompt=1024)
                    launch.assert_not_called()
                    self.assertEqual(result.verdict, "fail")
                    self.assertIn("exceeds 1024", result.findings[0].description)

    def test_prompt_limit_includes_runtime_formatting(self):
        self.prompt.write_text("x" * 700)
        result = self.run_adapter("codex", "pass", prompt=1024)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("runtime context exceeds", result.findings[0].description)

    def test_invalid_utf8_prompt_fails_before_launch(self):
        self.prompt.write_bytes(b"invalid\xff")
        with patch("moregan.agent_worker.run_bounded") as launch:
            self.assertEqual(self.run_adapter("codex", "pass").verdict, "fail")
        launch.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX FIFO")
    def test_fifo_prompt_is_rejected_without_blocking(self):
        self.prompt.unlink()
        os.mkfifo(self.prompt)
        start = time.monotonic()
        result = self.run_adapter("codex", "pass")
        self.assertEqual(result.verdict, "fail")
        self.assertIn("regular file", result.findings[0].description)
        self.assertLess(time.monotonic() - start, 1)

    def test_worker_limits_are_strict_and_unknown_settings_rejected(self):
        loader = WorkerConfigLoader(self.root)
        valid = dict(stage="evaluator", command=["provider"])
        for field, maximum in (("max_output_bytes", MAX_OUTPUT_BYTES), ("max_prompt_bytes", MAX_INPUT_BYTES),
                               ("timeout_seconds", 86400)):
            for value in (None, True, "100", 0, -1, 1.5, maximum + 1):
                with self.subTest(field=field, value=value), self.assertRaises(WorkerConfigError):
                    loader._coerce_worker(dict(valid, **{field: value}))
        for key in ("max_output_byte", "max_prompt_byte", "timeout_second"):
            with self.assertRaises(WorkerConfigError):
                loader._coerce_worker(dict(valid, **{key: 100}))
        command = loader._coerce_worker(dict(valid, max_output_bytes=4096, max_prompt_bytes=8192))
        self.assertEqual((command.max_output_bytes, command.max_prompt_bytes), (4096, 8192))

    def test_agent_limits_are_strict(self):
        for field in ("max_output_bytes", "max_prompt_bytes", "timeout_seconds"):
            for value in (None, True, "100", 0, -1, 1.5, MAX_INPUT_BYTES + 1):
                with self.subTest(field=field, value=value):
                    runner = AgentWorkerRunner("codex", "evaluator", self.prompt, self.root, 1)
                    setattr(runner, field, value)
                    self.assertEqual(runner.run().verdict, "fail")

    def test_scaffold_limits_and_cli_inheritance(self):
        for provider in ("codex", "claude"):
            AgentAdapterScaffolder(self.root).scaffold(provider, activate=True, force=True)
            commands = WorkerConfigLoader(self.root).load()
            self.assertTrue(all(command.max_output_bytes == MAX_OUTPUT_BYTES for command in commands))
            self.assertTrue(all(command.max_prompt_bytes == MAX_INPUT_BYTES for command in commands))
        with patch.dict(os.environ, {"MOREGAN_WORKER_TIMEOUT_SECONDS": "600", "MOREGAN_MAX_OUTPUT_BYTES": "2048",
                                    "MOREGAN_MAX_PROMPT_BYTES": "4096"}):
            args = build_parser().parse_args(["--provider", "codex", "--stage", "generator", "--prompt", "file"])
        self.assertEqual((args.timeout, args.max_output_bytes, args.max_prompt_bytes), (600, 2048, 4096))

    def test_stale_supervisor_marker_does_not_disable_standalone_cleanup(self):
        with patch.dict(os.environ, {processes.SUPERVISOR_ENV: "invalid"}):
            self.assertFalse(supervised_adapter())

    def test_cleanup_failure_retains_snapshot_and_skips_checkout_verification(self):
        worker = CommandWorker(WorkerCommand("evaluator", ["provider"], 1, True, "test"))
        failure = ProcessResult(125, error_kind="cleanup_error", reason="Could not confirm command cleanup")
        with patch("moregan.workers.run_bounded", return_value=failure):
            result = worker.run(self.context)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("worker_cleanup_failed", [item.category for item in result.findings])
        self.assertTrue(any(item.name == "no_write_check_unverified" for item in result.evidence))
        execution = next(item.path for item in result.evidence if item.kind == "execution_context")
        retained = Path(execution)
        workspace = WorkerWorkspace(self.root, True, "evaluator")
        workspace.temporary_root = retained.parent
        workspace.execution_root = retained
        self.addCleanup(workspace.cleanup)
        self.assertTrue(retained.is_dir())

    def test_runtime_stops_before_reassessment_on_generator_cleanup_failure(self):
        config = self.root / ".moregan" / "workers.yaml"
        config.parent.mkdir()
        payload = dict(stage="generator", verdict="fail", confidence=1, findings=[dict(
            severity="high", category="worker_cleanup_failed", description="Cleanup unconfirmed", remediation="Inspect")])
        command = [sys.executable, "-c", f"print({json.dumps(payload)!r})"]
        config.write_text(f"workers:\n  - stage: generator\n    command: {json.dumps(command)}\n    no_write: false\n")
        runtime = MoreGANRuntime(self.root, max_remediation_attempts=3)
        with patch.object(runtime, "_reassess_risk") as reassess:
            result = runtime.run("Change copy", run_checks=False)
        reassess.assert_not_called()
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.state["remediation_attempts"], 0)
        self.assertIn("worker.manual_review_required", (Path(result.trace_path) / "events.jsonl").read_text())

    def test_interrupted_unconfirmed_cleanup_retains_snapshot_and_warns(self):
        snapshot = Path(self.directory.name) / "retained"
        snapshot.mkdir()
        worker = CommandWorker(WorkerCommand("evaluator", ["provider"], 1, True, "test"))
        with patch("moregan.workspaces.tempfile.mkdtemp", return_value=str(snapshot)), \
                patch("moregan.workers.run_bounded", side_effect=ProcessCleanupInterrupted("cleanup failed")):
            with self.assertWarnsRegex(RuntimeWarning, "snapshot cleanup failed"), self.assertRaises(KeyboardInterrupt):
                worker.run(self.context)
        self.assertTrue((snapshot / "checkout" / "prompt.md").is_file())

    @unittest.skipUnless(os.name == "posix", "POSIX interruption")
    def test_process_cleanup_error_preserves_interruption_and_marks_uncertain_cleanup(self):
        popen = subprocess.Popen
        started = []

        def remember(*args, **kwargs):
            process = popen(*args, **kwargs)
            started.append(process)
            return process

        try:
            with patch("moregan.processes.subprocess.Popen", side_effect=remember), \
                    patch("moregan.processes._drain_posix", side_effect=KeyboardInterrupt), \
                    patch("moregan.processes._kill", side_effect=PermissionError("cleanup denied")):
                with self.assertRaisesRegex(ProcessCleanupInterrupted, "cleanup denied"):
                    run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], self.root)
            self.assertTrue(all(process.stdout.closed and process.stderr.closed for process in started))
        finally:
            for process in started:
                processes._kill(process)
                process.wait(timeout=2)


@unittest.skipUnless(os.name == "posix", "POSIX process-group supervision")
class NestedProviderProcessTests(ProviderExecutionFixture, unittest.TestCase):
    # These tests use actual nested CLI wrappers, never model/provider APIs.
    def run_nested(self, provider, mode, inner_timeout=10):
        heartbeat = Path(self.directory.name) / "heartbeat"
        pid_path = Path(self.directory.name) / "pid"
        child = ("import pathlib, time, signal\n"
                 "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                 f"p = pathlib.Path({str(heartbeat)!r})\n"
                 "while True:\n p.write_text(str(time.time_ns()))\n time.sleep(0.02)\n")
        redirect = ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" if mode == "success" else ""
        code = ("import sys, pathlib, subprocess, time; sys.stdin.read(); "
                f"p = subprocess.Popen([sys.executable, '-c', {child!r}]{redirect}); "
                f"pathlib.Path({str(pid_path)!r}).write_text(str(p.pid)); "
                "time.sleep(0.15); " + self.reply)
        if mode == "output_limit":
            code += "; sys.stdout.write(' ' * 2097152); sys.stdout.flush()"
        if mode not in ("success", "parent_exit"):
            code += "; time.sleep(60)"
        command = [sys.executable, "-m", "moregan.agent_worker", "--provider", provider, "--stage", "evaluator",
                   "--prompt", "prompt.md", "--timeout", str(inner_timeout)]
        worker = CommandWorker(WorkerCommand("evaluator", command, 4 if inner_timeout == 1 else 1, True, "test"))
        env = {f"MOREGAN_{provider.upper()}_COMMAND": json.dumps([sys.executable, "-c", code]),
               "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        try:
            with patch.dict(os.environ, env):
                result = worker.run(self.context)
            self.assertEqual(result.verdict, "pass" if mode == "success" else "fail")
            self.assertTrue(pid_path.is_file())
            removed = next(item.path for item in result.evidence if item.name == "snapshot_removed")
            self.assertFalse(Path(removed).exists())
            self.assertTrue(any(item.name == "no_write_check" and "0 changed" in item.summary for item in result.evidence))
            time.sleep(0.1)
            before = heartbeat.read_text()
            time.sleep(0.15)
            self.assertEqual(heartbeat.read_text(), before, "nested descendant survived worker cleanup")
        except KeyboardInterrupt:
            time.sleep(0.1)
            before = heartbeat.read_text()
            time.sleep(0.15)
            self.assertEqual(heartbeat.read_text(), before, "nested descendant survived interruption")
            raise
        finally:
            if pid_path.exists():
                try:
                    os.kill(int(pid_path.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_outer_timeout_kills_actual_provider_and_descendants(self):
        for provider in ("codex", "claude"):
            with self.subTest(provider=provider):
                self.run_nested(provider, "hang")

    def test_inner_timeout_uses_outer_group_cleanup(self):
        for provider in ("codex", "claude"):
            with self.subTest(provider=provider):
                self.run_nested(provider, "hang", inner_timeout=1)

    def test_parent_exit_with_open_pipes_still_times_out_and_cleans_group(self):
        self.run_nested("codex", "parent_exit")

    def test_success_cleans_background_descendants_before_workspace_cleanup(self):
        self.run_nested("claude", "success")

    def test_rejected_output_also_cleans_nested_descendants(self):
        self.run_nested("codex", "output_limit")

    def test_interruption_cleans_group_and_snapshot(self):
        drain = processes._drain_posix
        popen = subprocess.Popen
        started = []
        snapshots = []
        prepare = WorkerWorkspace.prepare

        def remember(*args, **kwargs):
            process = popen(*args, **kwargs)
            started.append(process)
            return process

        def snapshot(workspace):
            path = prepare(workspace)
            snapshots.append(path)
            return path

        def interrupt(process, stdout, stderr, deadline, input_bytes):
            if "moregan.agent_worker" not in process.args:
                return drain(process, stdout, stderr, deadline, input_bytes)
            pid = Path(self.directory.name) / "pid"
            heartbeat = Path(self.directory.name) / "heartbeat"
            until = time.monotonic() + 3
            while (not pid.exists() or not heartbeat.exists()) and time.monotonic() < until:
                time.sleep(0.01)
            raise KeyboardInterrupt

        with patch("moregan.processes._drain_posix", side_effect=interrupt), \
                patch("moregan.processes.subprocess.Popen", side_effect=remember), \
                patch.object(WorkerWorkspace, "prepare", snapshot):
            with self.assertRaises(KeyboardInterrupt):
                self.run_nested("codex", "hang")
        self.assertTrue(all(process.poll() is not None for process in started))
        self.assertTrue(snapshots)
        self.assertTrue(all(not path.exists() for path in snapshots))


if __name__ == "__main__":
    unittest.main()
