"""Private, immutable-once-written screening execution artifacts.

The worker and the enqueue service share this small filesystem boundary.  It
never accepts a caller supplied absolute path and it refuses symlinked path
components, including components created after the first check.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat as stat_module
import tempfile
from typing import Any, Mapping
from uuid import uuid4


EXECUTION_RE = re.compile(r"^scr-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_ROOT = Path("data") / "screening-executions"


class ArtifactError(RuntimeError):
    """An artifact cannot be safely created or verified."""


class ExecutionWorkspace:
    """A freshly-created execution directory held by trusted descriptors.

    The directory name is only a lookup hint.  All initial writes and rollback
    operations use the held directory/base descriptors, so a rename or a
    replacement at the original name cannot redirect them.
    """

    __slots__ = ("execution_id", "directory_fd", "base_fd", "device", "inode", "base_device", "base_inode", "_closed")

    def __init__(self, execution_id: str, directory_fd: int, base_fd: int) -> None:
        self.execution_id = execution_id
        self.directory_fd = directory_fd
        self.base_fd = base_fd
        directory_stat = os.fstat(directory_fd)
        base_stat = os.fstat(base_fd)
        self.device = directory_stat.st_dev
        self.inode = directory_stat.st_ino
        self.base_device = base_stat.st_dev
        self.base_inode = base_stat.st_ino
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd in (self.directory_fd, self.base_fd):
            try:
                os.close(fd)
            except OSError:
                # Closing is idempotent and must not turn a durable enqueue
                # into a false failure.  The descriptor has already ceased to
                # be usable, so there is nothing safe to retry here.
                pass

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArtifactError("execution workspace is closed")

    def named_entry(self) -> bool:
        """Whether the original execution name still identifies this inode."""

        self._ensure_open()
        try:
            value = os.stat(self.execution_id, dir_fd=self.base_fd, follow_symlinks=False)
        except OSError:
            return False
        return (value.st_dev, value.st_ino) == (self.device, self.inode)

    def require_named(self) -> None:
        if not self.named_entry():
            raise ArtifactError("execution workspace name changed")

    def write_bytes(self, relative: str, raw: bytes) -> tuple[str, str]:
        """Write a direct child through this workspace's directory FD."""

        self._ensure_open()
        if not isinstance(relative, str) or not relative or "/" in relative or "\\" in relative or relative in {".", ".."} or ":" in relative:
            raise ArtifactError("workspace artifact filename is invalid")
        if not isinstance(raw, bytes):
            raise ArtifactError("artifact content must be bytes")
        digest = sha256_bytes(raw)
        try:
            existing_fd = os.open(relative, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.directory_fd)
        except FileNotFoundError:
            existing_fd = None
        except OSError:
            raise ArtifactError("workspace artifact could not be opened") from None
        if existing_fd is not None:
            try:
                existing = b""
                while True:
                    chunk = os.read(existing_fd, 1024 * 1024)
                    if not chunk:
                        break
                    existing += chunk
                if existing != raw:
                    raise ArtifactError("immutable artifact already contains different bytes")
                return f"{ARTIFACT_ROOT.as_posix()}/{self.execution_id}/{relative}", digest
            except OSError:
                raise ArtifactError("workspace artifact could not be read") from None
            finally:
                os.close(existing_fd)

        temporary = f".artifact-{uuid4().hex}.tmp"
        temporary_fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            temporary_fd = os.open(temporary, flags, 0o600, dir_fd=self.directory_fd)
            offset = 0
            while offset < len(raw):
                offset += os.write(temporary_fd, raw[offset:])
            os.fsync(temporary_fd)
            os.fchmod(temporary_fd, 0o600)
            os.close(temporary_fd)
            temporary_fd = None
            os.replace(temporary, relative, src_dir_fd=self.directory_fd, dst_dir_fd=self.directory_fd)
            os.fsync(self.directory_fd)
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("workspace artifact atomic write failed") from None
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            try:
                os.unlink(temporary, dir_fd=self.directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        return f"{ARTIFACT_ROOT.as_posix()}/{self.execution_id}/{relative}", digest

    def write_json(self, relative: str, value: Any) -> tuple[str, str]:
        return self.write_bytes(relative, canonical_bytes(value))

    def read_bytes(self, relative: str, *, expected_digest: str | None = None) -> bytes:
        self._ensure_open()
        if not isinstance(relative, str) or not relative or "/" in relative or "\\" in relative:
            raise ArtifactError("workspace artifact filename is invalid")
        fd: int | None = None
        try:
            fd = os.open(relative, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.directory_fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        except OSError:
            raise ArtifactError("workspace artifact could not be read") from None
        finally:
            if fd is not None:
                os.close(fd)
        if expected_digest is not None and (not SHA256_RE.fullmatch(expected_digest) or sha256_bytes(raw) != expected_digest):
            raise ArtifactError("artifact digest verification failed")
        return raw

    def read_json(self, relative: str, *, expected_digest: str | None = None) -> Any:
        try:
            value = json.loads(self.read_bytes(relative, expected_digest=expected_digest))
        except (UnicodeError, json.JSONDecodeError):
            raise ArtifactError("workspace artifact JSON is invalid") from None
        return value


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

    def create_execution_workspace(self, execution_id: str) -> ExecutionWorkspace:
        """Create and immediately hold a descriptor for a fresh execution."""

        execution_id = validate_execution_id(execution_id)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd: int | None = None
        data_fd: int | None = None
        base_fd: int | None = None
        directory_fd: int | None = None
        try:
            root_fd = os.open(self.project_root, flags)
            try:
                data_fd = os.open("data", flags, dir_fd=root_fd)
            except FileNotFoundError:
                os.mkdir("data", mode=0o700, dir_fd=root_fd)
                data_fd = os.open("data", flags, dir_fd=root_fd)
            os.fchmod(data_fd, 0o700)
            try:
                base_fd = os.open("screening-executions", flags, dir_fd=data_fd)
            except FileNotFoundError:
                os.mkdir("screening-executions", mode=0o700, dir_fd=data_fd)
                base_fd = os.open("screening-executions", flags, dir_fd=data_fd)
            os.fchmod(base_fd, 0o700)
            os.mkdir(execution_id, mode=0o700, dir_fd=base_fd)
            directory_fd = os.open(execution_id, flags, dir_fd=base_fd)
            os.fchmod(directory_fd, 0o700)
            os.fsync(base_fd)
            workspace = ExecutionWorkspace(execution_id, directory_fd, base_fd)
            directory_fd = None
            base_fd = None
            return workspace
        except (ArtifactError, OSError):
            raise ArtifactError("execution workspace creation failed") from None
        finally:
            for fd in (directory_fd, base_fd, data_fd, root_fd):
                if fd is not None:
                    os.close(fd)

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

    @staticmethod
    def _remove_tree_fd(directory_fd: int) -> None:
        try:
            entries = list(os.scandir(f"/proc/self/fd/{directory_fd}"))
        except OSError:
            raise ArtifactError("execution artifact cleanup failed") from None
        for entry in entries:
            name = entry.name
            try:
                value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat_module.S_ISDIR(value.st_mode):
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_fd,
                    )
                    try:
                        ArtifactStore._remove_tree_fd(child_fd)
                    finally:
                        os.close(child_fd)
                    os.rmdir(name, dir_fd=directory_fd)
                else:
                    os.unlink(name, dir_fd=directory_fd)
            except OSError:
                raise ArtifactError("execution artifact cleanup failed") from None

    @staticmethod
    def _owned_name(workspace: ExecutionWorkspace) -> str | None:
        try:
            entries = list(os.scandir(f"/proc/self/fd/{workspace.base_fd}"))
        except OSError:
            raise ArtifactError("execution artifact cleanup failed") from None
        for entry in entries:
            try:
                value = os.stat(entry.name, dir_fd=workspace.base_fd, follow_symlinks=False)
            except OSError:
                continue
            if (value.st_dev, value.st_ino) == (workspace.device, workspace.inode):
                return entry.name
        return None

    def remove_execution(self, workspace: ExecutionWorkspace) -> None:
        """Remove only the inode owned by a live workspace.

        If the original name was replaced, the trusted parent descriptor is
        scanned for the owned inode and only that exact entry is removed.
        """

        if not isinstance(workspace, ExecutionWorkspace) or workspace.closed:
            raise ArtifactError("live execution workspace is required")
        try:
            base_stat = os.fstat(workspace.base_fd)
            directory_stat = os.fstat(workspace.directory_fd)
            if (base_stat.st_dev, base_stat.st_ino) != (workspace.base_device, workspace.base_inode):
                raise ArtifactError("execution artifact parent identity changed")
            if (directory_stat.st_dev, directory_stat.st_ino) != (workspace.device, workspace.inode):
                raise ArtifactError("execution artifact ownership mismatch")
            owned_name = self._owned_name(workspace)
            ArtifactStore._remove_tree_fd(workspace.directory_fd)
            if owned_name is None:
                return
            try:
                current = os.stat(owned_name, dir_fd=workspace.base_fd, follow_symlinks=False)
            except OSError:
                return
            if (current.st_dev, current.st_ino) != (workspace.device, workspace.inode):
                return
            os.rmdir(owned_name, dir_fd=workspace.base_fd)
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("execution artifact cleanup failed") from None
        finally:
            workspace.close()


def artifact_directory(project_root: Path, execution_id: str, *, create: bool = False) -> Path:
    return ArtifactStore(project_root).execution_dir(execution_id, create=create)


def write_atomic_json(project_root: Path, execution_id: str, relative: str, value: Any) -> tuple[str, str]:
    return ArtifactStore(project_root).write_json(execution_id, relative, value)


__all__ = ["ARTIFACT_ROOT", "ArtifactError", "ArtifactStore", "ExecutionWorkspace", "artifact_directory", "aware_iso", "canonical_bytes", "sha256_bytes", "validate_execution_id", "write_atomic_json"]
