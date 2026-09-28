# Adaptive Risk Routing

MoreGAN 1.12.0 classifies risk at intake and after every generator attempt,
including remediation, skipped generators, and generators that report failure.
Failed generation is still a failed run; reassessment records any partial patch
without treating it as ready for review.

## Evidence And Baseline

Run MoreGAN from the repository root, or pass that root with `--root`.
The runtime captures the starting Git HEAD and compares the current working tree
and index against that fixed commit. This includes changes already present at
intake and commits made during generation. Reusing a runtime for a new run resets
the baseline. A repository without a first commit uses an empty baseline.

Signals include changed paths, file count, line count, dependencies, migrations,
auth/payment paths, infrastructure, and request keywords. Java dependency signals
include `pom.xml`, `build.gradle`, `build.gradle.kts`, `gradle.lockfile`, and
`libs.versions.toml`. Other stack manifests and lockfiles are also recognized.

Tracked renames are inspected as old-path deletion plus new-path addition, so
renaming a sensitive file does not erase its signal. Staged and working-tree
counts are combined per file without counting an identical staged diff twice.
Untracked files contribute paths and bounded text-size estimates. New-file line
counts cap at 400, the high-risk threshold; reading 1 MiB of nonbinary content
also reaches that threshold. Binary files contribute paths, not text lines.
Git-ignored untracked files are not inspected.

MoreGAN's generated run, learning, backup, and benchmark-output directories are
excluded. Configuration, knowledge, and source files are not blanket-excluded.
Git inspection errors fail the run with `risk_inspection_failed`; they are not
interpreted as a clean diff. Without a Git repository, classification remains
request-only and the trace identifies that limitation.

## Review Ordering

Risk is monotonic within a run: `low -> medium -> high -> critical`. If a later
patch looks less risky, the runtime retains the earlier route and records both
the observed and effective risk.

For example, a low-risk request that generates authentication code runs:

```text
generator
risk reassessment: low -> critical
planner, architect, designer_decision (post-generation reviews)
deterministic checks
evaluator, security_evaluator, code_reviewer
production_readiness_reviewer, mr_readiness_analyzer, learning_curator
```

These newly required early reviews examine the existing patch. They are not
represented as having happened before generation, and they do not cause an
unnecessary extra generator call. Previously routed early reviews are not repeated
just because the risk changed. Normal pre-generation review failures still stop
before generation.

A failed post-generation review sends its findings to the generator using the
normal remediation budget. After repair, the runtime reassesses again, reruns all
post-generation reviews added during this run, and reruns verification. Skipped
required workers produce an incomplete outcome, never a pass.

Workers receive the current risk and route plus `MOREGAN_STAGE_PHASE`:
`standard` or `post_generation_review`. Stage context packs contain the same
`phase`; newly scaffolded Codex/Claude prompts explain how to handle it. Refresh
existing adapter templates deliberately with `--force` only after preserving any
local prompt customizations.

## Trace And Replay

- `plan.json`, `risk.initial.json`, and `context/base.json` preserve intake context.
- `risk.json` and `result.json.risk` contain the final effective classification.
- `risk.attempt<N>.json` records previous, observed and effective risk plus added stages.
- `risk_history.json` and `result.json.risk_history` retain every reassessment.
- `risk.reassessed` events, stage artifacts, and state history record execution order.
- Reports and read-only replay show risk changes; replay loads attempt-specific
  stage results, falling back to embedded results when an attempt file is absent.

The route lists required roles in canonical order. State history and stage order
show when roles actually ran, including post-generation reviews.

## Limits

These remain conservative heuristics, not a semantic security analysis. A path
can cause a false positive, and sensitive behavior in an innocuous-looking file
can be missed. Size estimates are routing signals, not exact change accounting.
Only returned generator attempts trigger reassessment; this does not monitor
concurrent external edits or sandbox provider processes. Existing changes belong
to the same assessed patch and are never reverted by the classifier.
