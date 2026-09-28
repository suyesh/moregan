"""Agent provider adapter templates for MoreGAN workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from moregan.agent_worker import PROVIDER_COMMAND_ENV
from moregan.workers import WORKER_STAGE_LABELS


WORKER_STAGE_ORDER = [
    "planner",
    "architect",
    "designer_decision",
    "generator",
    "evaluator",
    "security_evaluator",
    "code_reviewer",
    "production_readiness_reviewer",
    "mr_readiness_analyzer",
    "learning_curator",
]

STAGE_OBJECTIVES = {
    "planner": "Create a concise implementation plan, acceptance criteria, and risk notes. Do not edit files.",
    "architect": "Review the plan for architecture, data, API, dependency, and migration risks. Do not edit files.",
    "designer_decision": "Decide whether a Designer stage is needed and record the rationale. Do not edit files.",
    "generator": "Implement the requested change when MOREGAN_NO_WRITE is 0. Return evidence of files changed and validation run.",
    "evaluator": "Evaluate acceptance criteria, functional risk, and test quality. Do not edit files.",
    "security_evaluator": "Review the change for security-sensitive behavior and vulnerability risks. Do not edit files.",
    "code_reviewer": "Review changed code for correctness, maintainability, and missing tests. Do not edit files.",
    "production_readiness_reviewer": "Review deployability, rollback, observability, configuration, and operational safety.",
    "mr_readiness_analyzer": "Score whether the local branch is ready for human review. Do not edit files.",
    "learning_curator": "Capture evidence-backed lessons only when supported by this run. Do not over-promote patterns.",
}


@dataclass
class AdapterAction:
    path: str
    action: str
    detail: str


@dataclass
class AdapterResult:
    provider: str
    root: str
    actions: List[AdapterAction] = field(default_factory=list)


class AdapterError(ValueError):
    """Raised for unsupported adapter operations."""


class AgentAdapterScaffolder:
    """Writes Codex/Claude worker adapter templates."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.moregan_dir = self.root / ".moregan"

    def scaffold(self, provider: str, force: bool = False, dry_run: bool = False, activate: bool = False) -> AdapterResult:
        provider = provider.lower().strip()
        if provider not in PROVIDER_COMMAND_ENV:
            raise AdapterError(f"unsupported provider: {provider}")

        result = AdapterResult(provider=provider, root=str(self.root))
        adapter_dir = self.moregan_dir / "adapters" / provider
        self._ensure_directory(adapter_dir, result, dry_run)
        self._write_file(adapter_dir / "README.md", self._readme(provider), force, dry_run, result)
        for stage in WORKER_STAGE_ORDER:
            self._write_file(adapter_dir / f"{stage}.md", self._prompt(provider, stage), force, dry_run, result)

        sample_workers = self.moregan_dir / f"workers.{provider}.yaml"
        self._write_file(sample_workers, self._workers_yaml(provider), force, dry_run, result)
        if activate:
            self._write_file(self.moregan_dir / "workers.yaml", self._workers_yaml(provider), force, dry_run, result)
        return result

    def _ensure_directory(self, path: Path, result: AdapterResult, dry_run: bool) -> None:
        if path.is_dir():
            result.actions.append(AdapterAction(self._relative(path), "exists", "directory already exists"))
            return
        result.actions.append(AdapterAction(self._relative(path), "would_create" if dry_run else "created", "created directory"))
        if not dry_run:
            path.mkdir(parents=True, exist_ok=True)

    def _write_file(
        self,
        path: Path,
        content: str,
        force: bool,
        dry_run: bool,
        result: AdapterResult,
    ) -> None:
        if path.exists() and not force:
            result.actions.append(AdapterAction(self._relative(path), "skipped", "file exists; use --force to replace"))
            return

        action = "updated" if path.exists() else "created"
        dry_action = "would_update" if path.exists() else "would_create"
        result.actions.append(AdapterAction(self._relative(path), dry_action if dry_run else action, "wrote adapter template"))
        if dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _workers_yaml(self, provider: str) -> str:
        lines = [
            "version: 1",
            "workers:",
        ]
        for stage in WORKER_STAGE_ORDER:
            no_write = "false" if stage == "generator" else "true"
            execution = "repository" if stage == "generator" else "auto"
            timeout = "600" if stage == "generator" else "300"
            lines.extend(
                [
                    f"  - stage: {stage}",
                    f"    command: {self._command(provider, stage)}",
                    f"    timeout_seconds: {timeout}",
                    "    max_output_bytes: 1048576",
                    "    max_prompt_bytes: 1048576",
                    f"    no_write: {no_write}",
                    f"    execution: {execution}",
                ]
            )
        return "\n".join(lines) + "\n"

    def _command(self, provider: str, stage: str) -> str:
        values = [
            "python3",
            "-m",
            "moregan.agent_worker",
            "--provider",
            provider,
            "--stage",
            stage,
            "--prompt",
            f".moregan/adapters/{provider}/{stage}.md",
        ]
        return "[" + ", ".join(self._quote(value) for value in values) + "]"

    def _readme(self, provider: str) -> str:
        env_name = PROVIDER_COMMAND_ENV[provider]
        return f"""# MoreGAN {provider.title()} Adapter Templates

These prompts are used by `python3 -m moregan.agent_worker`.

Set `{env_name}` to a provider command that accepts the generated prompt on stdin and prints a single MoreGAN `StageResult` JSON object on stdout. Keep the command project-local or user-local; do not put tokens in `.moregan/workers.yaml`.

Example shape:

```bash
export {env_name}='<your provider command that reads stdin and emits StageResult JSON>'
```

If `{env_name}` is unset, the worker returns `SKIP` and the run is incomplete, not passed.

To activate this provider template:

```bash
cp .moregan/workers.{provider}.yaml .moregan/workers.yaml
```

Review workers before activation. Review, evaluation, security, production, MR readiness, and planning workers default to `MOREGAN_NO_WRITE=1` with `execution: auto`, which runs no-write workers in isolated snapshots by default. The generator stage defaults to write-enabled repository execution.

Temporary snapshots are removed after worker execution. MoreGAN verifies the original checkout's contents for no-write workers; integrity or cleanup failures stop the run for inspection without automatic reverts. Snapshots are not a process sandbox, and execution paths in completed traces are historical.

Worker commands have bounded JSON stdout (`max_output_bytes`, default 1048576), prompt input (`max_prompt_bytes`, default 1048576), and stderr tails (at most 4000 bytes). Oversized or non-UTF-8 stdout fails, never partial JSON. The deadline includes stdin delivery and output-pipe closure. These direct Python wrappers share the outer worker's POSIX process group so ordinary provider descendants are stopped before snapshot cleanup. Windows currently stops only direct children. Unconfirmed process cleanup retains the snapshot and stops for manual inspection.
"""

    def _prompt(self, provider: str, stage: str) -> str:
        label = WORKER_STAGE_LABELS.get(stage, stage)
        objective = STAGE_OBJECTIVES[stage]
        no_write_instruction = (
            "This stage is review-only. If MOREGAN_NO_WRITE is 1, do not modify files."
            if stage != "generator"
            else "This is the only default write-enabled stage. Modify files only when MOREGAN_NO_WRITE is 0."
        )
        return f"""# MoreGAN {provider.title()} {label} Worker

You are executing the `{stage}` stage for the MoreGAN runtime.

Objective: {objective}

{no_write_instruction}

If the runtime phase is `post_generation_review`, risk increased after generation.
Review the existing patch and updated risk evidence before verification. Do not
pretend this was a pre-generation review. Return blocking concerns as findings
for the runtime's bounded remediation loop.

Return exactly one JSON object and no markdown fences:

```json
{{
  "stage": "{stage}",
  "verdict": "pass",
  "confidence": 0.9,
  "findings": [
    {{
      "severity": "medium",
      "category": "example_category",
      "description": "Concrete issue or empty findings when none exist.",
      "remediation": "Concrete remediation.",
      "file": null,
      "line": null
    }}
  ],
  "evidence": [
    {{
      "kind": "worker",
      "name": "{stage}_summary",
      "summary": "What you checked or changed.",
      "path": null,
      "command": null
    }}
  ]
}}
```

Use `verdict: "fail"` for blocking findings. Use `verdict: "skip"` only when the stage cannot run honestly.
Critical or high findings require `fail`. Confidence must be a finite number from 0 to 1.
Use only the documented fields and exact verdict/severity strings. Findings and evidence must be
arrays of objects, not prose or null. A finding requires nonempty category, description and remediation;
line is a positive integer or null. Evidence requires nonempty kind, name and summary.
Do not include attempt numbers or timestamps; MoreGAN records execution metadata itself.
"""

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def _quote(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
