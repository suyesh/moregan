# MoreGAN Roadmap

MoreGAN separates implementation from verification. The runtime owns transitions,
workers return structured results, and engineers can inspect the evidence.
The project is alpha. Completed foundations are not a claim of production readiness.

## Now

- Executable runtime, state machine, bounded remediation, and structured stage results.
- Truthful pass/fail/incomplete outcomes and strict shared provider validation.
- Local command workers and Codex/Claude adapter templates.
- Deterministic checks and stack detection for Python, Node, Java/Spring Boot,
  Rails/Ruby, Go, and Rust.
- Per-check deadlines, bounded output tails, structured execution failures, and
  POSIX process-group cleanup.
- Intake and post-generation diff risk classification with monotonic escalation.
- Post-generation catch-up reviews and attempt-correct replay.
- Worker snapshot cleanup, checkout content/index verification and manual-review
  stops for workspace integrity failures.
- Bounded provider JSON and prompt delivery, strict UTF-8 handling, and nested
  Codex/Claude POSIX process supervision before workspace cleanup.
- Compact context packs, local learning observations, traces, and read-only replay.
- CLI initialization, skill setup, and package/publishing configuration.
- M1 implementation in 1.16.0: shared release CI, Python 3.10+ metadata,
  installed-wheel/skill smoke checks and version-tag publication gates.
- Benchmark foundation: six isolated Python fixtures, independent acceptance checks,
  generator-only versus full-route runs, baseline imports, and paired reports.

## Next

The product target is one installable runtime with three first-class entry points:
CLI, Codex skill, and Claude skill. Users should not need to write a provider
bridge or maintain a second prompt-only workflow. This is a target, not today's
installation experience.

| Milestone | Deliverable | Status |
|---|---|---|
| M1 | Supported-version CI, installed-package checks, and test-gated releases | Implemented; native CI validation pending |
| M2 | Built-in Codex/Claude bridges, guided setup, safe activation, prerequisite diagnostics | Planned |
| M3 | Thin skills using the same runtime and canonical persona prompts, with parity tests | Planned |
| M4 | Transactional generation, safe patch application and scoped undo/automatic recovery | Planned |
| M5 | Opt-in parallel reviewers and isolated competing generators with bounded concurrency | Planned |
| M6 | CI/PR integrations and machine-readable reports with explicit write permissions | Planned |
| M7 | Measured quality/cost, context reuse and evidence-tuned routing | Foundation exists; ongoing |

M1-M3 are the first adoption milestone: install, connect a supported authenticated
provider, and run from the terminal or a skill without writing Python glue.
Platform/process hardening and representative benchmarks continue alongside them;
measure sequential performance before enabling M5 competition by default.

**Parity means the same policy, persona prompts, checks, repair limits and verdict
rules for the same resolved inputs.** It does not promise identical generated code
across stochastic runs or across Codex and Claude models. Deterministic fixtures
must produce identical normalized results through all three entry points.

Acceptance criteria, safety boundaries and dependencies:
[Turnkey product milestones](docs/turnkey-product.md).

Details and code pointers: [September review](docs/review-2026-09-27.md).
User-facing capabilities and remaining integration gaps: [Product assessment](docs/product-status.md).
Published versus source versions: [Release status](docs/releases.md).
Benchmark usage and limitations: [Benchmark guide](docs/benchmarks.md).
Check limits and platform scope: [Tool execution](docs/tool-execution.md).
No-write coverage and exclusions: [Worker workspaces](docs/worker-workspaces.md).
Provider limits and process scope: [Provider execution](docs/provider-execution.md).

## Later

M4-M7 above retain the advanced product goals; removing unsupported claims from
the install guide did not cancel them. Automatic rollback and integrations now
have explicit acceptance criteria rather than descriptive configuration alone.
Broader enterprise connectors, living-documentation automation, stronger OS
sandboxing and calibrated cross-project learning follow validated core workflows.

## Original Ten Items

| # | Item | Current Progress |
|---|---|---|
| 1 | Real runtime | Truthful completion, workspace integrity and bounded provider execution through 1.15.0 |
| 2 | Structured persona output | Shared strict validation; oversized/invalid-UTF-8 output rejected in 1.15.0 |
| 3 | Deterministic evidence | Stack presets, deadlines and bounded output in 1.13.0; Windows child-tree cleanup pending |
| 4 | Execution trace | Implemented; replay attempt fidelity repaired in 1.12.0 |
| 5 | Empirical learning | Foundation implemented; calibration pending |
| 6 | Adaptive routing | Intake and post-generation escalation implemented in 1.12.0; heuristic tuning remains |
| 7 | Competitive generators | Planned in M5; isolated candidates, common gates, measured overhead |
| 8 | Benchmarks | Foundation implemented in 1.10.0; live effectiveness study pending |
| 9 | Measurable positioning | Limitations documented; no effectiveness claims yet |
| 10 | Real CLI | Existing commands implemented; turnkey onboarding and skill parity in M2-M3; runtime doctor/learn pending |

Meaningful features, fixes and distribution changes get a package version bump,
release notes and a GitHub/PyPI release after checks pass. Documentation-only
changes can be pushed without a release; explain that decision. Publication is
resumed at the maintainer's request. Completed work is committed and pushed to `main`.
Historical implementation notes remain in `.moregan/roadmap.yaml` and
`.moregan/progress.md`; old phase labels there are not promised release versions.
