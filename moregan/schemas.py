"""Structured result contracts for the MoreGAN runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


Severity = Literal["critical", "high", "medium", "low", "info"]
Verdict = Literal["pass", "fail", "skip"]
RiskLevel = Literal["low", "medium", "high", "critical"]


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
    status: str
    request: str
    trace_path: str
    risk: RiskClassification
    stages: List[StageResult]
    state: Dict[str, object]
    evidence: List[CommandEvidence] = field(default_factory=list)
