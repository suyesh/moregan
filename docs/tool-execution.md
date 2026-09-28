# Deterministic Check Execution

MoreGAN 1.13.0 bounds deterministic command execution. This covers explicit
commands, builtins, and detected stack presets, not model-provider commands.

## Configuration

In `.moregan/tools.yaml`:

```yaml
version: 1
commands:
  - name: java_verify
    command: ["./mvnw", "verify"]
    category: tests
    required: true
    timeout_seconds: 900
    max_output_bytes: 16000
    remediation: "Inspect the failing Maven goal and fix the build."
```

Use commands appropriate for your build; Maven `verify` only executes the checks
configured in that project's lifecycle. A Gradle check or configured Checkstyle,
SpotBugs, PMD, or dependency audit uses the same execution limits.

| Setting | Default | Accepted Values |
|---|---|---|
| `timeout_seconds` | 300 | Integer 1 through 86400 |
| `max_output_bytes` | 4000 | Integer 1 through 1048576, per stream |

Limits cannot be disabled. Quoted numbers, booleans, negative values, duplicate
command names/fields, unknown fields and malformed commands fail configuration
before any check executes. `moregan init` writes the defaults into new configs;
existing configs inherit defaults without being rewritten. Do not use `--force`
just to add these fields: that replaces local configuration.

## Evidence And Outcomes

Both output streams are continuously drained, retaining only a bounded byte tail.
There is no unlimited in-memory buffer or spill file. UTF-8 decoding replaces
invalid bytes; a tail may begin in the middle of a character or line. Output
truncation alone does not fail a command; the exit code remains authoritative.

`CommandEvidence` includes `timed_out`, `error_kind`, `reason`, effective limits,
`stdout_bytes`, `stderr_bytes`, and per-stream truncation flags. Counts describe
bytes actually captured, not bytes a killed process might still have buffered.
Launch diagnostics are separate from child-output byte counts.

- Exit 124 with `timed_out: true` means the deadline expired.
- Exit 127 with `error_kind: not_found` means the executable was unavailable.
- Exit 126 with `error_kind: launch_error` covers other launch failures.
- Exit 125 covers capture, cleanup, or incomplete discovery failures.
- Ordinary process exits retain their code; inspect `error_kind` to distinguish
  a command that itself exits with one of these numbers.

A required failure enters the existing bounded remediation loop. Optional
failures are advisory findings, not successes for that command. A missing optional
executable is skipped. A gate where all commands skip remains incomplete.
Timeout details reach generator remediation context, stage context packs,
JSON artifacts, the final report, and read-only replay.

Python compilation discovers tracked/untracked files through a NUL-delimited Git
listing, with a deadline of at most 30 seconds and a 1 MiB capture cap. Discovery
failure or truncation fails the check; MoreGAN never silently compiles a partial
list. The compilation subprocess has its own configured deadline. Non-Git file
discovery uses the local filesystem and excludes common build/environment dirs.

## Cleanup And Limits

On POSIX, each check starts a new session/process group. MoreGAN kills that group
on completion, timeout, capture error, or interruption, and waits for the direct
child. This includes normal descendants and a parent that exits while a child
still holds an output pipe. Stdin is closed; commands must be non-interactive.
Long-lived servers should not be launched as checks.

The deadline includes waiting for output pipes to close. Cleanup has a separate
bounded wait, so return can occur slightly after the configured deadline. OS-level
process creation and non-Git filesystem traversal are not independently timed.

This is resource supervision, not a sandbox. A process that starts a separate
session can escape POSIX group cleanup. Windows currently terminates only the
direct child and uses bounded daemon readers; descendants can survive or hold
pipes open. Windows process-tree containment and the full platform matrix remain
unverified. Provider workers still use their existing timeout/capture path and
do not yet share these output bounds. No claim of global CPU, disk, memory, or
network containment is made.
