# Getting Started

This guide describes the GitHub 1.15.0 runtime, not the older 1.5.0 PyPI release.
Install it using [INSTALL.md](../INSTALL.md), keep its virtual environment active,
and run these commands in your application repository. Start with a disposable
project when trying a new provider bridge. Never point an untrusted command at
credentials or valuable work.

## 1. Initialize And Inspect

```bash
moregan init
moregan run "Change button label" --no-checks
moregan inspect latest
moregan replay latest
```

Fresh initialization creates `.moregan/tools.yaml`, an empty `.moregan/workers.yaml`,
and local run/learning directories. It preserves existing configs and adds
generated-output exclusions to `.gitignore`. Review the actions it prints.

With no configured workers, this preview ends **INCOMPLETE**, exit **1**. That is
expected: no generator or evaluator executed. `--no-checks` does not disable
workers once configured; it must not be used as a general dry-run flag.

To target a different directory, put the global option before the command:

```bash
moregan --root /absolute/path/to/project init --dry-run
```

## 2. Select A Worker Template

Choose Codex or Claude; do not activate both configurations in succession:

```bash
moregan adapters codex
cp .moregan/workers.codex.yaml .moregan/workers.yaml
```

For Claude, substitute `claude` in both paths/commands. The copy above is appropriate
only when selecting a template for the fresh empty config. For existing customized
workers, inspect/merge individual entries instead of overwriting them.

Why not simply `moregan adapters codex --activate` after `init`? Activation
preserves any existing worker config, including the empty one. It reports a
skipped write. `--force` can replace both worker configs and customized prompt
files, so do not use it casually. On a new project, running `adapters --activate`
before `init` is another option; `init` then preserves the selected workers.

Generated prompts live in `.moregan/adapters/<provider>/`. Each configured stage
launches a separate command through `moregan.agent_worker`; roles run sequentially.

## 3. Check The Provider Boundary Without A Model

The following optional `probe.py` demonstrates the exact stdin/stdout interface.
It **does not implement or review anything** and deliberately returns `skip`,
never a fake pass. No model credentials or network calls are used by the probe.

<!-- provider-probe -->
```python
import json
import os
import sys

prompt = sys.stdin.read()
print(json.dumps({
    "stage": os.environ["MOREGAN_STAGE"],
    "verdict": "skip",
    "confidence": 1.0,
    "evidence": [{
        "kind": "probe",
        "name": "stdin_received",
        "summary": f"Received {len(prompt.encode('utf-8'))} prompt bytes; no model work performed."
    }]
}))
```

Point the selected provider variable to the actual absolute path of that script:

```bash
export MOREGAN_CODEX_COMMAND='["python3", "/absolute/path/to/probe.py"]'
moregan run "Change button label" --no-checks --max-remediation-attempts 0
moregan inspect latest
```

Use `MOREGAN_CLAUDE_COMMAND` for Claude. JSON argument lists handle spaces in
paths without shell quoting ambiguity. Commands are not evaluated by a shell.
Absolute bridge paths work even when review workers execute inside snapshots.

Expected outcome: **INCOMPLETE**, with `stdin_received` evidence and provider I/O
counts for routed workers. This tests wiring, not software quality. Unset the
probe variable or replace it before expecting implementation work.

## 4. Connect Your Real Agent

Replace the probe with a bridge that:

1. Reads the entire prompt from stdin and honors the supplied stage/no-write role.
2. Runs your authenticated coding-agent command with its model and permission settings.
3. Converts that provider's output into one valid MoreGAN StageResult object.
4. Writes protocol JSON to stdout and diagnostic logs to stderr.

MoreGAN ships prompt templates and process supervision, not a ready-to-use bridge
for each provider's native stream/event format. Merely setting the variable to
`codex` or `claude` does not establish this contract. Check
[worker output requirements](worker-contract.md) and
[execution limits](provider-execution.md) before connecting a live provider.

No-write workers use snapshots without `.git` and common dependency/build dirs.
Commands that need Git history or installed repository dependencies need deliberate
configuration. Deterministic checks run in the real project directory. Neither
path is an OS sandbox; provider costs and remote data handling belong to your
chosen command and service.

## 5. Make Project Checks Meaningful

Review `.moregan/tools.yaml`. Initialization includes builtins for whitespace,
Python compilation and unittest discovery, plus matching stack presets. It is
not a comprehensive build system detector. In particular, `unit_tests` means
Python unittest discovery when `tests/` exists, not every language's test runner.

Detected stack presets are enabled but **optional**. A failed optional check is
reported without blocking a pass; absent optional executables skip. Make your
actual acceptance tests and required security checks blocking. Remove or disable
irrelevant defaults after reviewing the generated config.

Example required Python unittest check (a complete minimal tools config):

<!-- required-python-check -->
```yaml
version: 1
commands:
  - name: application_tests
    command: ["python3", "-m", "unittest", "discover", "-s", "tests"]
    category: tests
    required: true
    timeout_seconds: 300
    max_output_bytes: 4000
    remediation: "Fix the failing application tests."
```

For pytest, use `["python3", "-m", "pytest"]`. Ensure tests are actually discovered:
an exit code of zero from an empty suite is not proof that a feature works.

### Java And Spring Boot

Maven/Gradle detection can suggest tests and configured Checkstyle, SpotBugs, PMD
and OWASP Dependency-Check tasks. MoreGAN does not add those plugins to your build.
Inspect the suggestions and mark the appropriate checks required.

Example Maven config, **only if your project already provides Checkstyle**:

<!-- required-maven-checks -->
```yaml
version: 1
commands:
  - name: maven_verify
    command: ["./mvnw", "verify"]
    category: tests
    required: true
    timeout_seconds: 900
    max_output_bytes: 16000
    remediation: "Fix the failing Maven lifecycle goal."
  - name: checkstyle
    command: ["./mvnw", "checkstyle:check"]
    category: lint
    required: true
    timeout_seconds: 300
    max_output_bytes: 8000
    remediation: "Fix the reported Checkstyle violations."
```

Do not duplicate the second command if your `verify` lifecycle already enforces
Checkstyle. Use `mvn` if no wrapper exists. With Gradle, configure your actual
`./gradlew check`, `checkstyleMain`, `checkstyleTest` or other available tasks.
Wrappers, a JDK, dependencies and plugin configuration must already work locally.
These example commands assume a POSIX shell environment; Windows wrapper names
need explicit configuration and native verification.

## 6. Run And Inspect

```bash
moregan run "Fix checkout validation" --max-remediation-attempts 1
moregan status
moregan inspect latest --json
moregan replay latest
```

The generator is write-enabled by default. Review findings after generation can
trigger repair, risk reassessment and fresh verification. The default is three
remediation attempts. Generator failures, pre-generation blocking reviews and
workspace/process cleanup failures stop rather than automatically retrying.

`result.json` and `final_report.md` summarize the outcome. Attempt-specific stage
files, state/event logs, risk history, context packs and `learning.json` preserve
the record. `inspect` and `replay` are read-only and return zero on successful
inspection even when the stored run failed. Replay does not resume execution.

For repeated measurement on isolated fixtures, see [benchmarks](benchmarks.md).

## Troubleshooting

| Symptom | Check |
|---|---|
| Every role skips | Confirm `workers.yaml` is populated and the selected provider variable reaches the agent terminal |
| Activation did nothing | `init` already created a config; inspect/merge the generated provider template |
| Import/module error | Keep the MoreGAN venv active; generated wrappers invoke `python3` |
| Invalid JSON | The bridge must emit one StageResult, not markdown, progress text or provider-native JSON events |
| Oversize output or prompt | Inspect `provider_io` evidence and configured byte limits; shorten the result/context |
| Tests failed but run passed | Check `required: true`; optional preset failures are advisory |
| No checks ran | Empty/all-skipped checks or `--no-checks` produce incomplete, not pass |
| Reviewer cannot use Git/dependencies | Default snapshots exclude `.git`, `.venv`, build and dependency directories |
| `no_write_violation` | Inspect original checkout changes; MoreGAN did not revert them |
| Cleanup could not be confirmed | Stop and inspect the reported processes/snapshot before another run |
| Skill and CLI differ | Check installed copies, Python paths and environment variables; prompt-only fallback is not runtime parity |
| pip still shows 1.5.0 | That is the current published release; use the GitHub installation for 1.15.0 |

Use `python -c "import os; print(bool(os.environ.get('MOREGAN_CODEX_COMMAND')))"`
inside the agent terminal to check visibility without printing credentials.
`moregan setup doctor --check` checks skill installation files, not model access.
