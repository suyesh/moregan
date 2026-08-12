"""Deterministic tool configuration and repository stack detection."""

from __future__ import annotations

import ast
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ToolCommand:
    name: str
    category: str
    required: bool
    remediation: str
    source: str
    command: Optional[List[str]] = None
    builtin: Optional[str] = None
    enabled: bool = True


@dataclass
class ToolSuggestion:
    name: str
    category: str
    command: List[str]
    reason: str
    remediation: str
    required: bool = False
    enabled: bool = True


class ToolConfigError(ValueError):
    """Raised when .moregan/tools.yaml cannot be interpreted."""


class ToolConfigLoader:
    """Loads deterministic checks from .moregan/tools.yaml when present."""

    CONFIG_PATH = Path(".moregan") / "tools.yaml"

    DEFAULT_TOOLS = [
        ToolCommand(
            name="git_diff_check",
            builtin="git_diff_check",
            category="git",
            required=True,
            remediation="Fix whitespace or conflict-marker issues reported by git diff --check.",
            source="default",
        ),
        ToolCommand(
            name="python_compile",
            builtin="python_compile",
            category="syntax",
            required=True,
            remediation="Fix Python syntax or import-time compilation errors.",
            source="default",
        ),
        ToolCommand(
            name="unit_tests",
            builtin="unit_tests",
            category="tests",
            required=True,
            remediation="Fix the failing tests or update tests only when requirements changed intentionally.",
            source="default",
        ),
    ]

    def __init__(self, root: Path):
        self.root = root

    def load(self) -> List[ToolCommand]:
        path = self.root / self.CONFIG_PATH
        if not path.exists():
            return list(self.DEFAULT_TOOLS)

        payload = self._parse_minimal_yaml(path.read_text(encoding="utf-8"))
        raw_commands = payload.get("commands")
        if not isinstance(raw_commands, list):
            raise ToolConfigError(f"{self.CONFIG_PATH} must define a commands list")

        commands = [self._coerce_command(item) for item in raw_commands]
        return [command for command in commands if command.enabled]

    def _coerce_command(self, payload: Dict[str, object]) -> ToolCommand:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ToolConfigError("each tool command needs a name")

        command = payload.get("command")
        builtin = payload.get("builtin")
        if command is None and builtin is None:
            raise ToolConfigError(f"{name} needs either command or builtin")

        coerced_command = self._coerce_command_value(command) if command is not None else None
        return ToolCommand(
            name=name,
            command=coerced_command,
            builtin=str(builtin).strip() if builtin is not None else None,
            category=str(payload.get("category", "custom")).strip() or "custom",
            required=self._coerce_bool(payload.get("required", True)),
            enabled=self._coerce_bool(payload.get("enabled", True)),
            remediation=str(payload.get("remediation", "Inspect the command output and fix the failed check.")),
            source=str(self.CONFIG_PATH),
        )

    def _coerce_command_value(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            return shlex.split(value)
        raise ToolConfigError("command must be a string or list")

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

    def _parse_minimal_yaml(self, text: str) -> Dict[str, object]:
        data: Dict[str, object] = {}
        current_section: Optional[str] = None
        current_item: Optional[Dict[str, object]] = None

        for raw_line in text.splitlines():
            line = self._strip_comment(raw_line).rstrip()
            if not line.strip():
                continue

            stripped = line.strip()
            if not line.startswith(" ") and stripped.endswith(":"):
                current_section = stripped[:-1]
                if current_section == "commands":
                    data[current_section] = []
                else:
                    data[current_section] = {}
                current_item = None
                continue

            if current_section == "commands" and stripped.startswith("- "):
                current_item = {}
                data.setdefault("commands", []).append(current_item)
                remainder = stripped[2:].strip()
                if remainder:
                    key, value = self._split_key_value(remainder)
                    current_item[key] = self._parse_scalar(value)
                continue

            if current_section == "commands" and current_item is not None:
                key, value = self._split_key_value(stripped)
                current_item[key] = self._parse_scalar(value)
                continue

            key, value = self._split_key_value(stripped)
            data[key] = self._parse_scalar(value)

        return data

    def _split_key_value(self, value: str) -> tuple:
        if ":" not in value:
            raise ToolConfigError(f"expected key: value, got {value!r}")
        key, raw = value.split(":", 1)
        return key.strip(), raw.strip()

    def _parse_scalar(self, value: str) -> object:
        if value == "":
            return ""
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                raise ToolConfigError(f"invalid list value: {value}") from exc
            if not isinstance(parsed, list):
                raise ToolConfigError(f"expected list value: {value}")
            return parsed
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            try:
                return ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return value[1:-1]
        try:
            return int(value)
        except ValueError:
            return value

    def _strip_comment(self, line: str) -> str:
        in_single = False
        in_double = False
        for index, character in enumerate(line):
            if character == "'" and not in_double:
                in_single = not in_single
            elif character == '"' and not in_single:
                in_double = not in_double
            elif character == "#" and not in_single and not in_double:
                return line[:index]
        return line


class StackToolDetector:
    """Suggests deterministic tools from repository files without running them."""

    def __init__(self, root: Path):
        self.root = root

    def suggest(self) -> List[ToolSuggestion]:
        suggestions: List[ToolSuggestion] = []
        suggestions.extend(self._python_suggestions())
        suggestions.extend(self._node_suggestions())
        suggestions.extend(self._java_suggestions())
        suggestions.extend(self._ruby_suggestions())
        suggestions.extend(self._rust_suggestions())
        suggestions.extend(self._go_suggestions())
        suggestions.extend(self._security_suggestions())
        return self._dedupe(suggestions)

    def _python_suggestions(self) -> List[ToolSuggestion]:
        suggestions: List[ToolSuggestion] = []
        if (self.root / "tests").is_dir():
            suggestions.append(
                ToolSuggestion(
                    name="pytest",
                    category="tests",
                    command=["python3", "-m", "pytest"],
                    reason="tests/ directory exists",
                    remediation="Fix failing pytest tests or update them for intentional behavior changes.",
                )
            )
            suggestions.append(
                ToolSuggestion(
                    name="python_unittest",
                    category="tests",
                    command=["python3", "-m", "unittest", "discover", "-s", "tests"],
                    reason="tests/ directory exists",
                    remediation="Fix failing Python unittest tests or update them for intentional behavior changes.",
                    enabled=False,
                )
            )
        if self._contains_any("pyproject.toml", ["[tool.ruff]", "ruff"]):
            suggestions.append(
                ToolSuggestion(
                    name="ruff_check",
                    category="lint",
                    command=["ruff", "check", "."],
                    reason="pyproject.toml references ruff",
                    remediation="Fix reported Ruff lint violations.",
                )
            )
        if self._contains_any("pyproject.toml", ["[tool.mypy]"]) or (self.root / "mypy.ini").exists():
            suggestions.append(
                ToolSuggestion(
                    name="mypy",
                    category="typecheck",
                    command=["mypy", "."],
                    reason="mypy configuration exists",
                    remediation="Fix reported Python type errors.",
                )
            )
        if self._contains_any("pyproject.toml", ["bandit"]) or (self.root / ".bandit").exists():
            suggestions.append(
                ToolSuggestion(
                    name="bandit",
                    category="security",
                    command=["python3", "-m", "bandit", "-r", "."],
                    reason="Bandit configuration or dependency reference exists",
                    remediation="Fix validated Bandit security findings.",
                )
            )
        if (self.root / "requirements.txt").exists() or self._contains_any("pyproject.toml", ["pip-audit"]):
            suggestions.append(
                ToolSuggestion(
                    name="pip_audit",
                    category="dependency_audit",
                    command=["python3", "-m", "pip_audit"],
                    reason="Python dependency manifest exists",
                    remediation="Review and remediate vulnerable Python dependencies.",
                )
            )
        return suggestions

    def _node_suggestions(self) -> List[ToolSuggestion]:
        package_json = self.root / "package.json"
        if not package_json.exists():
            return []
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

        scripts = payload.get("scripts", {})
        suggestions: List[ToolSuggestion] = []
        if "test" in scripts:
            suggestions.append(self._npm_script("npm_test", "tests", "test"))
        if "lint" in scripts:
            suggestions.append(self._npm_script("npm_lint", "lint", "lint"))
        if "typecheck" in scripts:
            suggestions.append(self._npm_script("npm_typecheck", "typecheck", "typecheck"))
        suggestions.append(
            ToolSuggestion(
                name="npm_audit",
                category="dependency_audit",
                command=["npm", "audit"],
                reason="package.json exists",
                remediation="Review and remediate vulnerable npm dependencies.",
            )
        )
        return suggestions

    def _npm_script(self, name: str, category: str, script: str) -> ToolSuggestion:
        return ToolSuggestion(
            name=name,
            category=category,
            command=["npm", "run", script],
            reason=f"package.json defines scripts.{script}",
            remediation=f"Fix failures from npm run {script}.",
        )

    def _java_suggestions(self) -> List[ToolSuggestion]:
        suggestions: List[ToolSuggestion] = []
        suggestions.extend(self._maven_suggestions())
        suggestions.extend(self._gradle_suggestions())
        return suggestions

    def _maven_suggestions(self) -> List[ToolSuggestion]:
        pom = self.root / "pom.xml"
        if not pom.exists():
            return []

        command = self._java_command("mvnw", "mvn")
        text = pom.read_text(encoding="utf-8", errors="ignore").lower()
        suggestions = [
            ToolSuggestion(
                "maven_test",
                "tests",
                command + ["test"],
                self._java_reason("pom.xml exists", text),
                "Fix failing Maven tests or update them for intentional behavior changes.",
            )
        ]
        if "maven-checkstyle-plugin" in text or (self.root / "checkstyle.xml").exists():
            suggestions.append(
                ToolSuggestion(
                    "maven_checkstyle",
                    "lint",
                    command + ["checkstyle:check"],
                    "Maven Checkstyle configuration detected",
                    "Fix reported Checkstyle violations.",
                )
            )
        if "spotbugs-maven-plugin" in text or "findbugs-maven-plugin" in text:
            suggestions.append(
                ToolSuggestion(
                    "maven_spotbugs",
                    "security",
                    command + ["spotbugs:check"],
                    "Maven SpotBugs configuration detected",
                    "Fix validated SpotBugs findings.",
                )
            )
        if "maven-pmd-plugin" in text or (self.root / "pmd.xml").exists():
            suggestions.append(
                ToolSuggestion(
                    "maven_pmd",
                    "lint",
                    command + ["pmd:check"],
                    "Maven PMD configuration detected",
                    "Fix reported PMD violations.",
                )
            )
        if "dependency-check-maven" in text or "dependency-check" in text:
            suggestions.append(
                ToolSuggestion(
                    "maven_dependency_check",
                    "dependency_audit",
                    command + ["dependency-check:check"],
                    "OWASP Dependency-Check Maven configuration detected",
                    "Review and remediate vulnerable Java dependencies.",
                )
            )
        return suggestions

    def _gradle_suggestions(self) -> List[ToolSuggestion]:
        build_files = ["build.gradle", "build.gradle.kts"]
        if not any((self.root / filename).exists() for filename in build_files):
            return []

        command = self._java_command("gradlew", "gradle")
        text = self._read_many(build_files + ["settings.gradle", "settings.gradle.kts"]).lower()
        suggestions = [
            ToolSuggestion(
                "gradle_test",
                "tests",
                command + ["test"],
                self._java_reason("Gradle build file exists", text),
                "Fix failing Gradle tests or update them for intentional behavior changes.",
            )
        ]
        if "checkstyle" in text or (self.root / "config" / "checkstyle").is_dir():
            suggestions.append(
                ToolSuggestion(
                    "gradle_checkstyle",
                    "lint",
                    command + ["checkstyleMain", "checkstyleTest"],
                    "Gradle Checkstyle configuration detected",
                    "Fix reported Checkstyle violations.",
                )
            )
        if "spotbugs" in text or "findbugs" in text:
            suggestions.append(
                ToolSuggestion(
                    "gradle_spotbugs",
                    "security",
                    command + ["spotbugsMain", "spotbugsTest"],
                    "Gradle SpotBugs configuration detected",
                    "Fix validated SpotBugs findings.",
                )
            )
        if "pmd" in text or (self.root / "config" / "pmd").is_dir():
            suggestions.append(
                ToolSuggestion(
                    "gradle_pmd",
                    "lint",
                    command + ["pmdMain", "pmdTest"],
                    "Gradle PMD configuration detected",
                    "Fix reported PMD violations.",
                )
            )
        if "dependencycheck" in text or "dependency-check" in text:
            suggestions.append(
                ToolSuggestion(
                    "gradle_dependency_check",
                    "dependency_audit",
                    command + ["dependencyCheckAnalyze"],
                    "OWASP Dependency-Check Gradle configuration detected",
                    "Review and remediate vulnerable Java dependencies.",
                )
            )
        return suggestions

    def _java_command(self, wrapper_name: str, fallback: str) -> List[str]:
        wrapper = self.root / wrapper_name
        if wrapper.exists():
            return [f"./{wrapper_name}"]
        return [fallback]

    def _java_reason(self, base: str, text: str) -> str:
        if "spring-boot" in text or "org.springframework.boot" in text:
            return f"{base}; Spring Boot detected"
        return base

    def _ruby_suggestions(self) -> List[ToolSuggestion]:
        gemfile = self.root / "Gemfile"
        if not gemfile.exists():
            return []
        text = gemfile.read_text(encoding="utf-8", errors="ignore")
        suggestions = [
            ToolSuggestion(
                "bundle_audit",
                "dependency_audit",
                ["bundle", "exec", "bundle-audit", "check", "--update"],
                "Gemfile exists",
                "Review and remediate vulnerable Ruby dependencies.",
            )
        ]
        if "rails" in text.lower() or (self.root / "config" / "routes.rb").exists():
            suggestions.append(
                ToolSuggestion(
                    "rspec",
                    "tests",
                    ["bundle", "exec", "rspec"],
                    "Rails or RSpec project files detected",
                    "Fix failing RSpec examples or update specs for intentional behavior changes.",
                )
            )
            suggestions.append(
                ToolSuggestion(
                    "rubocop",
                    "lint",
                    ["bundle", "exec", "rubocop"],
                    "Rails or Ruby project files detected",
                    "Fix reported RuboCop violations.",
                )
            )
            suggestions.append(
                ToolSuggestion(
                    "brakeman",
                    "security",
                    ["bundle", "exec", "brakeman", "--no-pager"],
                    "Rails project files detected",
                    "Fix validated Brakeman security findings.",
                )
            )
        return suggestions

    def _rust_suggestions(self) -> List[ToolSuggestion]:
        if not (self.root / "Cargo.toml").exists():
            return []
        return [
            ToolSuggestion("cargo_test", "tests", ["cargo", "test"], "Cargo.toml exists", "Fix failing Rust tests."),
            ToolSuggestion(
                "cargo_clippy",
                "lint",
                ["cargo", "clippy", "--all-targets", "--all-features"],
                "Cargo.toml exists",
                "Fix reported Clippy lints.",
            ),
            ToolSuggestion(
                "cargo_audit",
                "dependency_audit",
                ["cargo", "audit"],
                "Cargo.toml exists",
                "Review and remediate vulnerable Rust dependencies.",
            ),
        ]

    def _go_suggestions(self) -> List[ToolSuggestion]:
        if not (self.root / "go.mod").exists():
            return []
        return [
            ToolSuggestion("go_test", "tests", ["go", "test", "./..."], "go.mod exists", "Fix failing Go tests."),
            ToolSuggestion("go_vet", "lint", ["go", "vet", "./..."], "go.mod exists", "Fix reported go vet issues."),
            ToolSuggestion(
                "staticcheck",
                "lint",
                ["staticcheck", "./..."],
                "go.mod exists",
                "Fix reported staticcheck issues.",
            ),
        ]

    def _security_suggestions(self) -> List[ToolSuggestion]:
        suggestions: List[ToolSuggestion] = []
        if (self.root / ".semgrep.yml").exists() or (self.root / ".semgrep.yaml").exists():
            suggestions.append(
                ToolSuggestion(
                    "semgrep",
                    "security",
                    ["semgrep", "--config", "auto", "."],
                    "Semgrep configuration exists",
                    "Fix validated Semgrep findings.",
                )
            )
        if (self.root / ".gitleaks.toml").exists():
            suggestions.append(
                ToolSuggestion(
                    "gitleaks",
                    "secret_scan",
                    ["gitleaks", "detect", "--source", "."],
                    ".gitleaks.toml exists",
                    "Remove leaked secrets and rotate any exposed credentials.",
                )
            )
        return suggestions

    def _contains_any(self, relative_path: str, needles: List[str]) -> bool:
        path = self.root / relative_path
        if not path.exists():
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
        return any(needle in text for needle in needles)

    def _read_many(self, relative_paths: List[str]) -> str:
        chunks = []
        for relative_path in relative_paths:
            path = self.root / relative_path
            if path.exists():
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        return "\n".join(chunks)

    def _dedupe(self, suggestions: List[ToolSuggestion]) -> List[ToolSuggestion]:
        seen = set()
        unique = []
        for suggestion in suggestions:
            if suggestion.name in seen:
                continue
            seen.add(suggestion.name)
            unique.append(suggestion)
        return unique
