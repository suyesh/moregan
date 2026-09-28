"""Worker adapter interfaces for MoreGAN orchestration."""

from __future__ import annotations

import json
import os
import shutil
import shlex
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from moregan.processes import (
    MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, MAX_TIMEOUT_SECONDS, SUPERVISOR_ENV, ProcessCleanupInterrupted, run_bounded,
)
from moregan.schemas import (
    EvidenceReference, Finding, RiskClassification, StageResult, StageResultValidationError,
    output_tail, parse_stage_json, validate_stage_result,
)
from moregan.state import TaskState
from moregan.tools import ToolConfigError, ToolConfigLoader
from moregan.workspaces import CheckoutFingerprint, WorkerWorkspace


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
    attempt: int = 1
    remediation_context: Optional[Dict[str, object]] = None
    context_pack_path: Optional[str] = None
    context_estimated_tokens: int = 0
    phase: str = "standard"


@dataclass
class WorkerCommand:
    stage: str
    command: List[str]
    timeout_seconds: int
    no_write: bool
    source: str
    execution: str = "auto"
    max_output_bytes: int = MAX_OUTPUT_BYTES
    max_prompt_bytes: int = MAX_INPUT_BYTES


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
        result = StageResult(
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
            attempt=context.attempt,
            started_at=_timestamp(),
            completed_at=_timestamp(),
            duration_ms=_duration_ms(started),
        )
        self._attach_context_evidence(result, context)
        return result

    def _attach_context_evidence(self, result: StageResult, context: WorkerContext) -> None:
        if not context.context_pack_path:
            return
        result.evidence.append(
            EvidenceReference(
                kind="context_pack",
                name="stage_context",
                summary=f"Worker context pack is approximately {context.context_estimated_tokens} tokens.",
                path=context.context_pack_path,
            )
        )


class CommandWorker:
    """Runs a configured worker command that emits StageResult-compatible JSON."""

    def __init__(self, command: WorkerCommand):
        self.stage = command.stage
        self.command = command

    def run(self, context: WorkerContext) -> StageResult:
        started = time.perf_counter()
        started_at = _timestamp()
        isolated = self.command.execution == "isolated" or (
            self.command.execution == "auto" and self.command.no_write
        )
        try:
            workspace = WorkerWorkspace(context.root, isolated, self.stage)
        except (OSError, ValueError, RuntimeError) as exc:
            return self._failure_result(
                started, context.attempt, description=f"Could not resolve worker workspace: {exc}",
                remediation="Check the repository path and symlinks before retrying.",
            )
        stage_result = None
        no_write_before = None
        cleanup_unconfirmed = False
        try:
            if self.command.no_write:
                no_write_before = CheckoutFingerprint.capture(context.root)
            execution_root = workspace.prepare()
            context_pack_path = self._context_pack_for_execution(context, execution_root)
            stage_result = self._run_command(context, execution_root, context_pack_path, started, started_at)
        except ProcessCleanupInterrupted:
            cleanup_unconfirmed = True
            raise
        except (OSError, ValueError) as exc:
            stage_result = self._failure_result(
                started, context.attempt, description=f"Could not prepare {self.stage} worker: {exc}",
                remediation="Check workspace access, integrity scan limits, snapshot storage, symlinks and Git availability.",
            )
            if self.command.no_write and no_write_before is None:
                stage_result.findings[0].category = "no_write_check_failed"
        finally:
            cleanup_unconfirmed = cleanup_unconfirmed or (stage_result is not None and any(
                finding.category == "worker_cleanup_failed" for finding in stage_result.findings
            ))
            try:
                if workspace.temporary_root is not None and cleanup_unconfirmed:
                    raise OSError("Provider process cleanup is unconfirmed; snapshot retained for manual inspection")
                workspace.cleanup()
            except (OSError, ValueError, NotImplementedError) as exc:
                if stage_result is None:
                    warnings.warn(f"Worker interrupted; snapshot cleanup failed at {workspace.temporary_root}: {exc}",
                                  RuntimeWarning)
                else:
                    stage_result.verdict = "fail"
                    stage_result.findings.append(Finding(
                        severity="high", category="workspace_cleanup_failed",
                        description=f"Could not remove temporary worker snapshot at {workspace.temporary_root}: {exc}",
                        remediation="Inspect permissions and running worker processes, then remove the reported temporary snapshot.",
                    ))
            else:
                if stage_result is not None and workspace.temporary_root is not None:
                    stage_result.evidence.append(EvidenceReference(
                        kind="workspace_cleanup", name="snapshot_removed",
                        summary="Temporary worker snapshot removed; its execution path is historical.",
                        path=str(workspace.execution_root),
                    ))

        stage_result = self._finalize_result(stage_result, context, workspace.execution_root, no_write_before, workspace.root)
        stage_result.started_at = started_at
        stage_result.completed_at = _timestamp()
        stage_result.duration_ms = _duration_ms(started)
        return stage_result

    def _run_command(
        self, context: WorkerContext, execution_root: Path, context_pack_path: Optional[str],
        started: float, started_at: str,
    ) -> StageResult:
        env = os.environ.copy()
        env.update(
            {
                "MOREGAN_RUN_ID": context.run_id,
                "MOREGAN_STAGE": self.stage,
                "MOREGAN_STAGE_PHASE": context.phase,
                "MOREGAN_REQUEST": context.request,
                "MOREGAN_RISK_LEVEL": context.risk.level,
                "MOREGAN_ROUTE": json.dumps(context.route),
                "MOREGAN_NO_WRITE": "1" if self.command.no_write else "0",
                "MOREGAN_ATTEMPT": str(context.attempt),
                "MOREGAN_REMEDIATION_CONTEXT": json.dumps(context.remediation_context or {}, sort_keys=True),
                "MOREGAN_CONTEXT_PACK": context_pack_path or "",
                "MOREGAN_CONTEXT_TOKENS": str(context.context_estimated_tokens),
                "MOREGAN_EXECUTION_MODE": "isolated" if execution_root != context.root.resolve() else "repository",
                "MOREGAN_EXECUTION_ROOT": str(execution_root),
                "MOREGAN_MAX_OUTPUT_BYTES": str(self.command.max_output_bytes),
                "MOREGAN_MAX_PROMPT_BYTES": str(self.command.max_prompt_bytes),
                "MOREGAN_WORKER_TIMEOUT_SECONDS": str(self.command.timeout_seconds),
                SUPERVISOR_ENV: str(os.getpid()),
            }
        )

        try:
            result = run_bounded(
                self.command.command, execution_root, env=env,
                timeout_seconds=self.command.timeout_seconds,
                max_output_bytes=self.command.max_output_bytes, strict_stdout=True,
            )
        except (OSError, ValueError) as exc:
            return self._failure_result(
                started, context.attempt,
                description=f"{self.stage} worker command could not run: {exc}",
                remediation="Check the worker executable, arguments, permissions, and output encoding.",
            )

        if result.error_kind or result.exit_code != 0:
            stage_result = self._failure_result(
                started, context.attempt,
                description=f"{self.stage} worker: {result.reason or f'command exited with {result.exit_code}.'}",
                remediation="Check the provider command, execution limits, and process cleanup.",
                stdout_tail=result.stdout_tail, stderr_tail=result.stderr_tail,
            )
            if result.error_kind == "cleanup_error":
                stage_result.findings[0].category = "worker_cleanup_failed"
        else:
            try:
                payload = parse_stage_json(result.stdout_tail)
            except StageResultValidationError as exc:
                stage_result = self._failure_result(
                    started, context.attempt,
                    description=f"{self.stage} worker did not emit valid JSON on stdout: {exc}",
                    remediation="Make the worker command print one StageResult-compatible JSON object.",
                    stdout_tail=result.stdout_tail, stderr_tail=result.stderr_tail,
                )
            else:
                stage_result = self._stage_result_from_payload(payload, started, context.attempt, started_at)
        stage_result.evidence.append(EvidenceReference(
            kind="provider_io", name="worker_process",
            summary=f"stdout_bytes={result.stdout_bytes}; stderr_bytes={result.stderr_bytes}; "
                    f"stderr_truncated={result.stderr_truncated}; error_kind={result.error_kind or 'none'}; "
                    f"stdout_limit={self.command.max_output_bytes}; timeout_seconds={self.command.timeout_seconds}.",
        ))
        return stage_result

    def _finalize_result(
        self,
        stage_result: StageResult,
        context: WorkerContext,
        execution_root: Path,
        no_write_before: Optional[CheckoutFingerprint],
        repository_root: Path,
    ) -> StageResult:
        self._attach_execution_evidence(stage_result, repository_root, execution_root)
        self._attach_context_evidence(stage_result, context)
        if no_write_before is not None:
            if any(finding.category == "worker_cleanup_failed" for finding in stage_result.findings):
                stage_result.evidence.append(EvidenceReference(
                    kind="workspace_integrity", name="no_write_check_unverified",
                    summary="Checkout verification skipped because provider process cleanup is unconfirmed.",
                ))
            else:
                self._verify_checkout(stage_result, no_write_before, repository_root)
        return stage_result

    def _stage_result_from_payload(self, payload: object, started: float, attempt: int, started_at: str) -> StageResult:
        try:
            result = validate_stage_result(
                payload, self.stage, attempt=attempt, started_at=started_at,
                completed_at=_timestamp(), duration_ms=_duration_ms(started),
            )
        except StageResultValidationError as exc:
            return self._failure_result(
                started, attempt,
                description=f"{self.stage} worker returned invalid StageResult: {exc}",
                remediation="Return a valid StageResult object with correctly typed fields and concrete findings.",
            )
        result.evidence.append(EvidenceReference(
            kind="worker_command", name=f"{self.stage}_provider",
            summary=f"Executed provider command from {self.command.source}.", command=self.command.command,
        ))
        return result

    def _failure_result(
        self,
        started: float,
        attempt: int,
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
        stdout_tail, stderr_tail = output_tail(stdout_tail), output_tail(stderr_tail)
        if stdout_tail:
            evidence.append(
                EvidenceReference(
                    kind="stdout_tail",
                    name=f"{self.stage}_stdout",
                    summary=stdout_tail.strip()[-1000:],
                )
            )
        if stderr_tail:
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
            attempt=attempt,
            started_at=_timestamp(),
            completed_at=_timestamp(),
            duration_ms=_duration_ms(started),
        )

    def _context_pack_for_execution(self, context: WorkerContext, execution_root: Path) -> Optional[str]:
        if not context.context_pack_path:
            return None
        if execution_root == context.root.resolve():
            return context.context_pack_path

        source = Path(context.context_pack_path)
        if not source.exists():
            return context.context_pack_path
        target = execution_root / ".moregan" / "worker-context" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return str(target)

    def _attach_execution_evidence(self, result: StageResult, repository_root: Path, execution_root: Path) -> None:
        isolated = execution_root != repository_root
        result.evidence.append(
            EvidenceReference(
                kind="execution_context",
                name="isolated_snapshot" if isolated else "repository_checkout",
                summary=(
                    "Provider execution directory was a temporary snapshot, not the base checkout."
                    if isolated
                    else "Provider execution directory was the repository checkout."
                ),
                path=str(execution_root),
            )
        )

    def _attach_context_evidence(self, result: StageResult, context: WorkerContext) -> None:
        if not context.context_pack_path:
            return
        result.evidence.append(
            EvidenceReference(
                kind="context_pack",
                name="stage_context",
                summary=f"Worker context pack is approximately {context.context_estimated_tokens} tokens.",
                path=context.context_pack_path,
            )
        )

    def _verify_checkout(self, result: StageResult, before: CheckoutFingerprint, root: Path) -> None:
        try:
            after = CheckoutFingerprint.capture(root)
        except (OSError, ValueError) as exc:
            result.verdict = "fail"
            result.findings.append(Finding(
                severity="high", category="no_write_check_failed",
                description=f"Could not verify the checkout after the no-write worker: {exc}",
                remediation="Inspect the checkout manually and fix the integrity scan failure before retrying.",
            ))
            return
        changed = after.changes_from(before)
        summary = f"Compared content, modes and symlinks for {len(before.files)} before / {len(after.files)} after paths"
        if before.git_state or after.git_state:
            summary += ", plus Git index and HEAD"
        result.evidence.append(EvidenceReference(
            kind="workspace_integrity", name="no_write_check",
            summary=summary + f"; {len(changed)} changed path(s). No files were restored or reverted.",
        ))
        if changed:
            result.verdict = "fail"
            paths = ", ".join(repr(name) for name in changed[:20])[:1000]
            result.findings.append(Finding(
                severity="high", category="no_write_violation", file=changed[0],
                description=f"A no-write worker left checkout changes in {len(changed)} path(s): {paths}.",
                remediation="Inspect and reconcile these changes manually; MoreGAN did not revert user work. Fix the worker before retrying.",
            ))


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
            attempt=context.attempt,
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
        except (ToolConfigError, OSError, UnicodeError) as exc:
            raise WorkerConfigError(str(exc)) from exc

        raw_workers = payload.get("commands")
        if not isinstance(raw_workers, list):
            raise WorkerConfigError(f"{self.CONFIG_PATH} must define a workers list")

        if any(not isinstance(item, dict) for item in raw_workers):
            raise WorkerConfigError("each worker must be an object")
        commands = [self._coerce_worker(item) for item in raw_workers]
        if len({command.stage for command in commands}) != len(commands):
            raise WorkerConfigError("duplicate worker stages are not allowed")
        return commands

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
        allowed = {"stage", "command", "timeout_seconds", "no_write", "execution", "max_output_bytes", "max_prompt_bytes"}
        if any(key not in allowed for key in payload):
            raise WorkerConfigError("unknown worker setting; check field names")
        stage = str(payload.get("stage", "")).strip()
        if stage not in WORKER_STAGE_TO_STATE:
            raise WorkerConfigError(f"unsupported worker stage: {stage}")

        command = payload.get("command")
        if command is None:
            raise WorkerConfigError(f"{stage} worker needs a command")

        timeout = payload.get("timeout_seconds", 120)
        output_limit = payload.get("max_output_bytes", MAX_OUTPUT_BYTES)
        prompt_limit = payload.get("max_prompt_bytes", MAX_INPUT_BYTES)
        for name, value, maximum in (("timeout_seconds", timeout, MAX_TIMEOUT_SECONDS),
                                     ("max_output_bytes", output_limit, MAX_OUTPUT_BYTES),
                                     ("max_prompt_bytes", prompt_limit, MAX_INPUT_BYTES)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise WorkerConfigError(f"worker {name} must be an integer between 1 and {maximum}")
        return WorkerCommand(
            stage=stage,
            command=self._coerce_command(command),
            timeout_seconds=timeout,
            no_write=self._coerce_bool(payload.get("no_write", True)),
            source=str(self.CONFIG_PATH),
            execution=self._coerce_execution(payload.get("execution", "auto")),
            max_output_bytes=output_limit,
            max_prompt_bytes=prompt_limit,
        )

    def _coerce_command(self, value: object) -> List[str]:
        if isinstance(value, str):
            try:
                value = shlex.split(value)
            except ValueError as exc:
                raise WorkerConfigError(f"invalid worker command: {exc}") from exc
        if (not isinstance(value, list) or not value
                or any(not isinstance(item, str) or "\x00" in item for item in value) or not value[0].strip()):
            raise WorkerConfigError("worker command must contain a nonempty executable and string arguments")
        return value

    def _coerce_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "yes", "on", "1"}:
                return True
            if lowered in {"false", "no", "off", "0"}:
                return False
        raise WorkerConfigError("worker no_write must be a boolean")

    def _coerce_execution(self, value: object) -> str:
        execution = str(value or "auto").strip().lower()
        if execution not in {"auto", "repository", "isolated"}:
            raise WorkerConfigError("worker execution must be one of: auto, repository, isolated")
        return execution


def _timestamp() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
