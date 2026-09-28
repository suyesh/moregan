"""Isolated benchmark attempts with independent acceptance checks and paired reports."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional
from uuid import uuid4

from moregan import __version__
from moregan.benchmark_fixtures import DEFAULT_BENCHMARK_TASKS
from moregan.runtime import MoreGANRuntime, RiskClassifier
from moregan.workers import WorkerContext, WorkerRegistry


BENCHMARK_VERSION = 1
DEFAULT_SUITE_PATH = Path("benchmarks/moregan-starter.json")
BASELINE_TEMPLATE_PATH = Path("benchmarks/baseline-results.template.json")
METRICS = ("duration_ms", "token_usage", "cost_usd", "human_review_findings")
STATUSES = {"pass", "fail", "pending", "skip", "error"}


class BenchmarkError(ValueError):
    """Invalid benchmark configuration, measurement, or comparison."""


def _read_json(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BenchmarkError(f"Cannot read benchmark JSON at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError(f"Benchmark JSON must be an object: {path}")
    return payload


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", value):
        raise BenchmarkError(f"{label} must be a nonempty identifier (letters, digits, hyphens, underscores)")
    return value


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{label} must be a nonempty string")
    return value


def _strings(value, label):
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise BenchmarkError(f"{label} must be a nonempty list of strings")
    return value


@dataclass
class BenchmarkTask:
    id: str
    category: str
    request: str
    acceptance_criteria: list
    files: dict
    verification: str

    @property
    def fingerprint(self):
        return _digest(asdict(self))

    @property
    def prompt(self):
        return self.request + "\n\nAcceptance criteria:\n" + "\n".join(
            f"- {criterion}" for criterion in self.acceptance_criteria
        )


class BenchmarkSuiteLoader:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def load(self, suite_path: Optional[Path] = None) -> dict:
        path = self.root / (suite_path or DEFAULT_SUITE_PATH)
        suite = _read_json(path)
        if type(suite.get("version")) is not int or suite["version"] != BENCHMARK_VERSION:
            raise BenchmarkError("Unsupported benchmark suite version")
        _identifier(suite.get("name"), "Suite name")
        tasks = self.tasks(suite)
        suite["fingerprint"] = _digest([asdict(task) for task in tasks])
        return suite

    def tasks(self, suite: dict) -> list:
        raw = suite.get("tasks")
        if not isinstance(raw, list) or not raw:
            raise BenchmarkError("Benchmark suite needs a nonempty tasks list")
        tasks = []
        for item in raw:
            if not isinstance(item, dict):
                raise BenchmarkError("Each benchmark task must be an object")
            task_id = _identifier(item.get("id"), "Task id")
            files = item.get("files")
            if not isinstance(files, dict) or not files:
                raise BenchmarkError(f"{task_id}: files must be a nonempty mapping of relative paths to text")
            for name, source in files.items():
                path = PurePosixPath(name)
                if (not name or path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/"))
                        or "\\" in name or ":" in name or path.parts[0] in {".git", ".moregan"}
                        or not isinstance(source, str)):
                    raise BenchmarkError(f"{task_id}: invalid fixture file {name!r}")
            task = BenchmarkTask(
                task_id, _nonempty(item.get("category"), "Category"), _nonempty(item.get("request"), "Request"),
                _strings(item.get("acceptance_criteria"), "Acceptance criteria"), files,
                _nonempty(item.get("verification"), "Verification Python source"),
            )
            try:
                compile(task.verification, f"{task_id}/verify.py", "exec")
            except SyntaxError as exc:
                raise BenchmarkError(f"{task_id}: invalid verification Python: {exc}") from exc
            tasks.append(task)
        if len({task.id for task in tasks}) != len(tasks):
            raise BenchmarkError("Duplicate benchmark task ids")
        return tasks


class BenchmarkInitializer:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def init(self, force: bool = False, dry_run: bool = False) -> list:
        suite = {"version": BENCHMARK_VERSION, "name": "moregan-starter", "tasks": DEFAULT_BENCHMARK_TASKS}
        suite_path = self.root / DEFAULT_SUITE_PATH
        if suite_path.exists() and not force:
            suite = BenchmarkSuiteLoader(self.root).load()
        tasks = BenchmarkSuiteLoader(self.root).tasks(suite)
        template = {
            "version": BENCHMARK_VERSION, "suite_fingerprint": _digest([asdict(task) for task in tasks]),
            "tasks": [{"id": task.id, "status": "pending", "evidence": None,
                       **{key: None for key in METRICS}} for task in tasks],
        }
        actions = []
        for relative, payload in ((DEFAULT_SUITE_PATH, suite), (BASELINE_TEMPLATE_PATH, template)):
            path = self.root / relative
            if path.exists() and not force:
                action = "preserved"
            else:
                action = "updated" if path.exists() else "created"
                if dry_run:
                    action = "would_update" if path.exists() else "would_create"
                else:
                    _write_json(path, payload)
            actions.append({"path": str(relative), "action": action})
        return actions


def _metric(value, name):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise BenchmarkError(f"{name} must be a finite nonnegative number or null")
    if name in {"token_usage", "human_review_findings"} and type(value) is not int:
        raise BenchmarkError(f"{name} must be an integer or null")
    return value


def summarize(tasks):
    measured = [task for task in tasks if task["status"] in {"pass", "fail"}]
    summary = {
        "total_tasks": len(tasks), "measured_tasks": len(measured),
        "pass_count": sum(task["status"] == "pass" for task in tasks),
        "fail_count": sum(task["status"] == "fail" for task in tasks),
        "unmeasured_count": len(tasks) - len(measured),
        "success_rate": sum(task["status"] == "pass" for task in measured) / len(measured) if measured else None,
        "metric_coverage": {},
    }
    for metric in METRICS:
        values = [task[metric] for task in tasks if task.get(metric) is not None]
        summary["metric_coverage"][metric] = len(values)
        summary[metric + "_total"] = sum(values) if len(values) == len(tasks) and tasks else None
    duration = summary["duration_ms_total"]
    summary["average_duration_ms"] = duration / len(tasks) if duration is not None else None
    return summary


def _run_id(label):
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + "-" + label + "-" + uuid4().hex[:8]


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


class BenchmarkRunner:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.loader = BenchmarkSuiteLoader(self.root)

    def run(self, suite_path: Optional[Path] = None, mode: str = "moregan",
            baseline_results_path: Optional[Path] = None, limit: Optional[int] = None,
            verification_timeout: int = 30) -> dict:
        if mode not in {"moregan", "baseline"}:
            raise BenchmarkError("Mode must be moregan or baseline")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise BenchmarkError("Limit must be a positive integer")
        if type(verification_timeout) is not int or verification_timeout < 1:
            raise BenchmarkError("Verification timeout must be a positive integer")
        if baseline_results_path and mode != "baseline":
            raise BenchmarkError("--baseline-results requires --mode baseline")
        suite = self.loader.load(suite_path)
        all_tasks = self.loader.tasks(suite)
        imported = self._load_baseline(baseline_results_path, suite, all_tasks) if baseline_results_path else None
        tasks = all_tasks[:limit]
        run_dir = self.root / ".moregan/benchmarks/runs" / _run_id(mode)
        run_dir.mkdir(parents=True)
        started = time.perf_counter()
        payload = {
            "version": BENCHMARK_VERSION, "run_id": run_dir.name, "mode": mode,
            "measurement_source": "external_import" if imported is not None else "executed",
            "suite": {"name": suite["name"], "fingerprint": suite["fingerprint"]},
            "environment": None if imported is not None else {
                "moregan": __version__, "python": platform.python_version(), "platform": platform.system(),
            },
            "started_at": _timestamp(), "status": "running",
            "tasks": [{"id": task.id, "category": task.category, "task_fingerprint": task.fingerprint,
                       "status": "pending", "success": None, **{key: None for key in METRICS}} for task in tasks],
        }
        _write_json(run_dir / "suite.json", suite)
        self._save(run_dir, payload)
        for index, task in enumerate(tasks):
            result = dict(payload["tasks"][index])
            try:
                if imported is not None:
                    result.update(imported.get(task.id, {"status": "pending", "evidence": None}))
                else:
                    result.update(self._execute(task, mode, run_dir / "tasks" / task.id, verification_timeout))
            except Exception as exc:
                # Persist the failed attempt and continue so one provider error does not erase the suite.
                result.update(status="error", error=f"{type(exc).__name__}: {exc}")
            result["success"] = True if result["status"] == "pass" else False if result["status"] == "fail" else None
            payload["tasks"][index] = result
            self._save(run_dir, payload)
        summary = summarize(payload["tasks"])
        payload.update(
            status="incomplete" if summary["unmeasured_count"] else "fail" if summary["fail_count"] else "pass",
            completed_at=_timestamp(), duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self._save(run_dir, payload)
        return payload

    def _save(self, directory, payload):
        payload["summary"] = summarize(payload["tasks"])
        payload["result_path"] = str(directory / "result.json")
        payload["report_path"] = str(directory / "report.md")
        _write_json(directory / "result.json", payload)
        (directory / "report.md").write_text(render_benchmark_report(payload), encoding="utf-8")

    def _execute(self, task, mode, directory, timeout):
        directory.mkdir(parents=True)
        # Only fixture files enter the worker's cwd. No files from the user's checkout are copied here.
        with tempfile.TemporaryDirectory(prefix="moregan-benchmark-") as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            for name, content in task.files.items():
                target = workspace / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            config = workspace / ".moregan"
            config.mkdir()
            workers = self.root / ".moregan/workers.yaml"
            if workers.exists():
                shutil.copy2(workers, config / "workers.yaml")
            adapters = self.root / ".moregan/adapters"
            if adapters.is_dir():
                shutil.copytree(adapters, config / "adapters")
            self._init_git(workspace, Path(temporary) / "empty-git-template")
            started = time.perf_counter()
            if mode == "moregan":
                run = MoreGANRuntime(workspace).run(task.prompt)
                stages = run.stages
                risk = run.risk.level
                latest = {stage.stage: stage for stage in stages}
                skipped = [name for name in run.risk.route if name in latest and latest[name].verdict == "skip"]
                unreached = [name for name in run.risk.route if name not in latest]
                workflow_status = "incomplete" if skipped or (unreached and run.status != "fail") else run.status
                trace_path = directory / "trace"
                shutil.copytree(run.trace_path, trace_path)
            else:
                classification = RiskClassifier(workspace).classify(task.prompt)
                context = WorkerContext(workspace, directory.parent.parent.name, task.prompt,
                                        classification, ["generator"])
                stage = WorkerRegistry.from_root(workspace).get("generator").run(context)
                stages, risk = [stage], classification.level
                skipped = ["generator"] if stage.verdict == "skip" else []
                unreached = []
                workflow_status = "incomplete" if skipped else stage.verdict
                trace_path = directory / "trace"
                _write_json(trace_path / "generator.json", asdict(stage))
            generation_ms = int((time.perf_counter() - started) * 1000)
            # Materialize the trusted verifier only after workers return. It is outside the editable project.
            verifier = Path(temporary) / "verify.py"
            verifier.write_text(task.verification, encoding="utf-8")
            verification = self._verify(verifier, workspace, timeout)
            _write_json(directory / "verification.json", verification)
            # Keep the patch and local trace for inspection, excluding recursively copied run artifacts.
            shutil.copytree(workspace, directory / "workspace",
                            ignore=shutil.ignore_patterns(".git", ".moregan", "__pycache__"))
            final_stages = {stage.stage: stage for stage in stages}
            provider_errors = [stage.stage for stage in final_stages.values() if stage.verdict == "fail" and any(
                finding.category in {"worker_provider_failed", "worker_config_invalid", "agent_provider_failed"}
                for finding in stage.findings
            )]
            if provider_errors:
                status = "error"
            elif workflow_status == "incomplete":
                status = "skip"
            elif verification["status"] == "error":
                status = "error"
            elif workflow_status == "fail" or verification["status"] == "fail":
                status = "fail"
            else:
                status = "pass"
            return {
                "status": status, "workflow_status": workflow_status, "skipped_stages": skipped,
                "provider_error_stages": provider_errors,
                "unreached_stages": unreached,
                "duration_ms": generation_ms + verification["duration_ms"], "risk": risk,
                "verification": verification, "trace_path": str(trace_path),
                "finding_count": sum(len(stage.findings) for stage in stages),
                "iterations": max(stage.attempt for stage in stages),
                "evidence": str(directory / "verification.json"),
            }

    def _init_git(self, workspace, template):
        template.mkdir()
        ignore = workspace / ".gitignore"
        existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        ignore.write_text(existing + "\n.moregan/\n__pycache__/\n*.pyc\n", encoding="utf-8")
        # A fixture commit gives agents a real diff without inheriting a caller's Git directory or hooks.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        commands = [
            ["git", "init", "--quiet", f"--template={template}"],
            ["git", "add", "--all"],
            ["git", "-c", "user.name=MoreGAN Benchmark", "-c", "user.email=benchmark@moregan.local",
             "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={template}",
             "commit", "--quiet", "--allow-empty", "-m", "Benchmark fixture"],
        ]
        for command in commands:
            subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True, check=True, timeout=15)

    def _verify(self, verifier, workspace, timeout):
        started = time.perf_counter()
        try:
            result = subprocess.run([sys.executable, "-I", str(verifier), str(workspace)], cwd=workspace,
                                    capture_output=True, text=True, timeout=timeout, check=False)
            evidence = {"status": "pass" if result.returncode == 0 else "fail", "exit_code": result.returncode,
                        "stdout_tail": result.stdout[-4000:], "stderr_tail": result.stderr[-4000:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            evidence = {"status": "error", "exit_code": None, "error": str(exc)}
        evidence["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return evidence

    def _load_baseline(self, path, suite, tasks):
        payload = _read_json(self.root / path)
        if (type(payload.get("version")) is not int or payload["version"] != BENCHMARK_VERSION
                or payload.get("suite_fingerprint") != suite["fingerprint"]):
            raise BenchmarkError("Baseline version or suite fingerprint does not match this suite")
        values = payload.get("tasks")
        if not isinstance(values, list):
            raise BenchmarkError("Baseline tasks must be a list")
        records = {}
        known = {task.id for task in tasks}
        for item in values:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or item["id"] not in known or item["id"] in records):
                raise BenchmarkError("Unknown or duplicate baseline task id")
            status = item.get("status")
            if not isinstance(status, str) or status not in STATUSES:
                raise BenchmarkError("Invalid baseline task status")
            if status in {"pass", "fail"}:
                _nonempty(item.get("evidence"), "Measured baseline evidence reference")
            records[item["id"]] = {
                "status": status, "evidence": item.get("evidence"),
                **{key: _metric(item.get(key), key) for key in METRICS},
            }
        return records


def resolve_benchmark_run(root, ref):
    root = Path(root).resolve()
    runs = root / ".moregan/benchmarks/runs"
    if ref == "latest":
        candidates = sorted(runs.glob("*/result.json"))
        if not candidates:
            raise BenchmarkError("No benchmark runs found")
        return candidates[-1]
    path = root / ref
    if path.is_dir():
        path = path / "result.json"
    if path.is_file():
        return path
    path = runs / ref / "result.json"
    if path.is_file():
        return path
    raise BenchmarkError(f"Benchmark result not found: {ref}")


def load_benchmark_run(root, ref):
    payload = _read_json(resolve_benchmark_run(root, ref))
    if (type(payload.get("version")) is not int or payload["version"] != BENCHMARK_VERSION
            or payload.get("mode") not in ("baseline", "moregan")):
        raise BenchmarkError("Invalid benchmark result version or mode")
    _identifier(payload.get("run_id"), "Run id")
    if payload.get("measurement_source") not in ("external_import", "executed"):
        raise BenchmarkError("Invalid measurement source")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise BenchmarkError("Benchmark result tasks must be a list")
    seen = set()
    for item in tasks:
        if not isinstance(item, dict):
            raise BenchmarkError("Invalid benchmark result task")
        task_id = _identifier(item.get("id"), "Result task id")
        if task_id in seen or not isinstance(item.get("status"), str) or item["status"] not in STATUSES:
            raise BenchmarkError("Duplicate task or invalid result status")
        seen.add(task_id)
        _nonempty(item.get("task_fingerprint"), "Task fingerprint")
        for metric in METRICS:
            _metric(item.get(metric), metric)
    payload["summary"] = summarize(tasks)
    return payload


class BenchmarkComparator:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def compare(self, baseline_ref: str, moregan_ref: str) -> dict:
        baseline, moregan = (load_benchmark_run(self.root, ref) for ref in (baseline_ref, moregan_ref))
        if baseline["mode"] != "baseline" or moregan["mode"] != "moregan":
            raise BenchmarkError("Compare requires a baseline run followed by a MoreGAN run")
        left = {task["id"]: task for task in baseline["tasks"]}
        right = {task["id"]: task for task in moregan["tasks"]}
        if not left or set(left) != set(right):
            raise BenchmarkError("Comparison requires the same nonempty task set in both runs")
        for task_id in left:
            if left[task_id]["task_fingerprint"] != right[task_id]["task_fingerprint"]:
                raise BenchmarkError(f"Task definition differs between runs: {task_id}")
        paired = sorted(task_id for task_id in left if left[task_id]["status"] in {"pass", "fail"}
                        and right[task_id]["status"] in {"pass", "fail"})
        left_summary, right_summary = (summarize([side[task_id] for task_id in paired]) for side in (left, right))
        comparison = {
            "version": BENCHMARK_VERSION, "created_at": _timestamp(),
            "baseline_run_id": baseline["run_id"], "moregan_run_id": moregan["run_id"],
            "paired_task_count": len(paired), "total_tasks": len(left),
            "unmeasured_tasks": sorted(set(left) - set(paired)),
            "baseline_summary": left_summary, "moregan_summary": right_summary,
            "measurement_sources": [baseline.get("measurement_source"), moregan.get("measurement_source")],
            "environment_matches": (baseline["environment"] == moregan["environment"]
                                    if baseline.get("environment") and moregan.get("environment") else None),
            "delta": {key: _delta(left_summary.get(key), right_summary.get(key)) for key in
                      ("success_rate", "average_duration_ms", "token_usage_total", "cost_usd_total",
                       "human_review_findings_total")},
            "improvements": [key for key in paired if left[key]["status"] == "fail" and right[key]["status"] == "pass"],
            "regressions": [key for key in paired if left[key]["status"] == "pass" and right[key]["status"] == "fail"],
        }
        directory = self.root / ".moregan/benchmarks/comparisons" / _run_id("comparison")
        comparison["result_path"] = str(directory / "comparison.json")
        comparison["report_path"] = str(directory / "comparison.md")
        _write_json(directory / "comparison.json", comparison)
        (directory / "comparison.md").write_text(render_comparison_report(comparison), encoding="utf-8")
        return comparison


def _delta(left, right):
    return right - left if left is not None and right is not None else None


def _rate(value):
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def render_benchmark_report(payload):
    summary = payload["summary"]
    lines = ["# MoreGAN Benchmark Report", "", f"- Run: `{payload['run_id']}`",
             f"- Mode: {payload['mode']} ({payload['measurement_source']})", f"- Status: {payload['status']}",
             f"- Measured tasks: {summary['measured_tasks']}/{summary['total_tasks']}",
             f"- Success rate on measured tasks: {_rate(summary['success_rate'])}", "",
             "| Task | Status | Duration (ms) |", "|---|---|---:|"]
    for task in payload["tasks"]:
        lines.append(f"| {task['id']} | {task['status']} | {task.get('duration_ms')} |")
    lines.extend(["", "## Metric Coverage", ""])
    for metric, count in summary["metric_coverage"].items():
        lines.append(f"- {metric}: {count}/{summary['total_tasks']}")
    lines.extend(["", "Missing measurements are null, never zero. Skipped or errored tasks are unmeasured.",
                  "Starter fixtures are smoke benchmarks; they do not establish production effectiveness.", ""])
    return "\n".join(lines)


def render_comparison_report(payload):
    delta = payload["delta"]["success_rate"]
    rate = f"{delta * 100:+.1f} percentage points" if delta is not None else "n/a"
    return "\n".join([
        "# MoreGAN Benchmark Comparison", "", f"- Baseline: `{payload['baseline_run_id']}`",
        f"- MoreGAN: `{payload['moregan_run_id']}`",
        f"- Measured pairs: {payload['paired_task_count']}/{payload['total_tasks']}",
        f"- Success-rate delta on measured pairs: {rate}",
        f"- Improvements: {', '.join(payload['improvements']) or 'none'}",
        f"- Regressions: {', '.join(payload['regressions']) or 'none'}",
        f"- Unmeasured tasks: {', '.join(payload['unmeasured_tasks']) or 'none'}",
        f"- Measurement sources: {', '.join(payload['measurement_sources'])}",
        f"- Recorded environments match: {payload['environment_matches']}", "",
        "Only identical tasks measured in both runs contribute to deltas.",
        "Control provider/model settings and repeat runs before drawing conclusions.", "",
    ])
