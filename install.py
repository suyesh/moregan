#!/usr/bin/env python3
"""
MoreGAN installer and maintenance CLI.
"""

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.request import urlopen

VERSION = "1.14.0"
BRAND_NAME = "MoreGAN"
SKILL_NAME = "moregan"
DEFAULT_REPOSITORY_URL = "https://github.com/suyesh/moregan"
INSTALL_MANIFEST_PATH = Path(".moregan") / "install-manifest.json"
CLAUDE_PERSONAS = {
    "Planner.md": "moregan-planner.md",
    "Architect.md": "moregan-architect.md",
    "Designer.md": "moregan-designer.md",
    "Generator.md": "moregan-generator.md",
    "Evaluator.md": "moregan-evaluator.md",
    "SecurityEvaluator.md": "moregan-security-evaluator.md",
    "CodeReviewer.md": "moregan-code-reviewer.md",
    "ProductionReadinessReviewer.md": "moregan-production-readiness-reviewer.md",
    "MRReadinessAnalyzer.md": "moregan-mr-readiness-analyzer.md",
    "LearningCurator.md": "moregan-learning-curator.md",
}
CODEX_REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "INSTALL.md",
    "ROADMAP.md",
    "LICENSE",
    "install.py",
    "assets",
    ".moregan",
    "personas",
    "moregan",
]
CLAUDE_REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "INSTALL.md",
    "ROADMAP.md",
    "LICENSE",
    "install.py",
    "assets",
    ".moregan",
    "personas",
    "moregan",
]

# Use rich when available; otherwise fall back to a dependency-free terminal UI.
try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
    from rich.tree import Tree
except ImportError:
    def _plain(value):
        return re.sub(r"\[/?[a-zA-Z][^\]]*\]", "", str(value))

    class Console:
        def print(self, value="", *args, **kwargs):
            print(_plain(value))

    class Panel:
        def __init__(self, content, *args, **kwargs):
            self.content = content

        @classmethod
        def fit(cls, content, *args, **kwargs):
            return cls(content)

        def __str__(self):
            return str(self.content)

    class Progress:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def add_task(self, description, total=0):
            print(_plain(description))
            return 0

        def update(self, task, advance=1):
            pass

    class SpinnerColumn:
        pass

    class TextColumn:
        def __init__(self, *args, **kwargs):
            pass

    class BarColumn:
        pass

    class Prompt:
        @staticmethod
        def ask(prompt, choices=None, default=None):
            suffix = f" [{'/'.join(choices)}]" if choices else ""
            if default:
                suffix += f" ({default})"
            while True:
                response = input(f"{_plain(prompt)}{suffix}: ").strip() or default
                if choices is None or response in choices:
                    return response
                print(f"Choose one of: {', '.join(choices)}")

    class Confirm:
        @staticmethod
        def ask(prompt, default=False):
            default_text = "Y/n" if default else "y/N"
            response = input(f"{_plain(prompt)} [{default_text}]: ").strip().lower()
            if not response:
                return default
            return response in {"y", "yes"}

    class Table:
        def __init__(self, title="", *args, **kwargs):
            self.title = title
            self.rows = []

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *values):
            self.rows.append(values)

        def __str__(self):
            lines = [self.title] if self.title else []
            lines.extend(" | ".join(str(value) for value in row) for row in self.rows)
            return "\n".join(lines)

    class _Box:
        DOUBLE_EDGE = "double"
        ROUNDED = "rounded"
        DOUBLE = "double"

    box = _Box()

    class Tree:
        def __init__(self, label):
            self.label = label
            self.children = []

        def add(self, label):
            child = Tree(label)
            self.children.append(child)
            return child

        def __str__(self):
            lines = [str(self.label)]
            for child in self.children:
                for line in str(child).splitlines():
                    lines.append(f"  {line}")
            return "\n".join(lines)

try:
    import questionary
    from questionary import Choice
    from questionary import Style as QuestionaryStyle
except ImportError:
    questionary = None
    Choice = None
    QuestionaryStyle = None

try:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style as PromptToolkitStyle
except ImportError:
    Application = None
    KeyBindings = None
    Layout = None
    HSplit = None
    Window = None
    FormattedTextControl = None
    PromptToolkitStyle = None


@dataclass
class DoctorIssue:
    category: str
    path: Path
    detail: str
    action: str


class MoreGANInstaller:
    """Installer and maintenance commands for MoreGAN."""

    def __init__(self, source_dir: Optional[Path] = None, home: Optional[Path] = None, console: Optional[Console] = None):
        self.console = console or Console()
        self.source_dir = (source_dir or Path(__file__).parent).resolve()
        self.home = (home or Path.home()).resolve()
        self.claude_path = self._get_claude_path()
        self.codex_path = self._get_codex_path()
        self.installed_files: List[Path] = []
        self.install_targets: List[str] = []
        self.questionary_style = (
            QuestionaryStyle(
                [
                    ("qmark", "fg:#ffb454 bold"),
                    ("question", "fg:#e5e7eb bold"),
                    ("answer", "fg:#7dd3fc bold"),
                    ("pointer", "fg:#7dd3fc bold"),
                    ("highlighted", "fg:#081018 bg:#7dd3fc bold"),
                    ("selected", "fg:#7dd3fc bold"),
                    ("instruction", "fg:#9ca3af italic"),
                    ("text", "fg:#d1d5db"),
                    ("disabled", "fg:#6b7280 italic"),
                ]
            )
            if QuestionaryStyle is not None
            else None
        )

    def _get_claude_path(self) -> Dict[str, Path]:
        return {
            "global_skills": self.home / ".claude" / "skills" / SKILL_NAME,
            "global_agents": self.home / ".claude" / "agents",
            "config": self.home / ".claude",
        }

    def _get_codex_path(self) -> Dict[str, Path]:
        return {
            "global_skills": self.home / ".codex" / "skills" / SKILL_NAME,
            "config": self.home / ".codex",
        }

    def _get_backup_root(self, target_path: Path) -> Path:
        if str(target_path).startswith(str(self.claude_path["config"])):
            return self.claude_path["config"] / "backups" / SKILL_NAME
        if str(target_path).startswith(str(self.codex_path["config"])):
            return self.codex_path["config"] / "backups" / SKILL_NAME
        return self.source_dir / ".moregan" / "backups"

    def _read_install_manifest(self, base_dir: Optional[Path] = None) -> Optional[dict]:
        manifest_path = self._get_manifest_path(base_dir)
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _normalize_repository_url(self, remote_url: str) -> str:
        remote_url = remote_url.strip()

        ssh_match = re.match(r"git@github\.com:(?P<slug>.+?)(?:\.git)?$", remote_url)
        if ssh_match:
            return f"https://github.com/{ssh_match.group('slug')}"

        ssh_proto_match = re.match(r"ssh://git@github\.com/(?P<slug>.+?)(?:\.git)?$", remote_url)
        if ssh_proto_match:
            return f"https://github.com/{ssh_proto_match.group('slug')}"

        https_match = re.match(r"https://github\.com/(?P<slug>.+?)(?:\.git)?/?$", remote_url)
        if https_match:
            return f"https://github.com/{https_match.group('slug')}"

        return remote_url.removesuffix(".git").rstrip("/")

    def _get_repository_url(self) -> str:
        if (self.source_dir / ".git").exists():
            try:
                remote_url = self._git_output(["git", "config", "--get", "remote.origin.url"]).strip()
                if remote_url:
                    return self._normalize_repository_url(remote_url)
            except Exception:
                pass

        manifest = self._read_install_manifest()
        if manifest and manifest.get("repository_url"):
            return manifest["repository_url"]

        return DEFAULT_REPOSITORY_URL

    def show_banner(self):
        banner = Panel.fit(
            f"[bold magenta]{BRAND_NAME}[/bold magenta] [cyan]v{VERSION}[/cyan]\n"
            f"[dim]Installed skill name: {SKILL_NAME}[/dim]\n\n"
            "[italic]High-reliability engineering framework for AI code generation[/italic]\n"
            "[dim]Inspired by GAN architectures[/dim]",
            border_style="bright_blue",
            box=box.DOUBLE_EDGE,
            title="[bold yellow]⚡ Installation Wizard ⚡[/bold yellow]",
            title_align="center",
        )
        self.console.print(banner)
        self.console.print()

    def detect_claude(self) -> bool:
        return self.claude_path["config"].exists()

    def detect_codex(self) -> bool:
        return self.codex_path["config"].exists()

    def is_installed(self, target: str) -> bool:
        if target == "claude":
            return (self.claude_path["global_skills"] / "SKILL.md").exists()
        return (self.codex_path["global_skills"] / "SKILL.md").exists()

    def show_environment_status(self):
        claude_installed = self.detect_claude()
        codex_installed = self.detect_codex()

        table = Table(
            title="[bold cyan]🔍 Environment Detection[/bold cyan]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Environment", style="cyan", width=15)
        table.add_column("Status", width=20)
        table.add_column("Path", style="dim")

        table.add_row(
            "Claude Code",
            "[green]✅ Installed[/green]" if claude_installed else "[red]❌ Not Found[/red]",
            str(self.claude_path["config"]),
        )
        table.add_row(
            "Codex",
            "[green]✅ Installed[/green]" if codex_installed else "[red]❌ Not Found[/red]",
            str(self.codex_path["config"]),
        )

        self.console.print(table)
        self.console.print()

        if not claude_installed and not codex_installed:
            self.console.print("[bold red]⚠️  No supported AI coding environment detected![/bold red]")
            self.console.print("[yellow]Please install Claude Code or Codex first.[/yellow]")
            self.console.print("[dim]Expected locations: ~/.claude/ or ~/.codex/[/dim]")
            sys.exit(1)

    def resolve_targets(self, explicit_targets: Optional[Sequence[str]] = None, prefer_installed: bool = False):
        if explicit_targets:
            self.install_targets = list(dict.fromkeys(explicit_targets))
            return

        if prefer_installed:
            installed_targets = [target for target in ("claude", "codex") if self.is_installed(target)]
            if installed_targets:
                self.install_targets = installed_targets
                return

        self.choose_install_targets()

    def choose_install_targets(self):
        claude_installed = self.detect_claude()
        codex_installed = self.detect_codex()

        if claude_installed and codex_installed:
            target = self._select_option(
                f"Where should {BRAND_NAME} be installed?",
                [
                    ("both", "Both", "Install into Claude Code and Codex"),
                    ("claude", "Claude Code", "Install only into Claude Code"),
                    ("codex", "Codex", "Install only into Codex"),
                ],
                default="both",
            )
            self.install_targets = ["claude", "codex"] if target == "both" else [target]
        elif claude_installed:
            self.install_targets = ["claude"]
        elif codex_installed:
            self.install_targets = ["codex"]
        else:
            self.install_targets = []

    def _select_option(self, message: str, options: Sequence[tuple], default: str) -> str:
        if Application is not None and KeyBindings is not None:
            return self._run_terminal_select(message, options, default)

        if questionary is not None:
            choices = []
            for option in options:
                value, label = option[0], option[1]
                description = option[2] if len(option) > 2 else None
                choices.append(Choice(title=label, value=value, description=description))
            selection = questionary.select(
                message,
                choices=choices,
                default=default,
                use_indicator=True,
                qmark="◆",
                pointer="➜",
                style=self.questionary_style,
                instruction="Use ↑/↓ to move and Enter to select",
            ).ask()
            if selection is not None:
                return selection

        fallback_choices = [option[0] for option in options]
        return Prompt.ask(f"\n{message}", choices=fallback_choices, default=default)

    def _run_terminal_select(self, message: str, options: Sequence[tuple], default: str) -> str:
        option_values = [option[0] for option in options]
        selected_index = option_values.index(default) if default in option_values else 0
        result = {"value": option_values[selected_index]}

        style = PromptToolkitStyle.from_dict(
            {
                "dialog": "bg:#111827",
                "question": "fg:#f9fafb bold",
                "pointer": "fg:#7dd3fc bold",
                "selected": "fg:#081018 bg:#7dd3fc bold",
                "description": "fg:#94a3b8",
                "hint": "fg:#f59e0b italic",
            }
        )

        def build_lines():
            fragments = [
                ("class:question", f"{message}\n"),
                ("class:hint", "Space/Down: next   Up: previous   Enter: select\n\n"),
            ]

            for index, option in enumerate(options):
                value, label = option[0], option[1]
                description = option[2] if len(option) > 2 else None
                is_selected = index == selected_index_holder[0]
                pointer = "➜ " if is_selected else "  "
                style_name = "class:selected" if is_selected else ""
                fragments.append(("class:pointer" if is_selected else "", pointer))
                fragments.append((style_name, label))
                if description:
                    fragments.append(("", "\n   "))
                    fragments.append(("class:description", description))
                fragments.append(("", "\n"))

            return fragments

        selected_index_holder = [selected_index]

        control = FormattedTextControl(build_lines, focusable=True, show_cursor=False)
        bindings = KeyBindings()

        def move(delta: int):
            selected_index_holder[0] = (selected_index_holder[0] + delta) % len(options)

        @bindings.add(" ")
        @bindings.add("down")
        @bindings.add("tab")
        @bindings.add("j")
        def _next(event):
            move(1)

        @bindings.add("up")
        @bindings.add("s-tab")
        @bindings.add("k")
        def _previous(event):
            move(-1)

        @bindings.add("enter")
        def _accept(event):
            result["value"] = options[selected_index_holder[0]][0]
            event.app.exit(result=result["value"])

        @bindings.add("c-c")
        def _abort(event):
            raise KeyboardInterrupt()

        app = Application(
            layout=Layout(
                HSplit(
                    [
                        Window(content=control, always_hide_cursor=True),
                    ]
                )
            ),
            key_bindings=bindings,
            full_screen=False,
            style=style,
        )
        return app.run()

    def _confirm_with_select(self, message: str, default: bool = True) -> bool:
        if questionary is not None:
            return (
                self._select_option(
                    message,
                    [
                        ("yes", "Proceed", "Continue with installation"),
                        ("no", "Cancel", "Exit without making changes"),
                    ],
                    default="yes" if default else "no",
                )
                == "yes"
            )
        return Confirm.ask(message, default=default)

    def show_features(self):
        features_panel = Panel(
            "[bold green]✨ Features to Install:[/bold green]\n\n"
            "• [cyan]10 Personas[/cyan]: Planner, Architect, Designer, Generator, Evaluator, Security Evaluator, "
            "Code Reviewer, Production Readiness Reviewer, MR Readiness Analyzer, Learning Curator\n"
            "• [cyan]Failure Pattern Memory[/cyan]: Learning from past mistakes\n"
            "• [cyan]Confidence Scoring[/cyan]: Adaptive validation levels\n"
            "• [cyan]Rollback Mechanisms[/cyan]: Automatic recovery from failures\n"
            "• [cyan]Cross-Session Learning[/cyan]: Pattern evolution system\n"
            "• [cyan]Multi-Generator Mode[/cyan]: Parallel specialized generators\n"
            "• [cyan]Enterprise Integrations[/cyan]: CI/CD, monitoring, security tools\n"
            "• [cyan]Living Documentation[/cyan]: Auto-generated and maintained docs",
            border_style="green",
            box=box.ROUNDED,
        )
        self.console.print(features_panel)
        self.console.print()

    def create_backup(self, target_path: Path) -> Optional[Path]:
        if target_path.exists():
            backup_root = self._get_backup_root(target_path)
            backup_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_root / f"{target_path.name}.{timestamp}"
            self.console.print(f"[yellow]📦 Creating backup at {backup_path}[/yellow]")
            shutil.copytree(target_path, backup_path)
            return backup_path
        return None

    def _cleanup_sibling_backups(self, target_path: Path):
        parent = target_path.parent
        if not parent.exists():
            return

        backup_root = self._get_backup_root(target_path)
        backup_root.mkdir(parents=True, exist_ok=True)

        for child in parent.iterdir():
            if child == target_path or not child.is_dir():
                continue
            if not self._is_auto_repair_duplicate_name(child.name):
                continue
            destination = backup_root / child.name
            counter = 1
            while destination.exists():
                destination = backup_root / f"{child.name}-{counter}"
                counter += 1
            self.console.print(f"[yellow]📦 Moving backup out of skills directory: {child} -> {destination}[/yellow]")
            shutil.move(str(child), str(destination))

    def _get_manifest_path(self, base_dir: Optional[Path] = None) -> Path:
        return (base_dir or self.source_dir) / INSTALL_MANIFEST_PATH

    def _get_canonical_source_checkout(self) -> Optional[Path]:
        if (self.source_dir / ".git").exists():
            return self.source_dir

        manifest_path = self._get_manifest_path()
        if not manifest_path.exists():
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

        source_checkout = manifest.get("source_checkout")
        if not source_checkout:
            return None

        checkout_path = Path(source_checkout).expanduser()
        return checkout_path if checkout_path.exists() else None

    def _write_install_manifest(self, target: str, skills_dir: Path):
        manifest_path = self._get_manifest_path(skills_dir)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "skill_name": SKILL_NAME,
            "version": VERSION,
            "target": target,
            "source_checkout": str(self._get_canonical_source_checkout() or self.source_dir),
            "repository_url": self._get_repository_url(),
            "installed_from": str(self.source_dir),
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def install_files(self) -> bool:
        if not self.install_targets:
            self.choose_install_targets()

        target_label = " and ".join("Claude Code" if target == "claude" else "Codex" for target in self.install_targets)
        self.console.print(f"\n[bold cyan]🚀 Installing to {target_label}...[/bold cyan]")

        self.installed_files = []
        for target in self.install_targets:
            if target == "claude":
                self._install_claude_files()
            elif target == "codex":
                self._install_codex_files()

        return True

    def _install_claude_files(self):
        skills_dir = self.claude_path["global_skills"]
        agents_dir = self.claude_path["global_agents"]

        self._cleanup_sibling_backups(skills_dir)
        skills_dir.mkdir(parents=True, exist_ok=True)
        agents_dir.mkdir(parents=True, exist_ok=True)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console,
        ) as progress:
            files_to_copy = [
                ("SKILL.md", skills_dir / "SKILL.md"),
                ("README.md", skills_dir / "README.md"),
                ("INSTALL.md", skills_dir / "INSTALL.md"),
                ("ROADMAP.md", skills_dir / "ROADMAP.md"),
                ("LICENSE", skills_dir / "LICENSE"),
                ("install.py", skills_dir / "install.py"),
                ("assets", skills_dir / "assets"),
                ("docs", skills_dir / "docs"),
                (".moregan", skills_dir / ".moregan"),
                ("personas", skills_dir / "personas"),
                ("moregan", skills_dir / "moregan"),
                *[(f"personas/{source}", agents_dir / dest) for source, dest in CLAUDE_PERSONAS.items()],
            ]

            task = progress.add_task("[green]Installing files...", total=len(files_to_copy))

            for source, dest in files_to_copy:
                self._copy_path(self.source_dir / source, dest)
                self.installed_files.append(dest)
                progress.update(task, advance=1)

        self._update_skill_registry()
        self._write_install_manifest("claude", skills_dir)

    def _install_codex_files(self):
        skills_dir = self.codex_path["global_skills"]
        self._cleanup_sibling_backups(skills_dir)
        skills_dir.mkdir(parents=True, exist_ok=True)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console,
        ) as progress:
            files_to_copy = [
                ("SKILL.md", skills_dir / "SKILL.md"),
                ("README.md", skills_dir / "README.md"),
                ("INSTALL.md", skills_dir / "INSTALL.md"),
                ("ROADMAP.md", skills_dir / "ROADMAP.md"),
                ("LICENSE", skills_dir / "LICENSE"),
                ("install.py", skills_dir / "install.py"),
                ("assets", skills_dir / "assets"),
                ("docs", skills_dir / "docs"),
                (".moregan", skills_dir / ".moregan"),
                ("personas", skills_dir / "personas"),
                ("moregan", skills_dir / "moregan"),
            ]

            task = progress.add_task("[green]Installing Codex skill files...", total=len(files_to_copy))

            for source, dest in files_to_copy:
                self._copy_path(self.source_dir / source, dest)
                self.installed_files.append(dest)
                progress.update(task, advance=1)

        self._write_install_manifest("codex", skills_dir)

    def _copy_path(self, source: Path, dest: Path):
        if source.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(source, dest)
            return

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)

    def _update_skill_registry(self):
        registry_file = self.claude_path["config"] / "skills.json"
        if registry_file.exists():
            with registry_file.open("r", encoding="utf-8") as handle:
                registry = json.load(handle)
        else:
            registry = {"skills": []}

        skill_entry = {
            "name": SKILL_NAME,
            "path": str(self.claude_path["global_skills"]),
            "version": VERSION,
            "description": "High-reliability engineering framework with adversarial evaluation",
        }

        registry["skills"] = [entry for entry in registry.get("skills", []) if entry.get("name") != SKILL_NAME]
        registry["skills"].append(skill_entry)

        with registry_file.open("w", encoding="utf-8") as handle:
            json.dump(registry, handle, indent=2)

    def show_installation_tree(self):
        tree = Tree("[bold green]📁 Installed Files[/bold green]")

        file_groups: Dict[str, List[str]] = {}
        for file_path in self.installed_files:
            file_groups.setdefault(str(file_path.parent), []).append(file_path.name)

        for directory, files in file_groups.items():
            branch = tree.add(f"[cyan]{directory}[/cyan]")
            for file_name in files:
                if file_name.endswith(".md"):
                    branch.add(f"[green]📄 {file_name}[/green]")
                elif file_name.endswith(".yaml"):
                    branch.add(f"[yellow]⚙️ {file_name}[/yellow]")
                else:
                    branch.add(f"[blue]📁 {file_name}[/blue]")

        self.console.print(tree)

    def show_usage_instructions(self):
        usage_lines = []
        if "claude" in self.install_targets:
            usage_lines.append('Claude Code: [yellow]/moregan "Your feature request"[/yellow]')
        if "codex" in self.install_targets:
            usage_lines.append(f"Codex: ask Codex to use the [yellow]{BRAND_NAME}[/yellow] skill, for example:")
            usage_lines.append("   [yellow]Use MoreGAN to add user authentication with JWT[/yellow]")

        instructions = Panel(
            "[bold green]✅ Installation Complete![/bold green]\n\n"
            f"[bold cyan]To use {BRAND_NAME}:[/bold cyan]\n\n"
            + "\n".join(usage_lines)
            + "\n\n"
            + "[bold cyan]Executable runtime preview:[/bold cyan]\n"
            + '   [yellow]moregan run "Your engineering request"[/yellow]\n'
            + "   [yellow]moregan inspect latest[/yellow]\n\n"
            + "[bold cyan]Terminal maintenance:[/bold cyan]\n"
            + "   [yellow]moregan setup update[/yellow]\n"
            + "   [yellow]moregan setup doctor --check[/yellow]\n\n"
            + "[bold cyan]Maintenance in Claude/Codex:[/bold cyan]\n"
            + "   [yellow]/moregan update[/yellow]\n"
            + "   [yellow]/moregan doctor[/yellow]\n"
            + "   [yellow]Use MoreGAN to update[/yellow]\n"
            + "   [yellow]Use MoreGAN to run doctor[/yellow]\n\n"
            + "[bold cyan]The framework will:[/bold cyan]\n"
            + "• Create a structured plan\n"
            + "• Review architecture before coding\n"
            + "• Generate implementation\n"
            + "• Run parallel security & functional evaluation\n"
            + "• Learn from any failures\n"
            + "• Auto-generate documentation",
            border_style="green",
            box=box.DOUBLE,
            title="[bold]🎉 Success![/bold]",
            title_align="center",
        )
        self.console.print(instructions)

    def uninstall(self) -> bool:
        self.console.print(f"[bold red]🗑️  Uninstalling {BRAND_NAME}...[/bold red]")

        if not self.install_targets:
            self.resolve_targets(prefer_installed=True)

        if "claude" in self.install_targets:
            skills_dir = self.claude_path["global_skills"]
            agents_dir = self.claude_path["global_agents"]

            for persona_name in CLAUDE_PERSONAS.values():
                persona_path = agents_dir / persona_name
                if persona_path.exists():
                    persona_path.unlink()
                    self.console.print(f"[red]Removed {persona_name}[/red]")

            if skills_dir.exists():
                shutil.rmtree(skills_dir)
                self.console.print(f"[red]Removed {skills_dir}[/red]")

            registry_file = self.claude_path["config"] / "skills.json"
            if registry_file.exists():
                with registry_file.open("r", encoding="utf-8") as handle:
                    registry = json.load(handle)
                registry["skills"] = [entry for entry in registry.get("skills", []) if entry.get("name") != SKILL_NAME]
                with registry_file.open("w", encoding="utf-8") as handle:
                    json.dump(registry, handle, indent=2)

        if "codex" in self.install_targets:
            skills_dir = self.codex_path["global_skills"]
            if skills_dir.exists():
                shutil.rmtree(skills_dir)
                self.console.print(f"[red]Removed {skills_dir}[/red]")

        self.console.print("[green]✅ Uninstallation complete![/green]")
        return True

    def doctor(self, apply_fixes: bool = True) -> bool:
        self.console.print(f"[bold cyan]🩺 Running {BRAND_NAME} doctor...[/bold cyan]")
        issues = self._collect_doctor_issues()

        if not issues:
            self.console.print("[green]✅ Installation looks healthy.[/green]")
            return True

        for issue in issues:
            self.console.print(f"[yellow]• {issue.category}: {issue.detail} ({issue.path})[/yellow]")

        if not apply_fixes:
            self.console.print("[yellow]Dry run only. No changes were applied.[/yellow]")
            return False

        if not self.install_targets:
            self.resolve_targets(prefer_installed=True)

        for issue in issues:
            self._apply_doctor_issue(issue)

        repair_targets = [target for target in self.install_targets if self.is_installed(target)]
        if repair_targets:
            self.install_targets = repair_targets
            self.console.print("[cyan]Reinstalling canonical files to repair the installation...[/cyan]")
            self.install_files()

        self.console.print("[green]✅ Doctor completed repairs.[/green]")
        return True

    def _collect_doctor_issues(self) -> List[DoctorIssue]:
        issues: List[DoctorIssue] = []
        issues.extend(self._find_duplicate_skill_dirs(self.home / ".claude" / "skills"))
        issues.extend(self._find_duplicate_skill_dirs(self.home / ".codex" / "skills"))
        issues.extend(self._find_missing_installation_files())
        issues.extend(self._find_stale_personas())
        issues.extend(self._find_registry_duplicates())
        return issues

    def _find_duplicate_skill_dirs(self, parent: Path) -> List[DoctorIssue]:
        if not parent.exists():
            return []

        issues = []
        for child in parent.iterdir():
            if not child.is_dir() or not self._is_auto_repair_duplicate_name(child.name):
                continue
            issues.append(
                DoctorIssue(
                    category="duplicate_installation",
                    path=child,
                    detail="duplicate MoreGAN installation directory detected",
                    action="remove_tree",
                )
            )
        return issues

    def _is_auto_repair_duplicate_name(self, name: str) -> bool:
        if name == SKILL_NAME:
            return False
        duplicate_markers = [
            ".backup.",
            ".bak",
            "-backup",
            "_backup",
            " copy",
            "-copy",
            "_copy",
            "(copy)",
        ]
        return name.startswith(SKILL_NAME) and any(marker in name for marker in duplicate_markers)

    def _find_missing_installation_files(self) -> List[DoctorIssue]:
        issues = []
        if self.claude_path["global_skills"].exists():
            for name in CLAUDE_REQUIRED_FILES:
                path = self.claude_path["global_skills"] / name
                if not path.exists():
                    issues.append(
                        DoctorIssue(
                            category="missing_file",
                            path=path,
                            detail=f"missing Claude installation file: {name}",
                            action="reinstall_claude",
                        )
                    )
        if self.codex_path["global_skills"].exists():
            for name in CODEX_REQUIRED_FILES:
                path = self.codex_path["global_skills"] / name
                if not path.exists():
                    issues.append(
                        DoctorIssue(
                            category="missing_file",
                            path=path,
                            detail=f"missing Codex installation file: {name}",
                            action="reinstall_codex",
                        )
                    )
        return issues

    def _find_stale_personas(self) -> List[DoctorIssue]:
        agents_dir = self.claude_path["global_agents"]
        if not agents_dir.exists():
            return []

        issues = []
        for persona_name in CLAUDE_PERSONAS.values():
            persona_path = agents_dir / persona_name
            if persona_path.exists() and not self.claude_path["global_skills"].exists():
                issues.append(
                    DoctorIssue(
                        category="orphaned_persona",
                        path=persona_path,
                        detail=f"persona file exists without installed Claude skill: {persona_name}",
                        action="remove_file",
                    )
                )
        return issues

    def _find_registry_duplicates(self) -> List[DoctorIssue]:
        registry_file = self.claude_path["config"] / "skills.json"
        if not registry_file.exists():
            return []

        with registry_file.open("r", encoding="utf-8") as handle:
            registry = json.load(handle)
        entries = [entry for entry in registry.get("skills", []) if entry.get("name") == SKILL_NAME]
        if len(entries) <= 1:
            return []
        return [
            DoctorIssue(
                category="registry_duplicate",
                path=registry_file,
                detail=f"skills.json contains {len(entries)} MoreGAN entries",
                action="dedupe_registry",
            )
        ]

    def _apply_doctor_issue(self, issue: DoctorIssue):
        if issue.action == "remove_tree" and issue.path.exists():
            shutil.rmtree(issue.path)
            return
        if issue.action == "remove_file" and issue.path.exists():
            issue.path.unlink()
            return
        if issue.action == "dedupe_registry":
            self._update_skill_registry()
            return
        if issue.action == "reinstall_claude" and "claude" not in self.install_targets:
            self.install_targets.append("claude")
            return
        if issue.action == "reinstall_codex" and "codex" not in self.install_targets:
            self.install_targets.append("codex")

    def update_installation(self, force: bool = False, target_ref: str = "main") -> bool:
        self.console.print(f"[bold cyan]⬆️  Updating {BRAND_NAME} from GitHub...[/bold cyan]")
        self.resolve_targets(prefer_installed=True)
        if not self.install_targets:
            self.console.print("[yellow]No existing installation found. Running a fresh install instead.[/yellow]")
            self.choose_install_targets()

        for target in self.install_targets:
            if target == "claude":
                self.create_backup(self.claude_path["global_skills"])
            elif target == "codex":
                self.create_backup(self.codex_path["global_skills"])

        with tempfile.TemporaryDirectory() as temp_dir:
            downloaded_source = self._download_update_source(target_ref=target_ref, destination_root=Path(temp_dir))
            updater = MoreGANInstaller(source_dir=downloaded_source, home=self.home, console=self.console)
            updater.install_targets = list(self.install_targets)
            updater.install_files()

        self.console.print("[green]✅ Update complete.[/green]")
        return True

    def _download_update_source(self, target_ref: str, destination_root: Path) -> Path:
        repository_url = self._get_repository_url()
        archive_url = f"{repository_url}/archive/{target_ref}.zip"
        self.console.print(f"[cyan]Downloading update archive from {archive_url}[/cyan]")

        destination_root.mkdir(parents=True, exist_ok=True)
        with urlopen(archive_url) as response:
            payload = response.read()

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(destination_root)

        extracted_dirs = [path for path in destination_root.iterdir() if path.is_dir()]
        if len(extracted_dirs) != 1:
            raise RuntimeError("Unexpected update archive layout.")
        return extracted_dirs[0]

    def _git_output(self, command: Sequence[str]) -> str:
        result = subprocess.run(
            command,
            cwd=self.source_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def interactive_install(self):
        self.show_banner()
        self.show_environment_status()
        self.choose_install_targets()

        already_installed = any(self.is_installed(target) for target in self.install_targets)
        if already_installed:
            self.console.print(f"[yellow]⚠️  {SKILL_NAME} is already installed[/yellow]")
            action = self._select_option(
                "What would you like to do?",
                [
                    ("reinstall", "Reinstall", "Replace installed files from this checkout"),
                    ("uninstall", "Uninstall", "Remove the installed MoreGAN"),
                    ("cancel", "Cancel", "Exit without changing the installation"),
                ],
                default="cancel",
            )

            if action == "cancel":
                self.console.print("[yellow]Installation cancelled.[/yellow]")
                return
            if action == "uninstall":
                self.uninstall()
                return
            if action == "reinstall":
                for target in self.install_targets:
                    if target == "claude":
                        self.create_backup(self.claude_path["global_skills"])
                    elif target == "codex":
                        self.create_backup(self.codex_path["global_skills"])

        self.show_features()
        if not self._confirm_with_select("[bold cyan]Proceed with installation?[/bold cyan]", default=True):
            self.console.print("[yellow]Installation cancelled.[/yellow]")
            return

        if self.install_files():
            self.console.print("\n[bold green]✨ Installation successful![/bold green]")
            self.show_installation_tree()
            self.show_usage_instructions()
            return

        self.console.print("[bold red]❌ Installation failed![/bold red]")
        sys.exit(1)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and maintain MoreGAN.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["install", "uninstall", "update", "doctor"],
        default="install",
        help="command to run",
    )
    parser.add_argument(
        "--target",
        choices=["claude", "codex", "both"],
        help="install target override",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow updater to proceed with a dirty checkout or non-main branch",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="for doctor, report issues without applying fixes",
    )
    parser.add_argument(
        "--ref",
        default="main",
        help="git ref used by update (default: main)",
    )
    return parser.parse_args(argv)


def normalize_targets(target: Optional[str]) -> Optional[List[str]]:
    if not target:
        return None
    if target == "both":
        return ["claude", "codex"]
    return [target]


def main(argv: Optional[Sequence[str]] = None):
    args = parse_args(argv)
    installer = MoreGANInstaller()

    try:
        explicit_targets = normalize_targets(args.target)
        if args.command == "install":
            if explicit_targets:
                installer.show_banner()
                installer.show_environment_status()
                installer.resolve_targets(explicit_targets=explicit_targets)
                installer.show_features()
                if installer._confirm_with_select("[bold cyan]Proceed with installation?[/bold cyan]", default=True):
                    installer.install_files()
                    installer.console.print("\n[bold green]✨ Installation successful![/bold green]")
                    installer.show_installation_tree()
                    installer.show_usage_instructions()
                else:
                    installer.console.print("[yellow]Installation cancelled.[/yellow]")
            else:
                installer.interactive_install()
            return

        installer.resolve_targets(explicit_targets=explicit_targets, prefer_installed=True)

        if args.command == "uninstall":
            installer.uninstall()
        elif args.command == "doctor":
            installer.doctor(apply_fixes=not args.check)
        elif args.command == "update":
            installer.update_installation(force=args.force, target_ref=args.ref)
    except KeyboardInterrupt:
        installer.console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        sys.exit(0)
    except Exception as exc:
        installer.console.print(f"\n[bold red]❌ Error: {exc}[/bold red]")
        sys.exit(1)


def install_main():
    main(["install"])


def update_main():
    main(["update"])


def doctor_main():
    main(["doctor"])


if __name__ == "__main__":
    main()
