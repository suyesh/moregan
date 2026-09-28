# MoreGAN Session Handoff

Updated: 2026-09-27 after bounded deterministic execution.
Benchmark, completion/provider hardening, adaptive routing and check execution milestones are
implemented and tested; production hardening continues.

## Repository And Decisions

- Checkout: `/Users/suyesh/Desktop/hooligan-harness` (the directory name is historical).
- Branch: `main`; remote: `git@github.com:suyesh/moregan.git`.
- Previous pushed milestone: `40de23c Reassess generated patch risk and preserve review attempts`, version 1.12.0.
- Current feature version: 1.13.0, bounded deterministic tool execution.
- Commit and push each completed milestone to main, as requested by the user.
- Bump package versions for features. Keep all version constants and uv.lock aligned.
- PyPI publishing is paused. A push to main does not trigger the existing release workflow.
- Runtime is the product; skills call the runtime. Provider commands are required
  for actual persona execution. No claim of production readiness or measured
  agent improvement has been established.

## Completed Before This Session

Runtime/state machine, stage schemas, deterministic tools, bounded remediation,
worker commands, Codex/Claude adapters, snapshots for no-write stages, compact
context packs, empirical learning observations, traces, replay, intake diff risk,
and stack detection. Java/Spring Boot presets include Maven/Gradle tests and
configured Checkstyle, SpotBugs, PMD, and OWASP Dependency-Check integrations.

## Completed In 1.10.0

- Reviewed the current implementation and ran the original 52 tests.
- Reworked the unfinished benchmark runner so task attempts use isolated fixtures.
- Added six runnable Python fixtures, fresh Git repositories, and independent acceptance tests.
- Added generator-only baseline execution and full MoreGAN route execution.
- Added validated, explicitly labeled external baseline imports.
- Added CLI commands: `benchmark init`, `run`, `inspect`, `compare`.
- Prevented skipped workers, provider errors, pending imports, and timeouts from
  being counted as benchmark successes. Normal runtime verdicts were repaired in 1.11.0.
- Matched comparison task sets and content hashes; compute deltas from measured
  pairs and retain nulls for missing or partial metrics.
- Saved candidate source, traces, verification, JSON and Markdown reports, with
  unique run ids and atomic result checkpoints after each task.
- Added regression tests for fixtures, workspace separation, outcome validity,
  input validation, comparisons, provider failures, packaging and CLI behavior.
- Bumped version to 1.10.0; regenerated uv.lock using public PyPI while retaining
  dependency version pins. The old lock was 1.5.0 and referenced a private registry.
- Packaged benchmark modules and docs for wheels and skill installation.
- Simplified ROADMAP.md to Now / Next / Later and retained the original ten items.

## Completed In 1.11.0

- Added terminal `incomplete` state and result status. Skipped routed stages,
  `--no-checks`, and empty/entirely skipped evidence gates cannot pass.
- `moregan run` returns 1 for incomplete or failed work, 0 only for pass. It lists
  incomplete stages; JSON, Markdown reports, and state history retain the outcome.
- Shared strict JSON/schema validation across CommandWorker and AgentWorkerRunner.
  Reject wrong stages, invalid verdicts/severities, non-finite or coerced confidence,
  malformed findings/evidence, invalid lines, unknown/duplicate keys, and extra prose.
- Critical/high findings require fail; attempt numbers and timing are runtime-owned.
- Provider launch, prompt, encoding, timeout, and workspace preparation failures
  become structured failures. Timeout byte output is decoded and tailed safely.
- Hardened worker commands, timeouts, boolean settings and duplicate-stage config.
- Incomplete runs record unverified observations, never successful remediations.
- Fixed final learning-worker failure remediation, which previously raised an
  illegal state transition instead of finishing its bounded retry loop.
- Added 20 tests with table-driven malformed payload cases, actual subprocess
  timeouts, all risk routes, and nested Codex/Claude adapter execution.
- Updated README, skill outcome guidance, adapter prompts, review, roadmap and versions.

## Completed In 1.12.0

- Reassess risk after every returned generator attempt, including remediation,
  skips, and failures. A failed generator still fails; its partial patch is traced.
- Preserve the highest risk within a run. Newly required planner/architect/design
  reviews inspect the existing patch before verification. Their failures use the
  same remediation budget; rerun added reviews and verification after repair.
- Fixed run-start Git baseline covers staged/working-tree changes, untracked
  files, generated commits, and repositories with no first commit. Reset per run.
- NUL-delimited diff parsing preserves unusual filenames and sensitive rename
  origins. New-file size estimates are bounded; MoreGAN output dirs are excluded.
- Added Java manifests/lockfiles and other dependency lockfiles to high-risk paths.
- Git inspection failures become structured run failures, not clean-diff evidence.
- Persist risk.initial.json, per-attempt assessments, risk_history.json and final
  risk.json. plan.json and base context remain intake snapshots; stage context is current.
- Workers receive MOREGAN_STAGE_PHASE; new adapter prompts explain catch-up reviews.
- Fixed replay to use per-attempt artifacts with embedded-result fallback; reports
  and replay show risk changes and CLI announces escalation.
- Added 22 routing/replay tests. No new personas or paid provider calls.

## Completed In 1.13.0

- Added processes.py for continuously drained, bounded per-stream output tails.
  Defaults: 300 seconds and 4,000 bytes; limits validated, cannot be disabled.
- POSIX process groups are killed on completion, timeout, capture error and
  interruption; direct child reaped. Deadline includes inherited output pipes.
- Windows uses bounded daemon readers and only immediate-child termination.
  No Windows verification or child-tree containment claim. Escaped POSIX sessions
  remain outside supervision; this is not a sandbox.
- Structured timeout/launch/capture/cleanup evidence, byte counts and truncation
  flags reach JSON, reports, replay, generator remediation and stage context.
- Required timeouts fail and can remediate; optional failures remain advisory;
  missing optional commands skip. Ordinary command exit codes are preserved.
- Tool config rejects malformed commands, duplicate names/fields, unknown fields,
  invalid limits and ambiguous boolean values. Init and presets include defaults.
- Python compilation's Git discovery is bounded to 30 seconds / 1 MiB, uses NUL
  delimiters, and fails closed on truncated results. Non-Git traversal is unchanged.
- Added 20 real-process/config/runtime tests, including 16 MiB noisy output with
  bounded capture memory, inherited-pipe timeout, child cleanup, interruption and
  fail-then-pass remediation. Provider execution remains on its old capture path.
- Bumped package/skill/installer/lock to 1.13.0; added docs/tool-execution.md.

## Review Findings And Next Work

Read `docs/review-2026-09-27.md` first for concrete code references and impact.

The next milestone is worker snapshot cleanup and stronger no-write checks.
CommandWorker._execution_root still leaves temporary copies behind. Repository
no-write mode compares Git status text and misses edits to already-dirty files.
Read workers.py and its tests, clean up snapshots in finally paths, and detect
content changes without reverting preexisting user changes. Test success, failure,
timeout, interruption, tracked/untracked changes and already-dirty files. Snapshots
are not a sandbox; describe the actual protection without overclaiming.

After that:

1. Bound provider output and supervise worker processes. Deterministic execution
   now has a small processes.py helper; extending it to JSON providers needs
   bounded stdin, explicit oversized-result failures and nested-process handling.
2. Add Windows child-tree cleanup and validate the OS matrix.
3. Add release CI and verify or adjust the advertised Python 3.8+ support.
4. Expand fixtures to representative real repositories and collect actual
   provider token/cost measurements before running effectiveness studies.
5. Introduce competitive generators only after this evidence and hardening.

Risk policy and remaining limits are documented in docs/risk-routing.md. Routing
is heuristic and request-only outside Git. Fixed-baseline evidence includes
preexisting user changes but never reverts them. Canonical route order and actual
stage execution order differ when reviews are added after generation; use state
history, phase and risk history to distinguish them.

Completion policy: a routed worker must pass. At least one deterministic command
must execute, with no required failures; individual not-applicable commands may
skip and optional failures remain advisory. This policy is intentionally not a
claim of comprehensive test coverage. Read-only status/inspect/replay return 0
when inspection succeeds, regardless of the stored run outcome. Provider output
validation cannot establish that the provider's claims are true.

## Ten-Item Tracker

| # | Item | Status |
|---|---|---|
| 1 | Runtime | Implemented; truthful outcomes in 1.11.0 |
| 2 | Structured persona output | Shared strict provider validation in 1.11.0 |
| 3 | Deterministic evidence | Presets, deadlines, bounded output and POSIX cleanup in 1.13.0; Windows tree cleanup pending |
| 4 | Execution trace | Implemented; replay attempt fidelity fixed in 1.12.0 |
| 5 | Empirical learning | Foundation implemented |
| 6 | Adaptive routing | Post-generation escalation implemented in 1.12.0; heuristics need calibration |
| 7 | Competitive generators | Deferred |
| 8 | Benchmarks | Foundation implemented in 1.10.0 |
| 9 | Measurable positioning | Limitations documented; effectiveness study pending |
| 10 | CLI | Benchmark added; stronger doctor and learn pending |

## Verification And Limits

- Full unittest suite passed 135 tests on macOS under Python 3.12.11 and 3.14.0.
- Build: `uv build --clear --default-index https://pypi.org/simple`.
- Lock validation: `uv lock --check --default-index https://pypi.org/simple`.
- Wheel smoke environment: `/private/tmp/moregan-1.13.0-smoke.GZLlHk/venv`.
- Smoke script: `/private/tmp/moregan-1.13.0-smoke.GZLlHk/smoke.py`.
- Installed CLI exercised outside checkout: init, incomplete exit 1, both provider
  adapters, noisy output, timeout remediation, required failure exit 1, advisory
  optional timeout, inspect and attempt-correct replay. These used simulated
  provider commands, not live models.
- Fixture verifiers tested against both broken source and known repaired source.
- No paid Codex/Claude benchmark run or PyPI publication was performed.
- The full supported Python/OS matrix is not yet certified. Source review found
  a preexisting Python 3.8 incompatibility in install.py (str.removesuffix).

## Useful Commands

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile install.py moregan/*.py tests/*.py
git diff --check
ruby -e "require 'yaml'; YAML.load_file('.moregan/roadmap.yaml')"
uv lock --check --default-index https://pypi.org/simple
uv build --clear --default-index https://pypi.org/simple
```

For actual provider comparisons, see `docs/benchmarks.md`. Starter tasks are
public Python smoke benchmarks, not hidden real-world tasks. Temporary workspace
isolation is not an OS security boundary. Copied traces retain historical paths
to the temporary execution directory; inspect saved trace files and candidate
source directly.

On resuming, verify `git status` and the latest commit first. Do not rely on old
phase-version numbers in `.moregan/roadmap.yaml` as package-release promises.
