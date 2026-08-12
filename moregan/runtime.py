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
from typing import Dict, Iterable, List, Optional, Sequence

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

    def classify(self, request: str) -> RiskClassification:
        normalized = request.lower()
        for level in ("critical", "high", "medium"):
            matches = [keyword for keyword in RISK_KEYWORDS[level] if keyword in normalized]
            if matches:
                return RiskClassification(
                    level=level,
                    reasons=[f"matched request keyword: {keyword}" for keyword in matches],
                    route=ROUTES_BY_RISK[level],
                    confidence=0.8,
                )

        return RiskClassification(
            level="low",
            reasons=["no high-risk request keywords matched"],
            route=ROUTES_BY_RISK["low"],
            confidence=0.6,
        )


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
        self.write_json(run_dir, f"stages/{result.stage}.json", asdict(result))

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
        lines.extend(["", "## Stage Results", ""])
        for stage in result.stages:
            detail = f"{stage.verdict.upper()} ({stage.confidence:.2f} confidence)"
            if stage.findings:
                detail += f", {len(stage.findings)} finding(s)"
            lines.append(f"- {stage.stage}: {detail}")

        lines.extend(["", "## Deterministic Evidence", ""])
        if not result.evidence:
            lines.append("- No deterministic checks were requested.")
        for item in result.evidence:
            status = "SKIP" if item.skipped else "PASS" if item.passed else "FAIL"
            detail = item.reason or " ".join(item.command)
            required = "required" if item.required else "optional"
            lines.append(f"- {status}: {item.name} ({item.category}, {required}, {item.duration_ms}ms) - {detail}")

        (run_dir / "final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _slugify(self, request: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", request.lower()).strip("-")
        return (slug or "run")[:48]


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
        result = subprocess.run(command, cwd=self.root, check=False, capture_output=True, text=True)
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

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.classifier = RiskClassifier()
        self.trace_writer = TraceWriter(self.root)
        self.evidence_runner = DeterministicEvidenceRunner(self.root)
        self.worker_registry = WorkerRegistry.from_root(self.root)

    def run(self, request: str, run_checks: bool = True) -> HarnessRunResult:
        run_dir = self.trace_writer.create_run_dir(request)
        run_id = run_dir.name
        state_machine = StateMachine(run_id=run_id, request=request, timestamp_factory=self._timestamp)
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

        evidence: List[CommandEvidence] = []
        stages = [risk_stage]
        status = "pass"
        terminal_reason = "all routed stages completed without blocking failures"
        worker_context = WorkerContext(
            root=self.root,
            run_id=run_id,
            request=request,
            risk=risk,
            route=risk.route,
        )

        for route_stage in risk.route:
            if route_stage == "deterministic_evidence":
                evidence_stage, evidence = self._run_deterministic_evidence(
                    run_dir=run_dir,
                    state_machine=state_machine,
                    run_checks=run_checks,
                )
                stages.append(evidence_stage)
                if evidence_stage.verdict == "fail":
                    status = "fail"
                    terminal_reason = "blocking deterministic checks failed"
                    break
                continue

            worker_stage = self._run_worker_stage(
                run_dir=run_dir,
                state_machine=state_machine,
                route_stage=route_stage,
                context=worker_context,
            )
            stages.append(worker_stage)
            if worker_stage.verdict == "fail":
                status = "fail"
                terminal_reason = f"{route_stage} worker failed"
                break

        self._transition(
            run_dir,
            state_machine,
            TaskState.COMPLETED if status == "pass" else TaskState.FAILED,
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
        )
        self.trace_writer.write_json(run_dir, "result.json", asdict(result))
        self.trace_writer.write_report(run_dir, result)
        self.trace_writer.event(run_dir, "run.completed", status=status)
        return result

    def _run_worker_stage(
        self,
        run_dir: Path,
        state_machine: StateMachine,
        route_stage: str,
        context: WorkerContext,
    ) -> StageResult:
        next_state = WORKER_STAGE_TO_STATE[route_stage]
        self._transition(
            run_dir,
            state_machine,
            next_state,
            reason=f"routing {route_stage} worker",
            stage=route_stage,
        )
        self.trace_writer.event(run_dir, "worker.started", stage=route_stage)
        result = self.worker_registry.get(route_stage).run(context)
        self.trace_writer.write_stage(run_dir, result)
        self.trace_writer.event(run_dir, "worker.completed", stage=route_stage, verdict=result.verdict)
        return result

    def _run_deterministic_evidence(
        self,
        run_dir: Path,
        state_machine: StateMachine,
        run_checks: bool,
    ) -> tuple:
        self._transition(
            run_dir,
            state_machine,
            TaskState.DETERMINISTIC_EVIDENCE,
            reason="collecting deterministic evidence",
            stage="deterministic_evidence",
        )
        if run_checks:
            self.trace_writer.event(run_dir, "deterministic_evidence.started")
            evidence_start = time.perf_counter()
            evidence_started_at = self._timestamp()
            evidence = self.evidence_runner.run_all()
            evidence_stage = self._deterministic_stage(evidence, evidence_started_at, evidence_start)
            self.trace_writer.write_stage(run_dir, evidence_stage)
            self.trace_writer.event(
                run_dir,
                "deterministic_evidence.completed",
                failed=[item.name for item in evidence if not item.passed],
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
            started_at=self._timestamp(),
            completed_at=self._timestamp(),
            duration_ms=0,
        )
        self.trace_writer.write_stage(run_dir, skipped_stage)
        return skipped_stage, []

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
        self, evidence: List[CommandEvidence], started_at: str, started_timer: float
    ) -> StageResult:
        failed = [item for item in evidence if not item.passed]
        blocking_failed = [item for item in failed if item.required]
        return StageResult(
            stage="deterministic_evidence",
            verdict="fail" if blocking_failed else "pass",
            confidence=1.0,
            findings=[self._finding_from_command(item) for item in failed],
            evidence=[self._evidence_reference_from_command(item) for item in evidence],
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
