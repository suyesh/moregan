import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from moregan.init import MoreGANInitializer
from moregan.processes import ProcessResult, run_bounded
from moregan.replay import RunReplay
from moregan.runtime import DeterministicEvidenceRunner, MoreGANRuntime
from moregan.schemas import StageResult, WORKER_STAGES
from moregan.tools import ToolCommand, ToolConfigError, ToolConfigLoader
from moregan.workers import WorkerRegistry


class CheckWorker:
    def __init__(self, stage, action=None):
        self.stage = stage
        self.action = action

    def run(self, context):
        if self.action:
            self.action(context)
        return StageResult(self.stage, "pass", 1)


class BoundedProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runner = DeterministicEvidenceRunner(self.root)

    def command(self, code, **kwargs):
        return ToolCommand("check", "tests", True, "Fix check", "test",
                           command=[sys.executable, "-c", code], **kwargs)

    def run_code(self, code, **kwargs):
        return run_bounded([sys.executable, "-c", code], self.root, **kwargs)

    def configure(self, code, required=True, timeout=1, output=128):
        folder = self.root / ".moregan"
        folder.mkdir(exist_ok=True)
        path = folder / "tools.yaml"
        path.write_text("commands:\n  - name: check\n"
                        f"    command: {json.dumps([sys.executable, '-c', code])}\n"
                        f"    required: {str(required).lower()}\n"
                        f"    timeout_seconds: {timeout}\n    max_output_bytes: {output}\n", encoding="utf-8")
        return path

    def runtime(self, generator=None, attempts=0):
        runtime = MoreGANRuntime(self.root, max_remediation_attempts=attempts)
        runtime.worker_registry = WorkerRegistry({
            stage: CheckWorker(stage, generator if stage == "generator" else None) for stage in WORKER_STAGES
        })
        return runtime

    def test_output_is_bounded_while_both_streams_are_drained(self):
        code = ("import os\nfor _ in range(128):\n"
                " os.write(1, b'a' * 65536)\n os.write(2, b'b' * 65536)\n"
                "os.write(1, b'OUT\\xff')\nos.write(2, b'ERR\\xfe')\n")
        tracemalloc.start()
        try:
            result = self.run_code(code, timeout_seconds=10, max_output_bytes=128)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout_bytes, 128 * 65536 + 4)
        self.assertEqual(result.stderr_bytes, 128 * 65536 + 4)
        self.assertTrue(result.stdout_truncated and result.stderr_truncated)
        self.assertEqual(len(result.stdout_tail), 128)
        self.assertEqual(len(result.stderr_tail), 128)
        self.assertTrue(result.stdout_tail.endswith("OUT\ufffd"))
        self.assertTrue(result.stderr_tail.endswith("ERR\ufffd"))
        self.assertLess(peak, 2 * 1024 * 1024)
        json.dumps(asdict(result), allow_nan=False)

    def test_short_output_and_nonzero_exit_preserved(self):
        result = self.run_code("import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)")
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(result.stdout_tail, "out\n")
        self.assertEqual(result.stderr_tail, "err\n")
        self.assertEqual(result.stdout_bytes, 4)
        self.assertFalse(result.stdout_truncated or result.stderr_truncated or result.timed_out)
        self.assertIsNone(result.error_kind)

    def test_stdin_is_closed_and_silent_command_finishes(self):
        result = self.run_code("import sys; assert sys.stdin.read() == ''")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout_tail, "")

    def test_timeout_keeps_partial_output_and_is_serializable(self):
        start = time.monotonic()
        result = self.run_code("import time; print('started', flush=True); time.sleep(60)", timeout_seconds=1)
        self.assertLess(time.monotonic() - start, 4)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.exit_code, 124)
        self.assertEqual(result.error_kind, "timeout")
        self.assertEqual(result.stdout_tail, "started\n")
        self.assertIn("1s", result.reason)
        json.dumps(asdict(result))

    def test_limits_cannot_be_disabled_or_coerced(self):
        for field, maximum in (("timeout_seconds", 86400), ("max_output_bytes", 1048576)):
            for value in (0, -1, True, "10", 0.5, None, maximum + 1):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.run_code("pass", **{field: value})

    def test_missing_executable_and_other_launch_errors_are_structured(self):
        result = run_bounded(["definitely-not-a-moregan-check"], self.root)
        self.assertEqual((result.exit_code, result.error_kind), (127, "not_found"))
        with patch("moregan.processes.subprocess.Popen", side_effect=PermissionError("not executable")):
            result = self.run_code("pass")
        self.assertEqual((result.exit_code, result.error_kind), (126, "launch_error"))
        self.assertIn("not executable", result.reason)
        result = run_bounded([sys.executable, "-c", "pass"], self.root / "missing")
        self.assertEqual(result.error_kind, "launch_error")

    @unittest.skipUnless(os.name == "posix", "POSIX process groups")
    def test_capture_failure_and_interruption_always_reap_process(self):
        popen = subprocess.Popen
        processes = []

        def capture(*args, **kwargs):
            process = popen(*args, **kwargs)
            processes.append(process)
            return process

        with patch("moregan.processes.subprocess.Popen", side_effect=capture):
            with patch("moregan.processes._drain_posix", side_effect=OSError("pipe failed")):
                result = self.run_code("import time; time.sleep(60)")
            self.assertEqual(result.error_kind, "capture_error")
            with patch("moregan.processes._drain_posix", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_code("import time; time.sleep(60)")
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.assertTrue(all(process.stdout.closed and process.stderr.closed for process in processes))

    @unittest.skipUnless(os.name == "posix", "POSIX process groups")
    def test_timeout_kills_descendants_even_when_parent_already_exited(self):
        for parent_exits in (False, True):
            with self.subTest(parent_exits=parent_exits):
                heartbeat = self.root / "heartbeat"
                child_code = ("import pathlib, signal, time\n"
                              "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                              f"p = pathlib.Path({str(heartbeat)!r})\n"
                              "while True:\n p.write_text(str(time.time_ns()))\n time.sleep(0.02)\n")
                parent = ("import subprocess, sys, time\n"
                          f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
                          "print(child.pid, flush=True)\n" + ("" if parent_exits else "time.sleep(60)\n"))
                result = self.run_code(parent, timeout_seconds=1)
                pid = int(result.stdout_tail.strip())
                try:
                    self.assertTrue(result.timed_out)
                    time.sleep(0.1)
                    first = heartbeat.read_text()
                    time.sleep(0.15)
                    self.assertEqual(heartbeat.read_text(), first)
                finally:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(os.name == "posix", "POSIX process groups")
    def test_successful_check_cleans_up_background_children_with_closed_pipes(self):
        marker = self.root / "late-write"
        child = f"import pathlib, time; time.sleep(0.5); pathlib.Path({str(marker)!r}).touch()"
        parent = ("import subprocess, sys; "
                  f"p = subprocess.Popen([sys.executable, '-c', {child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                  "print(p.pid)")
        result = self.run_code(parent, timeout_seconds=2)
        pid = int(result.stdout_tail.strip())
        try:
            self.assertEqual(result.exit_code, 0)
            time.sleep(0.7)
            self.assertFalse(marker.exists())
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_init_writes_limits_for_defaults_and_stack_presets(self):
        (self.root / "pom.xml").write_text("<project/>", encoding="utf-8")
        MoreGANInitializer(self.root).init()
        content = (self.root / ".moregan/tools.yaml").read_text()
        commands = ToolConfigLoader(self.root).load()
        self.assertGreater(len(commands), 3)
        self.assertEqual(content.count("timeout_seconds: 300"), len(commands))
        self.assertEqual(content.count("max_output_bytes: 4000"), len(commands))
        self.assertTrue(all(command.timeout_seconds == 300 and command.max_output_bytes == 4000 for command in commands))

    def test_tool_configuration_rejects_invalid_limits_and_commands(self):
        loader = ToolConfigLoader(self.root)
        valid = dict(name="test", command=[sys.executable, "-c", "pass"])
        self.assertEqual(loader._coerce_command(valid).timeout_seconds, 300)
        self.assertEqual(loader._coerce_command(dict(name="git", builtin="git_diff_check", timeout_seconds=2)).timeout_seconds, 2)
        invalid = [None, [], dict(valid, builtin="git_diff_check"), dict(valid, timeout_second=1), {**valid, 1: "bad"}]
        for field, values in {
            "timeout_seconds": [False, None, 0, -1, 1.5, "1", 86401],
            "max_output_bytes": [True, None, 0, -1, 1.5, "1", 1048577],
            "command": [[], [False], [sys.executable, None], [""], ["nul\x00"], '"unclosed'],
            "required": [None, "sometimes", 3], "enabled": [None, "sometimes"],
        }.items():
            invalid.extend(dict(valid, **{field: value}) for value in values)
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ToolConfigError):
                loader._coerce_command(payload)

    def test_invalid_config_becomes_required_evidence_without_running_checks(self):
        path = self.configure("pass")
        initial = path.read_text()
        for content in (initial + "    timeout_seconds: 2\n", initial.replace("timeout_seconds: 1", "timeout_seconds: 0"),
                        initial + initial.split("commands:\n", 1)[1], "commands: [None]\n"):
            with self.subTest(content=content):
                path.write_text(content)
                with patch("moregan.runtime.run_bounded") as execute:
                    evidence = self.runner.run_all()
                execute.assert_not_called()
                self.assertEqual(len(evidence), 1)
                self.assertEqual(evidence[0].name, "tool_config")
                self.assertTrue(evidence[0].required)
                self.assertFalse(evidence[0].passed)
        path.write_bytes(b"\xff")
        self.assertEqual(self.runner.run_all()[0].name, "tool_config")

    def test_missing_optional_command_skips_but_permission_error_does_not(self):
        tool = replace(self.command("pass"), required=False, command=["definitely-not-a-moregan-check"])
        evidence = self.runner._run_tool(tool)
        self.assertTrue(evidence.passed and evidence.skipped)
        required = self.runner._run_tool(replace(tool, required=True))
        self.assertFalse(required.passed or required.skipped)
        with patch("moregan.processes.subprocess.Popen", side_effect=PermissionError("denied")):
            evidence = self.runner._run_tool(tool)
        self.assertFalse(evidence.passed or evidence.skipped)
        self.assertEqual(evidence.error_kind, "launch_error")

    def test_optional_timeout_is_advisory_required_timeout_fails(self):
        for required in (False, True):
            with self.subTest(required=required):
                self.configure("import time; time.sleep(60)", required=required)
                result = self.runtime().run("Change copy")
                self.assertEqual(result.status, "fail" if required else "pass")
                evidence = result.evidence[0]
                self.assertTrue(evidence.timed_out)
                self.assertFalse(evidence.passed or evidence.skipped)
                self.assertEqual(evidence.timeout_seconds, 1)
                self.assertEqual(evidence.max_output_bytes, 128)
                stage = next(stage for stage in result.stages if stage.stage == "deterministic_evidence")
                self.assertEqual(stage.findings[0].severity, "medium" if required else "low")
                self.assertIn("timed out", stage.findings[0].description)
                self.assertIn("timed out", (Path(result.trace_path) / "final_report.md").read_text())
                self.assertIn("timed out", RunReplay(Path(result.trace_path)).render())

    def test_timed_out_check_can_be_remediated_with_timeout_context(self):
        self.configure("import pathlib, time; print('check', flush=True); "
                       "time.sleep(60) if not pathlib.Path('fixed').exists() else None")
        contexts = []

        def generator(context):
            if context.attempt > 1:
                contexts.append(context.remediation_context)
                (self.root / "fixed").touch()

        result = self.runtime(generator, attempts=1).run("Change copy")
        self.assertEqual(result.status, "pass")
        self.assertEqual([item.timed_out for item in result.evidence], [True, False])
        self.assertEqual([item.attempt for item in result.evidence], [1, 2])
        failure = contexts[0]["deterministic_evidence"][0]
        self.assertEqual(failure["error_kind"], "timeout")
        self.assertEqual(failure["timeout_seconds"], 1)
        self.assertIn("check", failure["stdout_tail"])
        run = Path(result.trace_path)
        pack = json.loads((run / "context/stages/generator.attempt2.json").read_text())
        self.assertIn('"timed_out": true', json.dumps(pack))
        replay = RunReplay(run).to_dict()
        self.assertEqual([item["timed_out"] for item in replay["evidence"]], [True, False])

    def test_exhausted_timeout_budget_is_a_failure(self):
        self.configure("import time; time.sleep(60)")
        result = self.runtime(attempts=1).run("Change copy")
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.state["remediation_attempts"], 1)
        self.assertEqual(len(result.evidence), 2)
        self.assertTrue(all(item.timed_out for item in result.evidence))

    def test_truncation_is_visible_in_artifacts_and_stage_evidence(self):
        self.configure("print('x' * 1000)", output=64)
        result = self.runtime().run("Change copy")
        self.assertEqual(result.status, "pass")
        evidence = result.evidence[0]
        self.assertEqual(evidence.stdout_bytes, 1001)
        self.assertEqual(len(evidence.stdout_tail), 64)
        self.assertTrue(evidence.stdout_truncated)
        self.assertIn("output truncated", RunReplay(Path(result.trace_path)).render())
        self.assertIn("output truncated", (Path(result.trace_path) / "final_report.md").read_text())

    def test_builtin_test_command_uses_configured_limits(self):
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_hang.py").write_text(
            "import time, unittest\nclass TestHang(unittest.TestCase):\n"
            " def test_hang(self):\n  print('waiting', flush=True)\n  time.sleep(60)\n")
        path = self.configure("pass")
        path.write_text("commands:\n  - name: unit_tests\n    builtin: unit_tests\n"
                        "    timeout_seconds: 1\n    max_output_bytes: 4\n")
        evidence = self.runner.run_all()[0]
        self.assertTrue(evidence.timed_out and evidence.stdout_truncated)
        self.assertEqual(evidence.stdout_tail, "ing\n")
        self.assertEqual(evidence.exit_code, 124)

    def test_python_file_discovery_is_bounded_and_never_compiles_partial_lists(self):
        (self.root / ".git").mkdir()
        tool = ToolCommand("python_compile", "syntax", True, "Fix syntax", "test", builtin="python_compile", timeout_seconds=2)
        for output in (ProcessResult(124, timed_out=True, error_kind="timeout", reason="timed out"),
                       ProcessResult(0, stdout_tail="partial.py\x00", stdout_truncated=True)):
            with self.subTest(output=output), patch("moregan.runtime.run_bounded", return_value=output) as execute:
                evidence = self.runner._run_tool(tool)
                self.assertFalse(evidence.passed)
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(execute.call_args.kwargs["timeout_seconds"], 2)
                self.assertEqual(execute.call_args.kwargs["max_output_bytes"], 1048576)

    def test_python_file_discovery_handles_newline_filenames(self):
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        filename = "odd\nname.py"
        (self.root / filename).write_text("VALUE = 1\n")
        tool = ToolCommand("python_compile", "syntax", True, "Fix syntax", "test", builtin="python_compile", timeout_seconds=2)
        evidence = self.runner._run_tool(tool)
        self.assertTrue(evidence.passed)
        self.assertIn(filename, evidence.command)


if __name__ == "__main__":
    unittest.main()
