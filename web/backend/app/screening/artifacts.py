"""Private, immutable-once-written screening execution artifacts.

The worker and the enqueue service share this small filesystem boundary.  It
never accepts a caller supplied absolute path and it refuses symlinked path
components, including components created after the first check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat as stat_module
import tempfile
from typing import Any, Mapping


EXECUTION_RE = re.compile(r"^scr-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_ROOT = Path("data") / "screening-executions"


class ArtifactError(RuntimeError):
    """An artifact cannot be safely created or verified."""


@dataclass(frozen=True)
class ExecutionOwnership:
    """Identity captured at the instant a fresh execution directory is made.

    The name is deliberately not an ownership proof: a failed transaction can
    have its name replaced while cleanup is in progress.  Device/inode are
    the minimum opaque identity needed to fail closed in that case.
    """

    execution_id: str
    device: int
    inode: int


def aware_iso(value: datetime | None = None) -> str:
    point = value or datetime.now(timezone.utc)
    if point.tzinfo is None or point.utcoffset() is None:
        raise ArtifactError("artifact timestamp must be timezone-aware")
    return point.isoformat()


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ArtifactError("artifact value is not canonical JSON") from None


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_symlinks(root: Path, candidate: Path) -> None:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise ArtifactError("artifact path is outside BIDOPS_ROOT") from None
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ArtifactError("artifact path contains a symlink")


def _safe_root(project_root: Path) -> Path:
    configured = Path(project_root)
    if configured.is_symlink():
        raise ArtifactError("BIDOPS_ROOT must not be a symlink")
    root = configured.resolve()
    if not root.is_dir():
        raise ArtifactError("BIDOPS_ROOT is not a regular directory")
    return root


def validate_execution_id(execution_id: str) -> str:
    if not isinstance(execution_id, str) or EXECUTION_RE.fullmatch(execution_id) is None:
        raise ArtifactError("execution_id is invalid")
    return execution_id


class ArtifactStore:
    """Content-addressed writes rooted at one execution directory."""

    def __init__(self, project_root: Path):
        self.project_root = _safe_root(Path(project_root))
        self.base = self.project_root / ARTIFACT_ROOT

    @property
    def relative_root(self) -> str:
        return ARTIFACT_ROOT.as_posix()

    def execution_dir(self, execution_id: str, *, create: bool = False) -> Path:
        execution_id = validate_execution_id(execution_id)
        base = self.base
        _reject_symlinks(self.project_root, base)
        if create:
            base.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(base, 0o700)
        _reject_symlinks(self.project_root, base)
        target = base / execution_id
        if create:
            target.mkdir(mode=0o700, exist_ok=False)
            os.chmod(target, 0o700)
        _reject_symlinks(self.project_root, target)
        try:
            target.resolve().relative_to(self.project_root.resolve())
        except (OSError, ValueError):
            raise ArtifactError("artifact directory escapes BIDOPS_ROOT") from None
        if not target.is_dir():
            raise ArtifactError("execution artifact directory is not a directory")
        return target

    def capture_execution_ownership(self, execution_id: str) -> ExecutionOwnership:
        """Capture the identity of an existing execution directory."""

        target = self.execution_dir(execution_id, create=False)
        try:
            stat = os.stat(target, follow_symlinks=False)
        except OSError:
            raise ArtifactError("execution artifact ownership could not be captured") from None
        if not stat_module.S_ISDIR(stat.st_mode):
            raise ArtifactError("execution artifact ownership is not a directory")
        return ExecutionOwnership(execution_id, stat.st_dev, stat.st_ino)

    def _path(self, execution_id: str, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or relative.startswith("/") or "\\" in relative:
            raise ArtifactError("artifact filename is not relative")
        parts = relative.split("/")
        if any(part in {"", ".", ".."} or ":" in part for part in parts):
            raise ArtifactError("artifact filename contains traversal")
        directory = self.execution_dir(execution_id, create=False)
        candidate = directory.joinpath(*parts)
        _reject_symlinks(self.project_root, candidate.parent)
        if candidate.exists() and candidate.is_symlink():
            raise ArtifactError("artifact file is a symlink")
        try:
            candidate.parent.resolve().relative_to(directory.resolve())
        except (OSError, ValueError):
            raise ArtifactError("artifact filename escapes execution directory") from None
        return candidate

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            raise ArtifactError("artifact directory sync failed") from None
        try:
            os.fsync(fd)
        except OSError:
            raise ArtifactError("artifact directory sync failed") from None
        finally:
            os.close(fd)

    def write_bytes(self, execution_id: str, relative: str, raw: bytes) -> tuple[str, str]:
        if not isinstance(raw, bytes):
            raise ArtifactError("artifact content must be bytes")
        path = self._path(execution_id, relative)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        _reject_symlinks(self.project_root, path.parent)
        digest = sha256_bytes(raw)
        if path.exists():
            if not path.is_file() or path.read_bytes() != raw:
                raise ArtifactError("immutable artifact already contains different bytes")
            return f"{ARTIFACT_ROOT.as_posix()}/{execution_id}/{relative}", digest
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".artifact-", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            # Link is create-only and therefore cannot overwrite a concurrent
            # immutable artifact.  A collision is safe only when bytes match.
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != raw:
                    raise ArtifactError("immutable artifact write collision") from None
            os.chmod(path, 0o600)
            self._fsync_directory(path.parent)
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("artifact atomic write failed") from None
        finally:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass
        return f"{ARTIFACT_ROOT.as_posix()}/{execution_id}/{relative}", digest

    def write_json(self, execution_id: str, relative: str, value: Any) -> tuple[str, str]:
        return self.write_bytes(execution_id, relative, canonical_bytes(value))

    def replace_json(self, execution_id: str, relative: str, value: Any) -> tuple[str, str]:
        """Atomically replace a mutable progress artifact (never input)."""
        if relative == "screening-input.json":
            return self.write_json(execution_id, relative, value)
        path = self._path(execution_id, relative)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_symlinks(self.project_root, path.parent)
        raw = canonical_bytes(value)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".artifact-", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
            if path.is_symlink():
                raise ArtifactError("artifact replacement created a symlink")
            os.chmod(path, 0o600)
            _reject_symlinks(self.project_root, path.parent)
            self._fsync_directory(path.parent)
        except OSError:
            raise ArtifactError("artifact atomic replacement failed") from None
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
        return f"{ARTIFACT_ROOT.as_posix()}/{execution_id}/{relative}", sha256_bytes(raw)

    def append_jsonl(self, execution_id: str, relative: str, value: Mapping[str, Any]) -> tuple[str, str]:
        if not isinstance(value, Mapping):
            raise ArtifactError("JSONL item must be an object")
        path = self._path(execution_id, relative)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_symlinks(self.project_root, path.parent)
        raw = canonical_bytes(dict(value)) + b"\n"
        fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            offset = 0
            while offset < len(raw):
                offset += os.write(fd, raw[offset:])
            os.fsync(fd)
            os.fchmod(fd, 0o600)
            self._fsync_directory(path.parent)
        except OSError:
            raise ArtifactError("artifact append failed") from None
        finally:
            if fd is not None:
                os.close(fd)
        return f"{ARTIFACT_ROOT.as_posix()}/{execution_id}/{relative}", sha256_bytes(path.read_bytes())

    def read_bytes(self, execution_id: str, relative: str, *, expected_digest: str | None = None) -> bytes:
        path = self._path(execution_id, relative)
        try:
            raw = path.read_bytes()
        except OSError:
            raise ArtifactError("artifact could not be read") from None
        if expected_digest is not None and (not SHA256_RE.fullmatch(expected_digest) or sha256_bytes(raw) != expected_digest):
            raise ArtifactError("artifact digest verification failed")
        return raw

    def read_json(self, execution_id: str, relative: str) -> Any:
        try:
            return json.loads(self.read_bytes(execution_id, relative))
        except (UnicodeError, json.JSONDecodeError):
            raise ArtifactError("artifact JSON is invalid") from None

    def remove_execution(self, execution_id: str, ownership: ExecutionOwnership | None = None) -> None:
        """Remove one freshly-created execution directory without TOCTOU.

        The directory name is opened relative to the artifact root with
        ``O_NOFOLLOW``.  All descendants are then removed through directory
        descriptors, so a pathname or symlink swap cannot redirect cleanup
        outside the known execution directory.
        """
        validate_execution_id(execution_id)
        if not isinstance(ownership, ExecutionOwnership) or ownership.execution_id != execution_id:
            raise ArtifactError("execution artifact ownership is required")
        base = self.base
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd: int | None = None
        data_fd: int | None = None
        base_fd: int | None = None
        try:
            # Open every path component relative to a descriptor.  Checking a
            # pathname first and then opening it leaves a symlink-swap window
            # in the intermediate ``data`` directory.
            root_fd = os.open(self.project_root, directory_flags)
            data_fd = os.open("data", directory_flags, dir_fd=root_fd)
            base_fd = os.open("screening-executions", directory_flags, dir_fd=data_fd)
        except OSError:
            for fd in (base_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)
            raise ArtifactError("execution artifact cleanup failed") from None
        try:
            target_fd = os.open(
                execution_id,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=base_fd,
            )
        except OSError:
            for fd in (base_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)
            raise ArtifactError("execution artifact cleanup failed") from None

        try:
            opened_stat = os.fstat(target_fd)
            if (opened_stat.st_dev, opened_stat.st_ino) != (ownership.device, ownership.inode):
                raise ArtifactError("execution artifact ownership mismatch")
            # Verify the name before removing any descendant.  If the fresh
            # directory was renamed away and a replacement took its name,
            # cleanup must leave both objects untouched.
            named_stat = os.stat(execution_id, dir_fd=base_fd, follow_symlinks=False)
            if (named_stat.st_dev, named_stat.st_ino) != (ownership.device, ownership.inode):
                raise ArtifactError("execution artifact path changed before cleanup")
        except ArtifactError:
            os.close(target_fd)
            for fd in (base_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)
            raise
        except OSError:
            os.close(target_fd)
            for fd in (base_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)
            raise ArtifactError("execution artifact cleanup failed") from None

        def remove_fd(directory_fd: int) -> None:
            try:
                entries = list(os.scandir(f"/proc/self/fd/{directory_fd}"))
            except OSError:
                raise ArtifactError("execution artifact cleanup failed") from None
            for entry in entries:
                name = entry.name
                try:
                    stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.st_mode & 0o170000 == 0o040000:
                        child_fd = os.open(
                            name,
                            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=directory_fd,
                        )
                        try:
                            remove_fd(child_fd)
                        finally:
                            os.close(child_fd)
                        os.rmdir(name, dir_fd=directory_fd)
                    else:
                        os.unlink(name, dir_fd=directory_fd)
                except OSError:
                    raise ArtifactError("execution artifact cleanup failed") from None

        try:
            remove_fd(target_fd)
            current_stat = os.stat(execution_id, dir_fd=base_fd, follow_symlinks=False)
            target_stat = os.fstat(target_fd)
            if (current_stat.st_dev, current_stat.st_ino) != (ownership.device, ownership.inode) or (target_stat.st_dev, target_stat.st_ino) != (ownership.device, ownership.inode):
                raise ArtifactError("execution artifact path changed during cleanup")
            os.rmdir(execution_id, dir_fd=base_fd)
        except OSError:
            raise ArtifactError("execution artifact cleanup failed") from None
        finally:
            os.close(target_fd)
            for fd in (base_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)


def artifact_directory(project_root: Path, execution_id: str, *, create: bool = False) -> Path:
    return ArtifactStore(project_root).execution_dir(execution_id, create=create)


def write_atomic_json(project_root: Path, execution_id: str, relative: str, value: Any) -> tuple[str, str]:
    return ArtifactStore(project_root).write_json(execution_id, relative, value)


__all__ = ["ARTIFACT_ROOT", "ArtifactError", "ArtifactStore", "ExecutionOwnership", "artifact_directory", "aware_iso", "canonical_bytes", "sha256_bytes", "validate_execution_id", "write_atomic_json"]
