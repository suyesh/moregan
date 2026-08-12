import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from moregan.adapters import AgentAdapterScaffolder
from moregan.agent_worker import main as agent_worker_main
from moregan.cli import main as moregan_main
from moregan.init import MoreGANInitializer
from moregan.runtime import DeterministicEvidenceRunner, MoreGANRuntime, RiskClassifier, latest_run
from moregan.state import InvalidTransition, StateMachine, TaskState
from moregan.tools import ToolConfigLoader
from moregan.workers import WorkerConfigLoader


class MoreGANRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_risk_classifier_routes_security_sensitive_work_to_critical_path(self):
        risk = RiskClassifier().classify("Replace authentication token handling")

        self.assertEqual(risk.level, "critical")
        self.assertIn("architect", risk.route)
        self.assertIn("security_evaluator", risk.route)
        self.assertIn("learning_curator", risk.route)

    def test_runtime_creates_auditable_trace_without_checks(self):
        result = MoreGANRuntime(self.root).run("Change button copy", run_checks=False)
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        self.assertTrue((run_dir / "request.json").exists())
        self.assertTrue((run_dir / "plan.json").exists())
        self.assertTrue((run_dir / "risk.json").exists())
        self.assertTrue((run_dir / "state.json").exists())
        self.assertTrue((run_dir / "states.jsonl").exists())
        self.assertTrue((run_dir / "stages" / "risk_classifier.json").exists())
        self.assertTrue((run_dir / "stages" / "generator.json").exists())
        self.assertTrue((run_dir / "stages" / "deterministic_evidence.json").exists())
        self.assertTrue((run_dir / "stages" / "evaluator.json").exists())
        self.assertTrue((run_dir / "result.json").exists())
        self.assertTrue((run_dir / "events.jsonl").exists())
        self.assertTrue((run_dir / "final_report.md").exists())

        plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["risk"]["level"], "low")
        self.assertIn("confidence", plan["risk"])

        deterministic_stage = json.loads(
            (run_dir / "stages" / "deterministic_evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual(deterministic_stage["verdict"], "skip")
        self.assertEqual(deterministic_stage["evidence"][0]["kind"], "operator_choice")
        self.assertTrue((run_dir / "tool_suggestions.json").exists())

        generator_stage = json.loads((run_dir / "stages" / "generator.json").read_text(encoding="utf-8"))
        self.assertEqual(generator_stage["verdict"], "skip")
        self.assertIn("No files were modified", generator_stage["evidence"][0]["summary"])

        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_state"], "completed")
        self.assertEqual(
            [snapshot["state"] for snapshot in state["history"]],
            ["intake", "risk_classification", "generation", "deterministic_evidence", "evaluation", "completed"],
        )
        states_jsonl = (run_dir / "states.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(states_jsonl), 6)
        self.assertEqual(latest_run(self.root), run_dir)

    def test_runtime_records_failed_deterministic_checks_as_structured_findings(self):
        tests_dir = self.root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_failure.py").write_text(
            "import unittest\n\n"
            "class FailureTest(unittest.TestCase):\n"
            "    def test_failure(self):\n"
            "        self.assertTrue(False)\n",
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root, max_remediation_attempts=1).run("Update service tests")
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "fail")
        stage = json.loads((run_dir / "stages" / "deterministic_evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(stage["verdict"], "fail")
        self.assertEqual(stage["attempt"], 2)
        self.assertEqual(stage["findings"][0]["category"], "deterministic_check_failed")
        self.assertEqual(stage["findings"][0]["severity"], "high")
        self.assertIn("unit_tests", stage["findings"][0]["description"])
        self.assertTrue((run_dir / "stages" / "deterministic_evidence.attempt1.json").exists())
        self.assertTrue((run_dir / "stages" / "deterministic_evidence.attempt2.json").exists())
        self.assertTrue((run_dir / "stages" / "remediation.attempt2.json").exists())
        remediation = json.loads((run_dir / "remediation.json").read_text(encoding="utf-8"))
        self.assertEqual(remediation["attempts"][0]["failed_stage"], "deterministic_evidence")
        self.assertEqual(remediation["attempts"][0]["deterministic_evidence"][0]["name"], "unit_tests")

        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_state"], "failed")
        self.assertEqual(state["remediation_attempts"], 1)
        self.assertIn("remediation", [snapshot["state"] for snapshot in state["history"]])
        self.assertEqual(state["history"][-1]["reason"], "blocking deterministic checks failed after remediation attempts")

    def test_deterministic_failure_can_pass_after_generator_remediation(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        tests_dir = self.root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_marker.py").write_text(
            "import pathlib\n"
            "import unittest\n\n"
            "class MarkerTest(unittest.TestCase):\n"
            "    def test_marker_exists(self):\n"
            "        self.assertTrue(pathlib.Path('fixed.txt').exists())\n",
            encoding="utf-8",
        )
        code = (
            "import json, os, pathlib; "
            "root = pathlib.Path.cwd(); "
            "attempt = int(os.environ.get('MOREGAN_ATTEMPT', '1')); "
            "context = os.environ.get('MOREGAN_REMEDIATION_CONTEXT', '{}'); "
            "(root / 'fixed.txt').write_text(context) if attempt > 1 else None; "
            "print(json.dumps({'stage': 'generator', 'verdict': 'pass', 'confidence': 1.0, "
            "'findings': [], 'evidence': [{'kind': 'attempt', 'name': 'generator_attempt', "
            "'summary': str(attempt)}]}))"
        )
        command = json.dumps([sys.executable, "-c", code])
        (moregan_dir / "workers.yaml").write_text(
            "version: 1\n"
            "workers:\n"
            "  - stage: generator\n"
            f"    command: {command}\n"
            "    timeout_seconds: 10\n"
            "    no_write: false\n",
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root, max_remediation_attempts=2).run("Update service tests")
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        self.assertTrue((self.root / "fixed.txt").exists())
        self.assertIn("unit_tests", (self.root / "fixed.txt").read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads((run_dir / "stages" / "deterministic_evidence.attempt1.json").read_text(encoding="utf-8"))[
                "verdict"
            ],
            "fail",
        )
        self.assertEqual(
            json.loads((run_dir / "stages" / "deterministic_evidence.attempt2.json").read_text(encoding="utf-8"))[
                "verdict"
            ],
            "pass",
        )
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["remediation_attempts"], 1)
        self.assertEqual(state["current_state"], "completed")

    def test_worker_finding_is_passed_to_generator_remediation_context(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        generator_code = (
            "import json, os, pathlib; "
            "attempt = int(os.environ.get('MOREGAN_ATTEMPT', '1')); "
            "context = os.environ.get('MOREGAN_REMEDIATION_CONTEXT', '{}'); "
            "(pathlib.Path.cwd() / 'remediation-context.json').write_text(context) if attempt > 1 else None; "
            "print(json.dumps({'stage': 'generator', 'verdict': 'pass', 'confidence': 1.0, "
            "'findings': [], 'evidence': [{'kind': 'attempt', 'name': 'generator_attempt', "
            "'summary': str(attempt)}]}))"
        )
        evaluator_code = (
            "import json, os; "
            "attempt = int(os.environ.get('MOREGAN_ATTEMPT', '1')); "
            "verdict = 'pass' if attempt > 1 else 'fail'; "
            "findings = [] if verdict == 'pass' else [{'severity': 'medium', "
            "'category': 'acceptance_criteria_gap', "
            "'description': 'The endpoint response is missing the requested field.', "
            "'remediation': 'Update the generator output to include the requested field.'}]; "
            "print(json.dumps({'stage': 'evaluator', 'verdict': verdict, 'confidence': 1.0, "
            "'findings': findings, 'evidence': [{'kind': 'attempt', 'name': 'evaluator_attempt', "
            "'summary': str(attempt)}]}))"
        )
        (moregan_dir / "workers.yaml").write_text(
            "version: 1\n"
            "workers:\n"
            "  - stage: generator\n"
            f"    command: {json.dumps([sys.executable, '-c', generator_code])}\n"
            "    timeout_seconds: 10\n"
            "    no_write: false\n"
            "  - stage: evaluator\n"
            f"    command: {json.dumps([sys.executable, '-c', evaluator_code])}\n"
            "    timeout_seconds: 10\n"
            "    no_write: true\n",
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root, max_remediation_attempts=2).run("Add API endpoint", run_checks=False)
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        context = json.loads((self.root / "remediation-context.json").read_text(encoding="utf-8"))
        self.assertEqual(context["failed_stage"], "evaluator")
        self.assertEqual(context["findings"][0]["category"], "acceptance_criteria_gap")
        self.assertEqual(
            json.loads((run_dir / "stages" / "evaluator.attempt1.json").read_text(encoding="utf-8"))["verdict"],
            "fail",
        )
        self.assertEqual(
            json.loads((run_dir / "stages" / "evaluator.attempt2.json").read_text(encoding="utf-8"))["verdict"],
            "pass",
        )

    def test_medium_route_runs_dry_run_workers_through_state_machine(self):
        result = MoreGANRuntime(self.root).run("Add API endpoint", run_checks=False)
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        for stage_name in ["planner", "generator", "deterministic_evidence", "evaluator", "code_reviewer"]:
            self.assertTrue((run_dir / "stages" / f"{stage_name}.json").exists())

        planner_stage = json.loads((run_dir / "stages" / "planner.json").read_text(encoding="utf-8"))
        self.assertEqual(planner_stage["verdict"], "skip")
        self.assertEqual(planner_stage["evidence"][0]["kind"], "worker")

        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [snapshot["state"] for snapshot in state["history"]],
            [
                "intake",
                "risk_classification",
                "planning",
                "generation",
                "deterministic_evidence",
                "evaluation",
                "code_review",
                "completed",
            ],
        )

    def test_high_route_runs_production_readiness_and_learning_workers(self):
        result = MoreGANRuntime(self.root).run("Update database security", run_checks=False)
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        for stage_name in [
            "architect",
            "security_evaluator",
            "production_readiness_reviewer",
            "mr_readiness_analyzer",
            "learning_curator",
        ]:
            stage = json.loads((run_dir / "stages" / f"{stage_name}.json").read_text(encoding="utf-8"))
            self.assertEqual(stage["verdict"], "skip")

        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["history"][-2]["state"], "learning")
        self.assertEqual(state["current_state"], "completed")

    def test_worker_command_provider_emits_stage_result_json(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        code = (
            "import json, os; "
            "print(json.dumps({"
            "'stage': 'generator', "
            "'verdict': 'pass', "
            "'confidence': 0.91, "
            "'findings': [], "
            "'evidence': [{'kind': 'env', 'name': 'no_write', 'summary': os.environ.get('MOREGAN_NO_WRITE')}]"
            "}))"
        )
        command = json.dumps([sys.executable, "-c", code])
        (moregan_dir / "workers.yaml").write_text(
            "version: 1\n"
            "workers:\n"
            "  - stage: generator\n"
            f"    command: {command}\n"
            "    timeout_seconds: 10\n"
            "    no_write: true\n",
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root).run("Change button copy", run_checks=False)
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        generator_stage = json.loads((run_dir / "stages" / "generator.json").read_text(encoding="utf-8"))
        self.assertEqual(generator_stage["verdict"], "pass")
        self.assertEqual(generator_stage["confidence"], 0.91)
        self.assertEqual(generator_stage["evidence"][0]["summary"], "1")
        self.assertEqual(generator_stage["evidence"][-1]["kind"], "worker_command")

    def test_worker_command_failure_blocks_run_with_structured_finding(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        command = json.dumps([sys.executable, "-c", "raise SystemExit(5)"])
        (moregan_dir / "workers.yaml").write_text(
            "version: 1\n"
            "workers:\n"
            "  - stage: generator\n"
            f"    command: {command}\n"
            "    timeout_seconds: 10\n",
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root).run("Change button copy", run_checks=False)
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "fail")
        generator_stage = json.loads((run_dir / "stages" / "generator.json").read_text(encoding="utf-8"))
        self.assertEqual(generator_stage["verdict"], "fail")
        self.assertEqual(generator_stage["findings"][0]["category"], "worker_provider_failed")
        self.assertFalse((run_dir / "stages" / "deterministic_evidence.json").exists())

        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["current_state"], "failed")
        self.assertEqual(state["history"][-1]["reason"], "generator worker failed")

    def test_state_machine_rejects_invalid_transition(self):
        state_machine = StateMachine(run_id="run-1", request="Change copy")

        with self.assertRaises(InvalidTransition):
            state_machine.transition(TaskState.COMPLETED, reason="cannot complete intake directly")

        self.assertEqual(state_machine.current_state, TaskState.INTAKE)

    def test_tools_yaml_configures_deterministic_commands(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        command = json.dumps([sys.executable, "-c", "print('custom ok')"])
        (moregan_dir / "tools.yaml").write_text(
            "version: 1\n"
            "commands:\n"
            "  - name: custom_python_check\n"
            f"    command: {command}\n"
            "    category: custom\n"
            "    required: true\n"
            '    remediation: "Fix the custom check."\n',
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root).run("Run custom deterministic checks")
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        self.assertEqual([item.name for item in result.evidence], ["custom_python_check"])
        stage = json.loads((run_dir / "stages" / "deterministic_evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(stage["verdict"], "pass")
        self.assertEqual(stage["evidence"][0]["name"], "custom_python_check")
        self.assertIn("required", stage["evidence"][0]["summary"])

    def test_optional_tool_failure_records_finding_without_blocking_run(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        command = json.dumps([sys.executable, "-c", "raise SystemExit(7)"])
        (moregan_dir / "tools.yaml").write_text(
            "version: 1\n"
            "commands:\n"
            "  - name: optional_lint\n"
            f"    command: {command}\n"
            "    category: lint\n"
            "    required: false\n"
            '    remediation: "Fix optional lint failures."\n',
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root).run("Run optional lint")
        run_dir = Path(result.trace_path)

        self.assertEqual(result.status, "pass")
        stage = json.loads((run_dir / "stages" / "deterministic_evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(stage["verdict"], "pass")
        self.assertEqual(stage["findings"][0]["severity"], "low")
        self.assertEqual(stage["findings"][0]["remediation"], "Fix optional lint failures.")

    def test_stack_detection_writes_tool_suggestions(self):
        (self.root / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest", "lint": "eslint .", "typecheck": "tsc --noEmit"}}),
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root).run("Inspect node project", run_checks=False)
        run_dir = Path(result.trace_path)
        suggestions = json.loads((run_dir / "tool_suggestions.json").read_text(encoding="utf-8"))
        names = {suggestion["name"] for suggestion in suggestions}

        self.assertIn("npm_test", names)
        self.assertIn("npm_lint", names)
        self.assertIn("npm_typecheck", names)
        self.assertIn("npm_audit", names)

    def test_init_scaffolds_safe_repo_local_config(self):
        (self.root / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest", "lint": "eslint .", "typecheck": "tsc --noEmit"}}),
            encoding="utf-8",
        )

        result = MoreGANInitializer(self.root).init()

        self.assertTrue(result.changed)
        self.assertTrue((self.root / ".moregan").is_dir())
        self.assertTrue((self.root / ".moregan" / "runs").is_dir())
        self.assertTrue((self.root / ".moregan" / "tools.yaml").exists())
        self.assertTrue((self.root / ".moregan" / "workers.yaml").exists())
        self.assertIn(".moregan/runs/", (self.root / ".gitignore").read_text(encoding="utf-8"))

        tools_yaml = (self.root / ".moregan" / "tools.yaml").read_text(encoding="utf-8")
        self.assertIn("builtin: git_diff_check", tools_yaml)
        self.assertIn("name: npm_lint", tools_yaml)
        self.assertIn("enabled: false", tools_yaml)
        self.assertEqual([tool.name for tool in ToolConfigLoader(self.root).load()], [
            "git_diff_check",
            "python_compile",
            "unit_tests",
        ])

    def test_init_preserves_existing_config_unless_forced(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        tools_path = moregan_dir / "tools.yaml"
        tools_path.write_text("version: 1\ncommands: []\n", encoding="utf-8")

        result = MoreGANInitializer(self.root).init()

        self.assertIn("commands: []", tools_path.read_text(encoding="utf-8"))
        self.assertTrue(any(action.action == "skipped" and action.path == ".moregan/tools.yaml" for action in result.actions))

        MoreGANInitializer(self.root).init(force=True)

        self.assertIn("builtin: git_diff_check", tools_path.read_text(encoding="utf-8"))

    def test_cli_init_supports_dry_run_without_writing_files(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(moregan_main(["--root", str(self.root), "init", "--dry-run"]), 0)

        self.assertIn("MoreGAN dry run", output.getvalue())
        self.assertFalse((self.root / ".moregan").exists())

    def test_cli_setup_runs_installer_default_install_command(self):
        with patch("install.main", autospec=True) as installer_main:
            installer_main.return_value = None

            self.assertEqual(moregan_main(["--root", str(self.root), "setup"]), 0)

        installer_main.assert_called_once_with(["install"])

    def test_cli_setup_passes_installer_arguments_through(self):
        with patch("install.main", autospec=True) as installer_main:
            installer_main.return_value = None

            self.assertEqual(
                moregan_main(["--root", str(self.root), "setup", "doctor", "--target", "codex", "--check"]),
                0,
            )

        installer_main.assert_called_once_with(["doctor", "--target", "codex", "--check"])

    def test_agent_adapter_scaffold_writes_prompt_templates_and_worker_config(self):
        result = AgentAdapterScaffolder(self.root).scaffold("codex", activate=True)

        self.assertTrue(any(action.path == ".moregan/workers.yaml" for action in result.actions))
        self.assertTrue((self.root / ".moregan" / "adapters" / "codex" / "generator.md").exists())
        self.assertTrue((self.root / ".moregan" / "adapters" / "codex" / "README.md").exists())
        self.assertTrue((self.root / ".moregan" / "workers.codex.yaml").exists())
        self.assertTrue((self.root / ".moregan" / "workers.yaml").exists())

        readme = (self.root / ".moregan" / "adapters" / "codex" / "README.md").read_text(encoding="utf-8")
        self.assertIn("MOREGAN_CODEX_COMMAND", readme)

        commands = WorkerConfigLoader(self.root).load()
        stages = {command.stage: command for command in commands}
        self.assertIn("generator", stages)
        self.assertIn("code_reviewer", stages)
        self.assertFalse(stages["generator"].no_write)
        self.assertTrue(stages["code_reviewer"].no_write)
        self.assertIn("moregan.agent_worker", stages["generator"].command)

    def test_agent_adapter_scaffold_preserves_active_workers_unless_forced(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        workers_path = moregan_dir / "workers.yaml"
        workers_path.write_text("version: 1\nworkers: []\n", encoding="utf-8")

        result = AgentAdapterScaffolder(self.root).scaffold("claude", activate=True)

        self.assertEqual(workers_path.read_text(encoding="utf-8"), "version: 1\nworkers: []\n")
        self.assertTrue(any(action.action == "skipped" and action.path == ".moregan/workers.yaml" for action in result.actions))

        AgentAdapterScaffolder(self.root).scaffold("claude", activate=True, force=True)

        self.assertIn("moregan.agent_worker", workers_path.read_text(encoding="utf-8"))

    def test_cli_adapters_supports_dry_run_without_writing_files(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(moregan_main(["--root", str(self.root), "adapters", "codex", "--dry-run"]), 0)

        self.assertIn("MoreGAN dry run codex adapters", output.getvalue())
        self.assertFalse((self.root / ".moregan").exists())

    def test_agent_worker_skips_when_provider_command_env_is_missing(self):
        AgentAdapterScaffolder(self.root).scaffold("codex")
        prompt = self.root / ".moregan" / "adapters" / "codex" / "generator.md"

        output = io.StringIO()
        with patch.dict(os.environ, {"MOREGAN_CODEX_COMMAND": ""}):
            with redirect_stdout(output):
                self.assertEqual(
                    agent_worker_main(
                        [
                            "--provider",
                            "codex",
                            "--stage",
                            "generator",
                            "--prompt",
                            str(prompt),
                            "--root",
                            str(self.root),
                        ]
                    ),
                    0,
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["stage"], "generator")
        self.assertEqual(payload["verdict"], "skip")
        self.assertIn("MOREGAN_CODEX_COMMAND", payload["evidence"][0]["summary"])

    def test_agent_worker_normalizes_provider_stage_result_json(self):
        AgentAdapterScaffolder(self.root).scaffold("codex")
        prompt = self.root / ".moregan" / "adapters" / "codex" / "generator.md"
        code = (
            "import json, sys; "
            "prompt = sys.stdin.read(); "
            "print(json.dumps({"
            "'stage': 'generator', "
            "'verdict': 'pass', "
            "'confidence': 0.77, "
            "'findings': [], "
            "'evidence': [{'kind': 'prompt', 'name': 'runtime_context', 'summary': str('Runtime Context' in prompt)}]"
            "}))"
        )
        command = json.dumps([sys.executable, "-c", code])

        output = io.StringIO()
        with patch.dict(
            os.environ,
            {
                "MOREGAN_CODEX_COMMAND": command,
                "MOREGAN_RUN_ID": "run-1",
                "MOREGAN_REQUEST": "Change copy",
                "MOREGAN_RISK_LEVEL": "low",
                "MOREGAN_ROUTE": json.dumps(["generator"]),
                "MOREGAN_NO_WRITE": "0",
            },
        ):
            with redirect_stdout(output):
                self.assertEqual(
                    agent_worker_main(
                        [
                            "--provider",
                            "codex",
                            "--stage",
                            "generator",
                            "--prompt",
                            str(prompt),
                            "--root",
                            str(self.root),
                        ]
                    ),
                    0,
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["stage"], "generator")
        self.assertEqual(payload["verdict"], "pass")
        self.assertEqual(payload["confidence"], 0.77)
        self.assertEqual(payload["evidence"][0]["summary"], "True")
        self.assertEqual(payload["evidence"][-1]["kind"], "agent_provider")

    def test_cli_run_status_and_inspect_use_trace_artifacts(self):
        self.assertEqual(moregan_main(["--root", str(self.root), "run", "Add API endpoint", "--no-checks"]), 0)
        self.assertEqual(moregan_main(["--root", str(self.root), "status"]), 0)
        self.assertEqual(moregan_main(["--root", str(self.root), "inspect", "latest"]), 0)
        self.assertEqual(moregan_main(["--root", str(self.root), "replay", "latest"]), 0)

    def test_replay_reconstructs_run_without_rerunning_workers(self):
        moregan_dir = self.root / ".moregan"
        moregan_dir.mkdir()
        marker = self.root / "worker-count.txt"
        code = (
            "import json, pathlib; "
            f"path = pathlib.Path({str(marker)!r}); "
            "count = int(path.read_text() or '0') if path.exists() else 0; "
            "path.write_text(str(count + 1)); "
            "print(json.dumps({'stage': 'generator', 'verdict': 'pass', 'confidence': 1.0, "
            "'findings': [], 'evidence': [{'kind': 'marker', 'name': 'count', 'summary': str(count + 1)}]}))"
        )
        command = json.dumps([sys.executable, "-c", code])
        (moregan_dir / "workers.yaml").write_text(
            "version: 1\n"
            "workers:\n"
            "  - stage: generator\n"
            f"    command: {command}\n"
            "    no_write: false\n",
            encoding="utf-8",
        )

        result = MoreGANRuntime(self.root).run("Change button copy", run_checks=False)
        self.assertEqual(result.status, "pass")
        self.assertEqual(marker.read_text(encoding="utf-8"), "1")

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(moregan_main(["--root", str(self.root), "replay", "latest"]), 0)
        self.assertIn("MoreGAN Replay", output.getvalue())
        self.assertIn("generator: PASS", output.getvalue())
        self.assertEqual(marker.read_text(encoding="utf-8"), "1")

        json_output = io.StringIO()
        with redirect_stdout(json_output):
            self.assertEqual(moregan_main(["--root", str(self.root), "replay", "latest", "--json"]), 0)
        replay = json.loads(json_output.getvalue())
        self.assertEqual(replay["run_id"], Path(result.trace_path).name)
        self.assertEqual(replay["stages"][1]["stage"], "generator")

    def test_python_compile_candidates_include_untracked_git_files(self):
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True, text=True)
        (self.root / "new_runtime_file.py").write_text("VALUE = 1\n", encoding="utf-8")

        files = list(DeterministicEvidenceRunner(self.root)._python_files())

        self.assertIn("new_runtime_file.py", files)


if __name__ == "__main__":
    unittest.main()
