# Benchmarks

MoreGAN 1.10.0 includes six small Python fixtures: null response handling,
pagination, deduplication, path traversal, SQLite migration, and expiry boundaries.
They test the measurement machinery and basic coding behavior. They are not a
representative study of production engineering work.

## Run A Comparison

Install Git and install MoreGAN into the Python environment used by your worker commands, then:

```bash
moregan init
moregan adapters codex --activate
# Configure MOREGAN_CODEX_COMMAND as described in the README.
moregan benchmark init
moregan benchmark run --mode baseline
moregan benchmark run --mode moregan
moregan benchmark compare <baseline-run-id> <moregan-run-id>
moregan benchmark inspect latest
```

Claude uses `moregan adapters claude --activate` and `MOREGAN_CLAUDE_COMMAND`.
The baseline executes only the configured generator. MoreGAN executes its routed
workers and deterministic checks. Both receive the same task and acceptance
criteria and are scored by the same independent verification program.

Use `--limit 1` on both run commands for a quick provider check. Use `--json` on
run, inspect, or compare for automation. Global `--root PATH` precedes `benchmark`.
An executed run returns exit code 0 only when every task passes; failed or
incomplete runs return 1. Inspect and compare return 0 when the report is valid,
even when that report contains failed or unmeasured tasks.

## Execution And Artifacts

Each task starts in a new temporary workspace containing only its fixture files,
a copy of `.moregan/workers.yaml`, and adapter prompts. Repository tools, source
files, and accumulated learning are not copied. Each fixture gets an initial Git
commit so agents can inspect their patch; commits stay in the temporary directory.
Custom provider commands must be
installed executables, importable modules, or absolute script paths; relative
scripts in the original repository will not be present in the fixture.

The verification program is created outside the worker workspace after workers
finish and runs in a separate Python process. Its timeout defaults to 30 seconds
and can be set with `--verification-timeout`. Custom suites contain executable
Python and must be trusted, just like repository tests. Temporary workspaces
provide file separation, not an OS security sandbox; providers still have the
permissions of the invoking user.

Results are preserved under `.moregan/benchmarks/`:

```text
runs/<run-id>/
  suite.json
  result.json
  report.md
  tasks/<task-id>/
    workspace/          # candidate source after the attempt
    trace/              # provider or runtime evidence
    verification.json
comparisons/<comparison-id>/
  comparison.json
  comparison.md
```

The copied trace records original temporary execution paths; those paths are
historical. Use the saved candidate workspace and the trace files alongside it
for inspection. Results are checkpointed after each task, so a provider error
does not discard earlier measurements. Provider exceptions are reported as
errors and the remaining tasks continue. Keyboard interruption leaves the last
checkpoint with status `running`; there is no resume command yet.

`moregan init` adds local run and comparison directories to `.gitignore`.
Benchmark init preserves existing suite files; `--force` replaces them and
`--dry-run` previews changes.

## What Counts As Success

A measured pass requires independent acceptance tests to pass, the workflow to
pass, and every routed stage to execute. Skipped workers, missing providers,
provider errors, and verification timeouts are unmeasured. A provider claiming
PASS while leaving the original broken fixture fails acceptance verification.
Downstream reviews not reached because a blocking code check failed do not erase
that failure from the measurements.

This benchmark gate is stricter than the current ordinary `moregan run` verdict:
the ordinary runtime can still report PASS with skipped stages. That runtime
limitation is tracked in the [review](review-2026-09-27.md).

Reports expose measured task coverage beside success rate. Comparisons require
the same task ids and definition hashes, and calculate deltas only over pairs
measured on both sides. Pending tasks are not counted as regressions or successes.
Partially observed token, cost, or duration totals stay null instead of looking
like complete totals. Token usage, cost, and human review findings are not yet
collected automatically from providers.

## External Baselines

`benchmark init` also writes `benchmarks/baseline-results.template.json`. Fill in
actual measured statuses, evidence references, and any known metrics, then run:

```bash
moregan benchmark run --mode baseline \
  --baseline-results benchmarks/baseline-results.template.json
```

The file must retain the suite fingerprint. Pass/fail records require an evidence
reference, but imported evidence is self-reported and not re-executed or independently
validated. Reports label these measurements `external_import`; the original
execution environment is unknown. An untouched pending template cannot produce
a passing benchmark.

## Custom Suites And Study Design

Edit `benchmarks/moregan-starter.json` or provide `--suite PATH`. Each task needs
`id`, `category`, `request`, `acceptance_criteria`, a `files` mapping of relative
paths to source text, and `verification` containing a Python program. The verifier
receives the workspace path as its first argument and must exit nonzero on failure.
Changing any task content changes its fingerprint and prevents comparison with
the old definition. Fixtures currently target Python; Java/Spring Boot runtime
presets do not yet imply Java benchmark coverage.

Before publishing effectiveness claims, add representative repository tasks,
repeat paired runs, control model versions and settings, record costs, and arrange
independent human review. Public starter acceptance tests are not a hidden test
set or a defense against a provider intentionally gaming the benchmark.
