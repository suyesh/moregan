"""Task state machine for the MoreGAN runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set


class TaskState:
    INTAKE = "intake"
    RISK_CLASSIFICATION = "risk_classification"
    PLANNING = "planning"
    ARCHITECTURE_REVIEW = "architecture_review"
    DESIGN_DECISION = "design_decision"
    GENERATION = "generation"
    DETERMINISTIC_EVIDENCE = "deterministic_evidence"
    EVALUATION = "evaluation"
    SECURITY_EVALUATION = "security_evaluation"
    CODE_REVIEW = "code_review"
    PRODUCTION_REVIEW = "production_review"
    MR_READINESS = "mr_readiness"
    LEARNING = "learning"
    REMEDIATION = "remediation"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED}

ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    TaskState.INTAKE: {TaskState.RISK_CLASSIFICATION},
    TaskState.RISK_CLASSIFICATION: {
        TaskState.PLANNING,
        TaskState.GENERATION,
        TaskState.DETERMINISTIC_EVIDENCE,
    },
    TaskState.PLANNING: {TaskState.ARCHITECTURE_REVIEW, TaskState.GENERATION, TaskState.FAILED},
    TaskState.ARCHITECTURE_REVIEW: {TaskState.DESIGN_DECISION, TaskState.GENERATION, TaskState.FAILED},
    TaskState.DESIGN_DECISION: {TaskState.GENERATION, TaskState.FAILED},
    TaskState.GENERATION: {TaskState.DETERMINISTIC_EVIDENCE, TaskState.EVALUATION, TaskState.FAILED},
    TaskState.DETERMINISTIC_EVIDENCE: {
        TaskState.EVALUATION,
        TaskState.REMEDIATION,
        TaskState.COMPLETED,
        TaskState.FAILED,
    },
    TaskState.EVALUATION: {
        TaskState.SECURITY_EVALUATION,
        TaskState.CODE_REVIEW,
        TaskState.REMEDIATION,
        TaskState.COMPLETED,
        TaskState.FAILED,
    },
    TaskState.SECURITY_EVALUATION: {TaskState.CODE_REVIEW, TaskState.REMEDIATION, TaskState.FAILED},
    TaskState.CODE_REVIEW: {TaskState.PRODUCTION_REVIEW, TaskState.REMEDIATION, TaskState.COMPLETED, TaskState.FAILED},
    TaskState.PRODUCTION_REVIEW: {TaskState.MR_READINESS, TaskState.REMEDIATION, TaskState.FAILED},
    TaskState.MR_READINESS: {TaskState.LEARNING, TaskState.REMEDIATION, TaskState.FAILED},
    TaskState.LEARNING: {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.REMEDIATION: {TaskState.GENERATION, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
}


class InvalidTransition(ValueError):
    """Raised when runtime code attempts an illegal task-state transition."""


@dataclass
class StateSnapshot:
    state: str
    previous_state: Optional[str]
    timestamp: str
    reason: str
    stage: Optional[str] = None
    attempt: int = 1


@dataclass
class RunState:
    run_id: str
    request: str
    current_state: str
    max_remediation_attempts: int = 3
    remediation_attempts: int = 0
    history: List[StateSnapshot] = field(default_factory=list)


class StateMachine:
    """Enforces legal MoreGAN task transitions and records transition history."""

    def __init__(
        self,
        run_id: str,
        request: str,
        max_remediation_attempts: int = 3,
        timestamp_factory: Optional[Callable[[], str]] = None,
    ):
        self._timestamp = timestamp_factory or self._default_timestamp
        initial = StateSnapshot(
            state=TaskState.INTAKE,
            previous_state=None,
            timestamp=self._timestamp(),
            reason="run accepted",
            stage="intake",
        )
        self.run_state = RunState(
            run_id=run_id,
            request=request,
            current_state=TaskState.INTAKE,
            max_remediation_attempts=max_remediation_attempts,
            history=[initial],
        )

    @property
    def current_state(self) -> str:
        return self.run_state.current_state

    @property
    def latest_snapshot(self) -> StateSnapshot:
        return self.run_state.history[-1]

    def transition(self, next_state: str, reason: str, stage: Optional[str] = None) -> StateSnapshot:
        current = self.run_state.current_state
        if next_state not in ALLOWED_TRANSITIONS[current]:
            allowed = ", ".join(sorted(ALLOWED_TRANSITIONS[current])) or "none"
            raise InvalidTransition(f"cannot transition from {current} to {next_state}; allowed: {allowed}")

        if next_state == TaskState.REMEDIATION:
            self.run_state.remediation_attempts += 1
            if self.run_state.remediation_attempts > self.run_state.max_remediation_attempts:
                raise InvalidTransition(
                    f"remediation attempts exceeded: {self.run_state.remediation_attempts} "
                    f"> {self.run_state.max_remediation_attempts}"
                )

        snapshot = StateSnapshot(
            state=next_state,
            previous_state=current,
            timestamp=self._timestamp(),
            reason=reason,
            stage=stage,
            attempt=max(1, self.run_state.remediation_attempts + 1),
        )
        self.run_state.current_state = next_state
        self.run_state.history.append(snapshot)
        return snapshot

    def to_dict(self) -> dict:
        return asdict(self.run_state)

    def _default_timestamp(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
