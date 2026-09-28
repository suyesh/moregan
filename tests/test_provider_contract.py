import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from moregan.adapters import AgentAdapterScaffolder
from moregan.agent_worker import AgentWorkerRunner
from moregan.cli import main
from moregan.runtime import MoreGANRuntime, RiskClassifier
from moregan.schemas import (
    WORKER_STAGES, StageResultValidationError, parse_stage_json, validate_stage_result,
)
from moregan.state import InvalidTransition, StateMachine
from moregan.workers import CommandWorker, WorkerCommand, WorkerConfigError, WorkerConfigLoader, WorkerContext


def valid_result(**overrides):
    return dict({"stage": "generator", "verdict": "pass", "confidence": 0.8}, **overrides)


class ProviderContractTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.prompt = self.root / "prompt.md"
        self.prompt.write_text("Return StageResult JSON.", encoding="utf-8")

    def _validate(self, payload):
        return validate_stage_result(
            payload, "generator", attempt=2, started_at="2026-09-27T12:00:00",
            completed_at="2026-09-27T12:00:01", duration_ms=1000,
        )

    def _run_adapter(self, adapter, stdout=None, command=None, side_effect=None, returncode=0):
        command = command or [sys.executable, "-c", "pass"]
        context = WorkerContext(self.root, "test", "Change copy", RiskClassifier().classify("Change copy"), [], attempt=2)
        worker = CommandWorker(WorkerCommand("generator", command, 1, False, "test", "repository"))
        runner = AgentWorkerRunner(adapter if adapter != "command" else "codex", "generator", self.prompt, self.root, 1)
        with patch.dict(os.environ, {
            "MOREGAN_CODEX_COMMAND": json.dumps(command), "MOREGAN_CLAUDE_COMMAND": json.dumps(command),
            "MOREGAN_ATTEMPT": "2",
        }):
            if stdout is None and side_effect is None:
                return worker.run(context) if adapter == "command" else runner.run()
            completed = subprocess.CompletedProcess(command, returncode, stdout, "provider stderr")
            with patch("subprocess.run", return_value=completed, side_effect=side_effect):
                return worker.run(context) if adapter == "command" else runner.run()

    def test_minimal_result_and_runtime_owned_metadata(self):
        payload = valid_result(attempt=999, duration_ms=999999,
                               started_at="2000-01-01T00:00:00Z", completed_at="2000-01-01T00:00:00Z")
        result = self._validate(payload)
        self.assertEqual(result.attempt, 2)
        self.assertEqual(result.duration_ms, 1000)
        self.assertEqual(result.started_at, "2026-09-27T12:00:00")
        self.assertEqual(result.findings, [])
        self.assertEqual(result.evidence, [])
        for adapter in ("command", "codex", "claude"):
            with self.subTest(adapter=adapter):
                actual = self._run_adapter(adapter, stdout=json.dumps(payload))
                self.assertEqual(actual.verdict, "pass")
                self.assertEqual(actual.attempt, 2)
                self.assertNotEqual(actual.duration_ms, 999999)
                self.assertNotEqual(actual.started_at, payload["started_at"])

    def test_invalid_fields_fail_consistently_at_each_provider_boundary(self):
        invalid = [None, [], "pass", {}, {"stage": "generator"}]
        for field, values in {
            "stage": [None, "unknown", "evaluator", []],
            "verdict": [None, "PASS", "approved", True, []],
            "confidence": [None, True, "0.8", -0.1, 1.1, float("nan"), float("inf"), -float("inf")],
            "findings": [None, "none", {}, [None], ["ignored"], [{}]],
            "evidence": [None, "none", {}, [None], ["ignored"], [{}]],
            "attempt": [None, 0, -1, True, "2"],
            "duration_ms": [-1, True, "100"],
            "started_at": [False, 123, "not-a-date"],
            "completed_at": [[], "not-a-date"],
            "unexpected": ["ignored previously"],
        }.items():
            invalid.extend(dict(valid_result(), **{field: value}) for value in values)
        for required in ("stage", "verdict", "confidence"):
            payload = valid_result()
            del payload[required]
            invalid.append(payload)
        finding = dict(severity="low", category="review", description="Issue", remediation="Fix", file="app.py", line=1)
        for field, values in {
            "severity": ["urgent", None, True, []], "category": [None, ""],
            "description": [" ", 3, "\ud800"], "remediation": [None, []],
            "file": [0, ""], "line": [0, -1, True, "3", 2.5], "extra": [1],
        }.items():
            invalid.extend(valid_result(findings=[dict(finding, **{field: value})]) for value in values)
        evidence = dict(kind="test", name="check", summary="Passed")
        for field, values in {
            "kind": [None, ""], "name": [True, ""], "summary": [0, " "],
            "path": [False, ""], "command": [[], "pytest", [1], [""], ["python", None], ["\ud800"]], "extra": [1],
        }.items():
            invalid.extend(valid_result(evidence=[dict(evidence, **{field: value})]) for value in values)

        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(StageResultValidationError):
                    self._validate(payload)
                for adapter in ("command", "codex", "claude"):
                    result = self._run_adapter(adapter, stdout=json.dumps(payload))
                    self.assertEqual(result.verdict, "fail", (adapter, payload))
                    self.assertEqual(result.findings[0].category,
                                     "worker_provider_failed" if adapter == "command" else "agent_provider_failed")
                    json.dumps(asdict(result), allow_nan=False)

    def test_valid_findings_and_evidence_survive_validation(self):
        payload = valid_result(findings=[dict(severity="low", category="style", description="Naming",
                                              remediation="Rename", file="a.py", line=2)],
                               evidence=[dict(kind="command", name="tests", summary="Passed", command=["pytest", ""], path=None)])
        payload.update(attempt=1, started_at=None, completed_at=None, duration_ms=None)
        result = self._validate(payload)
        self.assertEqual(result.findings[0].line, 2)
        self.assertEqual(result.evidence[0].command, ["pytest", ""])
        for verdict in ("fail", "skip"):
            self.assertEqual(self._validate(dict(payload, verdict=verdict)).verdict, verdict)

    def test_blocking_findings_cannot_claim_pass_or_skip(self):
        for severity in ("high", "critical"):
            payload = valid_result(findings=[dict(severity=severity, category="security", description="Issue", remediation="Fix")])
            self.assertEqual(self._validate(dict(payload, verdict="fail")).verdict, "fail")
            for verdict in ("pass", "skip"):
                with self.assertRaises(StageResultValidationError):
                    self._validate(dict(payload, verdict=verdict))

    def test_json_must_be_exact_and_unambiguous(self):
        valid = json.dumps(valid_result())
        for text in (f"```json\n{valid}\n```", f"Result: {valid}", f"{valid}\n{valid}", "",
                     '{"stage":"generator","stage":"evaluator","verdict":"pass","confidence":1}',
                     '{"stage":"generator","verdict":"pass","confidence":NaN}',
                     '{"findings":[{"severity":"low","severity":"high"}]}'):
            with self.subTest(text=text):
                with self.assertRaises(StageResultValidationError):
                    parse_stage_json(text)
                for adapter in ("command", "codex", "claude"):
                    self.assertEqual(self._run_adapter(adapter, stdout=text).verdict, "fail")
        self.assertEqual(parse_stage_json(f" \n{valid}\n"), valid_result())

    def test_real_provider_processes_and_launch_errors(self):
        for adapter in ("command", "codex", "claude"):
            with self.subTest(adapter=adapter):
                command = [sys.executable, "-c", f"print({json.dumps(valid_result())!r})"]
                self.assertEqual(self._run_adapter(adapter, command=command).verdict, "pass")
                self.assertEqual(self._run_adapter(adapter, command=["definitely-not-a-moregan-provider"]).verdict, "fail")
                self.assertEqual(self._run_adapter(adapter, command=[sys.executable, "-c", "raise SystemExit(7)"]).verdict, "fail")
                command = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')"]
                self.assertEqual(self._run_adapter(adapter, command=command).verdict, "fail")

    def test_timeout_bytes_are_serializable_and_bounded(self):
        error = subprocess.TimeoutExpired("provider", 1, output=b"x" * 2000 + b"\xff", stderr=b"error\xff")
        for adapter in ("command", "codex", "claude"):
            with self.subTest(adapter=adapter):
                result = self._run_adapter(adapter, side_effect=error)
                self.assertEqual(result.verdict, "fail")
                self.assertEqual(result.attempt, 2)
                tails = [item.summary for item in result.evidence if item.kind.endswith("_tail")]
                self.assertEqual(len(tails), 2)
                self.assertTrue(all(isinstance(tail, str) and len(tail) <= 1000 for tail in tails))
                json.dumps(asdict(result), allow_nan=False)

    def test_real_timeouts_return_structured_failures(self):
        command = [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(10)"]
        for adapter in ("command", "codex", "claude"):
            with self.subTest(adapter=adapter):
                result = self._run_adapter(adapter, command=command)
                self.assertEqual(result.verdict, "fail")
                self.assertIn("timed out", result.findings[0].description)
                self.assertTrue(any(item.summary == "started" for item in result.evidence))
                json.dumps(asdict(result))

    def test_worker_preparation_error_is_structured(self):
        with patch.object(CommandWorker, "_execution_root", side_effect=OSError("disk full")):
            result = self._run_adapter("command")
        self.assertEqual(result.verdict, "fail")
        self.assertIn("disk full", result.findings[0].description)

    def test_agent_configuration_and_prompt_errors_are_structured(self):
        runner = AgentWorkerRunner("codex", "generator", self.prompt, self.root, 1)
        for command in ("[]", '["", "arg"]', '["python", 1]', "'unclosed", '["bad\\x00command"]'):
            with self.subTest(command=command), patch.dict(os.environ, {"MOREGAN_CODEX_COMMAND": command}):
                self.assertEqual(runner.run().verdict, "fail")
        for attempt in ("0", "-1", "invalid"):
            with patch.dict(os.environ, {"MOREGAN_ATTEMPT": attempt}):
                self.assertEqual(runner.run().verdict, "fail")
        runner.timeout_seconds = 0
        self.assertEqual(runner.run().verdict, "fail")
        runner.timeout_seconds = 1
        self.prompt.unlink()
        with patch.dict(os.environ, {"MOREGAN_CODEX_COMMAND": "provider"}):
            self.assertEqual(runner.run().verdict, "fail")

    def test_worker_config_rejects_invalid_commands_and_settings(self):
        loader = WorkerConfigLoader(self.root)
        valid = {"stage": "generator", "command": ["provider"]}
        for field, values in {
            "command": [[], [1], [""], ["provider", None], "'unclosed", "", ["bad\x00command"]],
            "timeout_seconds": [0, -1, True, "10", 1.5],
            "no_write": [None, "maybe", 3], "execution": ["invalid"], "stage": ["unknown"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(WorkerConfigError):
                    loader._coerce_worker(dict(valid, **{field: value}))
        config = self.root / ".moregan" / "workers.yaml"
        config.parent.mkdir()
        for text in ("version: 1\n", "workers: [1]\n",
                     'workers:\n  - stage: generator\n    command: ["provider"]\n'
                     '  - stage: generator\n    command: ["other"]\n'):
            config.write_text(text, encoding="utf-8")
            with self.assertRaises(WorkerConfigError):
                loader.load()
            result = MoreGANRuntime(self.root).run("Change copy")
            self.assertEqual(result.status, "fail")
            self.assertTrue(any(finding.category == "worker_config_invalid"
                                for stage in result.stages for finding in stage.findings))


class RuntimeOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        (self.root / ".moregan").mkdir()

    def _configure(self, failed_stage=None):
        code = (
            "import os, json; stage = os.environ['MOREGAN_STAGE']; "
            f"print(json.dumps({{'stage': stage, 'verdict': 'fail' if stage == {failed_stage!r} else 'pass', 'confidence': 1}}))"
        )
        config = "workers:\n" + "".join(
            f"  - stage: {stage}\n    command: {json.dumps([sys.executable, '-c', code])}\n    no_write: false\n"
            for stage in sorted(WORKER_STAGES)
        )
        (self.root / ".moregan" / "workers.yaml").write_text(config, encoding="utf-8")
        (self.root / ".moregan" / "tools.yaml").write_text(
            'commands:\n  - name: required_check\n'
            f'    command: {json.dumps([sys.executable, "-c", "pass"])}\n    required: true\n'
            '  - name: not_applicable\n    builtin: git_diff_check\n', encoding="utf-8",
        )

    def test_every_fully_executed_risk_route_passes(self):
        self._configure()
        for request, level in (("Change copy", "low"), ("Add endpoint", "medium"),
                               ("Update database", "high"), ("Update authentication", "critical")):
            with self.subTest(level=level):
                result = MoreGANRuntime(self.root).run(request)
                self.assertEqual(result.risk.level, level)
                self.assertEqual(result.status, "pass")
                self.assertEqual(result.state["current_state"], "completed")
                self.assertEqual(result.incomplete_stages, [])

    def test_every_unconfigured_risk_route_is_incomplete(self):
        for request, level in (("Change copy", "low"), ("Add endpoint", "medium"),
                               ("Update database", "high"), ("Update authentication", "critical")):
            with self.subTest(level=level):
                result = MoreGANRuntime(self.root).run(request, run_checks=False)
                self.assertEqual(result.risk.level, level)
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.state["current_state"], "incomplete")
                self.assertEqual(result.incomplete_stages, result.risk.route)

    def test_scaffolded_adapters_pass_through_both_validation_boundaries(self):
        self._configure()
        command = [sys.executable, "-c",
                   "import os, json, sys; sys.stdin.read(); print(json.dumps({"
                   "'stage': os.environ['MOREGAN_STAGE'], 'verdict': 'pass', 'confidence': 1, 'attempt': 900}))"]
        for provider in ("codex", "claude"):
            with self.subTest(provider=provider):
                AgentAdapterScaffolder(self.root).scaffold(provider, activate=True, force=True)
                with patch.dict(os.environ, {
                    f"MOREGAN_{provider.upper()}_COMMAND": json.dumps(command),
                    "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                }):
                    result = MoreGANRuntime(self.root).run("Change copy")
                self.assertEqual(result.status, "pass")
                self.assertTrue(all(stage.attempt == 1 for stage in result.stages))

    def test_no_checks_never_passes_even_with_all_workers(self):
        self._configure()
        result = MoreGANRuntime(self.root).run("Change copy", run_checks=False)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.incomplete_stages, ["deterministic_evidence"])

    def test_empty_and_all_skipped_checks_are_incomplete(self):
        self._configure()
        for text in ("commands: []\n", 'commands:\n  - name: no_git\n    builtin: git_diff_check\n'):
            with self.subTest(text=text):
                (self.root / ".moregan" / "tools.yaml").write_text(text, encoding="utf-8")
                result = MoreGANRuntime(self.root).run("Change copy")
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.incomplete_stages, ["deterministic_evidence"])

    def test_final_worker_failure_is_traced_after_bounded_remediation(self):
        self._configure(failed_stage="learning_curator")
        result = MoreGANRuntime(self.root, max_remediation_attempts=1).run("Update authentication")
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.state["current_state"], "failed")
        self.assertEqual(result.state["remediation_attempts"], 1)
        self.assertEqual(result.stages[-1].stage, "learning_curator")
        self.assertEqual(result.stages[-1].attempt, 2)

    def test_failure_takes_precedence_over_skips(self):
        self._configure(failed_stage="evaluator")
        result = MoreGANRuntime(self.root, max_remediation_attempts=0).run("Change copy", run_checks=False)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.incomplete_stages, ["deterministic_evidence"])

    def test_incomplete_state_is_terminal(self):
        machine = StateMachine("test", "copy")
        for state in ("risk_classification", "generation", "evaluation", "incomplete"):
            machine.transition(state, "test")
        with self.assertRaises(InvalidTransition):
            machine.transition("completed", "cannot turn skips into success")

    def test_cli_trace_report_and_replay_agree_on_incomplete(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.root), "run", "Change copy", "--no-checks"]), 1)
        self.assertIn("INCOMPLETE", output.getvalue())
        self.assertIn("Incomplete stages:", output.getvalue())
        run = next((self.root / ".moregan" / "runs").iterdir())
        result = json.loads((run / "result.json").read_text())
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["state"]["current_state"], "incomplete")
        self.assertIn("## Incomplete Stages", (run / "final_report.md").read_text())
        events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        self.assertEqual(events[-1]["status"], "incomplete")
        with redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.root), "replay", "latest"]), 0)
        self.assertIn("incomplete", output.getvalue())


if __name__ == "__main__":
    unittest.main()
