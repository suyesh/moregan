# MoreGAN Capability Assessment

Reviewed September 27, 2026 against GitHub runtime version **1.15.0**. This is a
source-backed product assessment, not a security certification or a live-agent
effectiveness study. PyPI still contains **1.5.0**; see [release status](releases.md).

## Bottom Line

MoreGAN is now a real, local orchestration and verification runtime. Engineers can
configure coding-agent commands, route reviews by patch risk, enforce selected
tests, repair verification failures and inspect the resulting evidence.

The largest adoption gap is **getting a real provider connected correctly**.
The project supplies stage prompts and process wrappers, but expects users to
provide a bridge that turns their agent's native output into StageResult JSON.
It is suitable for engineers willing to configure that boundary; it is not yet a
one-command, ready-to-use coding agent for everyone.

## Implemented Today

| Capability | What actually runs | Boundary / caveat |
|---|---|---|
| State machine | Python controls ordered transitions and terminal results | Persisted states are not an implemented resume feature |
| Worker roles | Local commands and generated Codex/Claude stage templates | Sequential; provider configuration is required |
| Strict results | Shared JSON/schema validation, runtime-owned timing/attempts | Proves shape/consistency, not truth of model claims |
| Adaptive routing | Request keywords plus Git paths/size, reassessed after generation | Conservative heuristics; no-Git projects are request-only |
| Verification | Builtin and configured commands with exit codes and output evidence | Detected stack presets are optional by default |
| Remediation | Review/check failures after generation can feed back into bounded retries | Generator/early-review/integrity failures stop; default retry limit is three |
| Workspace guards | Disposable review copies and original-checkout content/index checks | No rollback; exclusions apply; not a sandbox |
| Process limits | Bounded JSON, stderr tails, prompt input, deadlines and ordinary POSIX group cleanup | Windows child trees and escaped groups remain uncontained |
| Context curation | Bounded stage summaries, evidence and local lesson excerpts | Estimates, not measured savings or a provider billing budget |
| Traces/replay | Requests, risk/state history, attempt results, reports and read-only reconstruction | Replay does not rerun or resume work |
| Learning | Run-linked observations and aggregate pattern statistics | No trained weights, demonstrated generalization or calibrated success probability |
| Benchmarks | Six Python fixtures, independent acceptance checks and paired comparisons | Foundation only; no representative live-agent benefit measurement |
| CLI/skills | CLI, installation/maintenance commands, skill runtime-launch guidance | Skill prompt-only fallback is not runtime-equivalent |

Source map: [runtime](../moregan/runtime.py), [state](../moregan/state.py),
[schemas](../moregan/schemas.py), [workers](../moregan/workers.py),
[adapter templates](../moregan/adapters.py), [provider wrapper](../moregan/agent_worker.py),
[tools](../moregan/tools.py), [processes](../moregan/processes.py),
[workspaces](../moregan/workspaces.py), [context](../moregan/context.py),
[learning](../moregan/learning.py), [replay](../moregan/replay.py),
[benchmarks](../moregan/benchmarks.py), [CLI](../moregan/cli.py).

## Which Personas Run?

The runtime route, not the existence of a persona markdown file, determines work:

| Risk | Canonical route |
|---|---|
| Low | Generator, deterministic evidence, Evaluator |
| Medium | Planner, Generator, deterministic evidence, Evaluator, Code Reviewer |
| High | Planner, Architect, Generator, deterministic evidence, Evaluator, Security, Code Review, Production, MR Readiness, Learning Curator |
| Critical | High route plus Designer decision before Generator |

Risk can escalate after generation, adding catch-up reviews before verification.
The Designer decision is not a dispatched Designer implementation stage. The MR
role has no typed numeric score or runtime-enforced 70/100 threshold. Automatic
learning-artifact collection runs separately from whether the Learning Curator
worker is routed. See [worker contract](worker-contract.md).

Full installed persona files and generated runtime prompts are different assets.
Runtime templates currently use short objectives from `adapters.py`, not automatic
inclusion of `personas/*.md`. A configured command can use those files, but MoreGAN
does not ensure it does. Calling these separate roles is accurate; claiming all
rich persona instructions run automatically on every task is not.

## Findings From This Audit

1. **Onboarding can leave all workers disabled.** `init` creates `workers: []`;
   `adapters --activate` intentionally preserves an existing config. The previous
   README's sequence therefore did not reliably activate workers. Documentation
   now shows deliberate template selection; runtime behavior is unchanged.
2. **Provider integration is not turnkey.** Environment variables previously
   looked like raw CLI shortcuts. The guides now state the bridge contract and
   provide a no-model probe that reports skip honestly. Native provider stream
   adapters and end-to-end live-agent tests are still missing.
3. **Skill instructions still conflict with runtime scope.** `SKILL.md` prefers
   the runtime, but its older body mandates all personas, parallel work, numeric
   readiness gates, automatic commits and rollback. Those are not runtime
   guarantees. Make the skill a concise launcher with canonical runtime behavior,
   and clearly separate or remove incompatible fallback instructions.
4. **Installed configuration is sometimes descriptive, not executable.** YAML
   for multi-generator collaboration, automatic rollback, enterprise integrations
   and living documentation is not an implemented runtime subsystem. Some local
   knowledge files can be included as context excerpts; that does not execute
   their policy. Unsupported feature claims were removed from INSTALL.md.
5. **Verification strength depends on project setup.** Optional audits do not gate
   a pass, a command can discover zero tests, and a worker can assert inspection
   without proving it. Required acceptance checks and meaningful coverage matter
   more than adding another persona. Default snapshots also exclude Git history
   and dependency directories, which limits Git/build-based reviewer commands.
6. **Distribution and support claims are ahead of validation.** PyPI is ten minor
   versions behind source. Publishing has no test gate, Python 3.8 metadata
   conflicts with an installer method, and setup scripts still display 1.5.0.
   The full Python/OS matrix is not validated. Release CI is the next milestone.
7. **There is no measured proof of net benefit yet.** Runtime tests and fixture
   solutions verify plumbing; they do not demonstrate better coding outcomes,
   lower token use, or acceptable latency/cost with live providers.

These findings should not be confused with resolved runtime issues recorded in
[the earlier engineering review](review-2026-09-27.md).

## What Users Should Try

Start on a small repository with a known test suite. Install the GitHub version,
initialize config, verify the provider boundary with the skip-only probe, then
connect a real bridge. Promote essential checks to required and try a narrowly
scoped bug fix with one repair attempt. Inspect the actual patch, test output and
trace before accepting it. Use the same runtime path from the skill.

Good early users are engineers building custom coding-agent workflows, teams
wanting inspectable review evidence, and maintainers evaluating verification
overhead. Do not yet rely on MoreGAN for unattended production changes, automatic
merge/deployment, untrusted-code isolation or guaranteed security approval.

## Next Priorities

1. Test-gated packaging/releases and an honest supported Python/platform matrix.
2. Native provider bridges, safer activation UX and one runtime-consistent skill contract.
3. Windows child-tree cleanup and stronger process isolation where required.
4. Representative paired benchmarks with actual token/cost/time and human review data.
5. Only then expand competitive generators or tune routing from measured benefit.

The original ten-item tracker remains in [ROADMAP.md](../ROADMAP.md). This audit
changes documentation and adds documentation checks; it does not claim to have
implemented the missing runtime features or published a new package.

## Evidence

Before this documentation audit, the 1.15.0 runtime passed 200 tests on macOS with
Python 3.12.11 and 3.14.0, plus 28 installed-wheel process tests and simulated
Codex/Claude CLI smoke tests. After this audit, 203 tests pass on both Python
versions, including three documentation tests in `tests/test_documentation.py`.
Those execute the preview/probe flow for both adapters and a Python check;
Maven examples are config-validated, not tested against a Java application.
The rebuilt wheel/sdist includes all new guides. No paid/live model comparison
was performed.
