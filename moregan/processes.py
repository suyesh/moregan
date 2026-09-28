"""Bounded process I/O and deadlines, without invoking a shell."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence


DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_OUTPUT_BYTES = 4000
MAX_TIMEOUT_SECONDS = 86400
MAX_OUTPUT_BYTES = 1048576
MAX_INPUT_BYTES = 1048576
SUPERVISOR_ENV = "_MOREGAN_SUPERVISOR_PID"
_CHUNK_SIZE = 65536


@dataclass
class ProcessResult:
    exit_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False
    error_kind: Optional[str] = None
    reason: Optional[str] = None


class _ProcessError(OSError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class ProcessCleanupInterrupted(KeyboardInterrupt):
    """An interrupted process could not be confirmed stopped; retain its workspace."""


class _Tail:
    def __init__(self, limit: int, strict: bool = False):
        self.limit = limit
        self.strict = strict
        self.data = bytearray()
        self.total = 0
        self.lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self.lock:
            self.total += len(chunk)
            self.data.extend(chunk[-self.limit:])
            del self.data[:-self.limit]
            if self.strict and self.total > self.limit:
                raise _ProcessError("output_limit", f"Provider stdout exceeded {self.limit} bytes; partial JSON rejected.")

    def validate_encoding(self) -> None:
        with self.lock:
            try:
                self.data.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise _ProcessError("output_encoding", "Provider stdout is not valid UTF-8.") from exc

    def snapshot(self):
        with self.lock:
            return self.data.decode("utf-8", errors="replace"), self.total, self.total > self.limit


def run_bounded(
    command: Sequence[str], root: Path, *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    env: Optional[Mapping[str, str]] = None,
    input_bytes: Optional[bytes] = None,
    max_input_bytes: int = MAX_INPUT_BYTES,
    strict_stdout: bool = False,
    inherit_process_group: bool = False,
) -> ProcessResult:
    """Cap retained bytes per stream and enforce a deadline including open pipes.

    POSIX callers own a process group, killed on exit, timeout or interruption.
    A supervised adapter can inherit its outer worker's group; that outer worker
    then owns descendant cleanup. Strict stdout rejects oversize or non-UTF-8 JSON.
    Windows currently guarantees cleanup of the immediate process only.
    """
    for name, value, maximum in (
        ("timeout_seconds", timeout_seconds, MAX_TIMEOUT_SECONDS),
        ("max_output_bytes", max_output_bytes, MAX_OUTPUT_BYTES),
        ("max_input_bytes", max_input_bytes, MAX_INPUT_BYTES),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"{name} must be an integer between 1 and {maximum}")
    if input_bytes is not None and (not isinstance(input_bytes, bytes) or len(input_bytes) > max_input_bytes):
        raise ValueError(f"input_bytes must be bytes no larger than {max_input_bytes}")

    stdout = _Tail(max_output_bytes, strict=strict_stdout)
    stderr = _Tail(min(max_output_bytes, DEFAULT_MAX_OUTPUT_BYTES) if strict_stdout else max_output_bytes)
    deadline = time.monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(
            command, cwd=root, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=env,
            start_new_session=os.name == "posix" and not inherit_process_group,
        )
    except (OSError, ValueError) as exc:
        missing = isinstance(exc, FileNotFoundError) and root.is_dir()
        return ProcessResult(
            exit_code=127 if missing else 126, error_kind="not_found" if missing else "launch_error",
            reason=f"command not found: {command[0]}" if missing else f"Command could not start: {exc}",
            stderr_tail=str(exc)[-max_output_bytes:],
        )

    result = ProcessResult(exit_code=125)
    stop = threading.Event()
    readers = []
    interrupted = False
    try:
        if os.name == "posix":
            complete = _drain_posix(process, stdout, stderr, deadline, input_bytes)
        else:
            complete = _drain_threads(process, stdout, stderr, deadline, stop, readers, input_bytes)
        if not complete:
            result.timed_out = True
            result.exit_code = 124
            result.error_kind = "timeout"
            result.reason = f"Command timed out after {timeout_seconds}s (including stdin delivery and output-pipe closure)."
        else:
            result.exit_code = process.returncode
            if strict_stdout:
                stdout.validate_encoding()
    except _ProcessError as exc:
        result.exit_code = 125
        result.error_kind = exc.kind
        result.reason = str(exc)
    except (OSError, ValueError) as exc:
        result.error_kind = "capture_error"
        result.reason = f"Could not capture command output: {exc}"
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        stop.set()
        try:
            _kill(process, inherit_process_group)
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result.exit_code = 125
            result.error_kind = "cleanup_error"
            result.reason = f"Could not confirm command cleanup: {exc}"
            if interrupted:
                raise ProcessCleanupInterrupted(result.reason) from exc
        finally:
            if process.stdin is not None:
                process.stdin.close()
            process.stdout.close()
            process.stderr.close()
            for reader in readers:
                reader.join(timeout=0.1)

    result.stdout_tail, result.stdout_bytes, result.stdout_truncated = stdout.snapshot()
    result.stderr_tail, result.stderr_bytes, result.stderr_truncated = stderr.snapshot()
    return result


def supervised_adapter() -> bool:
    """Only direct, group-leading wrappers may defer group cleanup to a parent."""
    return (os.name == "posix" and os.environ.get(SUPERVISOR_ENV) == str(os.getppid())
            and os.getpgrp() == os.getpid())


def _kill(process: subprocess.Popen, inherit_process_group: bool = False) -> None:
    try:
        if os.name == "posix" and not inherit_process_group:
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass


def _drain_posix(process, stdout, stderr, deadline, input_bytes=None) -> bool:
    with selectors.DefaultSelector() as selector:
        for pipe, tail in ((process.stdout, stdout), (process.stderr, stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, tail)
        pending = memoryview(input_bytes or b"")
        if process.stdin is not None:
            if pending:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, None)
            else:
                process.stdin.close()
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            for key, _ in selector.select(timeout=min(remaining, 0.05)):
                if key.data is None:
                    try:
                        written = os.write(key.fd, pending[:_CHUNK_SIZE])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError as exc:
                        raise _ProcessError("input_delivery", "Provider closed stdin before the full prompt was delivered.") from exc
                    pending = pending[written:]
                    if not pending:
                        selector.unregister(key.fileobj)
                        process.stdin.close()
                    continue
                try:
                    chunk = os.read(key.fd, _CHUNK_SIZE)
                except BlockingIOError:
                    continue
                if chunk:
                    key.data.append(chunk)
                else:
                    selector.unregister(key.fileobj)
        return True


def _drain_threads(process, stdout, stderr, deadline, stop, readers, input_bytes=None) -> bool:
    # Windows selectors cannot monitor anonymous pipes. Daemon readers keep a
    # detached descendant holding a pipe from blocking the caller's deadline.
    errors = []

    def write():
        try:
            pending = memoryview(input_bytes or b"")
            while pending and not stop.is_set():
                written = process.stdin.write(pending[:_CHUNK_SIZE])
                pending = pending[written:]
            process.stdin.close()
        except (OSError, ValueError) as exc:
            if not stop.is_set():
                errors.append(_ProcessError("input_delivery", f"Could not deliver full provider prompt: {exc}"))

    def read(pipe, tail):
        try:
            while not stop.is_set():
                chunk = pipe.read(_CHUNK_SIZE)
                if not chunk:
                    return
                tail.append(chunk)
        except (OSError, ValueError) as exc:
            if not stop.is_set():
                errors.append(exc)

    for pipe, tail in ((process.stdout, stdout), (process.stderr, stderr)):
        reader = threading.Thread(target=read, args=(pipe, tail), daemon=True)
        readers.append(reader)
        reader.start()
    if process.stdin is not None:
        writer = threading.Thread(target=write, daemon=True)
        readers.append(writer)
        writer.start()
    while process.poll() is None or any(reader.is_alive() for reader in readers):
        if errors:
            raise errors[0]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(remaining, 0.01))
    if errors:
        raise errors[0]
    return True
