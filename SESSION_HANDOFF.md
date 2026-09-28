# MoreGAN Session Handoff

Updated: 2026-09-27 during M1 distribution implementation and release validation.
Benchmark, completion/provider hardening, adaptive routing, check execution and workspace milestones are
implemented and tested; production hardening continues.

## Repository And Decisions

- Checkout: `/Users/suyesh/Desktop/hooligan-harness` (the directory name is historical).
- Branch: `main`; remote: `git@github.com:suyesh/moregan.git`.
- Previous pushed change: `c2212e1 Explain GAN inspiration in README introduction`.
- Current feature version: 1.16.0, M1 distribution and release gates.
- Commit and push each completed milestone to main, as requested by the user.
- Bump package versions for features. Keep all version constants and uv.lock aligned.
- The user explicitly resumed publishing: meaningful features/fixes/distribution
  changes should get releases; use judgment to skip docs-only releases and say so.
  Main pushes run CI; version tags also create a GitHub release and publish to PyPI
  after shared CI passes. Confirm actual publication, not just tag/release creation.
  The prior audit found PyPI at 1.5.0; this is historical, not current verification.
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

## Completed In 1.14.0

- Added workspaces.py with per-invocation ownership of temporary snapshot parents.
  Cleanup runs in finally paths for success, failure, bad provider output, reported
  timeout, interruption, failed copies and failed context preparation.
- Handle read-only copied files/directories; report cleanup failures with the
  remaining path. No silent successful cleanup claims. Never delete the checkout.
- No-write workers hash original checkout contents before/after both execution
  modes, including already-dirty files. Compare modes, symlink entries, Git index,
  HEAD commit and symbolic reference. Non-Git directories are also checked.
- Git ignored/untracked build/cache/generated output is excluded. Tracked files
  remain covered even under excluded names. Git worktrees/unborn repos supported.
- Scan budgets: 30 seconds, 100,000 paths, 1 GiB read; Git capture capped at 1 MiB.
  Errors, truncation and unsupported submodules fail closed. No partial PASS.
- Snapshot copies preserve links initially, reject external/looping targets, and
  rebase internal links to the copy. Reject TMPDIR inside the checkout.
- Integrity/cleanup failures stop the runtime with worker.manual_review_required;
  no automatic generator remediation or rollback. Other failures retain retries.
- Persist cleanup and integrity evidence; removed execution paths are historical.
- Added 37 tests, adjusted old persistent-snapshot assertions, bumped all versions
  and lock to 1.14.0, and added docs/worker-workspaces.md.

## Completed In 1.15.0

- Both CommandWorker and AgentWorkerRunner now use the shared bounded executor.
  JSON stdout defaults to 1 MiB and fails on overflow or invalid UTF-8. Never
  parse a truncated tail as a result; strict StageResult validation remains.
- Provider stderr is continuously drained with at most a 4,000-byte tail.
  Successful results record provider_io counts, limits, truncation and errors;
  failure diagnostics still cap tails at 1,000 characters.
- Wrapper prompt templates are bounded regular UTF-8 files. Combined prompt,
  runtime context and formatting are capped (default 1 MiB) before launch.
- POSIX selectors write prompt stdin while reading both outputs. A blocked write,
  waiting child or inherited open pipe is bounded by the same deadline. Early
  stdin closure before delivery fails. Windows fallback adds a daemon writer.
- Generated direct Python wrappers inherit the outer worker's POSIX process
  group after a direct-parent/group-leader check. Standalone wrappers own their
  provider group. Kill ordinary descendants before snapshot cleanup/verification.
- Process cleanup failure stops for manual inspection without retries or diff
  reassessment, retains snapshots and skips checkout verification. Interruption
  plus cleanup failure also retains the snapshot and warns before propagating.
- New per-worker max_output_bytes/max_prompt_bytes settings, strict ranges,
  unknown-field rejection, inherited CLI defaults and scaffold configuration.
- Added 28 provider execution tests, retained the malformed-contract matrix, and
  updated metadata assertions. All version constants and lock bumped to 1.15.0.
- Docs/provider-execution.md covers limits, custom-wrapper cooperation, and
  non-sandbox scope. Windows trees and escaped POSIX groups remain uncontained.

## Capability And Documentation Audit

- User requested an assessment of current functionality, usage and README accuracy,
  and asked whether GitHub progress was also being published. No publish was requested
  or dispatched; confirmed live PyPI still has only version 1.5.0.
- Rebuilt README as a shorter user entry point, distinguishing source 1.15.0 from
  the older published package, manual provider setup, optional checks and true outcomes.
- Rewrote INSTALL.md to separate CLI, skill installation and provider configuration.
  Removed unsupported rollback/parallel-generator/integration claims and corrected
  setup/update semantics and unverified Python/platform support language.
- Added docs/getting-started.md, worker-contract.md, releases.md and product-status.md.
  A skip-only provider probe tests stdin/JSON plumbing without pretending work passed.
- Added three documentation tests covering both adapters' actual CLI onboarding,
  the init/activation preservation trap, probe output, example checks/schema and links.
- Important open gaps: init creates empty workers.yaml which --activate preserves;
  users still supply native-provider JSON bridges; generated runtime prompts do not
  automatically load full persona files; older SKILL.md body conflicts with routing,
  numeric readiness, rollback and parallelism. Documented, not silently declared fixed.
- No runtime or skill behavior change and no feature version bump in this docs-only
  audit. Release CI remains next, with provider onboarding/skill alignment next in line.

## Review Findings And Next Work

Read `docs/review-2026-09-27.md` first for concrete code references and impact.
Read `docs/turnkey-product.md` for the requested product destination and acceptance
criteria. The user wants native provider connections, easy CLI/skill installation,
equivalent runtime enforcement from both host skills, safe rollback, parallel
generators and real integrations. These are not being removed from product scope.

ROADMAP.md and .moregan/roadmap.yaml now track M1-M7 for distribution, onboarding,
parity, transactional recovery, parallelism, integrations and measured efficiency.
These labels supplement, rather than replace, the original ten-item tracker.
Parity requires identical normalized fixture results through the same runtime;
do not promise identical live model output across hosts/providers. Rollback must
preserve user work and stop on conflicting subsequent edits, never reset a checkout.
This milestone definition changes no runtime/skill behavior or package version.

M1 implementation is now present in 1.16.0; native CI passed in run 36386333966
for commit d04fef0. Actual release validation is in progress. Shared ci.yml builds
once, checks source/archive metadata and README,
runs the full Linux/macOS Python 3.10-3.14 suite, and installs that wheel in clean
environments. Windows 3.10/3.14 runs packaging/simulated-provider/skill smoke only.
workflow.yml validates version tags and notes, runs shared CI, creates the GitHub
release, then publishes the tested artifact without rebuilding. New scripts live
under scripts/ci, with regression coverage in tests/test_release.py.

Python metadata now requires 3.10+. Setup scripts check that floor and show the
runtime version. New adapter templates bind to sys.executable; regenerate them
after moving environments. Existing configs remain untouched. Native provider
bridges and skill-contract changes still belong to M2/M3, not this milestone.

Use CI to establish platform evidence before claiming Windows support. The shared
executor's Windows path still terminates only direct children and uses daemon I/O
threads. Add Windows child-tree supervision as a follow-up, not a claimed guarantee.
POSIX escaped sessions/custom wrappers with extra process layers remain documented
limitations. Native macOS validation is not certification of the whole matrix.

After that:

1. Implement native provider bridges, improve activation UX, and align the skill
   contract/persona prompting with runtime routing. See docs/product-status.md.
2. Add Windows child-tree cleanup with native platform tests and stronger isolation.
3. Expand fixtures to representative real repositories and collect actual
   provider token/cost measurements before running effectiveness studies.
4. Add transactional generation and owned-patch recovery before opt-in parallel
   reviewers and competing generators. Benchmark the added overhead.
5. Deliver revision-bound CI/PR integrations with explicit external-write permissions.
   M7 measurement is ongoing alongside this work, not postponed until the end.

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
| 1 | Runtime | Truthful outcomes, workspace integrity and bounded provider execution through 1.15.0 |
| 2 | Structured persona output | Strict schema, output size and UTF-8 checks through 1.15.0 |
| 3 | Deterministic evidence | Presets, deadlines, bounded output and POSIX cleanup in 1.13.0; Windows tree cleanup pending |
| 4 | Execution trace | Implemented; replay attempt fidelity fixed in 1.12.0 |
| 5 | Empirical learning | Foundation implemented |
| 6 | Adaptive routing | Post-generation escalation implemented in 1.12.0; heuristics need calibration |
| 7 | Competitive generators | Deferred |
| 8 | Benchmarks | Foundation implemented in 1.10.0 |
| 9 | Measurable positioning | Limitations documented; effectiveness study pending |
| 10 | CLI | Benchmark added; stronger doctor and learn pending |

## Verification And Limits

- Full unittest suite passed 203 tests on macOS under Python 3.12.11 and 3.14.0
  after this audit (200 runtime baseline tests plus three documentation tests).
- Documentation CLI smoke exercised both provider templates, preserved empty
  config on activation, deliberate template selection, skip-only probe and replay.
  Python check example executed one test; Maven examples were config-validated,
  not run against an actual Java application. No live model calls.
- Rebuilt wheel/sdist and confirmed README, INSTALL and all four new guides are
  packaged. Compilation, Markdown repository links, YAML and diff hygiene passed.
- Build: `uv build --clear --default-index https://pypi.org/simple`.
- Lock validation: `uv lock --check --default-index https://pypi.org/simple`.
- Wheel smoke environment: `/private/tmp/moregan-1.15.0-smoke.Xzp0tj/venv`.
- Smoke script: `/private/tmp/moregan-1.15.0-smoke.Xzp0tj/smoke.py`.
- All 28 provider execution tests also passed against the installed wheel outside checkout.
- Wheel and sdist built; installed CLI smoke passed for both provider adapters.
- Installed CLI exercises both adapters, pass, oversize/invalid-UTF-8 output,
  timeouts, scratch snapshots, preserved user files, inspect and replay.
  Simulated providers only; no live model access.
- Fixture verifiers tested against both broken source and known repaired source.
- No paid Codex/Claude benchmark run or PyPI publication was performed.
- The full supported Python/OS matrix is not yet certified. Source review found
  a preexisting Python 3.8 incompatibility in install.py (str.removesuffix).
  M1 deliberately raises the floor to 3.10; native CI results must be checked before
  marking the new matrix validated.

## Useful Commands

```bash
uv run --extra test python -m unittest discover -s tests -v
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
