"""Empirical learning artifacts for MoreGAN runs."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from moregan.schemas import CommandEvidence, StageResult


@dataclass
class LearningObservation:
    observation_id: str
    run_id: str
    pattern_id: str
    stage: str
    category: str
    severity: str
    description: str
    remediation: str
    outcome: str
    attempt: int
    source: str
    evidence: Dict[str, object] = field(default_factory=dict)
    created_at: str = ""


class EmpiricalLearningStore:
    """Stores run-backed observations and aggregate pattern statistics."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.learning_dir = self.root / ".moregan" / "learning"
        self.observations_path = self.learning_dir / "observations.jsonl"
        self.patterns_path = self.learning_dir / "patterns.json"

    def record_run(
        self,
        run_dir: Path,
        request: str,
        status: str,
        stages: Sequence[StageResult],
        evidence: Sequence[CommandEvidence],
        remediation_contexts: Sequence[Dict[str, object]],
    ) -> Dict[str, object]:
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        observations = self._observations_from_run(
            run_id=run_dir.name,
            request=request,
            status=status,
            stages=stages,
            evidence=evidence,
            remediation_contexts=remediation_contexts,
        )
        if observations:
            with self.observations_path.open("a", encoding="utf-8") as handle:
                for observation in observations:
                    handle.write(json.dumps(asdict(observation), sort_keys=True) + "\n")

        patterns = self._patterns_from_observations(self._load_observations())
        self.patterns_path.write_text(json.dumps(patterns, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        payload = {
            "run_id": run_dir.name,
            "status": status,
            "observation_count": len(observations),
            "observations": [asdict(observation) for observation in observations],
            "patterns": [
                pattern
                for pattern in patterns.get("patterns", [])
                if isinstance(pattern, dict)
                and any(observation.pattern_id == pattern.get("pattern_id") for observation in observations)
            ],
            "learning_store": {
                "observations_path": str(self.observations_path),
                "patterns_path": str(self.patterns_path),
            },
        }
        (run_dir / "learning.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return payload

    def _observations_from_run(
        self,
        run_id: str,
        request: str,
        status: str,
        stages: Sequence[StageResult],
        evidence: Sequence[CommandEvidence],
        remediation_contexts: Sequence[Dict[str, object]],
    ) -> List[LearningObservation]:
        remediated_stages = {
            str(context.get("failed_stage"))
            for context in remediation_contexts
            if isinstance(context, dict) and context.get("failed_stage")
        }
        observations: List[LearningObservation] = []
        for stage in stages:
            for finding in stage.findings:
                category = finding.category or "worker_finding"
                observations.append(
                    LearningObservation(
                        observation_id=self._observation_id(run_id, stage.stage, category, len(observations)),
                        run_id=run_id,
                        pattern_id=self._pattern_id(stage.stage, category, finding.remediation),
                        stage=stage.stage,
                        category=category,
                        severity=finding.severity,
                        description=finding.description,
                        remediation=finding.remediation,
                        outcome=self._outcome(status, stage.stage, remediated_stages),
                        attempt=stage.attempt,
                        source="stage_finding",
                        evidence={
                            "request_excerpt": request[:300],
                            "stage_verdict": stage.verdict,
                            "file": finding.file,
                            "line": finding.line,
                        },
                        created_at=self._timestamp(),
                    )
                )

        for item in evidence:
            if item.passed or item.skipped:
                continue
            category = item.category or item.name
            observations.append(
                LearningObservation(
                    observation_id=self._observation_id(run_id, "deterministic_evidence", category, len(observations)),
                    run_id=run_id,
                    pattern_id=self._pattern_id("deterministic_evidence", category, item.remediation or item.name),
                    stage="deterministic_evidence",
                    category=category,
                    severity="high" if item.required else "low",
                    description=f"`{item.name}` failed with exit code {item.exit_code}.",
                    remediation=item.remediation or "Inspect deterministic command output and fix the failing check.",
                    outcome=self._outcome(status, "deterministic_evidence", remediated_stages),
                    attempt=item.attempt,
                    source="deterministic_evidence",
                    evidence={
                        "name": item.name,
                        "required": item.required,
                        "command": item.command,
                        "stdout_tail": item.stdout_tail[-1000:],
                        "stderr_tail": item.stderr_tail[-1000:],
                    },
                    created_at=self._timestamp(),
                )
            )
        return observations

    def _patterns_from_observations(self, observations: Sequence[LearningObservation]) -> Dict[str, object]:
        grouped: Dict[str, List[LearningObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.pattern_id].append(observation)

        patterns = []
        for pattern_id, items in sorted(grouped.items()):
            successful = [item for item in items if item.outcome == "remediated"]
            failed = [item for item in items if item.outcome == "unresolved"]
            observations_count = len(items)
            confidence = len(successful) / observations_count if observations_count else 0.0
            patterns.append(
                {
                    "pattern_id": pattern_id,
                    "stage": items[-1].stage,
                    "category": items[-1].category,
                    "remediation": items[-1].remediation,
                    "statistics": {
                        "observations": observations_count,
                        "successful_applications": len(successful),
                        "failures": len(failed),
                        "confidence": round(confidence, 3),
                    },
                    "observations": [
                        {
                            "run": item.run_id,
                            "outcome": item.outcome,
                            "severity": item.severity,
                            "description": item.description,
                            "attempt": item.attempt,
                            "source": item.source,
                        }
                        for item in items[-10:]
                    ],
                }
            )
        return {"generated_at": self._timestamp(), "patterns": patterns}

    def _load_observations(self) -> List[LearningObservation]:
        observations = []
        if not self.observations_path.exists():
            return observations
        for line in self.observations_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                observations.append(LearningObservation(**payload))
        return observations

    def _outcome(self, status: str, stage: str, remediated_stages: Iterable[str]) -> str:
        if status == "pass" and stage in remediated_stages:
            return "remediated"
        if status == "pass":
            return "non_blocking"
        return "unresolved"

    def _pattern_id(self, stage: str, category: str, remediation: Optional[str]) -> str:
        raw = " ".join([stage, category, remediation or ""])
        slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
        return slug[:80] or "unknown-pattern"

    def _observation_id(self, run_id: str, stage: str, category: str, index: int) -> str:
        return f"{run_id}:{stage}:{category}:{index}"

    def _timestamp(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
