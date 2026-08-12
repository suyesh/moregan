"""Worker adapter interfaces for MoreGAN orchestration."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from moregan.schemas import EvidenceReference, Finding, RiskClassification, StageResult
from moregan.state import TaskState
from moregan.tools import ToolConfigError, ToolConfigLoader


WORKER_STAGE_TO_STATE: Dict[str, str] = {
    "planner": TaskState.PLANNING,
    "architect": TaskState.ARCHITECTURE_REVIEW,
    "designer_decision": TaskState.DESIGN_DECISION,
    "generator": TaskState.GENERATION,
    "evaluator": TaskState.EVALUATION,
    "security_evaluator": TaskState.SECURITY_EVALUATION,
    "code_reviewer": TaskState.CODE_REVIEW,
    "production_readiness_reviewer": TaskState.PRODUCTION_REVIEW,
    "mr_readiness_analyzer": TaskState.MR_READINESS,
    "learning_curator": TaskState.LEARNING,
}


WORKER_STAGE_LABELS: Dict[str, str] = {
    "planner": "Planner",
    "architect": "Architect",
    "designer_decision": "Designer Decision",
    "generator": "Generator",
    "evaluator": "Evaluator",
    "security_evaluator": "Security Evaluator",
    "code_reviewer": "Code Reviewer",
    "production_readiness_reviewer": "Production Readiness Reviewer",
    "mr_readiness_analyzer": "MR Readiness Analyzer",
    "learning_curator": "Learning Curator",
}


@dataclass
class WorkerContext:
    root: Path
    run_id: str
    request: str
    risk: RiskClassification
    route: List[str]


@dataclass
class WorkerCommand:
    stage: str
    command: List[str]
    timeout_seconds: int
    no_write: bool
    source: str


class WorkerAdapter(Protocol):
    stage: str

    def run(self, context: WorkerContext) -> StageResult:
        """Execute a worker stage and return a structured result."""


class DryRunWorker:
    """Records the orchestration boundary for a worker without doing provider work."""

    def __init__(self, stage: str):
        self.stage = stage

    def run(self, context: WorkerContext) -> StageResult:
        started = time.perf_counter()
        label = WORKER_STAGE_LABELS.get(self.stage, self.stage)
        return StageResult(
            stage=self.stage,
            verdict="skip",
            confidence=1.0,
            evidence=[
                EvidenceReference(
                    kind="worker",
                    name=f"{self.stage}_dry_run",
                    summary=(
                        f"{label} worker was routed but not executed because no provider adapter "
                        "is configured. No files were modified."
                    ),
                ),
                EvidenceReference(
                    kind="routing",
                    name="worker_route",
                    summary=f"Run route: {', '.join(context.route)}",
                ),
            ],
            started_at=_timestamp(),
            completed_at=_timestamp(),
            duration_ms=_duration_ms(started),
        )


class CommandWorker:
    """Runs a configured worker command that emits StageResult-compatible JSON."""

    def __init__(self, command: WorkerCommand):
        self.stage = command.stage
        self.command = command

    def run(self, context: WorkerContext) -> StageResult:
        started = time.perf_counter()
        env = os.environ.copy()
        env.update(
            {
                "MOREGAN_RUN_ID": context.run_id,
                "MOREGAN_STAGE": self.stage,
                "MOREGAN_REQUEST": context.request,
                "MOREGAN_RISK_LEVEL": context.risk.level,
                "MOREGAN_ROUTE": json.dumps(context.route),
                "MOREGAN_NO_WRITE": "1" if self.command.no_write else "0",
            }
        )

        try:
            result = subprocess.run(
                self.command.command,
                cwd=context.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.command.timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return self._failure_result(
                started,
                description=f"{self.stage} worker timed out after {self.command.timeout_seconds}s.",
                remediation="Increase timeout_seconds or fix the worker command so it completes.",
                stdout_tail=exc.stdout or "",
                stderr_tail=exc.stderr or "",
            )

        if result.returncode != 0:
            return self._failure_result(
                started,
                description=f"{self.stage} worker command exited with {result.returncode}.",
                remediation="Fix the worker command or its provider configuration.",
                stdout_tail=result.stdout,
                stderr_tail=result.stderr,
            )

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return self._failure_result(
                started,
                description=f"{self.stage} worker did not emit valid JSON on stdout.",
                remediation="Make the worker command print one StageResult-compatible JSON object.",
                stdout_tail=result.stdout,
                stderr_tail=result.stderr,
            )

        return self._stage_result_from_payload(payload, started)

    def _stage_result_from_payload(self, payload: Dict[str, object], started: float) -> StageResult:
        stage = str(payload.get("stage", self.stage))
        if stage != self.stage:
            return self._failure_result(
                started,
                description=f"worker emitted stage {stage!r}, expected {self.stage!r}.",
                remediation="Fix the worker output so stage matches the routed MoreGAN stage.",
            )

        verdict = str(payload.get("verdict", "")).lower()
        if verdict not in {"pass", "fail", "skip"}:
            return self._failure_result(
                started,
                description=f"{self.stage} worker emitted invalid verdict {verdict!r}.",
                remediation="Use one of: pass, fail, skip.",
            )

        confidence = float(payload.get("confidence", 1.0))
        return StageResult(
            stage=self.stage,
            verdict=verdict,  # type: ignore[arg-type]
            confidence=confidence,
            findings=[self._finding_from_payload(item) for item in self._list_payload(payload.get("findings"))],
            evidence=[
                *[self._evidence_from_payload(item) for item in self._list_payload(payload.get("evidence"))],
                EvidenceReference(
                    kind="worker_command",
                    name=f"{self.stage}_provider",
                    summary=f"Executed provider command from {self.command.source}.",
                    command=self.command.command,
                ),
            ],
            started_at=str(payload.get("started_at") or _timestamp()),
            completed_at=str(payload.get("completed_at") or _timestamp()),
            duration_ms=int(payload.get("duration_ms") or _duration_ms(started)),
        )

    def _failure_result(
        self,
        started: float,
        description: str,
        remediation: str,
        stdout_tail: str = "",
        stderr_tail: str = "",
    ) -> StageResult:
        evidence = [
            EvidenceReference(
                kind="worker_command",
                name=f"{self.stage}_provider",
                summary=f"Provider command failed from {self.command.source}.",
                command=self.command.command,
            )
        ]
        if stdout_tail.strip():
            evidence.append(
                EvidenceReference(
                    kind="stdout_tail",
                    name=f"{self.stage}_stdout",
                    summary=stdout_tail.strip()[-1000:],
                )
            )
        if stderr_tail.strip():
            evidence.append(
                EvidenceReference(
                    kind="stderr_tail",
                    name=f"{self.stage}_stderr",
                    summary=stderr_tail.strip()[-1000:],
                )
            )

        return StageResult(
            stage=self.stage,
            verdict="fail",
            confidence=1.0,
            findings=[
                Finding(
                    severity="high",
                    category="worker_provider_failed",
                    description=description,
                    remediation=remediation,
                )
            ],
            evidence=evidence,
            started_at=_timestamp(),
            completed_at=_timestamp(),
            duration_ms=_duration_ms(started),
        )

    def _finding_from_payload(self, payload: Dict[str, object]) -> Finding:
        return Finding(
            severity=str(payload.get("severity", "medium")),  # type: ignore[arg-type]
            category=str(payload.get("category", "worker_finding")),
            description=str(payload.get("description", "")),
            remediation=str(payload.get("remediation", "")),
            file=str(payload["file"]) if payload.get("file") else None,
            line=int(payload["line"]) if payload.get("line") else None,
        )

    def _evidence_from_payload(self, payload: Dict[str, object]) -> EvidenceReference:
        command = payload.get("command")
        return EvidenceReference(
            kind=str(payload.get("kind", "worker")),
            name=str(payload.get("name", f"{self.stage}_evidence")),
            summary=str(payload.get("summary", "")),
            path=str(payload["path"]) if payload.get("path") else None,
            command=[str(item) for item in command] if isinstance(command, list) else None,
        )

    def _list_payload(self, value: object) -> List[Dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]


class ConfigErrorWorker:
    """Fails a stage when worker configuration cannot be loaded."""

    def __init__(self, stage: str, error: str):
        self.stage = stage
        self.error = error

    def run(self, context: WorkerContext) -> StageResult:
        started = time.perf_counter()
        return StageResult(
            stage=self.stage,
            verdict="fail",
            confidence=1.0,
            findings=[
                Finding(
                    severity="high",
                    category="worker_config_invalid",
                    description=f"Worker configuration is invalid: {self.error}",
                    remediation="Fix .moregan/workers.yaml.",
                )
            ],
            evidence=[
                EvidenceReference(
                    kind="configuration",
                    name="workers_yaml",
                    summary="Could not load worker provider configuration.",
                    path=".moregan/workers.yaml",
                )
            ],
            started_at=_timestamp(),
            completed_at=_timestamp(),
            duration_ms=_duration_ms(started),
        )


class WorkerRegistry:
    """Resolves worker stage names to executable adapters."""

    def __init__(self, workers: Optional[Dict[str, WorkerAdapter]] = None, config_error: Optional[str] = None):
        self._workers = workers or {}
        self._config_error = config_error

    def get(self, stage: str) -> WorkerAdapter:
        if self._config_error:
            return ConfigErrorWorker(stage, self._config_error)
        return self._workers.get(stage, DryRunWorker(stage))

    @classmethod
    def from_root(cls, root: Path) -> "WorkerRegistry":
        try:
            commands = WorkerConfigLoader(root).load()
        except WorkerConfigError as exc:
            return cls(config_error=str(exc))
        return cls({command.stage: CommandWorker(command) for command in commands})


class WorkerConfigError(ValueError):
    """Raised when .moregan/workers.yaml cannot be interpreted."""


class WorkerConfigLoader:
    CONFIG_PATH = Path(".moregan") / "workers.yaml"

    def __init__(self, root: Path):
        self.root = root

    def load(self) -> List[WorkerCommand]:
        path = self.root / self.CONFIG_PATH
        if not path.exists():
            return []

        try:
            text = self._normalize_workers_section(path.read_text(encoding="utf-8"))
            payload = ToolConfigLoader(self.root)._parse_minimal_yaml(text)
        except ToolConfigError as exc:
            raise WorkerConfigError(str(exc)) from exc

        raw_workers = payload.get("commands")
        if raw_workers is None:
            return []
        if not isinstance(raw_workers, list):
            raise WorkerConfigError(f"{self.CONFIG_PATH} must define a workers list")

        return [self._coerce_worker(item) for item in raw_workers if isinstance(item, dict)]

    def _normalize_workers_section(self, text: str) -> str:
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not line.startswith(" ") and stripped.startswith("workers:"):
                lines.append(line.replace("workers:", "commands:", 1))
                continue
            lines.append(line)
        return "\n".join(lines)

    def _coerce_worker(self, payload: Dict[str, object]) -> WorkerCommand:
        stage = str(payload.get("stage", "")).strip()
        if stage not in WORKER_STAGE_TO_STATE:
            raise WorkerConfigError(f"unsupported worker stage: {stage}")

        command = payload.get("command")
        if command is None:
            raise WorkerConfigError(f"{stage} worker needs a command")

        return WorkerCommand(
            stage=stage,
            command=self._coerce_command(command),
            timeout_seconds=int(payload.get("timeout_seconds", 120)),
            no_write=self._coerce_bool(payload.get("no_write", True)),
            source=str(self.CONFIG_PATH),
        )

    def _coerce_command(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            return shlex.split(value)
        raise WorkerConfigError("worker command must be a string or list")

    def _coerce_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "yes", "on", "1"}:
                return True
            if lowered in {"false", "no", "off", "0"}:
                return False
        return bool(value)


def _timestamp() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
