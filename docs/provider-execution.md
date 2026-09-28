# Provider Execution Limits

MoreGAN 1.15.0 uses bounded process I/O for command workers and both Codex/Claude
wrappers. Skills use this same runtime path. No live model call is needed to test
these controls; they apply to local provider commands.

## Configuration

Settings belong to each worker in `.moregan/workers.yaml`:

```yaml
workers:
  - stage: generator
    command: ["python3", "-m", "moregan.agent_worker", "--provider", "codex", "--stage", "generator", "--prompt", ".moregan/adapters/codex/generator.md"]
    timeout_seconds: 600
    max_output_bytes: 1048576
    max_prompt_bytes: 1048576
    no_write: false
    execution: repository
```

| Setting | Default | Accepted Values |
|---|---|---|
| `timeout_seconds` | 120 for custom workers; scaffolds use 600 for generator, 300 otherwise | Integer 1 to 86400 |
| `max_output_bytes` | 1048576 | Integer 1 to 1048576 |
| `max_prompt_bytes` | 1048576 | Integer 1 to 1048576 |

Limits cannot be disabled. Booleans, quoted numbers, unknown fields and duplicate
fields are rejected. Existing configurations inherit defaults without a rewrite.
Avoid `adapters --force` merely to add limits; it replaces local configuration.

The wrapper CLI accepts `--timeout`, `--max-output-bytes`, and `--max-prompt-bytes`.
Defaults inherit `MOREGAN_WORKER_TIMEOUT_SECONDS`, `MOREGAN_MAX_OUTPUT_BYTES`, and
`MOREGAN_MAX_PROMPT_BYTES` set by the outer worker. Standalone defaults are 300
seconds and 1 MiB for each byte limit. Explicit flags may set different inner
limits, but cannot extend the outer worker's deadline or stdout limit.

`max_prompt_bytes` controls the built-in wrapper's UTF-8 stdin prompt, including
the template, runtime context and formatting. Templates must be regular files;
oversized or invalid-UTF-8 templates fail before provider launch. Context packs
remain path references, not automatically inlined files. Arbitrary custom commands
receive the limit in their environment but must implement their own prompt
construction controls. This is not a model token or billing budget.

## Output And Failures

Stdout is the JSON protocol, not a log stream. Both provider boundaries stop on
oversize stdout and fail on invalid UTF-8, malformed JSON or invalid StageResult
fields. A truncated tail is diagnostic only and is **never parsed as a result**.
The limit includes the wrapper's normalized JSON and added evidence; leave room
for that metadata when setting a small outer limit.

Stderr is drained continuously, retaining at most `min(max_output_bytes, 4000)`
bytes. Noisy stderr alone does not fail a successful command. Failure diagnostics
include tails of at most 1000 characters. Successful stages record byte counts
and truncation status, not stderr contents. Provider output can contain sensitive
data: inspect traces before sharing them.

`provider_io` evidence summarizes observed byte counts, stderr truncation, effective
stdout limit, timeout, and `error_kind`; wrapper evidence also includes prompt
bytes. Counts describe captured bytes, not unflushed data in killed processes.
Failures include `output_limit`, `output_encoding`, `input_delivery`, `timeout`,
launch/capture errors, and `cleanup_error`. Strict schema validation and
runtime-owned attempt/timing fields remain unchanged. Structurally valid claims
are still claims, not proof of correctness.

## Deadlines And Cleanup

The executor writes stdin while draining stdout/stderr. Its deadline includes
blocked stdin delivery, waiting for the provider, and inherited output pipes
held open after the parent exits. A provider that closes stdin before the full
prompt is written fails. Successful delivery means bytes reached the pipe, not
that a model actually read or understood them.

On POSIX, the outer command owns a process group. Generated direct Python wrappers
recognize that supervisor and keep their provider in the same group, rather than
creating a detached group. On success, failure, timeout or interruption, the outer
executor kills ordinary descendants and reaps its direct child before workspace
cleanup and no-write verification. A standalone wrapper owns its own provider
group. Long-lived servers are not supported as worker children.

If process cleanup cannot be confirmed, `worker_cleanup_failed` stops the run for
manual inspection, with no generator retry or post-generation diff inspection.
Temporary snapshots are retained and checkout verification is marked unverified.
Ordinary provider failures keep the existing bounded remediation policy.
An interruption still propagates; if cleanup also fails, the snapshot is retained
and a warning reports its path. An interrupted run need not have a finished stage artifact.

Cleanup has a separate bounded wait, so return can be slightly later than the
deadline. OS process creation, template filesystem calls, snapshot preparation,
and checkout scans are not part of the provider subprocess deadline. Scan limits
are documented in [worker workspaces](worker-workspaces.md).

## Platform Scope

Verified on macOS with Python 3.12 and 3.14 using actual subprocesses and simulated
providers, including blocked input, inherited pipes and nested child cleanup.
Windows uses bounded daemon I/O threads and terminates only direct children;
descendant containment and Windows behavior are not yet verified.

This is supervision, **not a sandbox**. POSIX descendants that create a separate
session/group can escape. Custom shell wrappers that relaunch MoreGAN through
extra process layers do not satisfy the generated wrapper's direct-parent
supervisor check; detached nested groups are not covered. The internal supervisor
marker is a cooperation mechanism, not authentication. No global CPU, filesystem,
network or provider memory limit is imposed. Use OS-level isolation for untrusted
provider code; stronger containment and Windows child-tree supervision remain
separate work.
