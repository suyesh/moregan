# MoreGAN

[![Publish to PyPI](https://github.com/suyesh/moregan/actions/workflows/workflow.yml/badge.svg)](https://github.com/suyesh/moregan/actions/workflows/workflow.yml)
[![PyPI version](https://img.shields.io/pypi/v/moregan)](https://pypi.org/project/moregan/)

<p align="center">
  <img src="https://raw.githubusercontent.com/suyesh/moregan/main/assets/moregan.png" alt="MoreGAN logo" width="520">
</p>

<p align="center">
  <strong>Implementation and verification should be separate jobs.</strong><br>
  Generator builds. Reviewers challenge. Tools check. Python controls the loop.
</p>

MoreGAN is a local Python runtime for orchestrating coding-agent commands. It
selects review stages from task and patch risk, runs your tests and checks, feeds
blocking findings back to the generator, and preserves a trace for human review.

**Status: alpha.** The runtime is executable and tested; provider setup is still
manual. Installing MoreGAN does not automatically connect Codex or Claude, and a
passing run is not a guarantee that the code is correct.

**Distribution status, checked September 27, 2026:** GitHub contains **1.15.0**;
[PyPI](https://pypi.org/project/moregan/) contains **1.5.0**. The newer runtime
features below require the GitHub version. Pushing to `main` does not publish to
PyPI. See [release status](https://github.com/suyesh/moregan/blob/main/docs/releases.md).

## What You Can Do

| Engineering task | What MoreGAN provides |
|---|---|
| Implement a fix or feature | A configured generator command, followed by separately invoked verification workers |
| Enforce project checks | Required tests, lint, type checks and security commands with exit-code evidence |
| Review sensitive changes | More review roles when auth, payments, migrations, dependencies or other risk signals appear |
| Repair a failed verification | Bounded generator retries with structured findings and fresh checks |
| Understand a run | Stage results, command output tails, risk changes, context packs and read-only replay |
| Evaluate the extra overhead | Six starter benchmark fixtures and paired generator-only versus MoreGAN reports |

Roles run **sequentially** today. Separate worker invocations do not guarantee
independent reasoning or different models. MoreGAN does not train a model:
**GAN means Generative Adversarial Network**, and the name borrows the adversarial
idea, not GAN training.

## Install

For the current GitHub implementation, use a virtual environment. These commands
are for macOS/Linux shells; use Python 3.12 or 3.14 for the locally tested path.

```bash
git clone https://github.com/suyesh/moregan.git
cd moregan
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
moregan --help
```

Keep that environment active when working in another repository. Git is needed
for diff-aware routing and benchmarks. Install your project's build/test tools
and your chosen provider command separately.

To install the **older published release** instead:

```bash
python3 -m pip install --upgrade moregan
```

That currently installs 1.5.0, not this README's 1.15.0 functionality. Metadata
advertises Python 3.8+, but the full support matrix is not certified and the
installer has a known Python 3.8 incompatibility. Windows process-tree cleanup is
unfinished. See [installation details](https://github.com/suyesh/moregan/blob/main/INSTALL.md).

## First Run

### Inspect The Workflow Without A Provider

In a disposable project or your target repository:

```bash
moregan init
moregan run "Change button label" --no-checks
moregan inspect latest
moregan replay latest
```

With the freshly created empty worker config, this produces **INCOMPLETE** and
exit code **1**. It writes a trace but generates no code. `--no-checks` disables
deterministic checks, not configured workers; it is **not a dry-run switch**.

### Connect Real Workers

For a freshly initialized repository, choose one provider:

```bash
moregan adapters codex
cp .moregan/workers.codex.yaml .moregan/workers.yaml
```

The copy deliberately replaces the empty config created by `init`. If you already
have customized workers, merge the template instead. `adapters --activate`
preserves an existing `workers.yaml`; it will not silently switch providers.

Set the command for **your own provider bridge**. This is a configuration example,
not an included script:

```bash
export MOREGAN_CODEX_COMMAND='["python3", "/absolute/path/to/your_provider_bridge.py"]'
```

For Claude, scaffold/copy `workers.claude.yaml` and use
`MOREGAN_CLAUDE_COMMAND`. The bridge must read the prompt from stdin, invoke your
configured agent, and print exactly one MoreGAN `StageResult` JSON object.
Setting the variable to bare `codex` or `claude` is not sufficient by itself.
Authentication and model selection belong to that command, not to MoreGAN.

Review `.moregan/tools.yaml`, mark your essential checks `required: true`, then:

```bash
moregan run "Fix checkout validation" --max-remediation-attempts 1
moregan status
moregan inspect latest
moregan replay latest --json
```

The [step-by-step guide](https://github.com/suyesh/moregan/blob/main/docs/getting-started.md)
includes a runnable, no-model provider probe, Java examples and troubleshooting.
The [worker contract](https://github.com/suyesh/moregan/blob/main/docs/worker-contract.md)
defines the provider boundary.

## How It Works

```text
Request + current diff
        |
   Initial risk route
        |
   Planning/review roles, when routed
        |
     Generator <----------------------+
        |                             |
   Inspect actual patch               |
   Escalate risk / add reviews         |
        |                             |
   Deterministic checks + reviewers    |
        |                             |
   Blocking finding -> bounded repair-+
        |
   PASS / FAIL / INCOMPLETE
        |
   Report + trace + learning observations
```

Python owns the transitions and retry budget. Risk is reassessed after generation
and cannot decrease during the same run. Newly required early reviews inspect
the existing patch. Generator failures, early review failures, and integrity or
cleanup failures are not automatically retried. See [routing policy](https://github.com/suyesh/moregan/blob/main/docs/risk-routing.md).

| Result | Meaning | Run exit code |
|---|---|---|
| `pass` | All routed workers passed, at least one check ran, and no required check failed | 0 |
| `fail` | A blocking check, worker or runtime guard failed | 1 |
| `incomplete` | No blocking failure, but required work was skipped | 1 |

Detected stack checks are **optional by default**. Optional failures do not block
a pass; make essential tests and security checks required. Syntax or whitespace
checks alone are not meaningful application acceptance tests.

## Supported Checks

MoreGAN detects project files and proposes/enables applicable commands. It does
not install tools, configure build plugins, or guarantee coverage.

| Stack | Examples of detected checks |
|---|---|
| Python | pytest, Ruff, mypy, Bandit, pip-audit |
| Node | npm test, lint/typecheck scripts, npm audit |
| Java / Spring Boot | Maven/Gradle tests, configured Checkstyle, SpotBugs, PMD, OWASP Dependency-Check |
| Ruby / Rails | RSpec, RuboCop, Brakeman, bundler-audit |
| Go | go test, go vet, staticcheck |
| Rust | cargo test, cargo clippy, cargo audit |

Any trusted command can be configured with argument lists. Check deadlines,
bounded logs and required/optional semantics are documented in
[tool execution](https://github.com/suyesh/moregan/blob/main/docs/tool-execution.md).

## Codex And Claude Skills

Skill installation is optional for CLI use:

```bash
moregan setup --target codex
# Or: moregan setup --target claude
```

Ask Codex to `Use MoreGAN to fix checkout validation`, or invoke the Claude skill
with `/moregan "Fix checkout validation"`.

The intended path is **skill -> same Python runtime -> configured workers**.
The skill does not remove the Python/provider requirements or reuse the current
chat as a worker automatically. Provider environment variables must be available
to the agent's terminal process. The prompt-only fallback is not equivalent to
runtime enforcement, and older fallback instructions still need alignment with
adaptive routing. See the [capability assessment](https://github.com/suyesh/moregan/blob/main/docs/product-status.md).

## Evidence And Safety

Runs live in `.moregan/runs/<run-id>/`: `result.json`, `final_report.md`, stage and
attempt files, risk history, state/events logs, context packs and `learning.json`.
`inspect` and `replay` read saved artifacts without invoking providers again.
Replay is **not resume**. Learning stores run-backed observations, not trained weights.

Review workers normally use disposable snapshots. MoreGAN compares the original
checkout before/after no-write workers without reverting user work. Provider JSON
and prompt limits default to 1 MiB; deterministic check tails default to 4,000
bytes. Ordinary POSIX descendants are cleaned up before workspace verification.

These controls are **not a sandbox**. Commands can access credentials, network and
files with your permissions. Escaped POSIX groups and Windows descendants remain
limitations. Traces may contain sensitive output. Snapshot exclusions, scan limits
and cleanup-failure policy are in [worker workspaces](https://github.com/suyesh/moregan/blob/main/docs/worker-workspaces.md)
and [provider execution](https://github.com/suyesh/moregan/blob/main/docs/provider-execution.md).

## Learn More

- [Getting started and troubleshooting](https://github.com/suyesh/moregan/blob/main/docs/getting-started.md)
- [Current capabilities, gaps and priorities](https://github.com/suyesh/moregan/blob/main/docs/product-status.md)
- [Planned turnkey installation, skill parity, safe rollback and parallel generators](https://github.com/suyesh/moregan/blob/main/docs/turnkey-product.md)
- [Worker JSON contract](https://github.com/suyesh/moregan/blob/main/docs/worker-contract.md)
- [Benchmarks and measurement limits](https://github.com/suyesh/moregan/blob/main/docs/benchmarks.md)
- [Roadmap and original ten-item tracker](https://github.com/suyesh/moregan/blob/main/ROADMAP.md)
- [Release status and PyPI publishing](https://github.com/suyesh/moregan/blob/main/docs/releases.md)

## Development

```bash
uv sync
uv run python -m unittest discover -s tests -q
uv run python -m compileall -q install.py moregan tests
git diff --check
```

Runtime tests use local subprocesses and simulated providers. No measured
improvement over standalone agents is claimed. Competitive generators, native
provider bridges, release CI and stronger containment remain work to do.

The product target is easy installation with built-in provider connections and
the same runtime enforcement from CLI, Codex skill and Claude skill. Safe rollback,
parallel generators and CI/PR integrations are explicit roadmap milestones, not
current features. Parity means the same prompts, checks and verdict rules, not
identical code from different models or repeated live generations.

## License

MIT. See [LICENSE](https://github.com/suyesh/moregan/blob/main/LICENSE).
