"""Compact runtime context packs for MoreGAN workers."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from moregan.schemas import CommandEvidence, RiskClassification, StageResult


MAX_LIST_ITEMS = 80
MAX_STAGE_SUMMARIES = 12
MAX_FINDINGS = 20
MAX_EVIDENCE = 20
MAX_TEXT = 1200

STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "from",
    "have",
    "into",
    "more",
    "that",
    "their",
    "this",
    "with",
    "would",
}


@dataclass
class ContextPack:
    path: str
    bytes: int
    estimated_tokens: int


class ContextPackWriter:
    """Writes capped JSON context packs and a manifest for each run."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def write_base_context(
        self,
        run_dir: Path,
        request: str,
        risk: RiskClassification,
        tool_suggestions: Sequence[object],
    ) -> ContextPack:
        payload: Dict[str, object] = {
            "kind": "base_context",
            "generated_at": self._timestamp(),
            "run_id": run_dir.name,
            "request": request,
            "risk": asdict(risk),
            "route": risk.route,
            "repository": self._repository_summary(),
            "tool_suggestions": [self._safe_asdict(item) for item in tool_suggestions],
            "local_lessons": self._local_lessons(request, risk),
        }
        pack = self._write_pack(run_dir, Path("context") / "base.json", payload)
        self._append_manifest(run_dir, "base", None, 1, pack)
        return pack

    def write_stage_context(
        self,
        run_dir: Path,
        request: str,
        risk: RiskClassification,
        stage: str,
        attempt: int,
        stages: Sequence[StageResult],
        evidence: Sequence[CommandEvidence],
        remediation_context: Optional[Dict[str, object]],
    ) -> ContextPack:
        payload: Dict[str, object] = {
            "kind": "stage_context",
            "generated_at": self._timestamp(),
            "run_id": run_dir.name,
            "stage": stage,
            "attempt": attempt,
            "request": request,
            "risk": asdict(risk),
            "route": risk.route,
            "repository": self._repository_summary(),
            "prior_stage_summaries": self._stage_summaries(stages),
            "deterministic_evidence": self._evidence_summary(evidence),
            "remediation_context": self._trim_value(remediation_context or {}),
            "local_lessons": self._local_lessons(request, risk),
        }
        path = Path("context") / "stages" / f"{stage}.attempt{attempt}.json"
        pack = self._write_pack(run_dir, path, payload)
        self._append_manifest(run_dir, "stage", stage, attempt, pack)
        return pack

    def _write_pack(self, run_dir: Path, relative_path: Path, payload: Dict[str, object]) -> ContextPack:
        target = run_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload["context_size"] = self._size_payload(payload)
        text = json.dumps(payload, indent=2, sort_keys=True)
        payload["context_size"] = self._size_payload(payload)
        text = json.dumps(payload, indent=2, sort_keys=True)
        target.write_text(text + "\n", encoding="utf-8")
        size = len((text + "\n").encode("utf-8"))
        return ContextPack(path=str(target), bytes=size, estimated_tokens=self._estimate_tokens(text))

    def _append_manifest(
        self,
        run_dir: Path,
        kind: str,
        stage: Optional[str],
        attempt: int,
        pack: ContextPack,
    ) -> None:
        target = run_dir / "context" / "manifest.json"
        if target.exists():
            payload = json.loads(target.read_text(encoding="utf-8"))
            packs = payload.get("packs", [])
            if not isinstance(packs, list):
                packs = []
        else:
            packs = []

        packs.append(
            {
                "kind": kind,
                "stage": stage,
                "attempt": attempt,
                "path": pack.path,
                "bytes": pack.bytes,
                "estimated_tokens": pack.estimated_tokens,
            }
        )
        total_tokens = sum(int(item.get("estimated_tokens", 0)) for item in packs if isinstance(item, dict))
        target.write_text(
            json.dumps(
                {
                    "run_id": run_dir.name,
                    "generated_at": self._timestamp(),
                    "packs": packs,
                    "total_estimated_tokens": total_tokens,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _repository_summary(self) -> Dict[str, object]:
        status = self._git_lines(["git", "status", "--short", "--untracked-files=all"])
        files = self._git_lines(["git", "ls-files"])
        if status is not None:
            return {
                "root": str(self.root),
                "is_git_repo": True,
                "status_clean": len(status) == 0,
                "status": self._limited(status),
                "changed_files": self._limited(self._changed_files_from_status(status)),
                "tracked_file_count": len(files or []),
            }

        workspace_files = list(self._workspace_files())
        return {
            "root": str(self.root),
            "is_git_repo": False,
            "status_clean": None,
            "status": [],
            "changed_files": [],
            "workspace_files": self._limited(workspace_files),
            "workspace_file_count": len(workspace_files),
        }

    def _changed_files_from_status(self, lines: Sequence[str]) -> List[str]:
        changed = []
        for line in lines:
            if len(line) < 4:
                continue
            changed.append(line[3:].strip())
        return sorted(set(changed))

    def _workspace_files(self) -> Iterable[str]:
        ignored = {".git", ".moregan/runs", "__pycache__", ".pytest_cache", ".venv", "venv", "dist", "build"}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            relative_text = str(relative)
            if any(relative_text == item or relative_text.startswith(f"{item}/") for item in ignored):
                continue
            yield relative_text

    def _stage_summaries(self, stages: Sequence[StageResult]) -> List[Dict[str, object]]:
        summaries = []
        for stage in stages[-MAX_STAGE_SUMMARIES:]:
            summaries.append(
                {
                    "stage": stage.stage,
                    "verdict": stage.verdict,
                    "confidence": stage.confidence,
                    "attempt": stage.attempt,
                    "finding_count": len(stage.findings),
                    "findings": [self._trim_value(asdict(item)) for item in stage.findings[:MAX_FINDINGS]],
                    "evidence": [self._trim_value(asdict(item)) for item in stage.evidence[:MAX_EVIDENCE]],
                }
            )
        return summaries

    def _evidence_summary(self, evidence: Sequence[CommandEvidence]) -> List[Dict[str, object]]:
        summarized = []
        for item in evidence[-MAX_EVIDENCE:]:
            summarized.append(
                {
                    "name": item.name,
                    "category": item.category,
                    "passed": item.passed,
                    "required": item.required,
                    "attempt": item.attempt,
                    "exit_code": item.exit_code,
                    "skipped": item.skipped,
                    "reason": item.reason,
                    "remediation": item.remediation,
                    "stdout_tail": item.stdout_tail[-MAX_TEXT:],
                    "stderr_tail": item.stderr_tail[-MAX_TEXT:],
                }
            )
        return summarized

    def _local_lessons(self, request: str, risk: RiskClassification) -> Dict[str, object]:
        keywords = self._keywords(" ".join([request, risk.level, *risk.reasons, *risk.route]))
        candidates = []
        for path in self._lesson_candidates():
            text = self._read_lesson_text(path)
            if not text:
                continue
            haystack = f"{path.relative_to(self.root)} {text}".lower()
            score = sum(1 for keyword in keywords if keyword in haystack)
            if score > 0 or path.name == "progress.md":
                candidates.append(
                    {
                        "path": str(path.relative_to(self.root)),
                        "score": score,
                        "excerpt": self._excerpt(text),
                    }
                )
        candidates.sort(key=lambda item: (int(item["score"]), item["path"]), reverse=True)
        return {
            "source_paths": [".moregan/knowledge", ".moregan/evolution", ".moregan/progress.md"],
            "items": candidates[:8],
        }

    def _lesson_candidates(self) -> Iterable[Path]:
        roots = [self.root / ".moregan" / "knowledge", self.root / ".moregan" / "evolution"]
        progress = self.root / ".moregan" / "progress.md"
        if progress.exists():
            yield progress
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() in {".md", ".yaml", ".yml", ".json"} and path.is_file():
                    yield path

    def _read_lesson_text(self, path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ""
        if path.name == "progress.md":
            return text[-4000:]
        return text[:4000]

    def _keywords(self, text: str) -> List[str]:
        words = re.findall(r"[a-z0-9_]{4,}", text.lower())
        return sorted({word for word in words if word not in STOPWORDS})

    def _excerpt(self, text: str) -> str:
        normalized = " ".join(line.strip() for line in text.splitlines() if line.strip())
        if len(normalized) <= MAX_TEXT:
            return normalized
        return normalized[: MAX_TEXT - 3] + "..."

    def _safe_asdict(self, value: object) -> object:
        try:
            return asdict(value)  # type: ignore[arg-type]
        except TypeError:
            return self._trim_value(value)

    def _trim_value(self, value: object) -> object:
        if isinstance(value, str):
            if len(value) <= MAX_TEXT:
                return value
            return value[: MAX_TEXT - 3] + "..."
        if isinstance(value, list):
            return [self._trim_value(item) for item in value[:MAX_LIST_ITEMS]]
        if isinstance(value, dict):
            return {str(key): self._trim_value(item) for key, item in value.items()}
        return value

    def _limited(self, values: Sequence[str]) -> Dict[str, object]:
        return {
            "items": list(values[:MAX_LIST_ITEMS]),
            "count": len(values),
            "truncated": len(values) > MAX_LIST_ITEMS,
        }

    def _git_lines(self, command: Sequence[str]) -> Optional[List[str]]:
        result = subprocess.run(command, cwd=self.root, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return [line for line in result.stdout.splitlines() if line]

    def _size_payload(self, payload: Dict[str, object]) -> Dict[str, int]:
        text = json.dumps(payload, sort_keys=True)
        return {
            "bytes": len(text.encode("utf-8")),
            "estimated_tokens": self._estimate_tokens(text),
        }

    def _estimate_tokens(self, text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    def _timestamp(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
