"""Structured result contracts for the MoreGAN runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional


Severity = Literal["critical", "high", "medium", "low", "info"]
Verdict = Literal["pass", "fail", "skip"]
RiskLevel = Literal["low", "medium", "high", "critical"]
RunStatus = Literal["pass", "fail", "incomplete"]
WORKER_STAGES = frozenset({
    "planner", "architect", "designer_decision", "generator", "evaluator", "security_evaluator",
    "code_reviewer", "production_readiness_reviewer", "mr_readiness_analyzer", "learning_curator",
})


@dataclass
class Finding:
    severity: Severity
    category: str
    description: str
    remediation: str
    file: Optional[str] = None
    line: Optional[int] = None


@dataclass
class EvidenceReference:
    kind: str
    name: str
    summary: str
    path: Optional[str] = None
    command: Optional[List[str]] = None


@dataclass
class StageResult:
    stage: str
    verdict: Verdict
    confidence: float
    findings: List[Finding] = field(default_factory=list)
    evidence: List[EvidenceReference] = field(default_factory=list)
    attempt: int = 1
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None


@dataclass
class RiskClassification:
    level: RiskLevel
    reasons: List[str]
    route: List[str]
    confidence: float
    evidence: Dict[str, object] = field(default_factory=dict)


@dataclass
class CommandEvidence:
    name: str
    command: List[str]
    passed: bool
    exit_code: int
    category: str = "custom"
    required: bool = True
    duration_ms: int = 0
    remediation: Optional[str] = None
    source: str = "default"
    attempt: int = 1
    skipped: bool = False
    reason: Optional[str] = None
    stdout_tail: str = ""
    stderr_tail: str = ""


@dataclass
class HarnessRunResult:
    run_id: str
    status: RunStatus
    request: str
    trace_path: str
    risk: RiskClassification
    stages: List[StageResult]
    state: Dict[str, object]
    evidence: List[CommandEvidence] = field(default_factory=list)
    incomplete_stages: List[str] = field(default_factory=list)


class StageResultValidationError(ValueError):
    """A provider result does not satisfy the shared stage contract."""


def parse_stage_json(text: str) -> object:
    """Decode exactly one JSON value, rejecting ambiguous keys and non-JSON numbers."""
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise StageResultValidationError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise StageResultValidationError(f"invalid JSON number: {value}")

    try:
        return json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise StageResultValidationError(f"invalid StageResult JSON: {exc}") from exc


def _object(value: object, schema: type, label: str) -> dict:
    if not isinstance(value, dict):
        raise StageResultValidationError(f"{label} must be an object")
    unknown = set(value) - set(schema.__dataclass_fields__)
    if unknown:
        raise StageResultValidationError(f"{label} has unknown fields: {sorted(map(str, unknown))}")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise StageResultValidationError(f"{label} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StageResultValidationError(f"{label} must contain valid Unicode") from exc
    return value


def _text(value: object, label: str) -> str:
    value = _string(value, label)
    if not value.strip():
        raise StageResultValidationError(f"{label} must be a nonempty string")
    return value


def _integer(value: object, label: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise StageResultValidationError(f"{label} must be an integer >= {minimum}")
    return value


def _items(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise StageResultValidationError(f"{label} must be a list")
    return value


def validate_stage_result(
    payload: object,
    expected_stage: str,
    *,
    attempt: int,
    started_at: str,
    completed_at: str,
    duration_ms: int,
) -> StageResult:
    """Validate provider data without coercion; execution metadata is owned by the caller."""
    data = _object(payload, StageResult, "stage result")
    stage = data.get("stage")
    if expected_stage not in WORKER_STAGES or stage != expected_stage:
        raise StageResultValidationError(f"stage must be {expected_stage!r} and a known worker stage")
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail", "skip"):
        raise StageResultValidationError("verdict must be pass, fail, or skip")
    confidence = data.get("confidence")
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
        raise StageResultValidationError("confidence must be a finite number between 0 and 1")

    findings = []
    for index, raw in enumerate(_items(data.get("findings", []), "findings")):
        label = f"findings[{index}]"
        item = _object(raw, Finding, label)
        severity = item.get("severity")
        if severity not in ("critical", "high", "medium", "low", "info"):
            raise StageResultValidationError(f"{label}.severity is invalid")
        file = _text(item["file"], f"{label}.file") if item.get("file") is not None else None
        line = _integer(item["line"], f"{label}.line", 1) if item.get("line") is not None else None
        findings.append(Finding(
            severity=severity,
            category=_text(item.get("category"), f"{label}.category"),
            description=_text(item.get("description"), f"{label}.description"),
            remediation=_text(item.get("remediation"), f"{label}.remediation"), file=file, line=line,
        ))
    if verdict != "fail" and any(finding.severity in {"critical", "high"} for finding in findings):
        raise StageResultValidationError("critical/high findings require verdict fail")

    evidence = []
    for index, raw in enumerate(_items(data.get("evidence", []), "evidence")):
        label = f"evidence[{index}]"
        item = _object(raw, EvidenceReference, label)
        command = item.get("command")
        if command is not None:
            command = _items(command, f"{label}.command")
            if not command or any(not isinstance(arg, str) for arg in command) or not command[0].strip():
                raise StageResultValidationError(f"{label}.command must be a nonempty string argument list")
            for arg in command:
                _string(arg, f"{label}.command argument")
        evidence.append(EvidenceReference(
            kind=_text(item.get("kind"), f"{label}.kind"),
            name=_text(item.get("name"), f"{label}.name"),
            summary=_text(item.get("summary"), f"{label}.summary"),
            path=_text(item["path"], f"{label}.path") if item.get("path") is not None else None,
            command=command,
        ))

    # Validate supplied metadata even though the runtime replaces it, so invalid payloads cannot pass silently.
    if "attempt" in data:
        _integer(data["attempt"], "attempt", 1)
    if data.get("duration_ms") is not None:
        _integer(data["duration_ms"], "duration_ms", 0)
    for name in ("started_at", "completed_at"):
        if data.get(name) is not None:
            value = _text(data[name], name)
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise StageResultValidationError(f"{name} must be an ISO timestamp") from exc
    return StageResult(
        stage=expected_stage, verdict=verdict, confidence=float(confidence), findings=findings, evidence=evidence,
        attempt=attempt, started_at=started_at, completed_at=completed_at, duration_ms=duration_ms,
    )


def output_tail(value: object, limit: int = 1000) -> str:
    """TimeoutExpired may carry bytes even when subprocess text mode was requested."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value.strip()[-limit:] if isinstance(value, str) else ""
