---
name: harness
description: Implements a high-reliability "Harness Engineering" loop with multi-generator collaboration, enterprise tool integration, and living documentation for Claude Code and Codex. Trigger when a user wants to "implement a feature," "start the harness," "use hooliGAN-harness," or "build with verification."
version: 1.4.0
---
## Objective

To replace one-shot code generation with a structured, self-correcting agentic loop that ensures all code is planned in YAML, implemented via best practices of coding, and verified by adversarial evaluators, code review, security review, and MR readiness analysis with confidence-based validation levels and failure pattern learning before declared complete.

## Instructions

### Runtime Compatibility

This skill is portable across Claude Code and Codex.

* In Claude Code, the installer also places persona files in `~/.claude/agents/`.
* In Codex, persona files live inside this skill at `personas/*.md`; read the relevant persona file before performing that role.
* Codex should use its native plan, terminal, file-editing, subagent, and browser tools where available. Do not require Claude-specific slash commands or agent paths when running in Codex.
* Treat `.harness/` files as project-local working artifacts. If they do not exist in the target repository, create them from the skill defaults.
* The MR Readiness Analyzer is local-git-only. It must not use GitLab MCP tools, `glab`, or any external service.

### Maintenance Intents

If the request is a harness maintenance command rather than feature work, do **not** run the full planning / generator / evaluator loop.

Maintenance intents include:

* Claude Code: `/harness update`, `/harness doctor`
* Codex: `Use hooliGAN-harness to update`, `Use hooliGAN-harness to run doctor`, or equivalent wording

For these intents:

* Run the installed skill's `install.py` maintenance command directly when available.
* `update` should execute the installer update flow, which downloads the latest hooliGAN-harness archive from GitHub over HTTPS for the requested ref and reinstalls the skill.
* `doctor` should execute the installer doctor flow, which scans for duplicate or broken installations and repairs them.
* Only fall back to the feature-work phases below when the request is clearly about implementing or modifying application code.

### Mandatory Persona Execution

For every feature-work task, the harness must run these personas and record their results before declaring the task complete:

1. Planner
2. Architect
3. Generator
4. Evaluator
5. Security Evaluator
6. Code Reviewer
7. Production Readiness Reviewer
8. MR Readiness Analyzer

Designer is the only conditional persona. The agent must decide whether Designer is needed from the task type and record the decision. Run Designer when the task touches frontend UI, UX, visual design, interaction behavior, accessibility, layout, copy that affects user experience, or design-system concerns. Record `Designer: not needed` with a short rationale for non-frontend or non-UX tasks.

The final user-facing response for feature work must include a persona execution summary and the MR Readiness Analyzer result.

Format the persona execution summary with colored status markers:

* `🟢 PASS` for personas that completed successfully.
* `⚪ Not needed` for Designer when the task has no frontend, UX, accessibility, or design impact.
* `🟡 Warning` for advisory states, including MR readiness scores from 50 to 69.
* `🔴 FAIL` or `🔴 Not ready` for failed gates and MR readiness scores below 50.

Example:

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

### 1. Phase 0: Initialization

* Read the repository README.md to understand the environment.
* Create .harness/dev_init.md with instructions to run the development server for downstream agents.
* Load .harness/knowledge/failure-patterns.yaml to understand common failure patterns.
* Initialize confidence scoring based on task complexity and historical performance.

### 2. Phase 1: Planning (The Planner)

* Create a technical roadmap at .harness/[nickname].yaml.
* Define specific, quantifiable Acceptance Criteria (AC) for every task.
* Initialize an append-only log at .harness/progress.md to track all session activity.

### 2.5. Phase 1.5: Architectural Review (The Architect)

* Review plan for system-wide impacts and architectural concerns.
* Identify design patterns from .harness/evolution/patterns.yaml that apply.
* Assess risks and propose alternative approaches.
* Define rollback strategy based on task complexity.
* Must run and APPROVE before Generator can proceed for every feature-work task.

### 2.6. Phase 1.6: Design Decision and Optional Review (The Designer)

* Decide whether Designer is needed for the task and record the rationale.
* Create UI/UX specifications for frontend components.
* Define design tokens, spacing, typography, and color systems.
* Specify interaction patterns and user flows.
* Ensure accessibility standards (WCAG 2.1 AA).
* If Designer is needed, Designer must APPROVE design before Frontend Generator proceeds.
* If Designer is not needed, record `Designer: not needed` and continue to Generator.

### 3. Phase 2: Implementation (The Generator)

* Select Task: Identify the next pending task based on depends_on logic.
* Multi-Generator Check: If enabled in .harness/collaboration/multi-generator.yaml, coordinate with other generators.
* Rollback Preparation: Create snapshot using .harness/rollback/rollback-strategy.yaml before changes.
* Confidence Assessment: Calculate confidence score using .harness/knowledge/confidence-scoring.yaml.
* Pattern Application: Apply relevant patterns from .harness/evolution/patterns.yaml.
* Logic Synthesis: Perform an impact analysis and define a testing strategy before writing code.
* Pattern Check: Review .harness/knowledge/failure-patterns.yaml for relevant patterns to avoid.
* Code Generation: Implement logic following SOLID, DRY, and KISS principles with pattern-aware defensive coding.
* Documentation Update: Trigger living documentation generation from .harness/documentation/living-docs.yaml.
* Atomic Updates: Every task completion requires a git commit and a progress entry.

### 4. Phase 3: Parallel Adversarial Evaluation

#### 4a. Functional Evaluation (The Evaluator)
* Hostile Barrier: Assume the Generator's output is riddled with bugs and happy-path logic.
* Instant Death Gates: Immediately FAIL the task if there is a global regression, linting error, or any lazy code such as placeholders like TODO or FIXME.
* AC Deep-Dive: Confirm every AC has a dedicated test and that test quality metrics like Mock Integrity and Coverage Stability are met.
* Verdict: Return a binary PASS or FAIL. If FAIL, provide a root cause analysis.

#### 4b. Security Evaluation (The Security Evaluator) - Runs in Parallel
* Security Scanning: Check for OWASP Top 10 vulnerabilities and security anti-patterns.
* Dependency Audit: Verify no known CVEs in dependencies.
* Secret Detection: Scan for hardcoded credentials or API keys.
* Verdict: Return PASS or FAIL with specific security findings.

#### 4c. Code Review Evaluation (The Code Reviewer)
* Changed-Code Review: Review the actual diff for correctness, maintainability, missing tests, and team-pattern violations.
* Scope Discipline: Ignore unrelated pre-existing issues unless the Generator made them worse.
* Verdict: Return PASS only when there are no critical or important review findings.

#### 4d. Production Readiness Evaluation (The Production Readiness Reviewer)
* Production Safety Review: Review the change for deployability, rollback safety, observability, configuration safety, data safety, performance risk, operational failure modes, and release hygiene.
* Scope Discipline: Do not duplicate broad code review or security review; focus on whether the change can safely run, fail, be diagnosed, and be recovered in production.
* Verdict: Return PASS only when there are no critical or important production readiness risks.

#### 4e. MR Readiness Analysis (The MR Readiness Analyzer)
* Local-Git Only: Use local git history and diffs to determine whether the branch is ready to become an MR.
* Submission Hygiene: Score commit story, change scope, self-review signals, and local validation evidence.
* External-Service Constraint: Never query GitLab, post comments, update MRs, modify labels, or use external MR tooling.
* Verdict: Return a readiness score and concrete cleanup actions if the branch is not ready.

Functional, security, code review, and production readiness evaluators must PASS for the task to be considered complete. MR readiness should score at least 70/100 before opening an MR or requesting human review.
MR readiness must always be run and its score must always be shown in the final response, even when the score is below 70 or the branch is not intended to become an MR yet.

### 5. Phase 4: Remediation and Reconciliation

* Automatic Rollback: If critical failures detected, execute rollback procedure from .harness/rollback/rollback-strategy.yaml.
* Remediation: If any Evaluator returns FAIL, the Generator must suspend new work, reproduce the failure locally, and fix the logic until it passes evaluation.
* Pattern Learning: Update .harness/knowledge/failure-patterns.yaml with new failure patterns discovered.
* Cross-Session Learning: Update .harness/evolution/patterns.yaml with successful patterns for future reuse.
* Confidence Adjustment: Decrease confidence score for similar future tasks based on failure type.
* Reconciliation: Once PASS is achieved, update the YAML task status to done and log the verification evidence including the git hash and test results in progress.md.
* Success Learning: Increase confidence scores and update pattern effectiveness metrics for successful implementations.
* Final Reporting: Include the execution status for Planner, Architect, Designer decision, Generator, Evaluator, Security Evaluator, Code Reviewer, Production Readiness Reviewer, and MR Readiness Analyzer. Include the MR readiness score and a concise readiness interpretation.

## Reference

### Personas
* **Planner**: Focuses on structured YAML roadmap creation and task decomposition.
* **Architect**: Reviews plans for system-wide impacts and design patterns before implementation.
* **Designer**: Creates UI/UX specifications, ensures accessibility, and defines interaction patterns for frontend tasks.
* **Generator**: Focuses on defensive programming, architectural synthesis, and local verification with pattern-aware implementation.
* **Evaluator**: Acts as the gatekeeper using a Zero-Trust approach to code quality.
* **Security Evaluator**: Parallel security-focused evaluation for vulnerabilities and security best practices.
* **Code Reviewer**: Reviews changed code for correctness, maintainability, test quality, and team conventions.
* **Production Readiness Reviewer**: Reviews deployability, rollback, observability, configuration, data safety, performance risk, and operational failure modes.
* **MR Readiness Analyzer**: Scores whether the local branch is ready to become an MR using local git history, diff scope, self-review signals, and validation evidence.

### Knowledge Systems
* **Failure Patterns**: Learning system that captures and prevents recurring failure patterns.
* **Confidence Scoring**: Adaptive scoring system that adjusts validation requirements based on task complexity and historical performance.
* **Evolution Patterns**: Cross-session learning system for discovering and refining successful implementation patterns.

### Reliability Mechanisms
* **Rollback Strategy**: Automated rollback mechanisms with snapshot creation and incident reporting.
* **Multi-Generator Collaboration**: Parallel work by specialized generators on independent modules.

### Integration & Documentation
* **External Tools**: Enterprise tool integrations for CI/CD, monitoring, security, and documentation.
* **Living Documentation**: Auto-generated and maintained documentation that stays in sync with code.
