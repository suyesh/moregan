import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moregan.replay import RunReplay
from moregan.runtime import MoreGANRuntime, RiskClassifier, ROUTES_BY_RISK
from moregan.schemas import Finding, StageResult, WORKER_STAGES
from moregan.workers import WorkerRegistry


class StubWorker:
    def __init__(self, stage, action, calls):
        self.stage, self.action, self.calls = stage, action, calls

    def run(self, context):
        self.calls.append((self.stage, context.attempt, context.risk.level, context.phase))
        result = self.action(context) if self.action else None
        return result or StageResult(stage=self.stage, verdict="pass", confidence=1)


class RiskReassessmentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.git("init")
        self.git("config", "user.name", "MoreGAN Test")
        self.git("config", "user.email", "moregan@example.com")
        self.write("copy.txt", "Original wording\n")
        self.write(".moregan/tools.yaml", "commands:\n  - name: check\n"
                   f"    command: {json.dumps([sys.executable, '-c', 'pass'])}\n    required: true\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.calls = []

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def runtime(self, actions=None, missing=(), attempts=2):
        actions = actions or {}
        runtime = MoreGANRuntime(self.root, max_remediation_attempts=attempts)
        runtime.worker_registry = WorkerRegistry({
            stage: StubWorker(stage, actions.get(stage), self.calls) for stage in WORKER_STAGES if stage not in missing
        })
        return runtime

    def failed(self, stage):
        return StageResult(stage=stage, verdict="fail", confidence=1,
                           findings=[Finding("high", "review_gap", "Patch needs changes", "Repair the patch")])

    def test_generated_auth_changes_escalate_before_verification(self):
        runtime = self.runtime({"generator": lambda ctx: self.write("src/auth/login.py", "VALUE = 1\n")})
        result = runtime.run("Change copy")
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.risk.level, "critical")
        self.assertEqual([call[0] for call in self.calls], ["generator", "planner", "architect", "designer_decision",
                         "evaluator", "security_evaluator", "code_reviewer", "production_readiness_reviewer",
                         "mr_readiness_analyzer", "learning_curator"])
        self.assertEqual(self.calls[0][2:], ("low", "standard"))
        self.assertEqual(self.calls[1][2:], ("critical", "post_generation_review"))
        run = Path(result.trace_path)
        self.assertEqual(json.loads((run / "risk.initial.json").read_text())["level"], "low")
        self.assertEqual(json.loads((run / "plan.json").read_text())["risk"]["level"], "low")
        self.assertEqual(json.loads((run / "risk.json").read_text())["level"], "critical")
        self.assertEqual(json.loads((run / "risk.attempt1.json").read_text()), result.risk_history[0])
        self.assertEqual(result.risk_history[0]["observed"]["evidence"]["changed_files"], ["src/auth/login.py"])
        context = json.loads((run / "context/stages/architect.attempt1.json").read_text())
        self.assertEqual(context["phase"], "post_generation_review")
        self.assertEqual(context["risk"]["level"], "critical")
        self.assertEqual(context["route"], ROUTES_BY_RISK["critical"])
        self.assertIn("low -> critical", (run / "final_report.md").read_text())
        self.assertIn("low -> critical", RunReplay(run).render())
        self.assertEqual(RunReplay(run).to_dict()["risk_history"], result.risk_history)

    def test_generated_dependency_migration_and_large_patches_escalate(self):
        for path, content, expected in (("pom.xml", "<project/>\n", "high"),
                                        ("db/migrations/001.sql", "ALTER TABLE demo ADD name TEXT;\n", "critical"),
                                        ("large.txt", "new\n" * 401, "high")):
            with self.subTest(path=path):
                result = self.runtime({"generator": lambda ctx: self.write(path, content)}).run("Change copy")
                self.assertEqual(result.status, "pass")
                self.assertEqual(result.risk_history[0]["previous_level"], "low")
                self.assertEqual(result.risk.level, expected)
                (self.root / path).unlink()

    def test_remediation_can_escalate_a_previously_low_route(self):
        def generator(ctx):
            if ctx.attempt == 2:
                self.write("auth.py", "fixed = True\n")
        result = self.runtime({"generator": generator,
                               "evaluator": lambda ctx: self.failed("evaluator") if ctx.attempt == 1 else None}).run("Change copy")
        self.assertEqual(result.status, "pass")
        self.assertEqual([item["effective"]["level"] for item in result.risk_history], ["low", "critical"])
        self.assertEqual([call[:2] for call in self.calls if call[0] == "generator"], [("generator", 1), ("generator", 2)])
        self.assertIn(("architect", 2, "critical", "post_generation_review"), self.calls)
        checks = [stage.attempt for stage in result.stages if stage.stage == "deterministic_evidence"]
        self.assertEqual(checks, [1, 2])
        replay = RunReplay(Path(result.trace_path)).to_dict()
        evaluations = [stage for stage in replay["stages"] if stage["stage"] == "evaluator"]
        self.assertEqual([stage["verdict"] for stage in evaluations], ["fail", "pass"])
        assessments = [stage for stage in replay["stages"] if stage["stage"] == "risk_reassessment"]
        self.assertEqual([stage["attempt"] for stage in assessments], [1, 2])
        self.assertIn("low -> low", assessments[0]["evidence"][0]["summary"])

    def test_risk_cannot_downgrade_when_remediation_removes_risky_change(self):
        def generator(ctx):
            if ctx.attempt == 1:
                self.write("auth.py", "risky = True\n")
            else:
                (self.root / "auth.py").unlink()
        result = self.runtime({"generator": generator,
                               "architect": lambda ctx: self.failed("architect") if ctx.attempt == 1 else None}).run("Change copy")
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.risk.level, "critical")
        self.assertEqual(result.risk_history[1]["observed"]["level"], "low")
        self.assertTrue(result.risk_history[1]["retained_prior_risk"])
        self.assertEqual([call[1] for call in self.calls if call[0] == "planner"], [1, 2])
        self.assertEqual([call[1] for call in self.calls if call[0] == "architect"], [1, 2])
        self.assertEqual([call[1] for call in self.calls if call[0] == "evaluator"], [2])
        remediation = json.loads((Path(result.trace_path) / "remediation.json").read_text())
        self.assertTrue(remediation["attempts"][0]["post_generation_review"])

    def test_initial_planner_is_not_repeated_when_only_architect_is_new(self):
        result = self.runtime({"generator": lambda ctx: self.write("pom.xml", "<project/>\n")}).run("Add endpoint")
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.risk.level, "high")
        self.assertEqual([call[0] for call in self.calls[:3]], ["planner", "generator", "architect"])
        self.assertEqual(sum(call[0] == "planner" for call in self.calls), 1)
        self.assertEqual(self.calls[0][3], "standard")
        self.assertEqual(self.calls[2][3], "post_generation_review")

    def test_missing_escalated_workers_are_incomplete(self):
        result = self.runtime({"generator": lambda ctx: self.write("auth.py", "VALUE = 1\n")},
                              missing=("architect", "security_evaluator")).run("Change copy")
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.incomplete_stages, ["architect", "security_evaluator"])

    def test_failed_catchup_review_exhausts_budget_without_verification(self):
        result = self.runtime({"generator": lambda ctx: self.write("auth.py", "VALUE = 1\n"),
                               "planner": lambda ctx: self.failed("planner")}, attempts=1).run("Change copy")
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.state["remediation_attempts"], 1)
        self.assertEqual([call[0] for call in self.calls], ["generator", "planner", "generator", "planner"])
        self.assertEqual(len(result.risk_history), 2)

    def test_initial_planner_failure_does_not_start_generation(self):
        result = self.runtime({"planner": lambda ctx: self.failed("planner")}).run("Add endpoint")
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.state["remediation_attempts"], 0)
        self.assertEqual([call[0] for call in self.calls], ["planner"])

    def test_failed_generator_still_records_patch_risk(self):
        def generator(ctx):
            self.write("auth.py", "partial = True\n")
            return self.failed("generator")
        result = self.runtime({"generator": generator}).run("Change copy")
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.risk.level, "critical")
        self.assertEqual(len(result.risk_history), 1)
        self.assertEqual([call[0] for call in self.calls], ["generator"])

    def test_commits_during_generation_do_not_hide_patch(self):
        original = self.git("rev-parse", "HEAD")
        def generator(ctx):
            self.write("auth.py", "VALUE = 1\n")
            self.git("add", "auth.py")
            self.git("commit", "-m", "generator commit")
        result = self.runtime({"generator": generator}).run("Change copy")
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.risk.level, "critical")
        self.assertEqual(result.risk.evidence["baseline_ref"], original)
        self.assertIn("auth.py", result.risk.evidence["changed_files"])

    def test_trace_files_do_not_escalate_clean_repository(self):
        result = self.runtime().run("Change copy")
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.risk.level, "low")
        self.assertEqual(result.risk.evidence["changed_files"], [])
        self.assertEqual([call[0] for call in self.calls], ["generator", "evaluator"])

    def test_real_command_workers_receive_updated_risk_and_review_phase(self):
        code = (
            "import json, os, pathlib; stage = os.environ['MOREGAN_STAGE']; "
            "pathlib.Path('auth.py').write_text('VALUE = 1\\n') if stage == 'generator' else None; "
            "print(json.dumps({'stage': stage, 'verdict': 'pass', 'confidence': 1, 'evidence': [{"
            "'kind': 'env', 'name': 'phase', 'summary': os.environ['MOREGAN_RISK_LEVEL'] + '|' + os.environ['MOREGAN_STAGE_PHASE']}]}))"
        )
        self.write(".moregan/workers.yaml", "workers:\n" + "".join(
            f"  - stage: {stage}\n    command: {json.dumps([sys.executable, '-c', code])}\n    no_write: false\n"
            for stage in sorted(WORKER_STAGES)
        ))
        self.git("add", ".moregan/workers.yaml")
        self.git("commit", "-m", "worker config")
        result = MoreGANRuntime(self.root).run("Change copy")
        self.assertEqual(result.status, "pass")
        architect = next(stage for stage in result.stages if stage.stage == "architect")
        self.assertEqual(architect.evidence[0].summary, "critical|post_generation_review")

    def test_initial_dirty_sensitive_files_remain_in_the_risk_scope(self):
        self.write("auth.py", "before = True\n")
        result = self.runtime({"generator": lambda ctx: (self.root / "auth.py").unlink()}).run("Change copy")
        self.assertEqual(result.risk_history[0]["previous_level"], "critical")
        self.assertEqual(result.risk_history[0]["observed"]["level"], "low")
        self.assertEqual(result.risk.level, "critical")
        self.assertEqual(self.calls[0][0], "planner")
        self.assertEqual(self.calls[0][3], "standard")

    def test_unborn_repository_keeps_empty_baseline_after_first_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            classifier = RiskClassifier(root)
            self.assertEqual(classifier.classify("Change copy").level, "low")
            (root / "auth.py").write_text("VALUE = 1\n")
            subprocess.run(["git", "add", "auth.py"], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "first"],
                           cwd=root, check=True, capture_output=True)
            risk = classifier.classify("Change copy")
            self.assertEqual(risk.level, "critical")
            self.assertEqual(risk.evidence["baseline_kind"], "empty_tree")
            self.assertEqual(risk.evidence["changed_files"], ["auth.py"])

    def test_unborn_staged_content_is_counted_even_when_working_file_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / "large.txt").write_text("line\n" * 500)
            subprocess.run(["git", "add", "large.txt"], cwd=root, check=True)
            (root / "large.txt").write_text("")
            risk = RiskClassifier(root).classify("Change copy")
            self.assertEqual(risk.level, "high")
            self.assertEqual(risk.evidence["diff"]["insertions"], 500)

    def test_reused_runtime_resets_the_baseline_for_each_run(self):
        def generator(ctx):
            self.write("auth.py", "VALUE = 1\n")
            self.git("add", "auth.py")
            self.git("commit", "-m", "generated")
        runtime = self.runtime({"generator": generator})
        first = runtime.run("Change copy")
        runtime.worker_registry = WorkerRegistry({stage: StubWorker(stage, None, self.calls) for stage in WORKER_STAGES})
        second = runtime.run("Change copy")
        self.assertEqual(first.risk.level, "critical")
        self.assertEqual(second.risk.level, "low")
        self.assertEqual(second.risk.evidence["baseline_ref"], self.git("rev-parse", "HEAD"))

    def test_classifier_handles_staged_deleted_renamed_and_unusual_paths(self):
        self.write("auth/original.txt", "sensitive\n")
        self.git("add", "auth/original.txt")
        self.git("commit", "-m", "sensitive fixture")
        self.git("mv", "auth/original.txt", "ordinary.txt")
        self.write("name\twith\nspaces.txt", "text\n")
        risk = RiskClassifier(self.root).classify("Change copy")
        self.assertEqual(risk.level, "critical")
        self.assertIn("auth/original.txt", risk.evidence["changed_files"])
        self.assertIn("ordinary.txt", risk.evidence["changed_files"])
        self.assertIn("name\twith\nspaces.txt", risk.evidence["changed_files"])
        self.assertEqual(risk.evidence["diff"]["deletions"], 1)

    def test_staged_diff_is_not_double_counted_and_new_file_size_counts(self):
        self.write("copy.txt", "new\n" * 200)
        self.git("add", "copy.txt")
        risk = RiskClassifier(self.root).classify("Change copy")
        self.assertEqual(risk.level, "medium")
        self.assertEqual(risk.evidence["diff"]["insertions"], 200)
        self.write("new.txt", "line\n" * 500)
        self.assertEqual(RiskClassifier(self.root).classify("Change copy").level, "high")

    def test_git_inspection_failure_is_a_structured_run_failure(self):
        runtime = self.runtime()
        with patch.object(runtime.classifier, "_git", side_effect=OSError("Git unavailable")):
            result = runtime.run("Change copy")
        self.assertEqual(result.status, "fail")
        self.assertEqual(self.calls, [])
        self.assertEqual(result.stages[0].findings[0].category, "risk_inspection_failed")
        self.assertTrue((Path(result.trace_path) / "result.json").exists())
        with patch("subprocess.run", side_effect=FileNotFoundError("git")):
            result = self.runtime().run("Change copy")
        self.assertEqual(result.status, "fail")
        self.assertTrue((Path(result.trace_path) / "result.json").exists())

    def test_post_generation_inspection_failure_is_not_a_clean_diff(self):
        def generator(ctx):
            (self.root / ".git").rename(self.root / "git-moved")
        result = self.runtime({"generator": generator}).run("Change copy")
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.stages[-1].findings[0].category, "risk_inspection_failed")
        self.assertEqual([call[0] for call in self.calls], ["generator"])

    def test_risk_route_lists_cannot_mutate_global_routes(self):
        result = RiskClassifier().classify("Change copy")
        result.route.append("bogus")
        self.assertNotIn("bogus", RiskClassifier().classify("Change copy").route)

    def test_replay_uses_embedded_attempt_when_attempt_file_is_missing(self):
        result = self.runtime({"evaluator": lambda ctx: self.failed("evaluator") if ctx.attempt == 1 else None}).run("Change copy")
        run = Path(result.trace_path)
        (run / "stages/evaluator.attempt1.json").unlink()
        replay = RunReplay(run).to_dict()
        self.assertEqual([item["verdict"] for item in replay["stages"] if item["stage"] == "evaluator"], ["fail", "pass"])


if __name__ == "__main__":
    unittest.main()
