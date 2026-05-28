# Harness Engineering: hooliGAN-harness v1.4.0

**Stop guessing if your agent’s code works. Force it to survive the loop.**

Inspired by the adversarial tension of GAN architectures, `hooliGAN-harness` is a high-reliability engineering framework for Claude Code and Codex. It replaces fragile "one-shot" generation with a zero-trust pipeline featuring architectural review, parallel security evaluation, confidence-based validation, automatic rollback, cross-session learning, multi-generator collaboration, and enterprise integrations — ensuring enterprise-grade code quality.

---

## 🎯 Zero Configuration Required!

**hooliGAN-harness works perfectly out-of-the-box with optimal defaults:**
- ✅ All intelligence features enabled (learning, patterns, confidence scoring)
- ✅ All safety features active (snapshots, rollback, security scanning)
- ✅ Multi-generator mode ready (parallel specialists)
- ✅ Living documentation automatic
- ✅ Python dependencies are managed through uv

Just install and use - that's it!

---

## 🚀 Quick Installation

### Automatic Installation (Recommended)

```bash
# Clone the repository
git clone https://github.com/aditikilledar/hooligan-harness.git
cd hooligan-harness

# Run the installer (macOS/Linux)
./setup.sh

# Or for Windows
setup.bat
```

The beautiful CLI installer will:
- Auto-detect Claude Code and Codex installations
- Let you choose where to install (Claude, Codex, or both)
- Sync Python dependencies with uv from `pyproject.toml`
- Set up all personas and configurations
- Provide usage instructions

---

## 🧬 The GAN Inspiration

In a Generative Adversarial Network (GAN), a Generator creates data and a Discriminator tries to catch the "fake."

We apply this to software engineering:

1. **The Generator** attempts to satisfy the feature requirements
2. **The Evaluator** assumes the code is buggy until proven otherwise
3. **The Security Evaluator** hunts for vulnerabilities in parallel
4. **The Architect** reviews designs before implementation begins
5. **The Code Reviewer** reviews the changed code like a senior teammate
6. **The Production Readiness Reviewer** checks whether the change can safely run in production
7. **The MR Readiness Analyzer** checks whether the submission is ready for human review

This competitive loop continues until the output is indistinguishable from senior-level production code.

---

## 🎭 The Nine Personas

| Persona | Role | Responsibility |
|---------|------|----------------|
| **Planner** | 📋 Architect | Translates human intent into rigid YAML roadmaps with quantifiable Acceptance Criteria |
| **Architect** | 🏗️ Reviewer | Reviews plans for system-wide impacts and suggests design patterns before coding |
| **Designer** | 🎨 UI/UX Expert | Creates design specifications, ensures accessibility, and defines user interactions |
| **Generator** | 💻 Builder | Implements using SOLID principles, defensive programming, and pattern awareness |
| **Evaluator** | 🔍 Gatekeeper | Zero-trust verification with professional disdain for lazy code |
| **Security Evaluator** | 🛡️ Guardian | Parallel OWASP Top 10 scanning and vulnerability detection |
| **Code Reviewer** | 🧾 Reviewer | Reviews the changed code for correctness, maintainability, test quality, and team conventions |
| **Production Readiness Reviewer** | 🚦 Reviewer | Reviews deployability, rollback, observability, configuration, data safety, performance risk, and operational failure modes |
| **MR Readiness Analyzer** | 📊 Reviewer | Scores local branch readiness using commit story, diff scope, self-review signals, and validation evidence |

Every feature task runs Planner, Architect, Generator, Evaluator, Security Evaluator, Code Reviewer, Production Readiness Reviewer, and MR Readiness Analyzer. Designer is conditional: the agent records whether it is needed and runs it for UI, UX, accessibility, interaction, visual design, layout, or design-system work. Final task output always includes the MR readiness result.

### Mandatory Execution Contract

For feature work, these personas are required and blocking:

1. **Planner** creates the task plan and acceptance criteria.
2. **Architect** approves the approach before implementation.
3. **Generator** implements and verifies locally.
4. **Evaluator** checks acceptance criteria and test quality.
5. **Security Evaluator** checks security risks.
6. **Code Reviewer** checks correctness, maintainability, and team conventions.
7. **Production Readiness Reviewer** checks deployability, rollback, observability, configuration, data safety, performance risk, and operational failure modes.
8. **MR Readiness Analyzer** produces the final local-git readiness score.

If Evaluator, Security Evaluator, Code Reviewer, or Production Readiness Reviewer returns `FAIL`, the harness must remediate and rerun the failed gate until it passes. MR Readiness is always shown at the end; a low score gives cleanup actions before requesting human review.

Designer is the only conditional persona. The agent must explicitly record either `Designer: needed` or `Designer: not needed` for every feature task.

Final persona output uses colored status markers:

```text
Persona Execution:
- 🟢 Planner: PASS
- 🟢 Architect: PASS
- ⚪ Designer: Not needed - no frontend/UX surface changed
- 🟢 Generator: PASS
- 🟢 Evaluator: PASS
- 🟢 Security Evaluator: PASS
- 🟢 Code Reviewer: PASS
- 🟢 Production Readiness Reviewer: PASS
- 🔴 MR Readiness Analyzer: 20/100 - Not ready
```

---

## ✨ Key Features

### 🧠 **Intelligence Layer** (v1.1.0)
- **Failure Pattern Memory**: Learns from past failures to prevent recurrence
- **Confidence Scoring**: Adapts validation rigor (0-100% confidence)
- **Pattern Recognition**: Auto-injects tests for known failure patterns

### 🛡️ **Reliability Layer** (v1.2.0)
- **Architectural Review**: Pre-implementation design validation
- **Automatic Rollback**: Snapshots and recovery on critical failures
- **Cross-Session Learning**: Pattern library that evolves over time
- **Incident Reporting**: Detailed failure analysis and prevention

### 🚀 **Scale Layer** (v1.3.0)
- **Multi-Generator Mode**: Frontend, backend, database specialists in parallel
- **Enterprise Integrations**: GitHub Actions, Jenkins, SonarQube, Datadog
- **Living Documentation**: Auto-generated API specs, diagrams, changelogs

---

## 📦 What Gets Installed

Claude Code:

```
~/.claude/
├── skills/
│   └── hooliGAN-harness/
│       ├── SKILL.md                    # Main skill definition
│       ├── README.md                   # This file
│       ├── install.py                  # Maintenance commands
│       └── .harness/
│           ├── knowledge/              # Failure patterns & confidence scoring
│           ├── evolution/              # Cross-session learning patterns
│           ├── rollback/               # Automatic rollback strategies
│           ├── collaboration/          # Multi-generator configuration
│           ├── integrations/           # External tool configs
│           └── documentation/          # Living docs generation
└── agents/
    ├── harness-planner.md             # Task planning persona
    ├── harness-architect.md           # Design review persona
    ├── harness-designer.md            # Conditional UI/UX design persona
    ├── harness-generator.md           # Code implementation persona
    ├── harness-evaluator.md           # Functional evaluation persona
    ├── harness-security-evaluator.md  # Security scanning persona
    ├── harness-code-reviewer.md       # Changed-code review persona
    ├── harness-production-readiness-reviewer.md # Production safety review persona
    └── harness-mr-readiness-analyzer.md # MR readiness scoring persona
```

Codex:

```
~/.codex/
└── skills/
    └── hooliGAN-harness/
        ├── SKILL.md                    # Main skill definition
        ├── README.md                   # This file
        ├── install.py                  # Maintenance commands
        ├── personas/                   # Persona instructions loaded by the skill
        └── .harness/                   # Configuration and knowledge base
```

---

## 💻 Usage

Once installed, trigger the harness in your coding agent session - **no configuration needed!**

### Claude Code
```bash
/harness "Add user authentication with JWT"
```

Maintenance shortcuts:

```bash
/harness update
/harness doctor
```

### Codex
Ask Codex to use the installed skill by name:

```text
Use hooliGAN-harness to add user authentication with JWT
```

Maintenance requests:

```text
Use hooliGAN-harness to update
Use hooliGAN-harness to run doctor
```

### Complex Features
```text
Use hooliGAN-harness to build a REST API with rate limiting, caching, and OpenAPI documentation
```

### With Specific Requirements
```text
Use hooliGAN-harness to refactor the payment system to use the Repository pattern with 95% test coverage
```

### Installer Maintenance
After installation, maintenance is exposed through the skill itself:

```bash
/harness update
/harness doctor
```

```text
Use hooliGAN-harness to update
Use hooliGAN-harness to run doctor
```

`update` downloads the latest harness archive from GitHub over HTTPS for the requested ref, then reinstalls the harness to existing targets. `doctor` scans for duplicate skill directories, stale Claude persona files, duplicate Claude registry entries, and missing installed files, then repairs them.

---

## 🔄 The Workflow

```mermaid
graph LR
    A[User Request] --> B[Planner]
    B --> C[Architect]
    C --> D{Designer Needed?}
    D -->|Yes| E[Designer]
    D -->|No| F[Record Designer Decision]
    E --> G[Generator]
    F --> G
    G --> H[Evaluator + Security Evaluator + Code Reviewer]
    H --> I[Production Readiness Reviewer]
    I --> J[MR Readiness Analyzer]
    J --> K{Pass?}
    K -->|No| L[Rollback & Learn]
    L --> G
    K -->|Yes| M[Show MR Readiness & Complete]
```

### Detailed Flow:

1. **Planning Phase**
   - Planner creates YAML roadmap with measurable acceptance criteria
   - Initializes progress tracking in `.harness/progress.md`

2. **Architectural Review**
   - Architect runs on every feature task before implementation
   - Identifies patterns from `.harness/evolution/patterns.yaml`
   - Defines rollback strategy

3. **Designer Decision**
   - The agent records whether Designer is needed
   - Designer runs for UI, UX, accessibility, interaction, visual design, layout, or design-system work
   - Non-design tasks record the rationale and continue

4. **Implementation Phase**
   - Generator creates snapshot for rollback
   - Applies learned patterns and avoids known failures
   - Implements with SOLID, DRY, KISS principles

5. **Parallel Evaluation**
   - Functional Evaluator checks all acceptance criteria
   - Security Evaluator scans for vulnerabilities
   - Code Reviewer reviews the changed code
   - Production Readiness Reviewer checks deployability, rollback, observability, configuration, data safety, performance risk, and operational failure modes
   - Functional, security, code review, and production readiness gates must PASS for task completion

6. **MR Readiness and Final Output**
   - MR Readiness Analyzer scores local branch readiness using local git only
   - Final output shows the MR readiness result and persona execution summary

7. **Learning & Documentation**
   - Updates failure patterns and confidence scores
   - Evolves successful patterns for reuse
   - Auto-generates API docs, diagrams, changelogs

---

## ⚙️ Configuration

### Enable Multi-Generator Mode
```yaml
# .harness/collaboration/multi-generator.yaml
multi_generator_configuration:
  enabled: true
  max_parallel_generators: 3
```

### Configure Confidence Levels
```yaml
# .harness/knowledge/confidence-scoring.yaml
confidence_levels:
  exploration: [0, 40]    # High validation
  development: [40, 70]   # Standard validation
  production: [70, 90]    # Streamlined validation
  verified: [90, 100]     # Minimal validation
```

### Set Up Enterprise Integrations
```yaml
# .harness/integrations/external-tools.yaml
integrations:
  ci_cd:
    github_actions:
      enabled: true
  monitoring:
    datadog:
      enabled: true
  security:
    sonarqube:
      enabled: true
```

---

## 📊 Metrics & Learning

The framework tracks:
- **Pattern Effectiveness**: Success rates of discovered patterns
- **Failure Prevention**: Reduction in recurring failures
- **Confidence Evolution**: Improvement in prediction accuracy
- **Collaboration Efficiency**: Multi-generator coordination metrics

---

## 🔧 Advanced Features

### Automatic Rollback Triggers
- Performance regression >20%
- Test coverage drop below 80%
- Security vulnerability detected
- Build failure after 2 attempts

### Pattern Evolution Stages
1. **Experimental** (3+ uses, 60% success)
2. **Proven** (10+ uses, 75% success)  
3. **Standard** (25+ uses, 85% success)
4. **Deprecated** (<50% success after 20 uses)

### Living Documentation Types
- OpenAPI specifications
- Mermaid architecture diagrams
- PlantUML state machines
- Architecture Decision Records (ADRs)
- Automated changelogs

---

## 🤝 Compatibility

- **Claude Code**: Full support with all features
- **Codex**: Full skill support with persona files bundled inside the skill
- **Python**: 3.8 or higher required
- **uv**: Required for Python package management
- **Platforms**: macOS, Linux, Windows

---

## 📚 Documentation

- **[Installation Guide](INSTALL.md)** - Detailed setup instructions
- **[Skill Documentation](SKILL.md)** - Technical skill reference
- **[Architecture](Architecture.jpg)** - Visual system overview

---

## 🏆 Why hooliGAN-harness?

1. **Zero-Trust Verification**: Every line of code is scrutinized
2. **Learning System**: Gets smarter with each use
3. **Enterprise Ready**: Integrates with your existing tools
4. **Parallel Execution**: Multiple specialists work simultaneously
5. **Self-Documenting**: Maintains its own documentation
6. **Failure Recovery**: Automatic rollback keeps you safe
7. **Production Quality**: Code that’s ready to ship

---

## 📈 Version History

- **v1.0.0**: Initial adversarial loop (Planner, Generator, Evaluator)
- **v1.1.0**: Added Security Evaluator, failure memory, confidence scoring
- **v1.2.0**: Added Architect, rollback mechanisms, cross-session learning
- **v1.3.0**: Added multi-generator mode, enterprise integrations, living docs
- **v1.3.1**: Added Codex skill installation support
- **v1.4.0**: Added Code Reviewer, Production Readiness Reviewer, and local-git MR Readiness Analyzer personas

---

## 🙏 Acknowledgments

Inspired by research from Anthropic, OpenAI, and the broader AI engineering community. Special thanks to the GAN architecture for showing us that adversarial training produces superior results.

---

## 📝 License

MIT License - See [LICENSE](LICENSE) file for details

---

## 🔗 References

* [Anthropic: Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
* [Anthropic: Managed Agents & Multi-Agent Orchestration](https://www.anthropic.com/engineering/managed-agents)
* [Anthropic: Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
* [GitHub Harness Framework Repo by celesteanders](https://github.com/celesteanders/harness)
* [Paper: GAN-inspired Multi-Agent Harnesses](https://medium.com/@gwrx2005/gan-inspired-multi-agent-harnesses-for-long-running-autonomous-software-engineering-architecture-37a8c2d59b6b)
