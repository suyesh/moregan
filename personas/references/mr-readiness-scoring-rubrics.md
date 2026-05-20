# Local Git MR Readiness Scoring Rubrics

Default to skepticism. A score above 70 must be earned with concrete local evidence.

## Commit Story - 35%

Evaluate commit message quality, WIP/fixup commits, logical progression, number of commits relative to change size, and whether the branch looks like an organized submission or a scratchpad.

- 90-100: Commits tell a clear development story. Each commit is a logical unit with a descriptive message.
- 70-80: Mostly clean history. Messages are reasonably descriptive with minor organization issues.
- 50-69: Generic messages or messy history. Some fixup commits should have been squashed.
- 30-49: Single large vague commit or a series of meaningless messages.
- 10-29: Multiple WIP/fixup commits left unsquashed.
- 0-9: Entire history is WIP/update commits or a single dump with no meaningful message.

## Change Scope - 30%

Evaluate total lines changed, files changed, concern focus, file type distribution, and whether the change should be split before opening an MR.

- 90-100: Tightly scoped, focused, easy to review, usually under 200 lines.
- 70-80: Reasonable size, roughly 200-400 lines, one clear concern.
- 50-69: Large, roughly 400-700 lines, probably could be split.
- 30-49: Very large or mixes multiple unrelated concerns.
- 10-29: Massive 1000+ line change that is hard to review in one pass.
- 0-9: Extreme 2000+ line dump.

## Self-Review Signals - 20%

Evaluate TODO/FIXME/HACK comments, debug statements, commented-out code, test presence, file organization, and whether the diff appears self-audited.

- 90-100: No debug artifacts, tests included, clean organization.
- 70-80: Minor self-review gaps.
- 50-69: Some debug artifacts, TODOs, or missing tests for new behavior.
- 30-49: Multiple self-review gaps.
- 0-29: Clearly unaudited submission.

## Local Validation Evidence - 15%

Evaluate whether the branch has evidence of local tests, lint, typecheck, build, or domain-specific validation in `.harness/progress.md`, task plans, command output, or commit messages.

- 90-100: Relevant tests and quality gates were run and passed, with specific evidence.
- 70-80: Core validation passed, with minor gaps such as no full-suite run for a narrow change.
- 50-69: Some validation evidence exists, but important checks are missing or vague.
- 30-49: Minimal evidence, such as only a syntax check or unverified manual inspection.
- 10-29: Validation was skipped, failed, or only implied.
- 0-9: No validation evidence and no explanation.

## Calibration Example

Large feature branch with several WIP commits, 30+ changed files, TODOs in new code, and no test evidence:

- Commit Story: 8
- Change Scope: 15
- Self-Review Signals: 20
- Local Validation Evidence: 5
- Overall: about 14 after hard-rule caps

The author should squash or rewrite commits, split the change, remove unfinished artifacts, and run validation before opening an MR.
