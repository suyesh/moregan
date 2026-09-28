"""Read-only replay rendering for MoreGAN run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


class ReplayError(ValueError):
    """Raised when a run cannot be replayed from existing artifacts."""


class RunReplay:
    """Reconstructs a MoreGAN run from trace artifacts without executing work."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir

    def to_dict(self) -> Dict[str, object]:
        result = self._read_json("result.json")
        state = self._read_json("state.json")
        stages = self._load_stages(result)
        learning = self._read_optional_json("learning.json")
        return {
            "run_id": result.get("run_id", self.run_dir.name),
            "status": result.get("status"),
            "request": result.get("request"),
            "risk": result.get("risk"),
            "risk_history": result.get("risk_history", []),
            "state": state,
            "stages": stages,
            "evidence": result.get("evidence", []),
            "learning": learning,
            "trace_path": str(self.run_dir),
        }

    def render(self) -> str:
        replay = self.to_dict()
        risk = replay.get("risk") or {}
        state = replay.get("state") or {}
        stages = replay.get("stages") or []
        evidence = replay.get("evidence") or []
        learning = replay.get("learning") or {}

        lines = [
            "# MoreGAN Replay",
            "",
            f"- Run: `{replay['run_id']}`",
            f"- Status: `{replay.get('status')}`",
            f"- Risk: `{risk.get('level')}`",
            f"- State: `{state.get('current_state')}`",
            f"- Request: {replay.get('request')}",
            "",
            "## State Transitions",
            "",
        ]

        for index, snapshot in enumerate(state.get("history", []), start=1):
            previous = snapshot.get("previous_state") or "start"
            lines.append(
                f"{index}. `{previous}` -> `{snapshot.get('state')}` "
                f"({snapshot.get('stage')}) - {snapshot.get('reason')}"
            )

        if replay.get("risk_history"):
            lines.extend(["", "## Risk Reassessment", ""])
            for assessment in replay["risk_history"]:
                lines.append(f"- Attempt {assessment['attempt']}: {assessment['previous_level']} -> "
                             f"{assessment['effective']['level']} (observed {assessment['observed']['level']})")

        lines.extend(["", "## Stage Results", ""])
        for stage in stages:
            lines.append(
                f"- {stage.get('stage')}: {str(stage.get('verdict')).upper()} "
                f"({float(stage.get('confidence', 0.0)):.2f} confidence)"
            )
            for finding in stage.get("findings", []):
                lines.append(
                    f"  - Finding {finding.get('severity')}: {finding.get('category')} - "
                    f"{finding.get('description')}"
                )
            for item in stage.get("evidence", []):
                summary = item.get("summary", "")
                if summary:
                    lines.append(f"  - Evidence {item.get('name')}: {summary}")

        lines.extend(["", "## Deterministic Evidence", ""])
        if not evidence:
            lines.append("- No deterministic evidence was recorded.")
        for item in evidence:
            status = "SKIP" if item.get("skipped") else "PASS" if item.get("passed") else "FAIL"
            command = " ".join(item.get("command") or [])
            detail = item.get("reason") or command or item.get("stderr_tail") or item.get("stdout_tail") or "no detail"
            lines.append(f"- {status}: {item.get('name')} ({item.get('category')}) - {detail}")

        lines.extend(["", "## Learning", ""])
        if not learning:
            lines.append("- No learning artifact was recorded.")
        else:
            lines.append(f"- Observations: {learning.get('observation_count', 0)}")
            for pattern in learning.get("patterns", []):
                if not isinstance(pattern, dict):
                    continue
                stats = pattern.get("statistics", {})
                confidence = float(stats.get("confidence", 0.0)) if isinstance(stats, dict) else 0.0
                lines.append(f"- Pattern `{pattern.get('pattern_id')}` confidence {confidence:.3f}")

        return "\n".join(lines) + "\n"

    def _read_json(self, name: str) -> Dict[str, object]:
        path = self.run_dir / name
        if not path.exists():
            raise ReplayError(f"run artifact not found: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReplayError(f"invalid JSON artifact: {path}") from exc
        if not isinstance(payload, dict):
            raise ReplayError(f"expected JSON object artifact: {path}")
        return payload

    def _read_optional_json(self, name: str) -> Dict[str, object]:
        path = self.run_dir / name
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReplayError(f"invalid JSON artifact: {path}") from exc
        if not isinstance(payload, dict):
            raise ReplayError(f"expected JSON object artifact: {path}")
        return payload

    def _load_stages(self, result: Dict[str, object]) -> List[Dict[str, object]]:
        ordered_stages = []
        for stage in result.get("stages", []):
            if not isinstance(stage, dict):
                continue
            stage_name = stage.get("stage")
            if not stage_name:
                continue
            stage_path = self.run_dir / "stages" / f"{stage_name}.attempt{stage.get('attempt', 1)}.json"
            if stage_path.exists():
                payload = json.loads(stage_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    ordered_stages.append(payload)
                    continue
            ordered_stages.append(stage)
        return ordered_stages
