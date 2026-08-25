"""Private, immutable-once-written screening execution artifacts.

The worker and the enqueue service share this small filesystem boundary.  It
never accepts a caller supplied absolute path and it refuses symlinked path
components, including components created after the first check.
"""

from __future__ import annotations

from datetime import datetime, timezone
import ctypes
import errno
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
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2
try:
    _LIBC = ctypes.CDLL(None, use_errno=True)
    _RENAMEAT2 = _LIBC.renameat2
    _RENAMEAT2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    _RENAMEAT2.restype = ctypes.c_int
except (AttributeError, OSError):
    _RENAMEAT2 = None


def _rename_at(source: str, destination: str, *, src_dir_fd: int, dst_dir_fd: int, flags: int) -> None:
    """Call Linux renameat2 with exact directory descriptors."""

    if _RENAMEAT2 is None:
        raise ArtifactError("renameat2 atomic rename is unsupported")
    ctypes.set_errno(0)
    result = _RENAMEAT2(
        src_dir_fd,
        os.fsencode(source),
        dst_dir_fd,
        os.fsencode(destination),
        flags,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST and flags == _RENAME_NOREPLACE:
        raise FileExistsError(error, os.strerror(error), destination)
    raise OSError(error, os.strerror(error), source)


def _rename_noreplace(source: str, destination: str, *, src_dir_fd: int, dst_dir_fd: int) -> None:
    """Move a name without ever replacing an existing destination."""

    _rename_at(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=_RENAME_NOREPLACE)


def _rename_exchange(source: str, destination: str, *, src_dir_fd: int, dst_dir_fd: int) -> None:
    """Atomically exchange two existing names without pathname fallback."""

    _rename_at(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, flags=_RENAME_EXCHANGE)


def _probe_renameat2(directory_fd: int) -> None:
    """Require the atomic rename primitives before creating/cleaning artifacts."""

    if _RENAMEAT2 is None:
        raise ArtifactError("atomic renameat2 is unavailable")

    # A same-name call only checks that the symbol exists.  It does not prove
    # that either flag works on the mounted filesystem.  Exercise both flags
    # against private file and directory pairs, and return each pair to its
    # original state before removing it.  The artifact parent is 0700 and is
    # owned by this process, so these probe names are not an input surface.
    prefix = f".renameat2-probe-{uuid4().hex}"
    pairs = (
        (f"{prefix}-file-a", f"{prefix}-file-b", False),
        (f"{prefix}-dir-a", f"{prefix}-dir-b", True),
    )
    expected: dict[str, tuple[int, int] | None] = {}

    def create(name: str, is_directory: bool) -> tuple[int, int]:
        try:
            if is_directory:
                os.mkdir(name, mode=0o700, dir_fd=directory_fd)
                fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
            else:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
            try:
                value = os.fstat(fd)
                return value.st_dev, value.st_ino
            finally:
                os.close(fd)
        except OSError as exc:
            raise ArtifactError("atomic renameat2 capability probe setup failed") from exc

    def verify(name: str, identity: tuple[int, int], is_directory: bool) -> None:
        fd: int | None = None
        try:
            fd = os.open(
                name,
                os.O_RDONLY
                | (getattr(os, "O_DIRECTORY", 0) if is_directory else 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            value = os.fstat(fd)
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (value.st_dev, value.st_ino) != identity or (named.st_dev, named.st_ino) != identity:
                raise ArtifactError("atomic renameat2 probe identity changed")
            if is_directory:
                with os.scandir(f"/proc/self/fd/{fd}") as entries:
                    if next(entries, None) is not None:
                        raise ArtifactError("atomic renameat2 probe directory is not empty")
        except ArtifactError:
            raise
        except OSError as exc:
            raise ArtifactError("atomic renameat2 probe verification failed") from exc
        finally:
            if fd is not None:
                os.close(fd)

    def remove(name: str, identity: tuple[int, int], is_directory: bool) -> None:
        verify(name, identity, is_directory)
        try:
            if is_directory:
                os.rmdir(name, dir_fd=directory_fd)
            else:
                os.unlink(name, dir_fd=directory_fd)
        except OSError as exc:
            raise ArtifactError("atomic renameat2 probe cleanup failed") from exc

    pending: BaseException | None = None
    try:
        for first, second, is_directory in pairs:
            first_identity = create(first, is_directory)
            expected[first] = first_identity
            try:
                _rename_noreplace(first, second, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            except OSError as exc:
                if exc.errno in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
                    raise ArtifactError("atomic renameat2 is unavailable") from None
                raise ArtifactError("atomic renameat2 NOREPLACE probe failed") from exc
            expected[second] = expected.pop(first)
            expected[first] = create(first, is_directory)
            try:
                _rename_exchange(second, first, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            except OSError as exc:
                if exc.errno in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
                    raise ArtifactError("atomic renameat2 is unavailable") from None
                raise ArtifactError("atomic renameat2 EXCHANGE probe failed") from exc
            expected[first], expected[second] = expected[second], expected[first]
            verify(first, expected[first], is_directory)  # type: ignore[arg-type]
            verify(second, expected[second], is_directory)  # type: ignore[arg-type]
            try:
                _rename_exchange(second, first, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            except OSError as exc:
                if exc.errno in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
                    raise ArtifactError("atomic renameat2 is unavailable") from None
                raise ArtifactError("atomic renameat2 EXCHANGE round-trip failed") from exc
            expected[first], expected[second] = expected[second], expected[first]
            verify(first, expected[first], is_directory)  # type: ignore[arg-type]
            verify(second, expected[second], is_directory)  # type: ignore[arg-type]
            remove(first, expected.pop(first), is_directory)  # type: ignore[arg-type]
            remove(second, expected.pop(second), is_directory)  # type: ignore[arg-type]
    except (ArtifactError, OSError) as exc:
        pending = exc if isinstance(exc, ArtifactError) else ArtifactError("atomic renameat2 capability probe failed")
    finally:
        cleanup_error: ArtifactError | None = None
        for name, identity in tuple(expected.items()):
            if identity is None:
                continue
            is_directory = name.endswith("-dir-a") or name.endswith("-dir-b")
            try:
                remove(name, identity, is_directory)
                expected.pop(name, None)
            except ArtifactError as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            pending = cleanup_error
    if pending is not None:
        raise pending


class ArtifactError(RuntimeError):
    """An artifact cannot be safely created or verified."""


class ExecutionWorkspace:
    """A freshly-created execution directory held by trusted descriptors.

    The directory name is only a lookup hint.  All initial writes and rollback
    operations use the held directory/base descriptors, so a rename or a
    replacement at the original name cannot redirect them.

    The supported threat boundary is the application-owned 0700 artifact
    tree.  A non-cooperating process with the same UID can still race an
    unlink after its final identity check because Linux has no compare-and-
    unlink primitive; exchange/quarantine narrows that window and all
    pathname/symlink swaps remain fail-closed.
    """

    __slots__ = ("execution_id", "directory_fd", "base_fd", "device", "inode", "base_device", "base_inode", "_children", "_closed")

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
        self._children: set[tuple[str, tuple[int, int]]] = set()
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

    def is_empty(self) -> bool:
        self._ensure_open()
        try:
            with os.scandir(f"/proc/self/fd/{self.directory_fd}") as entries:
                return next(entries, None) is None
        except OSError:
            raise ArtifactError("execution workspace could not be scanned") from None

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
                existing_stat = os.fstat(existing_fd)
                existing_identity = (existing_stat.st_dev, existing_stat.st_ino)
                if (relative, existing_identity) not in self._children:
                    raise ArtifactError("workspace artifact path is not owned")
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
            temporary_stat = os.fstat(temporary_fd)
            temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
            # Keep the inode discoverable even if the final verification open
            # fails after replace.  The name is only a hint; rollback matches
            # this exact inode before moving it to quarantine.
            self._children.add((relative, temporary_identity))
            os.replace(temporary, relative, src_dir_fd=self.directory_fd, dst_dir_fd=self.directory_fd)
            final_fd = os.open(relative, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.directory_fd)
            try:
                final_stat = os.fstat(final_fd)
                final_identity = (final_stat.st_dev, final_stat.st_ino)
                if final_identity != temporary_identity or not stat_module.S_ISREG(final_stat.st_mode):
                    raise ArtifactError("workspace artifact identity changed")
                self._children.add((relative, final_identity))
            finally:
                os.close(final_fd)
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
        workspace: ExecutionWorkspace | None = None
        preexisting: set[tuple[int, int]] = set()
        created_identity: tuple[int, int] | None = None
        opened_identity: tuple[int, int] | None = None
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
            _probe_renameat2(base_fd)
            with os.scandir(f"/proc/self/fd/{base_fd}") as entries:
                for entry in entries:
                    try:
                        value = os.stat(entry.name, dir_fd=base_fd, follow_symlinks=False)
                    except OSError:
                        continue
                    preexisting.add((value.st_dev, value.st_ino))
            os.mkdir(execution_id, mode=0o700, dir_fd=base_fd)
            try:
                created_stat = os.stat(execution_id, dir_fd=base_fd, follow_symlinks=False)
            except OSError:
                raise ArtifactError("created execution workspace could not be identified") from None
            created_identity = (created_stat.st_dev, created_stat.st_ino)
            directory_fd = os.open(execution_id, flags, dir_fd=base_fd)
            workspace = ExecutionWorkspace(execution_id, directory_fd, base_fd)
            opened_identity = (workspace.device, workspace.inode)
            directory_fd = None
            base_fd = None
            # The open must identify the inode created by this call, not a
            # pre-existing sibling that was swapped into the name between
            # mkdir and open.  A fresh workspace is empty before any writes.
            if opened_identity != created_identity or opened_identity in preexisting:
                if opened_identity != created_identity and created_identity is not None:
                    self._remove_fresh_directory(workspace.base_fd, created_identity)
                workspace.close()
                workspace = None
                raise ArtifactError("execution workspace was replaced during creation")
            if not workspace.is_empty():
                raise ArtifactError("execution workspace was not fresh")
            os.fchmod(workspace.directory_fd, 0o700)
            os.fsync(workspace.base_fd)
            return workspace
        except (ArtifactError, OSError) as exc:
            if workspace is not None:
                # Once the exact new inode is known and is still empty, this
                # removes only that inode.  A pre-existing/suspicious inode is
                # closed and preserved above.
                if opened_identity is not None and opened_identity not in preexisting:
                    self.remove_execution(workspace)
                else:
                    workspace.close()
            elif base_fd is not None:
                recovery_identity = created_identity or self._find_unique_new_directory(base_fd, preexisting)
                if recovery_identity is not None and recovery_identity not in preexisting:
                    self._remove_fresh_directory(base_fd, recovery_identity)
            if isinstance(exc, ArtifactError) and str(exc):
                raise ArtifactError(str(exc)) from None
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
    def _find_identities(directory_fd: int, identity: tuple[int, int]) -> list[str]:
        try:
            entries = os.scandir(f"/proc/self/fd/{directory_fd}")
        except OSError:
            raise ArtifactError("execution artifact cleanup failed") from None
        matches: list[str] = []
        with entries:
            for entry in entries:
                try:
                    value = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError:
                    continue
                if (value.st_dev, value.st_ino) == identity:
                    matches.append(entry.name)
        return matches

    @classmethod
    def _find_identity(cls, directory_fd: int, identity: tuple[int, int]) -> str | None:
        matches = cls._find_identities(directory_fd, identity)
        return matches[0] if matches else None

    @staticmethod
    def _find_unique_new_directory(base_fd: int, preexisting: set[tuple[int, int]]) -> tuple[int, int] | None:
        try:
            entries = os.scandir(f"/proc/self/fd/{base_fd}")
        except OSError:
            raise ArtifactError("fresh execution workspace scan failed") from None
        candidates: list[tuple[tuple[int, int], bool]] = []
        flags = getattr(os, "O_PATH", os.O_RDONLY) | getattr(os, "O_NOFOLLOW", 0)
        with entries:
            for entry in entries:
                candidate_fd: int | None = None
                try:
                    candidate_fd = os.open(entry.name, flags, dir_fd=base_fd)
                    value = os.fstat(candidate_fd)
                except OSError:
                    continue
                finally:
                    if candidate_fd is not None:
                        os.close(candidate_fd)
                identity = (value.st_dev, value.st_ino)
                if identity not in preexisting:
                    candidates.append((identity, stat_module.S_ISDIR(value.st_mode)))
        return candidates[0][0] if len(candidates) == 1 and candidates[0][1] else None

    @classmethod
    def _move_to_quarantine(cls, directory_fd: int, source: str) -> str:
        for _ in range(8):
            destination = f".rollback-{uuid4().hex}.tmp"
            try:
                _rename_noreplace(source, destination, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                return destination
            except FileExistsError:
                continue
            except ArtifactError:
                raise
            except OSError:
                raise ArtifactError("artifact quarantine move failed") from None
        raise ArtifactError("artifact quarantine name collision")

    @staticmethod
    def _create_quarantine_file(directory_fd: int) -> tuple[str, tuple[int, int]]:
        for _ in range(8):
            name = f".rollback-sink-{uuid4().hex}.tmp"
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            except OSError:
                raise ArtifactError("artifact quarantine sink creation failed") from None
            try:
                value = os.fstat(fd)
                return name, (value.st_dev, value.st_ino)
            except OSError:
                # The inode was never captured, so unlinking this name would
                # be an unsafe pathname deletion.  Preserve the unknown entry
                # and fail closed; callers cannot confuse it with a sink they
                # own.
                raise ArtifactError("artifact quarantine sink identification failed") from None
            finally:
                os.close(fd)
        raise ArtifactError("artifact quarantine sink name collision")

    @staticmethod
    def _create_quarantine_directory(directory_fd: int) -> tuple[str, tuple[int, int]]:
        for _ in range(8):
            name = f".rollback-sink-{uuid4().hex}.tmp"
            try:
                os.mkdir(name, mode=0o700, dir_fd=directory_fd)
            except FileExistsError:
                continue
            except OSError:
                raise ArtifactError("execution workspace quarantine sink creation failed") from None
            fd: int | None = None
            try:
                fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                value = os.fstat(fd)
                return name, (value.st_dev, value.st_ino)
            except OSError:
                # Without a successful fstat there is no ownership proof for
                # this directory name.  Do not rmdir an unknown replacement.
                raise ArtifactError("execution workspace quarantine sink identification failed") from None
            finally:
                if fd is not None:
                    os.close(fd)
        raise ArtifactError("execution workspace quarantine sink name collision")

    @staticmethod
    def _remove_exact_file(directory_fd: int, name: str, identity: tuple[int, int]) -> None:
        fd: int | None = None
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            value = os.fstat(fd)
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (value.st_dev, value.st_ino) != identity or (named.st_dev, named.st_ino) != identity:
                raise ArtifactError("artifact quarantine sink identity changed")
            os.unlink(name, dir_fd=directory_fd)
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("artifact quarantine sink cleanup failed") from None
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _remove_exact_directory(directory_fd: int, name: str, identity: tuple[int, int]) -> None:
        fd: int | None = None
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            value = os.fstat(fd)
            if (value.st_dev, value.st_ino) != identity:
                raise ArtifactError("execution workspace quarantine sink identity changed")
            with os.scandir(f"/proc/self/fd/{fd}") as entries:
                if next(entries, None) is not None:
                    raise ArtifactError("execution workspace quarantine sink is not empty")
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (named.st_dev, named.st_ino) != identity:
                raise ArtifactError("execution workspace quarantine sink identity changed")
            os.rmdir(name, dir_fd=directory_fd)
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("execution workspace quarantine sink cleanup failed") from None
        finally:
            if fd is not None:
                os.close(fd)

    @classmethod
    def _remove_fresh_directory(cls, base_fd: int, identity: tuple[int, int]) -> None:
        """Remove one provably fresh empty directory after an open/name swap."""

        matches = cls._find_identities(base_fd, identity)
        if len(matches) != 1:
            return
        name = matches[0]
        quarantine = cls._move_to_quarantine(base_fd, name)
        moved = True
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        candidate_fd: int | None = None
        try:
            candidate_fd = os.open(quarantine, flags, dir_fd=base_fd)
            candidate_stat = os.fstat(candidate_fd)
            if (candidate_stat.st_dev, candidate_stat.st_ino) != identity:
                cls._restore_quarantine_directory(base_fd, quarantine, name)
                moved = False
                return
            with os.scandir(f"/proc/self/fd/{candidate_fd}") as entries:
                if next(entries, None) is not None:
                    cls._restore_quarantine_directory(base_fd, quarantine, name)
                    moved = False
                    return
            current = os.stat(quarantine, dir_fd=base_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != identity:
                cls._restore_quarantine_directory(base_fd, quarantine, name)
                moved = False
                return
            os.rmdir(quarantine, dir_fd=base_fd)
            moved = False
        except OSError:
            raise ArtifactError("fresh execution workspace cleanup failed") from None
        finally:
            if candidate_fd is not None:
                os.close(candidate_fd)

        if moved:
            raise ArtifactError("fresh execution workspace quarantine was not removed")

    @staticmethod
    def _restore_quarantine_directory(directory_fd: int, quarantine: str, original: str) -> None:
        try:
            _rename_noreplace(quarantine, original, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        except FileExistsError:
            raise ArtifactError("execution workspace replacement occupied original name") from None
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("execution workspace quarantine restore failed") from None

    @staticmethod
    def _restore_quarantine_name(directory_fd: int, quarantine: str, original: str) -> None:
        try:
            _rename_noreplace(quarantine, original, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        except FileExistsError:
            raise ArtifactError("artifact quarantine replacement occupied original name") from None
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("artifact quarantine replacement restore failed") from None

    @staticmethod
    def _restore_replaced_file(directory_fd: int, quarantine: str, original: str, sink_identity: tuple[int, int]) -> None:
        fd: int | None = None
        try:
            fd = os.open(quarantine, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            value = os.fstat(fd)
        except OSError:
            raise ArtifactError("artifact quarantine replacement could not be inspected") from None
        finally:
            if fd is not None:
                os.close(fd)
        if (value.st_dev, value.st_ino) == sink_identity:
            raise ArtifactError("artifact quarantine sink removal failed")
        ArtifactStore._restore_quarantine_name(directory_fd, quarantine, original)

    @staticmethod
    def _restore_replaced_directory(directory_fd: int, quarantine: str, original: str, sink_identity: tuple[int, int]) -> None:
        fd: int | None = None
        try:
            fd = os.open(quarantine, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            value = os.fstat(fd)
        except OSError:
            raise ArtifactError("execution workspace quarantine replacement could not be inspected") from None
        finally:
            if fd is not None:
                os.close(fd)
        if (value.st_dev, value.st_ino) == sink_identity:
            raise ArtifactError("execution workspace quarantine sink removal failed")
        ArtifactStore._restore_quarantine_directory(directory_fd, quarantine, original)

    @classmethod
    def _restore_then_remove_sink_file(cls, directory_fd: int, quarantine: str, original: str, sink: str, sink_identity: tuple[int, int]) -> None:
        """Restore the owned entry and remove only our still-identified sink."""

        failure: ArtifactError | None = None
        try:
            cls._restore_quarantine_name(directory_fd, quarantine, original)
        except ArtifactError as exc:
            failure = exc
        try:
            cls._remove_exact_file(directory_fd, sink, sink_identity)
        except ArtifactError as exc:
            failure = failure or exc
        if failure is not None:
            raise failure

    @classmethod
    def _reverse_restore_remove_file(cls, directory_fd: int, quarantine: str, original: str, sink: str, sink_identity: tuple[int, int]) -> None:
        """Reverse a successful exchange, then restore and clean its sink.

        If the reverse exchange itself fails, the sink contains the owned
        data, so it is deliberately left untouched and the error is raised.
        """

        try:
            _rename_exchange(sink, quarantine, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        except (ArtifactError, OSError) as exc:
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError("artifact quarantine reverse exchange failed") from None
        cls._restore_then_remove_sink_file(directory_fd, quarantine, original, sink, sink_identity)

    @classmethod
    def _restore_then_remove_sink_directory(cls, directory_fd: int, quarantine: str, original: str, sink: str, sink_identity: tuple[int, int]) -> None:
        failure: ArtifactError | None = None
        try:
            cls._restore_quarantine_directory(directory_fd, quarantine, original)
        except ArtifactError as exc:
            failure = exc
        try:
            cls._remove_exact_directory(directory_fd, sink, sink_identity)
        except ArtifactError as exc:
            failure = failure or exc
        if failure is not None:
            raise failure

    @classmethod
    def _reverse_restore_remove_directory(cls, directory_fd: int, quarantine: str, original: str, sink: str, sink_identity: tuple[int, int]) -> None:
        try:
            _rename_exchange(sink, quarantine, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        except (ArtifactError, OSError) as exc:
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError("execution workspace quarantine reverse exchange failed") from None
        cls._restore_then_remove_sink_directory(directory_fd, quarantine, original, sink, sink_identity)

    @classmethod
    def _quarantine_remove_child(cls, directory_fd: int, identity: tuple[int, int]) -> bool:
        matches = cls._find_identities(directory_fd, identity)
        if len(matches) != 1:
            return False
        original = matches[0]
        try:
            current = os.stat(original, dir_fd=directory_fd, follow_symlinks=False)
        except OSError:
            return False
        if (current.st_dev, current.st_ino) != identity or not stat_module.S_ISREG(current.st_mode):
            return False
        quarantine = cls._move_to_quarantine(directory_fd, original)
        try:
            sink, sink_identity = cls._create_quarantine_file(directory_fd)
        except ArtifactError:
            cls._restore_quarantine_name(directory_fd, quarantine, original)
            raise
        exchanged = False
        try:
            try:
                _rename_exchange(quarantine, sink, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            except (ArtifactError, OSError) as exc:
                cls._restore_then_remove_sink_file(directory_fd, quarantine, original, sink, sink_identity)
                if isinstance(exc, ArtifactError):
                    raise
                raise ArtifactError("artifact quarantine exchange failed") from None
            exchanged = True
            moved_fd: int | None = None
            try:
                moved_fd = os.open(sink, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                moved = os.fstat(moved_fd)
                named = os.stat(sink, dir_fd=directory_fd, follow_symlinks=False)
                if (
                    (moved.st_dev, moved.st_ino) != identity
                    or (named.st_dev, named.st_ino) != identity
                    or not stat_module.S_ISREG(moved.st_mode)
                ):
                    exchanged = False
                    cls._reverse_restore_remove_file(directory_fd, quarantine, original, sink, sink_identity)
                    raise ArtifactError("artifact quarantine inode mismatch")
            except OSError:
                if exchanged:
                    exchanged = False
                    cls._reverse_restore_remove_file(directory_fd, quarantine, original, sink, sink_identity)
                raise ArtifactError("artifact quarantine verification failed") from None
            finally:
                if moved_fd is not None:
                    os.close(moved_fd)
            try:
                cls._remove_exact_file(directory_fd, sink, identity)
            except ArtifactError:
                exchanged = False
                cls._reverse_restore_remove_file(directory_fd, quarantine, original, sink, sink_identity)
                raise
            try:
                cls._remove_exact_file(directory_fd, quarantine, sink_identity)
            except ArtifactError:
                cls._restore_replaced_file(directory_fd, quarantine, original, sink_identity)
                raise
            return True
        except ArtifactError:
            raise
        except OSError:
            raise ArtifactError("artifact quarantine exchange failed") from None

    @classmethod
    def _quarantine_remove_workspace(cls, base_fd: int, identity: tuple[int, int]) -> bool:
        matches = cls._find_identities(base_fd, identity)
        if len(matches) != 1:
            return False
        original = matches[0]
        quarantine = cls._move_to_quarantine(base_fd, original)
        try:
            sink, sink_identity = cls._create_quarantine_directory(base_fd)
        except ArtifactError:
            cls._restore_quarantine_directory(base_fd, quarantine, original)
            raise
        exchanged = False
        candidate_fd: int | None = None
        try:
            try:
                _rename_exchange(quarantine, sink, src_dir_fd=base_fd, dst_dir_fd=base_fd)
            except (ArtifactError, OSError) as exc:
                cls._restore_then_remove_sink_directory(base_fd, quarantine, original, sink, sink_identity)
                if isinstance(exc, ArtifactError):
                    raise
                raise ArtifactError("execution workspace quarantine exchange failed") from None
            exchanged = True
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            candidate_fd = os.open(sink, flags, dir_fd=base_fd)
            value = os.fstat(candidate_fd)
            named = os.stat(sink, dir_fd=base_fd, follow_symlinks=False)
            with os.scandir(f"/proc/self/fd/{candidate_fd}") as entries:
                nonempty = next(entries, None) is not None
            if (
                (value.st_dev, value.st_ino) != identity
                or (named.st_dev, named.st_ino) != identity
                or nonempty
            ):
                exchanged = False
                cls._reverse_restore_remove_directory(base_fd, quarantine, original, sink, sink_identity)
                raise ArtifactError("execution workspace quarantine inode mismatch")
            try:
                cls._remove_exact_directory(base_fd, sink, identity)
            except ArtifactError:
                exchanged = False
                cls._reverse_restore_remove_directory(base_fd, quarantine, original, sink, sink_identity)
                raise
            try:
                cls._remove_exact_directory(base_fd, quarantine, sink_identity)
            except ArtifactError:
                cls._restore_replaced_directory(base_fd, quarantine, original, sink_identity)
                raise
            return True
        except ArtifactError:
            raise
        except OSError:
            if exchanged:
                cls._reverse_restore_remove_directory(base_fd, quarantine, original, sink, sink_identity)
            raise ArtifactError("execution workspace quarantine cleanup failed") from None
        finally:
            if candidate_fd is not None:
                os.close(candidate_fd)

    def remove_execution(self, workspace: ExecutionWorkspace) -> None:
        """Remove only the inode owned by a live workspace.

        If the original name was replaced, the trusted parent descriptor is
        scanned for the owned inode and only that exact entry is removed.
        """

        if not isinstance(workspace, ExecutionWorkspace) or workspace.closed:
            raise ArtifactError("live execution workspace is required")
        try:
            _probe_renameat2(workspace.base_fd)
            base_stat = os.fstat(workspace.base_fd)
            directory_stat = os.fstat(workspace.directory_fd)
            if (base_stat.st_dev, base_stat.st_ino) != (workspace.base_device, workspace.base_inode):
                raise ArtifactError("execution artifact parent identity changed")
            if (directory_stat.st_dev, directory_stat.st_ino) != (workspace.device, workspace.inode):
                raise ArtifactError("execution artifact ownership mismatch")
            # Only direct children created through this workspace may be
            # removed.  Unknown files/directories are preserved and therefore
            # prevent the workspace directory from being removed below.
            for _child_name, child_identity in tuple(workspace._children):
                self._quarantine_remove_child(workspace.directory_fd, child_identity)
            with os.scandir(f"/proc/self/fd/{workspace.directory_fd}") as entries:
                if next(entries, None) is not None:
                    raise ArtifactError("unknown execution artifacts were preserved")
            self._quarantine_remove_workspace(workspace.base_fd, (workspace.device, workspace.inode))
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
