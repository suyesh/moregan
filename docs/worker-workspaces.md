# Worker Workspaces And No-Write Checks

MoreGAN 1.14.0 manages worker snapshots and verifies checkout integrity. These
controls detect mistakes; they are not a sandbox or a guarantee against hostile
code running with the user's permissions.

## Execution Modes

| Setting | Execution Directory |
|---|---|
| `execution: auto`, `no_write: true` | Temporary repository copy |
| `execution: auto`, `no_write: false` | Original checkout |
| `execution: isolated` | Temporary copy, regardless of `no_write` |
| `execution: repository` | Original checkout, regardless of `no_write` |

`no_write: true` checks the **original checkout** in both execution modes. Writes
inside a temporary copy are disposable and do not themselves cause a violation.
`no_write: false` disables checkout integrity checks, not snapshot cleanup.

## Snapshot Lifecycle

Every isolated worker invocation owns a fresh temporary parent directory. MoreGAN
removes only that directory in a `finally` path, including success, provider
failure, malformed output, reported timeout, preparation failure and interruption.
Partial copies are removed too. Read-only copied files/directories are made
removable on permission failure; source permissions are never changed by cleanup.

Successful removal adds `workspace_cleanup` evidence named `snapshot_removed`.
The recorded execution path is historical: it no longer exists after the stage.
Provider evidence that points into the copy is also historical; referenced files
are not automatically exported. The original stage context pack remains in the
run trace, while its temporary worker copy is deleted.

If removal fails, a `workspace_cleanup_failed` finding includes the leftover path
and makes the stage fail. On interruption, MoreGAN attempts cleanup and propagates
the interruption; a cleanup error produces a warning with the path. No finished
stage result is promised for an interrupted process.

Copies exclude `.git`, common dependency/build/cache directories, `*.pyc`, and
generated MoreGAN run/learning/benchmark output. Internal symlinks are rebased to
the copy, including absolute links. External or looping symlinks fail preparation
instead of being followed into unrelated files. Snapshot storage inside the source
checkout is rejected to avoid recursive copying. Set `TMPDIR` outside the repo.

## What Integrity Checks Cover

MoreGAN streams file contents through SHA-256, records permission modes and symlink
targets, and compares before/after fingerprints. It does not rely on file size,
mtime, or `git status` text as proof that content is unchanged.

- Git projects: tracked files (including tracked ignored/build files), eligible
  untracked files, staged index entries, HEAD commit and symbolic HEAD reference.
- Non-Git directories: regular files, directory modes and symlink entries outside
  common dependency/build/cache and generated-output exclusions.
- Added, deleted, renamed or further-modified dirty/untracked files are detected.
- Git worktrees and repositories without a first commit use the same checks.

Git-ignored untracked files are outside the check, as are untracked paths under
`.git`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.venv`, `venv`,
`node_modules`, `dist`, `build`, and generated MoreGAN output directories. Tracked
paths are not filtered by these exclusions. Git metadata beyond index/HEAD (such
as configuration and hooks), timestamps, ownership and extended attributes are
not compared. Symlink targets outside the checkout are not read or verified.

Each scan has cooperative limits of 30 seconds, 100,000 paths and 1 GiB of file
content; each Git listing has a 1 MiB capture limit. Truncated listings, unreadable
files, unsupported special files, unstable file reads, scan-limit failures and
submodule entries fail closed with `no_write_check_failed`. Run MoreGAN in a
submodule separately. A scan does not silently certify partial coverage. Limits
cannot interrupt an OS filesystem call that blocks inside the kernel.

## Failure Policy

A difference produces `no_write_violation`, with changed paths and a comparison
summary in stage evidence. The current implementation shows up to 20 path names
in the finding, bounded to 1,000 characters, plus the total changed count.

Integrity violations, verification failures and cleanup failures stop the run and
record `worker.manual_review_required`; they do not trigger generator remediation.
Inspect and reconcile the checkout before another run. MoreGAN does not reset,
restore, stage, commit or revert files while performing these checks. Preexisting
user work is not overwritten by an attempted automatic rollback. Ordinary review
findings and deterministic-check failures retain their existing retry policy.

Concurrent user/editor writes can trigger a violation; the check cannot attribute
the writer. Changes made and restored between scans can evade detection. Provider
commands can still access absolute paths, external files, credentials and network
resources. Surviving child processes may write after verification. Provider process
supervision/output bounds and Windows validation remain separate milestones.
Do not use these controls as a security boundary for untrusted providers.
