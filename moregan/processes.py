"""Bounded output capture for deterministic checks, without invoking a shell."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MAX_OUTPUT_BYTES = 4000
MAX_TIMEOUT_SECONDS = 86400
MAX_OUTPUT_BYTES = 1048576
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


class _Tail:
    def __init__(self, limit: int):
        self.limit = limit
        self.data = bytearray()
        self.total = 0
        self.lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self.lock:
            self.total += len(chunk)
            self.data.extend(chunk[-self.limit:])
            del self.data[:-self.limit]

    def snapshot(self):
        with self.lock:
            return self.data.decode("utf-8", errors="replace"), self.total, self.total > self.limit


def run_bounded(
    command: Sequence[str], root: Path, *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> ProcessResult:
    """Cap retained bytes per stream and enforce a deadline including open pipes.

    POSIX checks own a process group, killed on exit, timeout or interruption.
    Windows currently guarantees cleanup of the immediate process only.
    """
    for name, value, maximum in (
        ("timeout_seconds", timeout_seconds, MAX_TIMEOUT_SECONDS),
        ("max_output_bytes", max_output_bytes, MAX_OUTPUT_BYTES),
    ):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"{name} must be an integer between 1 and {maximum}")

    stdout, stderr = _Tail(max_output_bytes), _Tail(max_output_bytes)
    deadline = time.monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(
            command, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, start_new_session=os.name == "posix",
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
    try:
        if os.name == "posix":
            complete = _drain_posix(process, stdout, stderr, deadline)
        else:
            complete = _drain_threads(process, stdout, stderr, deadline, stop, readers)
        if not complete:
            result.timed_out = True
            result.exit_code = 124
            result.error_kind = "timeout"
            result.reason = f"Command timed out after {timeout_seconds}s (including output-pipe closure)."
        else:
            result.exit_code = process.returncode
    except (OSError, ValueError) as exc:
        result.error_kind = "capture_error"
        result.reason = f"Could not capture command output: {exc}"
    finally:
        stop.set()
        try:
            _kill(process)
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result.exit_code = 125
            result.error_kind = "cleanup_error"
            result.reason = f"Could not confirm command cleanup: {exc}"
        finally:
            process.stdout.close()
            process.stderr.close()
            for reader in readers:
                reader.join(timeout=0.1)

    result.stdout_tail, result.stdout_bytes, result.stdout_truncated = stdout.snapshot()
    result.stderr_tail, result.stderr_bytes, result.stderr_truncated = stderr.snapshot()
    return result


def _kill(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass


def _drain_posix(process, stdout, stderr, deadline) -> bool:
    with selectors.DefaultSelector() as selector:
        for pipe, tail in ((process.stdout, stdout), (process.stderr, stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, tail)
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            for key, _ in selector.select(timeout=min(remaining, 0.05)):
                chunk = os.read(key.fd, _CHUNK_SIZE)
                if chunk:
                    key.data.append(chunk)
                else:
                    selector.unregister(key.fileobj)
        return True


def _drain_threads(process, stdout, stderr, deadline, stop, readers) -> bool:
    # Windows selectors cannot monitor anonymous pipes. Daemon readers keep a
    # detached descendant holding a pipe from blocking the caller's deadline.
    errors = []

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
    while process.poll() is None or any(reader.is_alive() for reader in readers):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(remaining, 0.01))
    if errors:
        raise OSError(str(errors[0]))
    return True
