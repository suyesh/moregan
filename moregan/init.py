"""Repository initialization for MoreGAN."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from moregan.tools import StackToolDetector, ToolSuggestion
from moregan.processes import DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_TIMEOUT_SECONDS


DEFAULT_TOOLS = [
    {
        "name": "git_diff_check",
        "builtin": "git_diff_check",
        "category": "git",
        "required": True,
        "remediation": "Fix whitespace or conflict-marker issues reported by git diff --check.",
    },
    {
        "name": "python_compile",
        "builtin": "python_compile",
        "category": "syntax",
        "required": True,
        "remediation": "Fix Python syntax or import-time compilation errors.",
    },
    {
        "name": "unit_tests",
        "builtin": "unit_tests",
        "category": "tests",
        "required": True,
        "remediation": "Fix the failing tests or update tests only when requirements changed intentionally.",
    },
]


@dataclass
class InitAction:
    path: str
    action: str
    detail: str


@dataclass
class InitResult:
    root: str
    actions: List[InitAction] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(action.action in {"created", "updated", "would_create", "would_update"} for action in self.actions)


class MoreGANInitializer:
    """Creates safe repository-local MoreGAN configuration."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.moregan_dir = self.root / ".moregan"

    def init(self, force: bool = False, dry_run: bool = False, update_gitignore: bool = True) -> InitResult:
        result = InitResult(root=str(self.root))
        self._ensure_directory(self.moregan_dir, result, dry_run)
        self._ensure_directory(self.moregan_dir / "runs", result, dry_run)
        self._ensure_directory(self.moregan_dir / "learning", result, dry_run)
        self._write_config(
            relative_path=Path(".moregan") / "tools.yaml",
            content=self._tools_yaml(),
            force=force,
            dry_run=dry_run,
            result=result,
        )
        self._write_config(
            relative_path=Path(".moregan") / "workers.yaml",
            content=self._workers_yaml(),
            force=force,
            dry_run=dry_run,
            result=result,
        )
        if update_gitignore:
            self._ensure_gitignore(dry_run=dry_run, result=result)
        return result

    def _ensure_directory(self, path: Path, result: InitResult, dry_run: bool) -> None:
        relative = self._relative(path)
        if path.is_dir():
            result.actions.append(InitAction(relative, "exists", "directory already exists"))
            return
        result.actions.append(InitAction(relative, "would_create" if dry_run else "created", "created directory"))
        if not dry_run:
            path.mkdir(parents=True, exist_ok=True)

    def _write_config(
        self,
        relative_path: Path,
        content: str,
        force: bool,
        dry_run: bool,
        result: InitResult,
    ) -> None:
        path = self.root / relative_path
        if path.exists() and not force:
            result.actions.append(InitAction(str(relative_path), "skipped", "file exists; use --force to replace"))
            return

        action = "updated" if path.exists() else "created"
        dry_action = "would_update" if path.exists() else "would_create"
        result.actions.append(InitAction(str(relative_path), dry_action if dry_run else action, "wrote default config"))
        if dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _ensure_gitignore(self, dry_run: bool, result: InitResult) -> None:
        path = self.root / ".gitignore"
        entries = [".moregan/runs/", ".moregan/learning/", ".moregan/benchmarks/runs/",
                   ".moregan/benchmarks/comparisons/"]
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            missing = [entry for entry in entries if entry not in lines]
            if not missing:
                result.actions.append(InitAction(".gitignore", "exists", "already ignores local MoreGAN artifacts"))
                return
            updated = "\n".join(lines + missing) + "\n"
            detail = "added " + ", ".join(missing)
            result.actions.append(InitAction(".gitignore", "would_update" if dry_run else "updated", detail))
            if not dry_run:
                path.write_text(updated, encoding="utf-8")
            return

        result.actions.append(
            InitAction(".gitignore", "would_create" if dry_run else "created", "ignores local MoreGAN artifacts")
        )
        if not dry_run:
            path.write_text("".join(f"{entry}\n" for entry in entries), encoding="utf-8")

    def _tools_yaml(self) -> str:
        lines = [
            "version: 1",
            "commands:",
        ]
        for tool in DEFAULT_TOOLS:
            lines.extend(
                [
                    f"  - name: {tool['name']}",
                    f"    builtin: {tool['builtin']}",
                    f"    category: {tool['category']}",
                    f"    required: {str(tool['required']).lower()}",
                    f"    timeout_seconds: {DEFAULT_TIMEOUT_SECONDS}",
                    f"    max_output_bytes: {DEFAULT_MAX_OUTPUT_BYTES}",
                    f"    remediation: {self._quote(str(tool['remediation']))}",
                ]
            )

        suggestions = self._suggestions()
        if suggestions:
            lines.extend(
                [
                    "",
                    "# Detected stack presets. They are optional by default, so failures produce findings but do not block.",
                ]
            )
            for suggestion in suggestions:
                lines.extend(
                    [
                        f"  - name: {suggestion.name}",
                        f"    command: {self._inline_list(suggestion.command)}",
                        f"    category: {suggestion.category}",
                        f"    required: {str(suggestion.required).lower()}",
                        f"    enabled: {str(suggestion.enabled).lower()}",
                        f"    timeout_seconds: {DEFAULT_TIMEOUT_SECONDS}",
                        f"    max_output_bytes: {DEFAULT_MAX_OUTPUT_BYTES}",
                        f"    reason: {self._quote(suggestion.reason)}",
                        f"    remediation: {self._quote(suggestion.remediation)}",
                    ]
                )

        return "\n".join(lines) + "\n"

    def _workers_yaml(self) -> str:
        return "\n".join(
            [
                "version: 1",
                "workers: []",
                "",
                "# Example:",
                "# workers:",
                "#   - stage: generator",
                "#     command: [\"python3\", \"scripts/moregan_generator.py\"]",
                "#     timeout_seconds: 120",
                "#     no_write: false",
                "#     execution: repository  # auto, repository, or isolated",
            ]
        ) + "\n"

    def _suggestions(self) -> List[ToolSuggestion]:
        default_names = {str(tool["name"]) for tool in DEFAULT_TOOLS}
        suggestions = []
        for suggestion in StackToolDetector(self.root).suggest():
            if suggestion.name in default_names or suggestion.name == "python_unittest":
                continue
            suggestions.append(suggestion)
        return suggestions

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def _inline_list(self, values: List[str]) -> str:
        return "[" + ", ".join(self._quote(value) for value in values) + "]"

    def _quote(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
