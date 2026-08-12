# MoreGAN Roadmap

## North Star

MoreGAN should become an executable adversarial orchestration layer for coding agents. The runtime should enforce the workflow, collect evidence, route work by risk, and make each worker produce machine-readable results that engineers can inspect, replay, benchmark, and trust.

The core product promise is deliberately narrow:

> Separate implementation from independent verification, and make the verification trail useful to engineers.

## Product Principles

- The runtime enforces the protocol. Prompts can guide workers, but Python controls state, routing, retries, and pass/fail decisions.
- Every stage returns structured output. A result should have a verdict, confidence, findings, evidence, and duration.
- Deterministic evidence is first-class. Tests, linting, type checks, security scans, coverage, secret detection, and git validation should run as tools, not as model opinions.
- MoreGAN should be adaptive, not bureaucratic. Low-risk edits should run a small path; high-risk work should trigger architecture, security, production, readiness, and learning gates.
- Learning must be empirical. Lessons need run evidence, outcomes, and confidence derived from observations.
- Claims must be benchmarked. Strong marketing language should wait until MoreGAN can show measured improvement over a baseline agent.

## Roadmap

## Ten-Item Progress Tracker

This maps the original improvement list to the current implementation state.

| # | Improvement | Current status |
|---|-------------|----------------|
| 1 | Real harness runtime | Implemented foundation: Python owns routing, state, stages, retries, and pass/fail trace output. |
| 2 | Structured persona output | Implemented foundation: workers return `StageResult` JSON with verdicts, findings, evidence, confidence, and attempts. |
| 3 | Deterministic evidence layer | Implemented foundation plus stack presets: `.moregan/tools.yaml`, built-ins, explicit commands, required/optional checks, structured command evidence, and detected Python/Node/Java/Spring Boot/Rails/Go/Rust presets. |
| 4 | Execution trace | Implemented and improving: run directories, events, state, stage artifacts, replay, remediation artifacts, and compact context packs. |
| 5 | Empirical learning system | Implemented foundation: run-backed observations, outcomes, and aggregate pattern confidence. |
| 6 | Adaptive routing | Implemented foundation: request keywords plus changed paths, dependency files, sensitive paths, file count, and changed-line evidence. |
| 7 | Competitive generators | Planned later; benchmark and provider hardening moved earlier. |
| 8 | Benchmark tasks | Next major evaluation item. |
| 9 | Measurable positioning | Partially implemented: README claims are more conservative; needs benchmark-backed release claims. |
| 10 | Real CLI | Partially implemented: `init`, `setup`, `run`, `status`, `inspect`, `replay`, and `adapters` exist; `benchmark`, `learn`, and stronger `doctor` remain. |

### v1.6: Structured Runtime Outputs

Goal: make the current runtime inspectable and automation-friendly.

- Add shared schema objects for findings, evidence references, stage results, risk classification, command evidence, and full run results.
- Write `stages/*.json` artifacts for runtime stages.
- Convert deterministic command failures into structured findings.
- Keep `events.jsonl`, `result.json`, and `final_report.md` as the human/debugging layer.

### v1.7: Real State Machine

Goal: replace "the model remembered the protocol" with enforced transitions.

- Add task states: intake, risk_classification, planning, generation, evaluation, remediation, readiness, learning, completed, failed.
- Add transition validation and max remediation attempts.
- Make skipped stages explicit with reasons.
- Persist state snapshots so interrupted runs can be inspected and resumed.

Status: the first state-machine implementation is in place for the executable runtime path. Runs now persist `state.json` and `states.jsonl`, reject invalid transitions, and surface the final state in CLI status output. Future worker stages can attach to the already-defined states.

### v1.8: Deterministic Tool Layer

Goal: make zero-trust verification real.

- Add configurable tool adapters for test, lint, typecheck, coverage, dependency audit, secret scan, Semgrep, and git diff validation.
- Detect likely project stacks and propose default commands.
- Store tool output tails, exit codes, durations, and remediation hints in structured evidence.
- Allow repository-local `.moregan/tools.yaml` overrides.

Status: the first deterministic tool layer is implemented. MoreGAN loads `.moregan/tools.yaml` when present, supports built-in and explicit commands, records required/optional status, duration, output tails, and remediation text, and records detected stack suggestions in run traces.

### v1.9: Stack-Aware Tool Presets

Goal: make `moregan init` useful immediately in common engineering stacks.

- Detect Python, Node, Java/Spring Boot, Rails/Ruby, Go, and Rust project files.
- Write optional enabled presets for tests, linting, type checking, security scanning, and dependency auditing.
- Skip optional presets cleanly when executables are missing.
- Keep required defaults focused on broadly safe built-ins.

Status: stack-aware presets are implemented. `moregan init` now writes enabled optional presets for detected stacks, and missing optional tools become structured skips instead of runtime crashes.

### v2.0: Worker Orchestration

Goal: use LLM workers as replaceable executors inside the runtime.

- Define planner, generator, evaluator, security, reviewer, production, readiness, and learning worker interfaces.
- Require each worker to emit the same structured stage contract.
- Add provider adapters for local agent CLIs where practical.
- Support dry-run, inspect-only, and no-write modes.

Status: worker orchestration is implemented. MoreGAN now resolves routed worker stages through adapter interfaces, writes dry-run `StageResult` artifacts when no provider is configured, and can run provider-backed local commands from `.moregan/workers.yaml` when they emit StageResult-compatible JSON.

### v2.1: Provider-Backed Workers

Goal: let engineers plug real local worker providers into the runtime without changing MoreGAN code.

- Load worker provider commands from `.moregan/workers.yaml`.
- Pass run context through environment variables.
- Require providers to emit one `StageResult` JSON object on stdout.
- Convert provider failures, invalid JSON, invalid stages, and timeouts into structured findings.
- Keep provider commands no-write by default through `MOREGAN_NO_WRITE=1`.

Status: the first provider-backed worker adapter is implemented for local commands. Dedicated Claude/Codex CLI adapters can now be layered on top of the same command contract.

### v2.2: Run Replay

Goal: let engineers reconstruct a run from trace artifacts without re-executing providers or deterministic tools.

- Add `moregan replay <run_id>` and `moregan replay latest`.
- Print state transitions, stage verdicts, findings, evidence, and deterministic command evidence in order.
- Add JSON replay output for automation.
- Treat replay as read-only inspection of `.moregan/runs/<run>/`.

Status: read-only run replay is implemented in the runtime. The CLI can render a human replay report or JSON reconstruction from existing artifacts.

### v2.3: Repository Initialization

Goal: make the first command useful and safe in a real engineering repo.

- Add `moregan init`.
- Create `.moregan/tools.yaml`, `.moregan/workers.yaml`, and `.moregan/runs/`.
- Add `.moregan/runs/` to `.gitignore`.
- Preserve existing config by default, with `--force` for intentional replacement.
- Seed disabled stack-specific deterministic tool suggestions when they can be detected.

Status: repository initialization is implemented. `moregan init` supports safe defaults, `--force`, `--dry-run`, and `--no-gitignore`.

### v2.4: Agent CLI Adapters

Goal: make Codex and Claude workers easy to wire into MoreGAN without custom glue scripts.

- Add first-class adapter templates for Codex and Claude command-line workflows.
- Generate provider prompts that require the `StageResult` JSON contract.
- Preserve `MOREGAN_NO_WRITE` behavior for review/evaluation workers.
- Capture provider command metadata and trace it alongside stage results.

Status: Codex and Claude adapter templates are implemented. `moregan adapters codex` and `moregan adapters claude` scaffold provider prompts and worker YAML, while `moregan.agent_worker` normalizes provider CLI output into MoreGAN `StageResult` JSON.

### v2.5: Remediation Loop

Goal: turn failed evidence into bounded repair attempts.

- Feed structured findings from deterministic tools and worker stages back to the generator.
- Add max remediation attempts and attempt-specific stage artifacts.
- Rerun only failed gates plus required downstream gates.
- Preserve failure reports when remediation cannot resolve blockers.

Status: the first remediation loop is implemented. Required deterministic failures and routed worker failures after generation are converted into remediation context, the generator is rerun with `MOREGAN_REMEDIATION_CONTEXT`, attempts are bounded with `--max-remediation-attempts`, and traces preserve `remediation.json` plus attempt-specific stage artifacts.

### v2.6: Adaptive Routing

Goal: spend rigor where risk justifies it.

- Classify work by request, touched files, diff size, dependencies, auth, payments, data migrations, infrastructure, and public API changes.
- Map low, medium, high, and critical work to different routes.
- Record why stages were selected or skipped.
- Let benchmarks tune routing thresholds.

Status: the first adaptive routing foundation is implemented. Risk classification now combines request keywords with local git evidence including changed paths, dependency/config/infra files, auth/payment/migration paths, touched-file count, and changed-line count.

### v2.7: Context Curation

Goal: reduce token/context cost while preserving useful worker context.

- Write compact JSON context packs under `.moregan/runs/<run>/context/`.
- Include request, route, risk, repository summary, prior stage summaries, deterministic evidence, remediation context, and local lessons.
- Pass context paths and approximate token counts through worker environment variables.
- Keep no-write worker context inside isolated snapshots.

Status: compact context packs are implemented. Runtime writes `context/base.json`, `context/stages/<stage>.attempt<N>.json`, and `context/manifest.json`; worker results include context-pack evidence with approximate token counts.

### v2.8: Empirical Learning

Goal: make learning evidence-backed instead of prose-invented.

- Write `learning.json` for every run.
- Append observations to `.moregan/learning/observations.jsonl` only when findings or failed deterministic evidence exist.
- Aggregate recurring observations in `.moregan/learning/patterns.json`.
- Compute confidence from observed remediated versus unresolved outcomes.
- Surface learning in inspect and replay output.

Status: the first empirical learning store is implemented. Clean runs do not invent lessons; failures and remediations record run-backed observations with outcomes and aggregate pattern statistics.

### v3.0: Competitive Generators

Goal: make the GAN analogy operational.

- Run multiple candidate solutions for high-risk or ambiguous work.
- Give candidates different objectives: smallest patch, architecture-first, security/performance-first.
- Judge candidates against the same acceptance criteria and deterministic evidence.
- Support choose-best and synthesize-best modes.

### v3.5: Benchmarks

Goal: prove MoreGAN is useful.

- Add benchmark task fixtures for bug fixes, features, refactors, security hardening, migrations, and docs.
- Measure success rate, test pass rate, regression rate, security findings, iterations, wall time, token usage, cost, and human review findings.
- Compare baseline agent runs against agent-plus-MoreGAN runs.
- Publish only claims that have supporting benchmark data.

### v4.0: Benchmark-Driven Runtime

Goal: let evidence tune the harness.

- Use benchmark results to choose routes, evaluators, and generator strategies.
- Promote empirical learning patterns only after repeated supporting observations.
- Add replay tooling for failed or surprising runs.
- Produce release-quality reports engineers can attach to reviews.

## Current Branch Focus

This branch starts v1.6 through v2.9 plus stack-aware presets. The runtime now has repository initialization, Codex/Claude adapter templates, structured stage output, an enforced state machine, configurable deterministic tools, stack-aware presets, dry-run worker orchestration, provider-backed local command workers, read-only run replay, bounded remediation attempts, isolated no-write worker execution, compact context packs, empirical learning artifacts, and diff-aware adaptive routing. The next priority is a small benchmark harness.
