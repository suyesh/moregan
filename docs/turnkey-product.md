# Turnkey MoreGAN Product Milestones

Agreed product direction, September 27, 2026. These are planned deliverables with
acceptance criteria, not available commands or a production-readiness claim.
M1 is complete in published 1.16.0, with verification in [release status](releases.md).
M2 provider onboarding is next.
See [current capabilities](product-status.md) for runtime behavior
and [ROADMAP.md](../ROADMAP.md) for progress against the original ten items.

## Product Contract

MoreGAN should be useful without making engineers build an agent framework first.
Installation, provider connection and repository checks must be understandable
without writing a JSON bridge or learning the internal stage schema.

```text
Terminal CLI       Codex skill       Claude skill
       \               |               /
        +------- one run request ------+
                       |
        One versioned MoreGAN runtime
        Canonical persona prompts and policy
        Provider adapters + deterministic tools
                       |
        Patch + evidence + truthful outcome
```

The host is the entry point; the configured provider performs the worker calls.
A Codex skill and a Claude skill can use the same provider configuration. If they
use different providers/models, their coding output and judgments can differ.
No promise to reuse a host chat, subscription or authentication beyond supported
provider capabilities. Prerequisites and possible model charges must be explicit.

## M1: Reliable Distribution

- Test the deliberately supported Python/OS matrix; fix incompatibilities or
  narrow metadata instead of advertising unverified support.
- Test a wheel installed outside the checkout, including CLI, skill assets and
  setup/update paths. Keep runtime and installed skill versions compatible.
- Require tests, metadata/version consistency, package validation and installed
  smoke checks before publication. Keep `workflow.yml` for Trusted Publishing.
- Document recovery from a failed install/update without modifying user projects.
- Publication resumed with the maintainer's explicit authorization. Release
  meaningful changes after quality gates; docs-only changes need not be released.

Done when clean supported environments can install and execute the tested package,
and a failed quality gate prevents publication. Depends on no new provider feature.

## M2: No-Glue Provider Onboarding

- Ship native Codex and Claude bridges that invoke documented, version-supported
  noninteractive provider interfaces and normalize their actual outputs. Retain
  the custom command adapter as an advanced option, not the default requirement.
- Preserve strict StageResult validation: malformed, truncated, refused, timed-out
  or missing provider results must not be turned into a fabricated PASS.
- Setup detects missing runtime/provider prerequisites and authentication state
  without printing credentials. With both providers available, offer an explicit
  choice and persist it. With one available, show the selected default.
- Replace the init/activation trap with intentional provider selection: an empty
  generated config can be activated; customized settings are preserved or merged
  with an explicit preview. No manual file copy or environment variable is needed
  for the standard supported path.
- Keep pip installation and skill setup supported. Offer a bootstrap path that
  manages an isolated supported Python environment, with consent, for users who
  do not already have Python. Do not silently alter system Python or install
  provider tools. A skill is not a way to eliminate the runtime dependency.
- Prerequisite diagnostics report the runtime, provider/model, connection status,
  selected workers, required project tools and a concrete next action on failure.
- Test fresh setup, repeat setup, switching providers, missing auth, version
  mismatch and provider failures with fixtures; add opt-in real-provider smoke
  checks before claiming end-to-end live compatibility.

Done when a user with a supported authenticated provider can install, configure,
and complete a small verified change without writing glue code. Depends on M1.

## M3: Skill And CLI Parity

- Install Codex and Claude skills as thin launchers of the same versioned runtime.
  Launch from the target repository, not the skill installation directory.
- Both skills resolve the same request, repo configuration, provider/model, risk
  policy, checks, permissions and retry limits as the CLI. They report the saved
  runtime result instead of writing an independent completion verdict.
- Missing prerequisites produce setup guidance or a failed/incomplete result.
  Remove the competing prompt-only fallback; do not silently bypass runtime gates.
- Reconcile the existing persona files with executable behavior and use one
  canonical prompt composer for every entry point. Include the relevant role
  content when routed, record its version/hash, and bound context deliberately.
  Do not blindly inject stale mandatory-all-persona or rollback instructions.
- Keep adaptive routing. The same task should not run extra personas simply
  because it entered through a skill. A design decision is not a dispatched
  Designer; a claimed readiness threshold needs a typed contract and enforcement.
- Do not auto-commit, publish, merge or deploy just because an old skill document
  says to. Permissions and user approvals are shared runtime inputs.
- Version mismatch must be diagnosed, not silently mixed. Test clean skill
  installation, updates and dispatch for both hosts against the installed wheel.

The automated parity gate uses the same initial repository snapshot, request,
configuration, recorded provider responses and tool outputs through CLI and both
skill launch paths. Compare routes, prompt hashes, attempts, patch hashes,
findings, check outcomes, exit codes and final status after normalizing only
run identifiers, timestamps, durations and temporary paths. Include pass, fail,
incomplete, escalation, remediation and cancellation fixtures.

Identical generated bytes from repeated live models are not a supportable promise.
Parity is identical orchestration and enforcement for identical resolved inputs.
Host-level smoke tests verify actual skill dispatch separately from deterministic
launcher tests. Depends on M2; release fixtures must pass before claiming parity.

## M4: Safe Changes And Recovery

- Generate in run-owned isolated workspaces, including an explicitly recorded
  starting snapshot of relevant pre-existing staged, unstaged and untracked work.
- Verify a candidate before applying it. Reject application if the original
  checkout/index or affected paths changed since the recorded baseline.
- Store the owned patch and pre/post fingerprints. Apply atomically where possible
  and retain recovery evidence when an application is interrupted.
- Automatic rollback means discard an unaccepted candidate or recover a partially
  applied MoreGAN-owned patch when preconditions still match. Undo of an accepted
  change is user-requested and refuses overlapping subsequent edits.
- Never reset the user's branch, clear their index, delete unrelated files or
  restore an entire checkout on a model's recommendation. Conflicts stop for
  human review. Filesystem undo does not reverse migrations or external API effects.
- Test dirty repositories, concurrent edits, staged changes, new files, symlinks,
  cancellation and crashes. Prove unrelated work is preserved on every failure.

Done when failure recovery is tested rather than merely described in YAML.
Depends on M1-M3 and native process supervision on each claimed platform.
Workspace isolation is not an OS sandbox and does not contain arbitrary side effects.

## M5: Bounded Parallelism And Competition

- First run independent reviewers concurrently against the same immutable patch;
  keep stage dependencies and reproducible result aggregation in the runtime.
- Then offer opt-in competing generators with distinct objectives in separate
  workspaces. They must never write simultaneously to the user's checkout.
- Evaluate every candidate against the same independent acceptance checks. A judge
  cannot override a failed required gate. Select an eligible candidate or report
  failure; any synthesized patch goes through all required verification again.
- Bound candidate count, concurrency, wall time and retries. Preserve cancellation,
  cleanup, candidate-specific traces and ownership checks under partial failure.
- Report measured usage when available, with unknown values explicit. A strict
  monetary cap requires provider-enforceable limits or conservative reservations;
  a locally observed token total alone cannot guarantee the final provider bill.
- Require benchmark evidence for quality versus added cost/time before making
  competition a default. Specialized cooperative generators come after safe
  competing candidates, with explicit file ownership and conflict handling.

Depends on M4 and sequential benchmark baselines. This includes original item 7,
but concurrent reviewers and competitive generators are separate acceptance gates.

## M6: Useful Engineering Integrations

- Start with headless CI verification and portable JSON/SARIF-style evidence
  exports tied to an exact commit/patch, rather than many shallow connectors.
- Add GitHub PR and GitLab MR integrations for fetching a requested change and
  attaching verification summaries. Provider tests, authentication scopes,
  retries/idempotency, stale revision detection and redaction are required.
- External writes are disabled unless enabled/approved explicitly; default runs
  do not create issues, publish comments, push branches, merge or deploy.
- Use the same policy and verdicts locally and in CI. Missing credentials or
  provider access must be visible, never replaced with successful empty reviews.
- Keep existing stack-tool commands available. Issue trackers, notifications,
  observability backends and living-documentation automation are later extensions,
  each with an owner, executable adapter and tested permission boundary.

Depends on stable M1-M3 contracts; patch-producing integrations also depend on M4.
Existing external-tools YAML is reference material, not proof of implemented APIs.

## M7: Measured Quality And Efficiency

This work starts with the existing benchmark foundation, not after M6 finishes.
Expand to representative repositories including Java/Spring Boot and real
regressions. Compare baseline and MoreGAN on matched tasks with independent tests,
repeated runs and human review; record quality, false-positive findings, wall time,
tokens and cost. Unknown metrics stay unknown.

Use those results to choose routes and context sizes. Reuse immutable evidence only
when the relevant source, dependencies, tools, configuration and environment keys
match; changed inputs invalidate it. A cached model judgment is not fresh evidence
about a changed patch. Trace cache hits and misses. Keep learning evidence-backed
and calibrate across independent runs before promoting broad recommendations.

Done is measured tradeoffs, not a preset improvement percentage. Hardening and
benefit measurement remain ongoing after the first turnkey release.
