# MoreGAN Installation Guide

## Quick Start

### PyPI
```bash
python3 -m pip install moregan
moregan setup
```

`moregan setup` runs the same installer flow as `./setup.sh`. It installs the MoreGAN skill into Claude Code, Codex, or both.

Target a specific agent:
```bash
moregan setup --target codex
moregan setup --target claude
moregan setup --target both
```

### macOS / Linux
```bash
./setup.sh
```

### Windows
```batch
setup.bat
```

### Manual Installation with uv
```bash
# Sync dependencies from pyproject.toml
uv sync

# Run installer
uv run python install.py
```

## What Gets Installed

The installer auto-detects Claude Code and Codex. If both are present, it asks whether to install to Claude, Codex, or both.

### Claude Code Installation
- `~/.claude/skills/moregan/`
  - `SKILL.md` - Main skill definition
  - `README.md` - Documentation
  - `INSTALL.md` - Installation guide
  - `ROADMAP.md` - Product/runtime roadmap
  - `LICENSE` - License text
  - `assets/` - Logo and documentation assets
  - `install.py` - Maintenance commands
  - `moregan/` - Executable runtime package
  - `.moregan/` - Configuration and knowledge base
    - `knowledge/` - Failure patterns, retrospectives, and confidence scoring
    - `evolution/` - Cross-session learning patterns
    - `rollback/` - Rollback strategies
    - `collaboration/` - Multi-generator configuration
    - `integrations/` - External tool integrations
    - `documentation/` - Living documentation config

### Agent Personas
- `~/.claude/agents/`
  - `moregan-planner.md` - Plans tasks and creates YAML roadmaps
  - `moregan-architect.md` - Reviews plans for architectural impacts
  - `moregan-designer.md` - Reviews UI/UX plans and accessibility
  - `moregan-generator.md` - Implements code following best practices
  - `moregan-evaluator.md` - Adversarial functional evaluation
  - `moregan-security-evaluator.md` - Parallel security scanning
  - `moregan-code-reviewer.md` - Reviews changed code for quality and correctness
  - `moregan-production-readiness-reviewer.md` - Reviews deployability, rollback, observability, and operational safety
  - `moregan-mr-readiness-analyzer.md` - Scores local branch readiness before MR creation
  - `moregan-learning-curator.md` - Captures evidence-backed lessons for future MoreGAN work

### Codex Installation
- `~/.codex/skills/moregan/`
  - `SKILL.md` - Main skill definition
  - `README.md` - Documentation
  - `INSTALL.md` - Installation guide
  - `ROADMAP.md` - Product/runtime roadmap
  - `LICENSE` - License text
  - `assets/` - Logo and documentation assets
  - `install.py` - Maintenance commands
  - `moregan/` - Executable runtime package
  - `personas/` - Persona instructions used by the skill
  - `.moregan/` - Configuration and knowledge base

## Features

### 🧠 Intelligence Layer
- **Failure Pattern Memory**: Learns from past failures to prevent recurrence
- **Confidence Scoring**: Adapts validation rigor (0-100% confidence)
- **Cross-Session Learning**: Discovers and refines patterns over time
- **Learning Curator**: Records retrospectives and promotes recurring lessons into future guardrails

### 🛡️ Reliability Layer
- **Architect Review**: Pre-implementation design validation
- **Automatic Rollback**: Snapshots and recovery on critical failures
- **Parallel Evaluation**: Security and functional checks run simultaneously

### 🚀 Scale Layer
- **Multi-Generator Mode**: Specialized generators work in parallel
- **Enterprise Integrations**: GitHub Actions, Jenkins, SonarQube, Datadog
- **Living Documentation**: Auto-generated API specs and diagrams

## System Requirements

- **Python**: 3.8 or higher
- **uv**: Optional, useful for source-checkout development
- **Claude Code or Codex**: At least one supported environment must be installed (`~/.claude/` or `~/.codex/` must exist)
- **Dependencies**: Installed by `pip` for PyPI installs, or synced from `pyproject.toml` by `uv` for source development
  - `rich` - Beautiful terminal UI

## Usage

After installation, use MoreGAN in your coding agent session.

Claude Code:

```bash
/moregan "Add user authentication with JWT and rate limiting"
/moregan update
/moregan doctor
```

Codex:

```text
Use MoreGAN to add user authentication with JWT and rate limiting
Use MoreGAN to update
Use MoreGAN to run doctor
```

The framework will:
1. Create a structured YAML plan
2. Run Architect before coding on every feature task
3. Decide whether Designer is needed, and run Designer for UI/UX/accessibility/design work
4. Generate implementation with tests
5. Run functional, security, changed-code, and production readiness evaluation
6. Score local branch readiness before MR creation and show the result in final output
7. Run Learning Curator to capture evidence-backed lessons after MR readiness
8. Learn from failures and successful patterns without over-promoting one-off observations
9. Auto-generate documentation

Executable runtime preview:

```bash
moregan init
moregan adapters codex
moregan adapters claude
moregan run "Add OAuth login"
moregan status
moregan inspect latest
moregan replay latest
```

`init` creates `.moregan/tools.yaml`, `.moregan/workers.yaml`, `.moregan/runs/`, and a `.gitignore` entry for local run traces. Existing config files are preserved unless `--force` is used.
The runtime writes auditable artifacts under `.moregan/runs/`, including `state.json`, `states.jsonl`, `tool_suggestions.json`, and structured stage files in `stages/*.json`.
It also writes compact context packs under `.moregan/runs/<run>/context/` so workers can read useful run context without receiving oversized inline prompts.
When a required deterministic check or routed worker fails after generation, the runtime can run bounded remediation attempts and writes `remediation.json` plus attempt-specific stage artifacts.
Repository-local deterministic checks are configured in `.moregan/tools.yaml`.
Worker stages are recorded as dry-run `SKIP` results until a provider command is configured in `.moregan/workers.yaml`.
Codex and Claude can read the installed skill instructions directly, but these executable runtime and maintenance commands need local Python 3.8+.
Provider-backed workers support `execution: auto`, `execution: isolated`, and `execution: repository`. In `auto`, no-write workers run in isolated snapshots by default, while write-enabled generator workers run in the repository checkout.
Provider-backed workers receive `MOREGAN_CONTEXT_PACK` and `MOREGAN_CONTEXT_TOKENS`; isolated workers get a copied pack inside their temporary snapshot.

Useful runtime flags:

```bash
moregan run "Fix checkout bug" --max-remediation-attempts 1
moregan run "Inspect current branch" --no-checks
```

Adapter templates:

```bash
moregan adapters codex --activate
moregan adapters claude --activate
```

`adapters` writes `.moregan/adapters/<provider>/` prompts and `.moregan/workers.<provider>.yaml`. With `--activate`, it also writes `.moregan/workers.yaml` unless that file already exists; use `--force` for intentional replacement. Set `MOREGAN_CODEX_COMMAND` or `MOREGAN_CLAUDE_COMMAND` to a provider command that reads the prompt from stdin and prints one `StageResult` JSON object.

PyPI trusted publishing:

- PyPI project name: `moregan`
- Workflow file: `.github/workflows/workflow.yml`
- PyPI workflow filename field: `workflow.yml`
- Recommended PyPI environment: `pypi`

## Advanced Configuration

### Enable Multi-Generator Mode
Edit `.moregan/collaboration/multi-generator.yaml`:
```yaml
multi_generator_configuration:
  enabled: true  # Set to true
  max_parallel_generators: 3
```

### Configure External Integrations
Edit `.moregan/integrations/external-tools.yaml` to enable:
- CI/CD pipelines (GitHub Actions, Jenkins, GitLab CI)
- Monitoring (Datadog, Sentry, Prometheus)
- Security scanning (Snyk, SonarQube, Veracode)
- Documentation (Confluence, Notion, Docusaurus)

### Adjust Confidence Thresholds
Edit `.moregan/knowledge/confidence-scoring.yaml` to customize validation levels.

## Maintenance

Terminal:

```bash
moregan setup update
moregan setup doctor --check
```

Run maintenance through the installed skill when you are inside Claude Code or Codex.

Claude Code:

```bash
/moregan update
/moregan doctor
```

Codex:

```text
Use MoreGAN to update
Use MoreGAN to run doctor
```

`update` downloads the latest `moregan` archive from GitHub over HTTPS for the requested ref, then reinstalls the skill. `doctor` removes duplicate backup/copy installs, fixes Claude registry duplication, removes orphaned persona files, and repairs missing installed files.

## Uninstallation

To remove MoreGAN:

```bash
uv run python install.py uninstall
```

Or manually remove:
- `~/.claude/skills/moregan/`
- Agent files from `~/.claude/agents/moregan-*.md`
- `~/.codex/skills/moregan/`

## Troubleshooting

### "No supported AI coding environment detected"
- Ensure Claude Code or Codex is installed
- Check that `~/.claude/` or `~/.codex/` exists

### "Permission denied" errors
- On macOS/Linux: `chmod +x setup.sh`
- Run with appropriate permissions

### "uv not found"
- The setup scripts attempt to install uv automatically
- Manual installation: https://github.com/astral-sh/uv

### "Python version too old"
- Upgrade to Python 3.8 or higher
- Check version: `python --version` or `python3 --version`

## Support

- **Repository**: https://github.com/suyesh/moregan
- **Issues**: https://github.com/suyesh/moregan/issues
- **Documentation**: See README.md for framework details

## License

MIT License - See LICENSE file for details
