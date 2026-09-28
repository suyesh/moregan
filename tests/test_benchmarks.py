import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from moregan.benchmark_fixtures import DEFAULT_BENCHMARK_TASKS
from moregan.benchmarks import (
    BASELINE_TEMPLATE_PATH, DEFAULT_SUITE_PATH, BenchmarkComparator, BenchmarkError,
    BenchmarkInitializer, BenchmarkRunner, BenchmarkSuiteLoader, load_benchmark_run,
    resolve_benchmark_run, summarize,
)
from moregan.cli import main
from moregan.init import MoreGANInitializer
from moregan.workers import WORKER_STAGE_TO_STATE


SOLUTIONS = [
    "def names(payload):\n    return [item['name'] for item in ((payload or {}).get('items') or [])]\n",
    "def paginate(items, page, size):\n    if page <= 0 or size <= 0:\n        raise ValueError()\n"
    "    return items[(page-1)*size:page*size]\n",
    "def unique(items):\n    result = []\n    for item in items:\n        if item not in result:\n"
    "            result.append(item)\n    return result\n",
    "from pathlib import Path\ndef resolve_asset(root, name):\n    root = Path(root).resolve()\n"
    "    value = (root / name).resolve()\n    if Path(name).is_absolute() or root not in value.parents:\n"
    "        raise ValueError()\n    return value\n",
    "def migrate(connection):\n    columns = [row[1] for row in connection.execute('PRAGMA table_info(users)')]\n"
    "    if 'display_name' not in columns:\n        connection.execute('ALTER TABLE users ADD COLUMN display_name TEXT')\n",
    "def is_expired(now, expires_at):\n    return expires_at is not None and now >= expires_at\n",
]


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        BenchmarkInitializer(self.root).init()

    def write_suite(self, tasks=None):
        payload = {"version": 1, "name": "test-suite", "tasks": tasks or [DEFAULT_BENCHMARK_TASKS[0]]}
        (self.root / DEFAULT_SUITE_PATH).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def workers(self, solution=None, stages=None, extra=""):
        stages = stages or list(WORKER_STAGE_TO_STATE)
        program = "import json, os; from pathlib import Path; stage = os.environ['MOREGAN_STAGE']; "
        if solution is not None:
            program += f"Path('app.py').write_text({solution!r}) if stage == 'generator' else None; "
        program += extra + "print(json.dumps({'stage': stage, 'verdict': 'pass', 'confidence': 1.0}))"
        lines = ["version: 1", "workers:"]
        for stage in stages:
            lines.extend([f"  - stage: {stage}", f"    command: {json.dumps([sys.executable, '-c', program])}",
                          "    no_write: false", "    timeout_seconds: 5"])
        config = self.root / ".moregan"
        config.mkdir(exist_ok=True)
        (config / "workers.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def external(self, tasks):
        suite = BenchmarkSuiteLoader(self.root).load()
        payload = {"version": 1, "suite_fingerprint": suite["fingerprint"], "tasks": tasks}
        path = self.root / "baseline.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_init_preserves_edits_and_dry_run_writes_nothing(self):
        suite = self.write_suite()
        BenchmarkInitializer(self.root).init()
        self.assertEqual(json.loads((self.root / DEFAULT_SUITE_PATH).read_text()), suite)
        elsewhere = self.root / "dry"
        actions = BenchmarkInitializer(elsewhere).init(dry_run=True)
        self.assertFalse(elsewhere.exists())
        self.assertTrue(all(action["action"].startswith("would_") for action in actions))
        BenchmarkInitializer(self.root).init(force=True)
        self.assertEqual(len(BenchmarkSuiteLoader(self.root).load()["tasks"]), 6)

    def test_all_fixtures_fail_initially_and_pass_reference_solutions(self):
        runner = BenchmarkRunner(self.root)
        for task, solution in zip(DEFAULT_BENCHMARK_TASKS, SOLUTIONS):
            with self.subTest(task=task["id"]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "project"
                workspace.mkdir()
                verifier = root / "verify.py"
                verifier.write_text(task["verification"], encoding="utf-8")
                (workspace / "app.py").write_text(task["files"]["app.py"], encoding="utf-8")
                self.assertEqual(runner._verify(verifier, workspace, 5)["status"], "fail")
                # Remove import cache to exercise new contents even with equal-sized source edits.
                for cache in workspace.glob("__pycache__/*.pyc"):
                    cache.unlink()
                (workspace / "app.py").write_text(solution, encoding="utf-8")
                check = runner._verify(verifier, workspace, 5)
                self.assertEqual(check["status"], "pass", check)

    def test_no_provider_never_counts_as_success(self):
        result = BenchmarkRunner(self.root).run(limit=1)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["summary"]["success_rate"])
        task = result["tasks"][0]
        self.assertEqual(task["status"], "skip")
        self.assertIsNone(task["success"])
        self.assertIn("generator", task["skipped_stages"])
        self.assertTrue(Path(task["evidence"]).exists())
        self.assertTrue(Path(result["report_path"]).exists())

    def test_baseline_executes_only_generator_moregan_runs_full_route(self):
        self.write_suite()
        self.workers(SOLUTIONS[0])
        runner = BenchmarkRunner(self.root)
        baseline = runner.run(mode="baseline")
        moregan = runner.run(mode="moregan")
        self.assertEqual(baseline["status"], "pass")
        self.assertEqual(moregan["status"], "pass")
        self.assertTrue((Path(baseline["tasks"][0]["trace_path"]) / "generator.json").exists())
        stages = list((Path(moregan["tasks"][0]["trace_path"]) / "stages").glob("*.json"))
        self.assertGreater(len(stages), 2)
        self.assertNotEqual(baseline["run_id"], moregan["run_id"])

    def test_provider_pass_without_fix_fails_independent_verification(self):
        self.write_suite()
        self.workers()
        result = BenchmarkRunner(self.root).run()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["tasks"][0]["workflow_status"], "pass")
        self.assertEqual(result["tasks"][0]["verification"]["status"], "fail")

    def test_provider_command_failure_is_unmeasured(self):
        self.write_suite()
        self.workers(stages=["generator"], extra="raise SystemExit(3); ")
        result = BenchmarkRunner(self.root).run(mode="baseline")
        self.assertEqual(result["tasks"][0]["status"], "error")
        self.assertEqual(result["tasks"][0]["provider_error_stages"], ["generator"])
        self.assertIsNone(result["summary"]["success_rate"])

    def test_missing_reviewer_cannot_inflate_moregan_success(self):
        self.write_suite()
        self.workers(SOLUTIONS[0], stages=["generator"])
        result = BenchmarkRunner(self.root).run()
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["tasks"][0]["verification"]["status"], "pass")
        self.assertIsNone(result["tasks"][0]["success"])

    def test_blocking_code_failure_counts_as_failure_when_reviews_are_unreached(self):
        self.write_suite()
        self.workers("def broken(:\n")
        result = BenchmarkRunner(self.root).run()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["summary"]["measured_tasks"], 1)
        self.assertEqual(result["summary"]["success_rate"], 0)
        self.assertIn("evaluator", result["tasks"][0]["unreached_stages"])
        self.assertEqual(result["tasks"][0]["skipped_stages"], [])

    def test_workspaces_are_independent_and_do_not_edit_checkout(self):
        tasks = [copy.deepcopy(DEFAULT_BENCHMARK_TASKS[0]) for _ in range(2)]
        tasks[1]["id"] = "second"
        self.write_suite(tasks)
        (self.root / "app.py").write_text("user change", encoding="utf-8")
        self.workers(SOLUTIONS[0], stages=["generator"], extra=(
            "assert Path('.git').is_dir(); assert not Path('marker').exists(); Path('marker').touch(); "
        ))
        result = BenchmarkRunner(self.root).run(mode="baseline")
        self.assertEqual(result["status"], "pass")
        self.assertEqual((self.root / "app.py").read_text(), "user change")
        self.assertFalse((self.root / "marker").exists())
        self.assertEqual(len(list(Path(result["result_path"]).parent.glob("tasks/*/workspace/marker"))), 2)

    def test_invalid_suite_is_rejected_before_running(self):
        for field, value in (("id", "../escape"), ("request", None), ("files", {"../escape": "x"}),
                             ("files", {".moregan/workers.yaml": "x"}), ("files", {"C:/x": "x"}),
                             ("acceptance_criteria", [False]), ("verification", "invalid python !")):
            with self.subTest(field=field, value=value):
                task = copy.deepcopy(DEFAULT_BENCHMARK_TASKS[0])
                task[field] = value
                self.write_suite([task])
                with self.assertRaises(BenchmarkError):
                    BenchmarkRunner(self.root).run()
        self.write_suite([DEFAULT_BENCHMARK_TASKS[0]] * 2)
        with self.assertRaises(BenchmarkError):
            BenchmarkSuiteLoader(self.root).load()
        self.assertFalse((self.root / ".moregan/benchmarks/runs").exists())

    def test_invalid_baseline_metrics_and_fingerprints_are_rejected(self):
        self.write_suite()
        for metric, value in (("duration_ms", -1), ("cost_usd", float("nan")), ("token_usage", True),
                              ("human_review_findings", "5"), ("token_usage", 1.5)):
            with self.subTest(metric=metric):
                path = self.external([{"id": DEFAULT_BENCHMARK_TASKS[0]["id"], "status": "pass",
                                      "evidence": "review.txt", metric: value}])
                with self.assertRaises(BenchmarkError):
                    BenchmarkRunner(self.root).run(mode="baseline", baseline_results_path=path)
        path.write_text('{"version": 1, "suite_fingerprint": "wrong", "tasks": []}', encoding="utf-8")
        with self.assertRaises(BenchmarkError):
            BenchmarkRunner(self.root).run(mode="baseline", baseline_results_path=path)

    def test_external_baseline_requires_evidence_and_preserves_missing_metrics(self):
        self.write_suite()
        measured = {"id": DEFAULT_BENCHMARK_TASKS[0]["id"], "status": "pass"}
        with self.assertRaises(BenchmarkError):
            BenchmarkRunner(self.root).run(mode="baseline", baseline_results_path=self.external([measured]))
        measured["evidence"] = "acceptance-output.txt"
        result = BenchmarkRunner(self.root).run(mode="baseline", baseline_results_path=self.external([measured]))
        self.assertEqual(result["measurement_source"], "external_import")
        self.assertIsNone(result["summary"]["token_usage_total"])
        self.assertEqual(result["summary"]["metric_coverage"]["token_usage"], 0)

    def test_untouched_baseline_template_remains_incomplete(self):
        result = BenchmarkRunner(self.root).run(mode="baseline", baseline_results_path=BASELINE_TEMPLATE_PATH)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["summary"]["unmeasured_count"], 6)
        self.assertIsNone(result["summary"]["success_rate"])

    def test_comparison_uses_identical_measured_pairs_and_recomputes_summaries(self):
        self.write_suite()
        baseline = BenchmarkRunner(self.root).run(mode="baseline", baseline_results_path=self.external([
            {"id": DEFAULT_BENCHMARK_TASKS[0]["id"], "status": "fail", "evidence": "test-output.txt"}]))
        self.workers(SOLUTIONS[0])
        moregan = BenchmarkRunner(self.root).run()
        moregan["summary"]["success_rate"] = 55
        Path(moregan["result_path"]).write_text(json.dumps(moregan), encoding="utf-8")
        comparison = BenchmarkComparator(self.root).compare(baseline["run_id"], moregan["run_id"])
        self.assertEqual(comparison["delta"]["success_rate"], 1)
        self.assertEqual(comparison["improvements"], [DEFAULT_BENCHMARK_TASKS[0]["id"]])
        self.assertIsNone(comparison["delta"]["cost_usd_total"])
        self.assertTrue(Path(comparison["report_path"]).exists())
        with self.assertRaises(BenchmarkError):
            BenchmarkComparator(self.root).compare(moregan["run_id"], baseline["run_id"])
        moregan["tasks"][0]["task_fingerprint"] = "changed"
        Path(moregan["result_path"]).write_text(json.dumps(moregan), encoding="utf-8")
        with self.assertRaises(BenchmarkError):
            BenchmarkComparator(self.root).compare(baseline["run_id"], moregan["run_id"])

    def test_comparison_excludes_unmeasured_pairs_and_rejects_task_set_mismatch(self):
        baseline = BenchmarkRunner(self.root).run(mode="baseline", baseline_results_path=BASELINE_TEMPLATE_PATH, limit=1)
        moregan = BenchmarkRunner(self.root).run(limit=1)
        comparison = BenchmarkComparator(self.root).compare(baseline["run_id"], moregan["run_id"])
        self.assertEqual(comparison["paired_task_count"], 0)
        self.assertIsNone(comparison["delta"]["success_rate"])
        moregan["tasks"] = []
        Path(moregan["result_path"]).write_text(json.dumps(moregan), encoding="utf-8")
        with self.assertRaises(BenchmarkError):
            BenchmarkComparator(self.root).compare(baseline["run_id"], moregan["run_id"])

    def test_partial_metric_totals_are_not_presented_as_complete(self):
        tasks = [{"status": "pass", "token_usage": 200}, {"status": "pass", "token_usage": None}]
        summary = summarize(tasks)
        self.assertIsNone(summary["token_usage_total"])
        self.assertEqual(summary["metric_coverage"]["token_usage"], 1)

    def test_timeout_is_an_error_and_provider_error_does_not_erase_results(self):
        task = copy.deepcopy(DEFAULT_BENCHMARK_TASKS[0])
        task["verification"] = "import time; time.sleep(10)"
        self.write_suite([task])
        self.workers(SOLUTIONS[0])
        result = BenchmarkRunner(self.root).run(verification_timeout=1)
        self.assertEqual(result["tasks"][0]["status"], "error")
        with patch("moregan.benchmarks.MoreGANRuntime.run", side_effect=ValueError("bad provider output")):
            result = BenchmarkRunner(self.root).run()
        self.assertEqual(result["tasks"][0]["status"], "error")
        self.assertIn("bad provider output", result["tasks"][0]["error"])
        self.assertTrue(Path(result["result_path"]).exists())

    def test_middle_task_error_preserves_other_measurements(self):
        outcomes = [{"status": "pass"}, RuntimeError("provider crashed"), {"status": "fail"}]
        with patch.object(BenchmarkRunner, "_execute", side_effect=outcomes):
            result = BenchmarkRunner(self.root).run(limit=3)
        saved = json.loads(Path(result["result_path"]).read_text())
        self.assertEqual([task["status"] for task in saved["tasks"]], ["pass", "error", "fail"])
        self.assertEqual(saved["summary"]["measured_tasks"], 2)
        self.assertEqual(saved["summary"]["success_rate"], 0.5)
        self.assertEqual(saved["status"], "incomplete")

    def test_interrupted_run_preserves_expected_task_count(self):
        with patch.object(BenchmarkRunner, "_execute", side_effect=[{"status": "pass"}, KeyboardInterrupt()]):
            with self.assertRaises(KeyboardInterrupt):
                BenchmarkRunner(self.root).run(limit=3)
        saved = load_benchmark_run(self.root, "latest")
        self.assertEqual(saved["status"], "running")
        self.assertEqual([task["status"] for task in saved["tasks"]], ["pass", "pending", "pending"])
        self.assertEqual(saved["summary"]["total_tasks"], 3)
        self.assertEqual(saved["summary"]["measured_tasks"], 1)

    def test_cli_init_run_inspect_compare_and_errors(self):
        args = ["--root", str(self.root), "benchmark"]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ["init"]), 0)
            self.assertEqual(main(args + ["run", "--limit", "1", "--json"]), 1)
            moregan = load_benchmark_run(self.root, "latest")
            self.assertEqual(main(args + ["inspect"]), 0)
            self.assertEqual(main(args + ["inspect", "latest", "--json"]), 0)
            self.assertEqual(main(args + ["run", "--mode", "baseline", "--limit", "1"]), 1)
            baseline = load_benchmark_run(self.root, "latest")
            self.assertEqual(main(args + ["compare", baseline["run_id"], moregan["run_id"]]), 0)
            self.assertEqual(main(args + ["run", "--limit", "0"]), 1)
            self.assertEqual(main(args + ["inspect", "missing"]), 1)
        self.assertEqual(resolve_benchmark_run(self.root, Path(baseline["result_path"]).parent),
                         Path(baseline["result_path"]))

    def test_init_ignores_benchmark_outputs_idempotently(self):
        MoreGANInitializer(self.root).init()
        MoreGANInitializer(self.root).init()
        entries = (self.root / ".gitignore").read_text().splitlines()
        for entry in (".moregan/benchmarks/runs/", ".moregan/benchmarks/comparisons/"):
            self.assertEqual(entries.count(entry), 1)


if __name__ == "__main__":
    unittest.main()
