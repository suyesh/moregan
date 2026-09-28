"""Executable runtime primitives for MoreGAN.

This module is intentionally deterministic. It does not generate code or ask an
LLM to self-grade; it creates auditable run traces and records local evidence
that higher-level agent orchestration can consume.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from moregan.context import ContextPackWriter
from moregan.learning import EmpiricalLearningStore
from moregan.schemas import (
    CommandEvidence,
    EvidenceReference,
    Finding,
    HarnessRunResult,
    RiskClassification,
    Severity,
    StageResult,
)
from moregan.state import StateMachine, StateSnapshot, TaskState
from moregan.tools import StackToolDetector, ToolCommand, ToolConfigError, ToolConfigLoader, ToolSuggestion
from moregan.workers import WORKER_STAGE_TO_STATE, WorkerContext, WorkerRegistry


RISK_KEYWORDS: Dict[str, List[str]] = {
    "critical": [
        "authentication",
        "authorization",
        "auth",
        "payment",
        "billing",
        "encryption",
        "secret",
        "token",
        "permission",
        "migration",
    ],
    "high": [
        "database",
        "schema",
        "public api",
        "infrastructure",
        "deploy",
        "dependency",
        "security",
        "firewall",
        "rate limit",
    ],
    "medium": [
        "refactor",
        "endpoint",
        "service",
        "cache",
        "background job",
        "configuration",
        "config",
        "tests",
    ],
}

RISK_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

CRITICAL_PATH_PATTERNS = [
    "auth",
    "authentication",
    "authorization",
    "permission",
    "payment",
    "billing",
    "stripe",
    "secret",
    "token",
    "migration",
]

HIGH_PATH_PATTERNS = [
    "database",
    "schema",
    "deploy",
    "dockerfile",
    "docker-compose",
    "terraform",
    "kubernetes",
    ".github/workflows",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "gemfile",
    "cargo.toml",
    "go.mod",
]

MEDIUM_PATH_PATTERNS = ["api", "controller", "route", "service", "config", "test", "spec"]

ROUTES_BY_RISK: Dict[str, List[str]] = {
    "low": ["generator", "deterministic_evidence", "evaluator"],
    "medium": ["planner", "generator", "deterministic_evidence", "evaluator", "code_reviewer"],
    "high": [
        "planner",
        "architect",
        "generator",
        "deterministic_evidence",
        "evaluator",
        "security_evaluator",
        "code_reviewer",
        "production_readiness_reviewer",
        "mr_readiness_analyzer",
        "learning_curator",
    ],
    "critical": [
        "planner",
        "architect",
        "designer_decision",
        "generator",
        "deterministic_evidence",
        "evaluator",
        "security_evaluator",
        "code_reviewer",
        "production_readiness_reviewer",
        "mr_readiness_analyzer",
        "learning_curator",
    ],
}


class RiskClassifier:
    """Routes work by risk before persona selection."""

    def __init__(self, root: Optional[Path] = None):
        self.root = root.resolve() if root else None

    def classify(self, request: str) -> RiskClassification:
        normalized = request.lower()
        selected_level = "low"
        reasons: List[str] = []
        confidence = 0.6
        for level in ("critical", "high", "medium"):
            matches = [keyword for keyword in RISK_KEYWORDS[level] if keyword in normalized]
            if matches:
                selected_level = level
                reasons.extend(f"matched request keyword: {keyword}" for keyword in matches)
                confidence = max(confidence, 0.8)
                break

        repository_evidence = self._repository_evidence()
        repository_level, repository_reasons = self._repository_risk(repository_evidence)
        if repository_reasons:
            reasons.extend(repository_reasons)
            confidence = max(confidence, 0.75)
        selected_level = self._max_level(selected_level, repository_level)
        if not reasons:
            reasons.append("no high-risk request keywords or repository changes matched")
        return RiskClassification(
            level=selected_level,  # type: ignore[arg-type]
            reasons=reasons,
            route=ROUTES_BY_RISK[selected_level],
            confidence=confidence,
            evidence=repository_evidence,
        )

    def _repository_evidence(self) -> Dict[str, object]:
        if self.root is None:
            return {"source": "not_configured", "changed_files": [], "changed_file_count": 0}
        if not (self.root / ".git").exists():
            return {"source": "no_git_repository", "changed_files": [], "changed_file_count": 0}

        status = self._git_lines(["git", "status", "--short", "--untracked-files=all"])
        changed_files = self._changed_files_from_status(status)
        diff = self._diff_stats()
        return {
            "source": "git",
            "changed_files": changed_files,
            "changed_file_count": len(changed_files),
            "status": status[:120],
            "diff": diff,
        }

    def _repository_risk(self, evidence: Dict[str, object]) -> Tuple[str, List[str]]:
        changed_files = [str(item) for item in evidence.get("changed_files", []) if item]
        diff = evidence.get("diff", {})
        insertions = int(diff.get("insertions", 0)) if isinstance(diff, dict) else 0
        deletions = int(diff.get("deletions", 0)) if isinstance(diff, dict) else 0
        total_changed_lines = insertions + deletions
        reasons = []
        level = "low"

        critical_paths = [path for path in changed_files if self._matches_any(path, CRITICAL_PATH_PATTERNS)]
        high_paths = [path for path in changed_files if self._matches_any(path, HIGH_PATH_PATTERNS)]
        medium_paths = [path for path in changed_files if self._matches_any(path, MEDIUM_PATH_PATTERNS)]

        if critical_paths:
            level = self._max_level(level, "critical")
            reasons.append(f"repository critical-risk paths changed: {', '.join(critical_paths[:5])}")
        if high_paths:
            level = self._max_level(level, "high")
            reasons.append(f"repository high-risk paths changed: {', '.join(high_paths[:5])}")
        if medium_paths:
            level = self._max_level(level, "medium")
            reasons.append(f"repository medium-risk paths changed: {', '.join(medium_paths[:5])}")
        if len(changed_files) >= 8:
            level = self._max_level(level, "high")
            reasons.append(f"repository diff touches {len(changed_files)} files")
        elif len(changed_files) >= 3:
            level = self._max_level(level, "medium")
            reasons.append(f"repository diff touches {len(changed_files)} files")
        if total_changed_lines >= 400:
            level = self._max_level(level, "high")
            reasons.append(f"repository diff changes {total_changed_lines} lines")
        elif total_changed_lines >= 80:
            level = self._max_level(level, "medium")
            reasons.append(f"repository diff changes {total_changed_lines} lines")
        return level, reasons

    def _git_lines(self, command: Sequence[str]) -> List[str]:
        if self.root is None:
            return []
        result = subprocess.run(command, cwd=self.root, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line]

    def _changed_files_from_status(self, lines: Sequence[str]) -> List[str]:
        changed = []
        for line in lines:
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            changed.append(path)
        return sorted(set(changed))

    def _diff_stats(self) -> Dict[str, int]:
        if self.root is None:
            return {"files": 0, "insertions": 0, "deletions": 0}
        files = set()
        insertions = 0
        deletions = 0
        for command in (["git", "diff", "--numstat"], ["git", "diff", "--cached", "--numstat"]):
            result = subprocess.run(command, cwd=self.root, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                continue
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                added, removed, path = parts[0], parts[1], parts[2]
                files.add(path)
                insertions += int(added) if added.isdigit() else 0
                deletions += int(removed) if removed.isdigit() else 0
        return {"files": len(files), "insertions": insertions, "deletions": deletions}

    def _matches_any(self, path: str, patterns: Sequence[str]) -> bool:
        normalized = path.lower()
        return any(pattern in normalized for pattern in patterns)

    def _max_level(self, left: str, right: str) -> str:
        return left if RISK_LEVEL_ORDER[left] >= RISK_LEVEL_ORDER[right] else right


class TraceWriter:
    """Writes durable per-run artifacts under .moregan/runs."""

    def __init__(self, root: Path):
        self.root = root

    def create_run_dir(self, request: str) -> Path:
        runs_dir = self.root / ".moregan" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = self._slugify(request)
        run_dir = runs_dir / f"{timestamp}-{slug}"
        counter = 1
        while run_dir.exists():
            run_dir = runs_dir / f"{timestamp}-{slug}-{counter}"
            counter += 1
        run_dir.mkdir()
        (run_dir / "stages").mkdir()
        return run_dir

    def event(self, run_dir: Path, event_type: str, **payload: object) -> None:
        event = {"type": event_type, "timestamp": datetime.now().isoformat(timespec="seconds"), **payload}
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def write_json(self, run_dir: Path, name: str, payload: object) -> None:
        target = run_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def write_stage(self, run_dir: Path, result: StageResult) -> None:
        payload = asdict(result)
        self.write_json(run_dir, f"stages/{result.stage}.json", payload)
        self.write_json(run_dir, f"stages/{result.stage}.attempt{result.attempt}.json", payload)

    def write_state(self, run_dir: Path, state_machine: StateMachine, snapshot: StateSnapshot) -> None:
        self.write_json(run_dir, "state.json", state_machine.to_dict())
        with (run_dir / "states.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(snapshot), sort_keys=True) + "\n")

    def write_report(self, run_dir: Path, result: HarnessRunResult) -> None:
        lines = [
            "# MoreGAN Run Report",
            "",
            f"- Run: `{result.run_id}`",
            f"- Status: `{result.status}`",
            f"- Risk: `{result.risk.level}`",
            f"- Request: {result.request}",
            "",
            "## State",
            "",
            f"- Current: `{result.state['current_state']}`",
            f"- Transitions: {len(result.state['history'])}",
            "",
            "## Route",
            "",
        ]
        lines.extend(f"- {stage}" for stage in result.risk.route)
        if result.incomplete_stages:
            lines.extend(["", "## Incomplete Stages", ""])
            lines.extend(f"- {stage}" for stage in result.incomplete_stages)
        lines.extend(["", "## Stage Results", ""])
        for stage in result.stages:
            detail = f"{stage.verdict.upper()} ({stage.confidence:.2f} confidence)"
            if stage.attempt > 1:
                detail += f", attempt {stage.attempt}"
            if stage.findings:
                detail += f", {len(stage.findings)} finding(s)"
            lines.append(f"- {stage.stage}: {detail}")

        lines.extend(["", "## Deterministic Evidence", ""])
        if not result.evidence:
            lines.append("- No deterministic command evidence was collected.")
        for item in result.evidence:
            status = "SKIP" if item.skipped else "PASS" if item.passed else "FAIL"
            detail = item.reason or " ".join(item.command)
            required = "required" if item.required else "optional"
            lines.append(
                f"- {status}: {item.name} "
                f"(attempt {item.attempt}, {item.category}, {required}, {item.duration_ms}ms) - {detail}"
            )

        lines.extend(["", "## Learning", ""])
        learning = self._learning_summary(run_dir)
        if learning is None:
            lines.append("- No learning artifact was recorded.")
        else:
            lines.append(f"- Observations: {learning.get('observation_count', 0)}")
            for pattern in learning.get("patterns", []):
                if not isinstance(pattern, dict):
                    continue
                stats = pattern.get("statistics", {})
                confidence = float(stats.get("confidence", 0.0)) if isinstance(stats, dict) else 0.0
                lines.append(f"- Pattern `{pattern.get('pattern_id')}` confidence {confidence:.3f}")

        (run_dir / "final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _slugify(self, request: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", request.lower()).strip("-")
        return (slug or "run")[:48]

    def _learning_summary(self, run_dir: Path) -> Optional[Dict[str, object]]:
        path = run_dir / "learning.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None


class DeterministicEvidenceRunner:
    """Runs local checks that should not be delegated to an LLM."""

    def __init__(self, root: Path):
        self.root = root
        self.tool_loader = ToolConfigLoader(root)
        self.stack_detector = StackToolDetector(root)

    def run_all(self) -> List[CommandEvidence]:
        try:
            tools = self.tool_loader.load()
        except ToolConfigError as exc:
            return [
                CommandEvidence(
                    name="tool_config",
                    command=[],
                    passed=False,
                    exit_code=2,
                    category="configuration",
                    required=True,
                    remediation="Fix .moregan/tools.yaml so MoreGAN can load deterministic checks.",
                    source=str(ToolConfigLoader.CONFIG_PATH),
                    stderr_tail=str(exc),
                )
            ]

        return [self._run_tool(tool) for tool in tools if tool.enabled]

    def suggest_tools(self) -> List[ToolSuggestion]:
        return self.stack_detector.suggest()

    def _run_tool(self, tool: ToolCommand) -> CommandEvidence:
        if tool.builtin == "git_diff_check":
            return self._git_diff_check(tool)
        if tool.builtin == "python_compile":
            return self._python_compile_check(tool)
        if tool.builtin == "unit_tests":
            return self._unittest_check(tool)
        if tool.builtin:
            return CommandEvidence(
                name=tool.name,
                command=[],
                passed=False,
                exit_code=2,
                category=tool.category,
                required=tool.required,
                remediation=f"Use a supported builtin or explicit command for {tool.name}.",
                source=tool.source,
                stderr_tail=f"unsupported builtin: {tool.builtin}",
            )
        if not tool.command:
            return CommandEvidence(
                name=tool.name,
                command=[],
                passed=False,
                exit_code=2,
                category=tool.category,
                required=tool.required,
                remediation=f"Add a command for {tool.name}.",
                source=tool.source,
                stderr_tail="tool command is empty",
            )
        return self._run(tool, tool.command)

    def _git_diff_check(self, tool: ToolCommand) -> CommandEvidence:
        if not (self.root / ".git").exists():
            return self._skip(tool, ".git not found")
        return self._run(tool, ["git", "diff", "--check"])

    def _python_compile_check(self, tool: ToolCommand) -> CommandEvidence:
        python_files = list(self._python_files())
        if not python_files:
            return self._skip(tool, "no Python files found")
        return self._run(tool, [sys.executable, "-m", "py_compile", *python_files])

    def _unittest_check(self, tool: ToolCommand) -> CommandEvidence:
        if not (self.root / "tests").is_dir():
            return self._skip(tool, "tests/ not found")
        return self._run(tool, [sys.executable, "-m", "unittest", "discover", "-s", "tests"])

    def _python_files(self) -> Iterable[str]:
        if (self.root / ".git").exists():
            tracked = self._git_file_list(["git", "ls-files", "*.py"])
            untracked = self._git_file_list(["git", "ls-files", "--others", "--exclude-standard", "*.py"])
            if tracked is not None and untracked is not None:
                return sorted(set(tracked + untracked))

        ignored_parts = {".git", ".venv", "venv", "__pycache__", "build", "dist"}
        return [
            str(path.relative_to(self.root))
            for path in self.root.rglob("*.py")
            if not ignored_parts.intersection(path.relative_to(self.root).parts)
        ]

    def _git_file_list(self, command: Sequence[str]) -> Optional[List[str]]:
        result = subprocess.run(command, cwd=self.root, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return [line for line in result.stdout.splitlines() if line]

    def _run(self, tool: ToolCommand, command: Sequence[str]) -> CommandEvidence:
        started = time.perf_counter()
        try:
            result = subprocess.run(command, cwd=self.root, check=False, capture_output=True, text=True)
        except FileNotFoundError as exc:
            return CommandEvidence(
                name=tool.name,
                command=list(command),
                passed=not tool.required,
                exit_code=127,
                category=tool.category,
                required=tool.required,
                duration_ms=self._duration_ms(started),
                remediation=tool.remediation,
                source=tool.source,
                skipped=not tool.required,
                reason=f"command not found: {command[0]}" if command else "command not found",
                stderr_tail=str(exc),
            )
        return CommandEvidence(
            name=tool.name,
            command=list(command),
            passed=result.returncode == 0,
            exit_code=result.returncode,
            category=tool.category,
            required=tool.required,
            duration_ms=self._duration_ms(started),
            remediation=tool.remediation,
            source=tool.source,
            stdout_tail=self._tail(result.stdout),
            stderr_tail=self._tail(result.stderr),
        )

    def _skip(self, tool: ToolCommand, reason: str) -> CommandEvidence:
        return CommandEvidence(
            name=tool.name,
            command=[],
            passed=True,
            exit_code=0,
            category=tool.category,
            required=tool.required,
            remediation=tool.remediation,
            source=tool.source,
            skipped=True,
            reason=reason,
        )

    def _tail(self, value: str, limit: int = 4000) -> str:
        return value[-limit:] if len(value) > limit else value

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


class MoreGANRuntime:
    """Coordinates a deterministic MoreGAN run trace."""

    def __init__(self, root: Path, max_remediation_attempts: int = 3):
        self.root = root.resolve()
        self.max_remediation_attempts = max(0, max_remediation_attempts)
        self.classifier = RiskClassifier(self.root)
        self.trace_writer = TraceWriter(self.root)
        self.context_writer = ContextPackWriter(self.root)
        self.learning_store = EmpiricalLearningStore(self.root)
        self.evidence_runner = DeterministicEvidenceRunner(self.root)
        self.worker_registry = WorkerRegistry.from_root(self.root)

    def run(self, request: str, run_checks: bool = True) -> HarnessRunResult:
        run_dir = self.trace_writer.create_run_dir(request)
        run_id = run_dir.name
        state_machine = StateMachine(
            run_id=run_id,
            request=request,
            max_remediation_attempts=self.max_remediation_attempts,
            timestamp_factory=self._timestamp,
        )
        self.trace_writer.write_state(run_dir, state_machine, state_machine.latest_snapshot)
        self.trace_writer.event(run_dir, "run.started", request=request)

        self._transition(
            run_dir,
            state_machine,
            TaskState.RISK_CLASSIFICATION,
            reason="classifying request risk and selecting runtime route",
            stage="risk_classifier",
        )
        risk_start = time.perf_counter()
        risk_started_at = self._timestamp()
        risk = self.classifier.classify(request)
        risk_stage = StageResult(
            stage="risk_classifier",
            verdict="pass",
            confidence=risk.confidence,
            findings=[],
            evidence=[
                EvidenceReference(
                    kind="routing",
                    name="selected_route",
                    summary=f"{risk.level} risk route selected: {', '.join(risk.route)}",
                ),
                *[
                    EvidenceReference(kind="heuristic", name="risk_reason", summary=reason)
                    for reason in risk.reasons
                ],
            ],
            started_at=risk_started_at,
            completed_at=self._timestamp(),
            duration_ms=self._duration_ms(risk_start),
        )
        self.trace_writer.write_json(run_dir, "request.json", {"request": request})
        self.trace_writer.write_json(run_dir, "plan.json", {"risk": asdict(risk), "route": risk.route})
        self.trace_writer.write_json(run_dir, "risk.json", asdict(risk))
        self.trace_writer.write_stage(run_dir, risk_stage)
        self.trace_writer.event(run_dir, "risk.classified", level=risk.level, reasons=risk.reasons)
        tool_suggestions = self.evidence_runner.suggest_tools()
        self.trace_writer.write_json(
            run_dir,
            "tool_suggestions.json",
            [asdict(suggestion) for suggestion in tool_suggestions],
        )
        self.context_writer.write_base_context(
            run_dir=run_dir,
            request=request,
            risk=risk,
            tool_suggestions=tool_suggestions,
        )

        evidence: List[CommandEvidence] = []
        stages = [risk_stage]
        remediation_contexts: List[Dict[str, object]] = []
        status = "pass"
        terminal_reason = "all routed stages completed without blocking failures"
        current_index = 0
        remediation_context: Optional[Dict[str, object]] = None

        while current_index < len(risk.route):
            route_stage = risk.route[current_index]
            attempt = max(1, state_machine.run_state.remediation_attempts + 1)

            if route_stage == "deterministic_evidence":
                evidence_stage, current_evidence = self._run_deterministic_evidence(
                    run_dir=run_dir,
                    state_machine=state_machine,
                    run_checks=run_checks,
                    attempt=attempt,
                )
                evidence.extend(current_evidence)
                stages.append(evidence_stage)
                if evidence_stage.verdict == "fail":
                    remediated = self._attempt_remediation(
                        run_dir=run_dir,
                        state_machine=state_machine,
                        stages=stages,
                        failed_stage=evidence_stage,
                        failed_route_index=current_index,
                        risk=risk,
                        request=request,
                        evidence=current_evidence,
                        remediation_contexts=remediation_contexts,
                    )
                    if remediated is None:
                        status = "fail"
                        terminal_reason = "blocking deterministic checks failed"
                        if state_machine.run_state.remediation_attempts:
                            terminal_reason += " after remediation attempts"
                        break
                    current_index = remediated["retry_index"]  # type: ignore[assignment]
                    remediation_context = remediated["context"]  # type: ignore[assignment]
                    continue
                current_index += 1
                continue

            context_pack = self.context_writer.write_stage_context(
                run_dir=run_dir,
                request=request,
                risk=risk,
                stage=route_stage,
                attempt=attempt,
                stages=stages,
                evidence=evidence,
                remediation_context=remediation_context,
            )
            worker_context = WorkerContext(
                root=self.root,
                run_id=run_id,
                request=request,
                risk=risk,
                route=risk.route,
                attempt=attempt,
                remediation_context=remediation_context,
                context_pack_path=context_pack.path,
                context_estimated_tokens=context_pack.estimated_tokens,
            )
            worker_stage = self._run_worker_stage(
                run_dir=run_dir,
                state_machine=state_machine,
                route_stage=route_stage,
                context=worker_context,
                attempt=attempt,
            )
            stages.append(worker_stage)
            if worker_stage.verdict == "fail":
                remediated = self._attempt_remediation(
                    run_dir=run_dir,
                    state_machine=state_machine,
                    stages=stages,
                    failed_stage=worker_stage,
                    failed_route_index=current_index,
                    risk=risk,
                    request=request,
                    evidence=[],
                    remediation_contexts=remediation_contexts,
                )
                if remediated is None:
                    status = "fail"
                    terminal_reason = f"{route_stage} worker failed"
                    if route_stage != "generator" and state_machine.run_state.remediation_attempts:
                        terminal_reason += " after remediation attempts"
                    break
                current_index = remediated["retry_index"]  # type: ignore[assignment]
                remediation_context = remediated["context"]  # type: ignore[assignment]
                continue
            current_index += 1

        latest_stages = {stage.stage: stage for stage in stages}
        incomplete_stages = [name for name in risk.route if name not in latest_stages
                             or latest_stages[name].verdict == "skip"]
        if status == "pass" and incomplete_stages:
            status = "incomplete"
            terminal_reason = "required stages were not executed: " + ", ".join(incomplete_stages)
        terminal_state = {"pass": TaskState.COMPLETED, "fail": TaskState.FAILED, "incomplete": TaskState.INCOMPLETE}
        self._transition(
            run_dir,
            state_machine,
            terminal_state[status],
            reason=terminal_reason,
            stage="run",
        )
        result = HarnessRunResult(
            run_id=run_id,
            status=status,
            request=request,
            trace_path=str(run_dir),
            risk=risk,
            stages=stages,
            state=state_machine.to_dict(),
            evidence=evidence,
            incomplete_stages=incomplete_stages,
        )
        learning = self.learning_store.record_run(
            run_dir=run_dir,
            request=request,
            status=status,
            stages=stages,
            evidence=evidence,
            remediation_contexts=remediation_contexts,
        )
        self.trace_writer.write_json(run_dir, "result.json", asdict(result))
        self.trace_writer.write_report(run_dir, result)
        self.trace_writer.event(
            run_dir,
            "learning.recorded",
            observation_count=learning.get("observation_count", 0),
        )
        self.trace_writer.event(run_dir, "run.completed", status=status)
        return result

    def _run_worker_stage(
        self,
        run_dir: Path,
        state_machine: StateMachine,
        route_stage: str,
        context: WorkerContext,
        attempt: int,
    ) -> StageResult:
        next_state = WORKER_STAGE_TO_STATE[route_stage]
        self._transition(
            run_dir,
            state_machine,
            next_state,
            reason=f"routing {route_stage} worker",
            stage=route_stage,
        )
        self.trace_writer.event(run_dir, "worker.started", stage=route_stage, attempt=attempt)
        result = self.worker_registry.get(route_stage).run(context)
        result.attempt = attempt
        self.trace_writer.write_stage(run_dir, result)
        self.trace_writer.event(run_dir, "worker.completed", stage=route_stage, verdict=result.verdict, attempt=attempt)
        return result

    def _run_deterministic_evidence(
        self,
        run_dir: Path,
        state_machine: StateMachine,
        run_checks: bool,
        attempt: int,
    ) -> tuple:
        self._transition(
            run_dir,
            state_machine,
            TaskState.DETERMINISTIC_EVIDENCE,
            reason="collecting deterministic evidence",
            stage="deterministic_evidence",
        )
        if run_checks:
            self.trace_writer.event(run_dir, "deterministic_evidence.started", attempt=attempt)
            evidence_start = time.perf_counter()
            evidence_started_at = self._timestamp()
            evidence = self.evidence_runner.run_all()
            for item in evidence:
                item.attempt = attempt
            evidence_stage = self._deterministic_stage(evidence, evidence_started_at, evidence_start, attempt=attempt)
            self.trace_writer.write_stage(run_dir, evidence_stage)
            self.trace_writer.event(
                run_dir,
                "deterministic_evidence.completed",
                failed=[item.name for item in evidence if not item.passed],
                attempt=attempt,
            )
            return evidence_stage, evidence

        skipped_stage = StageResult(
            stage="deterministic_evidence",
            verdict="skip",
            confidence=1.0,
            findings=[],
            evidence=[
                EvidenceReference(
                    kind="operator_choice",
                    name="run_checks",
                    summary="Deterministic checks were skipped with --no-checks.",
                )
            ],
            attempt=attempt,
            started_at=self._timestamp(),
            completed_at=self._timestamp(),
            duration_ms=0,
        )
        self.trace_writer.write_stage(run_dir, skipped_stage)
        return skipped_stage, []

    def _attempt_remediation(
        self,
        run_dir: Path,
        state_machine: StateMachine,
        stages: List[StageResult],
        failed_stage: StageResult,
        failed_route_index: int,
        risk: RiskClassification,
        request: str,
        evidence: List[CommandEvidence],
        remediation_contexts: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not self._can_remediate(state_machine, failed_stage.stage, failed_route_index, risk.route):
            exhausted = (
                state_machine.run_state.remediation_attempts
                >= state_machine.run_state.max_remediation_attempts
            )
            self.trace_writer.event(
                run_dir,
                "remediation.exhausted" if exhausted else "remediation.skipped",
                failed_stage=failed_stage.stage,
                remediation_attempts=state_machine.run_state.remediation_attempts,
                max_remediation_attempts=state_machine.run_state.max_remediation_attempts,
            )
            return None

        next_attempt = state_machine.run_state.remediation_attempts + 2
        context = self._remediation_context(
            failed_stage=failed_stage,
            failed_route_index=failed_route_index,
            route=risk.route,
            next_attempt=next_attempt,
            evidence=evidence,
        )
        remediation_contexts.append(context)
        self._transition(
            run_dir,
            state_machine,
            TaskState.REMEDIATION,
            reason=f"feeding {failed_stage.stage} findings back to generator",
            stage="remediation",
        )
        remediation_attempt = state_machine.run_state.remediation_attempts
        remediation_stage = StageResult(
            stage="remediation",
            verdict="pass",
            confidence=1.0,
            evidence=[
                EvidenceReference(
                    kind="remediation",
                    name="failed_stage",
                    summary=f"Attempt {remediation_attempt}: retrying after {failed_stage.stage} failed.",
                ),
                EvidenceReference(
                    kind="remediation",
                    name="retry_route",
                    summary=f"Retry will restart at {risk.route[context['retry_index']]}.",
                ),
            ],
            attempt=next_attempt,
            started_at=self._timestamp(),
            completed_at=self._timestamp(),
            duration_ms=0,
        )
        stages.append(remediation_stage)
        self.trace_writer.write_stage(run_dir, remediation_stage)
        self._append_remediation_record(run_dir, context)
        self.trace_writer.event(
            run_dir,
            "remediation.started",
            failed_stage=failed_stage.stage,
            remediation_attempt=remediation_attempt,
            next_attempt=next_attempt,
        )

        context_pack = self.context_writer.write_stage_context(
            run_dir=run_dir,
            request=request,
            risk=risk,
            stage="generator",
            attempt=next_attempt,
            stages=stages,
            evidence=evidence,
            remediation_context=context,
        )
        generator_context = WorkerContext(
            root=self.root,
            run_id=run_dir.name,
            request=request,
            risk=risk,
            route=risk.route,
            attempt=next_attempt,
            remediation_context=context,
            context_pack_path=context_pack.path,
            context_estimated_tokens=context_pack.estimated_tokens,
        )
        generator_stage = self._run_worker_stage(
            run_dir=run_dir,
            state_machine=state_machine,
            route_stage="generator",
            context=generator_context,
            attempt=next_attempt,
        )
        stages.append(generator_stage)
        self.trace_writer.event(
            run_dir,
            "remediation.completed",
            failed_stage=failed_stage.stage,
            remediation_attempt=remediation_attempt,
            generator_verdict=generator_stage.verdict,
        )
        if generator_stage.verdict == "fail":
            return None
        return {"retry_index": context["retry_index"], "context": context}

    def _can_remediate(
        self,
        state_machine: StateMachine,
        failed_stage: str,
        failed_route_index: int,
        route: List[str],
    ) -> bool:
        if state_machine.run_state.remediation_attempts >= state_machine.run_state.max_remediation_attempts:
            return False
        if failed_stage == "generator":
            return False
        try:
            generator_index = route.index("generator")
        except ValueError:
            return False
        return failed_route_index > generator_index

    def _remediation_context(
        self,
        failed_stage: StageResult,
        failed_route_index: int,
        route: List[str],
        next_attempt: int,
        evidence: List[CommandEvidence],
    ) -> Dict[str, object]:
        return {
            "next_attempt": next_attempt,
            "failed_stage": failed_stage.stage,
            "failed_verdict": failed_stage.verdict,
            "failed_route_index": failed_route_index,
            "retry_index": self._retry_index(route, failed_route_index),
            "findings": [asdict(finding) for finding in failed_stage.findings],
            "stage_evidence": [asdict(item) for item in failed_stage.evidence],
            "deterministic_evidence": [self._command_evidence_context(item) for item in evidence if not item.passed],
        }

    def _retry_index(self, route: List[str], failed_route_index: int) -> int:
        try:
            deterministic_index = route.index("deterministic_evidence")
            generator_index = route.index("generator")
        except ValueError:
            return failed_route_index
        if generator_index < deterministic_index <= failed_route_index:
            return deterministic_index
        return failed_route_index

    def _command_evidence_context(self, item: CommandEvidence) -> Dict[str, object]:
        return {
            "name": item.name,
            "category": item.category,
            "required": item.required,
            "exit_code": item.exit_code,
            "remediation": item.remediation,
            "stdout_tail": item.stdout_tail[-1000:],
            "stderr_tail": item.stderr_tail[-1000:],
        }

    def _append_remediation_record(self, run_dir: Path, context: Dict[str, object]) -> None:
        target = run_dir / "remediation.json"
        if target.exists():
            payload = json.loads(target.read_text(encoding="utf-8"))
            attempts = payload.get("attempts", [])
            if not isinstance(attempts, list):
                attempts = []
        else:
            attempts = []
        attempts.append(context)
        self.trace_writer.write_json(
            run_dir,
            "remediation.json",
            {
                "max_remediation_attempts": self.max_remediation_attempts,
                "attempts": attempts,
            },
        )

    def _transition(
        self,
        run_dir: Path,
        state_machine: StateMachine,
        next_state: str,
        reason: str,
        stage: str,
    ) -> None:
        snapshot = state_machine.transition(next_state, reason=reason, stage=stage)
        self.trace_writer.write_state(run_dir, state_machine, snapshot)
        self.trace_writer.event(
            run_dir,
            "state.transitioned",
            state=next_state,
            previous_state=snapshot.previous_state,
            stage=stage,
            reason=reason,
        )

    def _deterministic_stage(
        self, evidence: List[CommandEvidence], started_at: str, started_timer: float, attempt: int
    ) -> StageResult:
        failed = [item for item in evidence if not item.passed]
        blocking_failed = [item for item in failed if item.required]
        verdict = "fail" if blocking_failed else "pass" if any(not item.skipped for item in evidence) else "skip"
        return StageResult(
            stage="deterministic_evidence",
            verdict=verdict,
            confidence=1.0,
            findings=[self._finding_from_command(item) for item in failed],
            evidence=[self._evidence_reference_from_command(item) for item in evidence],
            attempt=attempt,
            started_at=started_at,
            completed_at=self._timestamp(),
            duration_ms=self._duration_ms(started_timer),
        )

    def _evidence_reference_from_command(self, item: CommandEvidence) -> EvidenceReference:
        if item.skipped:
            summary = f"SKIP: {item.reason}"
        else:
            required = "required" if item.required else "optional"
            summary = f"{'PASS' if item.passed else 'FAIL'}: exit code {item.exit_code} ({required}, {item.duration_ms}ms)"
        return EvidenceReference(
            kind="command",
            name=item.name,
            summary=summary,
            command=item.command,
        )

    def _finding_from_command(self, item: CommandEvidence) -> Finding:
        details = item.stderr_tail.strip() or item.stdout_tail.strip()
        description = f"`{item.name}` failed with exit code {item.exit_code}."
        if details:
            description = f"{description} Last output: {details[-500:]}"

        return Finding(
            severity="low" if not item.required else self._severity_for_command(item.name),
            category="deterministic_check_failed",
            description=description,
            remediation=item.remediation or self._remediation_for_command(item.name),
        )

    def _severity_for_command(self, name: str) -> Severity:
        if name in {"python_compile", "unit_tests"}:
            return "high"
        return "medium"

    def _remediation_for_command(self, name: str) -> str:
        remediations = {
            "git_diff_check": "Fix whitespace or conflict-marker issues reported by git diff --check.",
            "python_compile": "Fix Python syntax or import-time compilation errors.",
            "unit_tests": "Fix the failing tests or update tests only when requirements changed intentionally.",
        }
        return remediations.get(name, "Inspect the command output and fix the failing deterministic check.")

    def _timestamp(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


def latest_run(root: Path) -> Optional[Path]:
    runs_dir = root.resolve() / ".moregan" / "runs"
    if not runs_dir.exists():
        return None
    runs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    return runs[-1] if runs else None
