# Worker Contract

There are two supported boundaries:

- **Custom worker:** `.moregan/workers.yaml` directly launches your command. It
  receives `MOREGAN_*` environment context and returns StageResult JSON. Stdin is
  closed; this path does not automatically construct a persona prompt.
- **Codex/Claude template:** the configured command launches `moregan.agent_worker`,
  which builds a prompt from the generated stage template and runtime context,
  sends it to the selected provider bridge on stdin, validates its result and
  returns normalized JSON. The outer worker validates that result too.

See [getting started](getting-started.md) for activation and a no-model probe.

## StageResult JSON

<!-- stage-result -->
```json
{
  "stage": "evaluator",
  "verdict": "fail",
  "confidence": 0.9,
  "findings": [{
    "severity": "high",
    "category": "missing_regression_test",
    "description": "The changed validation branch has no regression test.",
    "remediation": "Add a test that fails before the fix and passes afterward.",
    "file": "tests/test_checkout.py",
    "line": 42
  }],
  "evidence": [{
    "kind": "review",
    "name": "validation_branch",
    "summary": "Inspected the changed validation branch and its tests."
  }]
}
```

- `stage` must match the requested known role.
- `verdict` is exactly `pass`, `fail` or `skip`.
- `confidence` is a finite number between 0 and 1, not a string or boolean. It is
  a worker-provided assertion, not a calibrated runtime probability.
- Findings/evidence may be omitted as empty lists. Supplied entries must validate.
- Severity is `critical`, `high`, `medium`, `low` or `info`. Critical/high findings
  require `fail`; the runtime does not impose a blanket medium-severity failure.
- Finding category, description and remediation must be nonempty strings. File
  is a nonempty string or null; line is a positive integer or null.
- Evidence requires nonempty kind/name/summary; path and an argument-list command
  are optional. An evidence description does not prove a tool was executed.
- Runtime owns attempts and timing. Do not supply conflicting metadata.
- Unknown fields, duplicate keys, surrounding prose, markdown fences, invalid
  UTF-8 and oversized stdout fail. A top-level `score` field is not supported.

`mr_readiness_analyzer` currently uses this same contract: any numeric readiness
assessment can only be expressed as evidence prose, not a typed score with a
runtime-enforced threshold. `designer_decision` records a decision; the runtime
does not automatically dispatch a separate Designer worker afterward.

## Runtime Context

Useful environment keys include `MOREGAN_STAGE`, `MOREGAN_STAGE_PHASE`,
`MOREGAN_REQUEST`, `MOREGAN_RISK_LEVEL`, `MOREGAN_ROUTE`, `MOREGAN_ATTEMPT`,
`MOREGAN_NO_WRITE`, `MOREGAN_REMEDIATION_CONTEXT`, `MOREGAN_CONTEXT_PACK`,
`MOREGAN_CONTEXT_TOKENS`, `MOREGAN_EXECUTION_MODE` and `MOREGAN_EXECUTION_ROOT`.

The stage context pack contains capped summaries of prior results, repository
context, deterministic evidence, risk and relevant local lessons. A provider must
actually read it when needed. Token estimates are approximate; MoreGAN does not
enforce a model token/cost budget or transparently cache model responses.

Generated stage prompts use objectives defined in `moregan/adapters.py`. They do
not automatically load the complete installed `personas/*.md` text. To use richer
persona guidance in runtime workers, deliberately customize the generated prompts
or your bridge. Refreshing templates with `--force` can overwrite customization.

## Trust And Execution

The runtime validates the contract, but cannot prove that an agent genuinely
reviewed the patch, ran the reported commands, or followed no-write instructions.
Deterministic command evidence is collected separately. Use meaningful required
checks and human review rather than treating confidence or prose as proof.

Review snapshots are disposable copies, not hardened sandboxes. Consult
[workspace coverage](worker-workspaces.md) and [provider limits](provider-execution.md)
for exclusions, process-group scope, deadlines and retained-snapshot failures.
