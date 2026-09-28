"""Temporary worker copies and content-based checkout integrity checks."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from moregan.processes import MAX_OUTPUT_BYTES, run_bounded


IGNORED_NAMES = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "dist", "build",
})
GENERATED_PATHS = (
    ".moregan/runs", ".moregan/learning", ".moregan/benchmarks/runs",
    ".moregan/benchmarks/comparisons",
)
MAX_SCAN_FILES = 100000
MAX_SCAN_BYTES = 1024 * 1024 * 1024
SCAN_TIMEOUT_SECONDS = 30


class WorkspaceCheckError(OSError):
    """The workspace cannot be copied or verified safely."""


def _ignored(relative: Path) -> bool:
    return (bool(set(relative.parts) & IGNORED_NAMES) or relative.suffix == ".pyc" or
            any(relative.as_posix() == name or relative.as_posix().startswith(name + "/")
                for name in GENERATED_PATHS))


class WorkerWorkspace:
    """Own only the temporary directory allocated for this worker invocation."""

    def __init__(self, root: Path, isolated: bool, stage: str):
        self.root = root.resolve()
        self.isolated = isolated
        self.stage = stage
        self.temporary_root: Optional[Path] = None
        self.execution_root = self.root

    def prepare(self) -> Path:
        if not self.isolated:
            return self.root
        self.temporary_root = Path(tempfile.mkdtemp(prefix=f"moregan-{self.stage}-"))
        self.temporary_root = self.temporary_root.resolve()
        if self.root == self.temporary_root or self.root in self.temporary_root.parents:
            raise WorkspaceCheckError("Snapshot storage must be outside the repository; check TMPDIR.")
        self.execution_root = self.temporary_root / "checkout"
        shutil.copytree(self.root, self.execution_root, symlinks=True, ignore=self._ignore)
        self._rebase_links()
        return self.execution_root

    def _ignore(self, directory: str, names: List[str]) -> List[str]:
        relative = Path(directory).relative_to(self.root)
        return [name for name in names if _ignored(relative / name)]

    def _rebase_links(self) -> None:
        # Never follow external links during copying, or leave absolute links
        # pointing back into the checkout. Internal links refer to the copy.
        for directory, directories, files in os.walk(self.execution_root, followlinks=False):
            for name in directories + files:
                copied = Path(directory) / name
                if not copied.is_symlink():
                    continue
                original = self.root / copied.relative_to(self.execution_root)
                try:
                    target = original.resolve().relative_to(self.root)
                except (ValueError, RuntimeError) as exc:
                    raise WorkspaceCheckError(f"Snapshot link escapes the repository or loops: {original}") from exc
                destination = self.execution_root / target
                copied.unlink()
                copied.symlink_to(os.path.relpath(destination, copied.parent), target_is_directory=original.is_dir())

    def cleanup(self) -> None:
        target = self.temporary_root
        if target is None:
            return
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            try:
                shutil.rmtree(target)
            except PermissionError:
                self._make_removable(target)
                shutil.rmtree(target)

    def _make_removable(self, target: Path) -> None:
        def unlock(path):
            mode = path.lstat().st_mode
            if not stat.S_ISLNK(mode):
                os.chmod(path, mode | stat.S_IRWXU, follow_symlinks=False)

        unlock(target)
        for directory, directories, files in os.walk(target, followlinks=False):
            for name in directories + files:
                unlock(Path(directory) / name)


@dataclass
class CheckoutFingerprint:
    files: Dict[str, str]
    git_state: Dict[str, str]

    @classmethod
    def capture(cls, root: Path) -> "CheckoutFingerprint":
        try:
            return _FingerprintReader(root.resolve()).capture()
        except (OSError, ValueError, RuntimeError) as exc:
            raise WorkspaceCheckError(str(exc)) from exc

    def changes_from(self, before: "CheckoutFingerprint") -> List[str]:
        changed = [name for name in self.files.keys() | before.files.keys()
                   if self.files.get(name) != before.files.get(name)]
        changed.extend(f".git/{name}" for name in self.git_state.keys() | before.git_state.keys()
                       if self.git_state.get(name) != before.git_state.get(name))
        return sorted(changed)


class _FingerprintReader:
    def __init__(self, root: Path):
        self.root = root
        self.deadline = time.monotonic() + SCAN_TIMEOUT_SECONDS
        self.bytes_read = 0

    def _check_budget(self) -> None:
        if time.monotonic() > self.deadline or self.bytes_read > MAX_SCAN_BYTES:
            raise WorkspaceCheckError("Checkout integrity scan exceeded its time or byte limit.")

    def capture(self) -> CheckoutFingerprint:
        if not self.root.is_dir():
            raise WorkspaceCheckError("Repository directory is unavailable.")
        if (self.root / ".git").exists():
            index = self._git(["ls-files", "--stage", "-z"])
            paths = set()
            for entry in index.split("\x00"):
                if entry:
                    fields = entry.split("\t", 1)
                    if len(fields) != 2:
                        raise WorkspaceCheckError("Invalid Git index listing.")
                    if fields[0].startswith("160000 "):
                        raise WorkspaceCheckError("Submodules are not covered by checkout integrity verification; run in the submodule separately.")
                    paths.add(fields[1])
            untracked = self._git(["ls-files", "--others", "--exclude-standard", "-z"])
            paths.update(name for name in untracked.split("\x00") if name and not _ignored(Path(name)))
            git_state = {
                "index": hashlib.sha256(index.encode("utf-8")).hexdigest(),
                "HEAD": self._git(["rev-parse", "--verify", "--quiet", "HEAD"], allow_empty=True),
                "HEAD-ref": self._git(["symbolic-ref", "--quiet", "HEAD"], allow_empty=True),
            }
        else:
            paths = self._filesystem_paths()
            git_state = {}
        if len(paths) > MAX_SCAN_FILES:
            raise WorkspaceCheckError("Checkout integrity scan exceeded its file limit.")
        files = {name: self._signature(Path(name)) for name in sorted(paths)}
        self._check_budget()
        return CheckoutFingerprint(files, git_state)

    def _git(self, arguments: List[str], allow_empty: bool = False) -> str:
        self._check_budget()
        result = run_bounded(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *arguments], self.root,
            timeout_seconds=max(1, int(self.deadline - time.monotonic())), max_output_bytes=MAX_OUTPUT_BYTES,
        )
        if (result.error_kind or result.stdout_truncated or
                result.exit_code != 0 and not (allow_empty and result.exit_code == 1)):
            raise WorkspaceCheckError(f"Cannot verify Git state: {result.reason or result.stderr_tail or 'incomplete listing'}")
        if "\ufffd" in result.stdout_tail:
            raise WorkspaceCheckError("Cannot safely decode Git paths for integrity verification.")
        return result.stdout_tail

    def _filesystem_paths(self):
        paths = set()

        def onerror(error):
            raise error

        for directory, directories, files in os.walk(self.root, followlinks=False, onerror=onerror):
            self._check_budget()
            relative = Path(directory).relative_to(self.root)
            directories[:] = [name for name in directories if not _ignored(relative / name)]
            for name in directories + files:
                path = relative / name
                if not _ignored(path):
                    paths.add(path.as_posix())
                    if len(paths) > MAX_SCAN_FILES:
                        raise WorkspaceCheckError("Checkout integrity scan exceeded its file limit.")
        return paths

    def _signature(self, relative: Path) -> str:
        self._check_budget()
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkspaceCheckError("Integrity scan received a path outside the checkout.")
        for parent in relative.parents:
            if (self.root / parent).is_symlink():
                raise WorkspaceCheckError(f"Integrity scan cannot traverse symlink directory: {parent}")
        path = self.root / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return "missing"
        mode = metadata.st_mode
        if stat.S_ISLNK(mode):
            return "link:" + os.readlink(path)
        if stat.S_ISDIR(mode):
            return f"directory:{stat.S_IMODE(mode)}"
        if not stat.S_ISREG(mode):
            raise WorkspaceCheckError(f"Unsupported file type in integrity scan: {relative}")
        digest = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise WorkspaceCheckError(f"File type changed during integrity scan: {relative}")
            for chunk in iter(lambda: source.read(65536), b""):
                self.bytes_read += len(chunk)
                self._check_budget()
                digest.update(chunk)
            after = os.fstat(source.fileno())
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mode, value.st_mtime_ns, value.st_ctime_ns)

        if identity(metadata) != identity(after) or identity(after) != identity(path.lstat()):
            raise WorkspaceCheckError(f"File changed during integrity scan: {relative}")
        return f"file:{stat.S_IMODE(mode)}:{digest.hexdigest()}"
