# 🚀 hooliGAN-harness Installation Guide

## Quick Start

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
- `~/.claude/skills/hooliGAN-harness/`
  - `SKILL.md` - Main skill definition
  - `README.md` - Documentation
  - `.harness/` - Configuration and knowledge base
    - `knowledge/` - Failure patterns, retrospectives, and confidence scoring
    - `evolution/` - Cross-session learning patterns
    - `rollback/` - Rollback strategies
    - `collaboration/` - Multi-generator configuration
    - `integrations/` - External tool integrations
    - `documentation/` - Living documentation config

### Agent Personas
- `~/.claude/agents/`
  - `harness-planner.md` - Plans tasks and creates YAML roadmaps
  - `harness-architect.md` - Reviews plans for architectural impacts
  - `harness-designer.md` - Reviews UI/UX plans and accessibility
  - `harness-generator.md` - Implements code following best practices
  - `harness-evaluator.md` - Adversarial functional evaluation
  - `harness-security-evaluator.md` - Parallel security scanning
  - `harness-code-reviewer.md` - Reviews changed code for quality and correctness
  - `harness-production-readiness-reviewer.md` - Reviews deployability, rollback, observability, and operational safety
  - `harness-mr-readiness-analyzer.md` - Scores local branch readiness before MR creation
  - `harness-learning-curator.md` - Captures evidence-backed lessons for future harness work

### Codex Installation
- `~/.codex/skills/hooliGAN-harness/`
  - `SKILL.md` - Main skill definition
  - `README.md` - Documentation
  - `INSTALL.md` - Installation guide
  - `personas/` - Persona instructions used by the skill
  - `.harness/` - Configuration and knowledge base

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
- **uv**: Required for Python package management
- **Claude Code or Codex**: At least one supported environment must be installed (`~/.claude/` or `~/.codex/` must exist)
- **Dependencies**: Synced from `pyproject.toml` by uv
  - `rich` - Beautiful terminal UI

## Usage

After installation, use the harness in your coding agent session.

Claude Code:

```bash
/harness "Add user authentication with JWT and rate limiting"
/harness update
/harness doctor
```

Codex:

```text
Use hooliGAN-harness to add user authentication with JWT and rate limiting
Use hooliGAN-harness to update
Use hooliGAN-harness to run doctor
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

## Advanced Configuration

### Enable Multi-Generator Mode
Edit `.harness/collaboration/multi-generator.yaml`:
```yaml
multi_generator_configuration:
  enabled: true  # Set to true
  max_parallel_generators: 3
```

### Configure External Integrations
Edit `.harness/integrations/external-tools.yaml` to enable:
- CI/CD pipelines (GitHub Actions, Jenkins, GitLab CI)
- Monitoring (Datadog, Sentry, Prometheus)
- Security scanning (Snyk, SonarQube, Veracode)
- Documentation (Confluence, Notion, Docusaurus)

### Adjust Confidence Thresholds
Edit `.harness/knowledge/confidence-scoring.yaml` to customize validation levels.

## Maintenance

Run maintenance through the installed skill, not through the setup wrapper.

Claude Code:

```bash
/harness update
/harness doctor
```

Codex:

```text
Use hooliGAN-harness to update
Use hooliGAN-harness to run doctor
```

`update` downloads the latest `hooligan-harness` archive from GitHub over HTTPS for the requested ref, then reinstalls the skill. `doctor` removes duplicate backup/copy installs, fixes Claude registry duplication, removes orphaned persona files, and repairs missing installed files.

## Uninstallation

To remove hooliGAN-harness:

```bash
uv run python install.py uninstall
```

Or manually remove:
- `~/.claude/skills/hooliGAN-harness/`
- Agent files from `~/.claude/agents/harness-*.md`
- `~/.codex/skills/hooliGAN-harness/`

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

- **Repository**: https://github.com/suyesh/hooligan-harness
- **Issues**: https://github.com/suyesh/hooligan-harness/issues
- **Documentation**: See README.md for framework details

## License

MIT License - See LICENSE file for details
