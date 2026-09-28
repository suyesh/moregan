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
- Compact context packs, local learning observations, traces, and read-only replay.
- CLI initialization, skill setup, and package/publishing configuration.
- Benchmark foundation: six isolated Python fixtures, independent acceptance checks,
  generator-only versus full-route runs, baseline imports, and paired reports.

## Next

1. Provider output bounds and process cleanup; Windows child-tree supervision.
2. Supported-version CI, package checks, and release gates.
3. Representative benchmark tasks, repeated live-agent runs, token/cost collection,
   and independent human evaluation.

Details and code pointers: [September review](docs/review-2026-09-27.md).
Benchmark usage and limitations: [Benchmark guide](docs/benchmarks.md).
Check limits and platform scope: [Tool execution](docs/tool-execution.md).
No-write coverage and exclusions: [Worker workspaces](docs/worker-workspaces.md).

## Later

- Competitive generators with the same acceptance criteria and evidence gates.
- Routing and evaluator selection tuned by measured benefit and cost.
- Stronger process isolation and repository configuration validation.
- Empirical learning calibrated across independent runs.
- Richer `doctor` and `learn` commands.

## Original Ten Items

| # | Item | Current Progress |
|---|---|---|
| 1 | Real runtime | Truthful completion in 1.11.0; workspace lifecycle and integrity hardened in 1.14.0 |
| 2 | Structured persona output | Shared strict provider validation implemented in 1.11.0 |
| 3 | Deterministic evidence | Stack presets, deadlines and bounded output in 1.13.0; Windows child-tree cleanup pending |
| 4 | Execution trace | Implemented; replay attempt fidelity repaired in 1.12.0 |
| 5 | Empirical learning | Foundation implemented; calibration pending |
| 6 | Adaptive routing | Intake and post-generation escalation implemented in 1.12.0; heuristic tuning remains |
| 7 | Competitive generators | Deferred until benchmarks and reliability improve |
| 8 | Benchmarks | Foundation implemented in 1.10.0; live effectiveness study pending |
| 9 | Measurable positioning | Limitations documented; no effectiveness claims yet |
| 10 | Real CLI | Init, setup, adapters, run, status, inspect, replay, benchmark; doctor/learn pending |

Every feature gets a package version bump. Completed milestones are tested,
committed, and pushed to `main`. PyPI publishing remains paused until requested.
Historical implementation notes remain in `.moregan/roadmap.yaml` and
`.moregan/progress.md`; old phase labels there are not promised release versions.
