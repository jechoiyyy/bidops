"""Immutable, byte-oriented company profile snapshots.

The screening runtime must never silently use a different profile than the one
that was recorded with an execution.  This module is intentionally independent
from the profile *parser*: the source of truth here is the exact byte stream,
and the stored artifact is verified again whenever it is read.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.models import utc_now
from .models import CompanyProfileSnapshot


PROFILE_SOURCE_PATH: Final[str] = "docs/reference/company-profile.md"
BASELINE_COMMIT: Final[str] = "ee621835db934ddac944f7a07a986ed0b73ecc7a"
BASELINE_PROFILE_PATH: Final[Path] = Path(__file__).with_name("baseline_company_profile.md")
BASELINE_PROFILE_SHA256: Final[str] = "a231ab54c36031a7e72779bbca550f70561dc0c946dc5544eeb930c7c6149de2"
PROFILE_ARTIFACT_PREFIX: Final[str] = "web/data/profile-snapshots/"
GIT_TIMEOUT_SECONDS: Final[float] = 10.0
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class ProfileSnapshotError(RuntimeError):
    """Raised when the canonical profile source or snapshot is unsafe."""


class ProfileSnapshotConflict(ProfileSnapshotError):
    """Raised when a durable profile artifact does not match its digest."""


class _GitLookupUnavailable(ProfileSnapshotError):
    """Git is unavailable, so the approved vendored baseline may be used."""


SnapshotError = ProfileSnapshotError
SnapshotConflict = ProfileSnapshotConflict


@dataclass(frozen=True)
class ProfileSource:
    """The bytes and metadata used to create one profile snapshot."""

    raw: bytes
    source_kind: str
    source_ref: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


def _safe_under(root: Path, candidate: Path, *, label: str) -> Path:
    """Resolve *candidate* and reject paths that escape *root*."""

    root_resolved = root.resolve(strict=True)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ProfileSnapshotError(f"{label} path is missing or outside the project root") from exc
    return resolved


def _reject_symlink_components(root: Path, candidate: Path, *, label: str) -> None:
    """Reject the source/artifact path itself and every existing component."""

    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ProfileSnapshotError(f"{label} path is outside the project root") from None
    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise ProfileSnapshotError(f"{label} path must not contain a symlink")


def _project_root(project_root: Path | None) -> Path:
    configured = project_root or get_settings().bidops_root
    root = Path(configured).resolve()
    if not root.is_dir():
        raise ProfileSnapshotError("project root is not a directory")
    return root


def _source_path(root: Path, relative: str = PROFILE_SOURCE_PATH) -> Path:
    # The relative path is a protocol value, not user-controlled filesystem
    # input.  Keep this strict even though _safe_under also checks traversal.
    if relative != PROFILE_SOURCE_PATH:
        raise ProfileSnapshotError("profile source path is not the canonical path")
    candidate = root / relative
    _reject_symlink_components(root, candidate, label="profile source")
    path = _safe_under(root, candidate, label="profile source")
    if not path.is_file():
        raise ProfileSnapshotError("profile source is not a regular file")
    return path


def read_working_tree_source(project_root: Path | None = None) -> ProfileSource:
    """Read the current profile as raw bytes."""

    root = _project_root(project_root)
    path = _source_path(root)
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise ProfileSnapshotError("profile source could not be read") from exc
    return ProfileSource(raw=raw, source_kind="working_tree", source_ref=PROFILE_SOURCE_PATH)


def _git_blob(root: Path, commit: str, relative: str) -> bytes:
    if commit != BASELINE_COMMIT or not _HEX40_RE.fullmatch(commit):
        raise ProfileSnapshotError("git profile source must use the approved full commit")
    if relative != PROFILE_SOURCE_PATH:
        raise ProfileSnapshotError("git profile source path is not the canonical path")
    # The project is a nested worktree in this repository.  Git object paths
    # are relative to the repository top-level, while the contract path is
    # relative to the BidOps project root.
    try:
        repo_top_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
        if repo_top_result.returncode != 0:
            raise _GitLookupUnavailable("git repository could not be located")
        repo_top = Path(repo_top_result.stdout.strip()).resolve()
        project_prefix = root.resolve().relative_to(repo_top)
        git_relative = (project_prefix / relative).as_posix()
    except subprocess.TimeoutExpired:
        raise ProfileSnapshotError("git profile source inspection timed out") from None
    except FileNotFoundError as exc:
        raise _GitLookupUnavailable("git executable is unavailable") from exc
    except (OSError, ValueError) as exc:
        raise ProfileSnapshotError("git repository path is invalid") from exc
    # Verify the object is a blob before reading it.  Separate argv items are
    # used throughout; no source value is interpolated into a shell command.
    try:
        kind = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-t", f"{commit}:{git_relative}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ProfileSnapshotError("git profile source inspection timed out") from None
    except FileNotFoundError as exc:
        raise _GitLookupUnavailable("git executable is unavailable") from exc
    except OSError as exc:
        raise ProfileSnapshotError("git profile source could not be inspected") from exc
    if kind.returncode != 0 or kind.stdout.strip() != "blob":
        raise ProfileSnapshotError("approved git profile blob is missing")
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{git_relative}"],
            check=False,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ProfileSnapshotError("git profile source read timed out") from None
    except FileNotFoundError as exc:
        raise _GitLookupUnavailable("git executable is unavailable") from exc
    except OSError as exc:
        raise ProfileSnapshotError("git profile source could not be read") from exc
    if result.returncode != 0:
        raise ProfileSnapshotError("approved git profile blob could not be read")
    return bytes(result.stdout)


def _vendored_baseline_blob() -> bytes:
    """Read and verify the one approved baseline blob bundled for containers."""

    path = BASELINE_PROFILE_PATH
    if path.is_symlink() or not path.is_file():
        raise ProfileSnapshotError("vendored baseline profile is missing or not a regular file")
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise ProfileSnapshotError("vendored baseline profile could not be read") from exc
    if hashlib.sha256(raw).hexdigest() != BASELINE_PROFILE_SHA256:
        raise ProfileSnapshotConflict("vendored baseline profile digest does not match its identity")
    return raw


def read_git_source(
    project_root: Path | None = None,
    *,
    commit: str = BASELINE_COMMIT,
    relative: str = PROFILE_SOURCE_PATH,
) -> ProfileSource:
    """Read the approved historical profile blob as raw bytes."""

    root = _project_root(project_root)
    try:
        raw = _git_blob(root, commit, relative)
        # Git remains authoritative whenever it is available, while this
        # equality check prevents the vendored fallback from drifting from the
        # approved historical blob in source checkouts.
        if raw != _vendored_baseline_blob():
            raise ProfileSnapshotConflict("git profile blob differs from vendored baseline")
    except _GitLookupUnavailable:
        if commit != BASELINE_COMMIT or relative != PROFILE_SOURCE_PATH:
            raise ProfileSnapshotError("approved git profile source is unavailable") from None
        raw = _vendored_baseline_blob()
    return ProfileSource(raw=raw, source_kind="git_blob", source_ref=commit)


def profile_artifact_path(project_root: Path, digest: str) -> Path:
    """Return the physical artifact path after validating its digest."""

    if not _HEX64_RE.fullmatch(digest):
        raise ProfileSnapshotError("profile digest is invalid")
    root = _project_root(project_root)
    directory = root / "web" / "data" / "profile-snapshots"
    _reject_symlink_components(root, directory, label="profile artifact")
    if directory.exists():
        _safe_under(root, directory, label="profile artifact")
    return directory / f"{digest}.md"


def _artifact_bytes(root: Path, digest: str) -> bytes:
    path = profile_artifact_path(root, digest)
    try:
        _reject_symlink_components(root, path, label="profile artifact")
        path_resolved = _safe_under(root, path, label="profile artifact")
        if not path_resolved.is_file():
            raise ProfileSnapshotError("profile artifact is not a regular file")
        raw = path_resolved.read_bytes()
    except ProfileSnapshotError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ProfileSnapshotError("profile artifact could not be read") from exc
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ProfileSnapshotConflict("profile artifact digest does not match its identity")
    return raw


def _write_artifact(root: Path, digest: str, raw: bytes) -> None:
    path = profile_artifact_path(root, digest)
    directory = path.parent
    try:
        _reject_symlink_components(root, directory, label="profile artifact")
        directory.mkdir(parents=True, exist_ok=True)
        # Re-check after mkdir to catch a symlink introduced concurrently.
        _reject_symlink_components(root, path, label="profile artifact")
        _safe_under(root, directory, label="profile artifact")
        if path.exists() or path.is_symlink():
            existing = _artifact_bytes(root, digest)
            if existing != raw:
                raise ProfileSnapshotConflict("profile artifact already contains different bytes")
            return
        # Write a hidden same-directory temp file, fsync it, then hard-link it
        # into place.  os.link is atomic and never replaces an existing path,
        # so concurrent writers cannot expose a partial artifact or overwrite
        # a different byte stream.
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=directory,
                prefix=f".{digest}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary_name, path)
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
    except FileExistsError:
        existing = _artifact_bytes(root, digest)
        if existing != raw:
            raise ProfileSnapshotConflict("profile artifact already contains different bytes")
    except ProfileSnapshotError:
        raise
    except OSError as exc:
        raise ProfileSnapshotError("profile artifact could not be written") from exc


def _artifact_relative(digest: str) -> str:
    return f"{PROFILE_ARTIFACT_PREFIX}{digest}.md"


def create_profile_snapshot(
    session: Session,
    *,
    source_kind: str = "working_tree",
    commit: str = BASELINE_COMMIT,
    source_ref: str | None = None,
    profile_source: str | None = None,
    source: str | None = None,
    project_root: Path | None = None,
) -> CompanyProfileSnapshot:
    """Persist/reuse a snapshot for the canonical working tree or baseline blob."""

    if source is not None:
        if profile_source is not None:
            raise ProfileSnapshotError("provide only one profile source selector")
        profile_source = source
    if profile_source is not None:
        if profile_source == "current":
            source_kind = "working_tree"
        elif profile_source == "git":
            source_kind = "git_blob"
        elif profile_source.startswith("git:"):
            source_kind = "git_blob"
            commit = profile_source.removeprefix("git:")
        else:
            raise ProfileSnapshotError("profile source selector is invalid")
    if source_ref is not None:
        if source_kind == "working_tree":
            if source_ref != PROFILE_SOURCE_PATH:
                raise ProfileSnapshotError("profile source path is not the canonical path")
        elif source_kind == "git_blob":
            commit = source_ref
        else:
            raise ProfileSnapshotError("unknown profile source kind")
    root = _project_root(project_root)
    if source_kind == "working_tree":
        source = read_working_tree_source(root)
    elif source_kind == "git_blob":
        source = read_git_source(root, commit=commit)
    else:
        raise ProfileSnapshotError("unknown profile source kind")

    digest = source.digest
    version = f"company-profile.sha256:{digest}"
    artifact = _artifact_relative(digest)

    existing = session.scalar(
        select(CompanyProfileSnapshot).where(CompanyProfileSnapshot.digest == digest)
    )
    if existing is not None:
        if (
            existing.version != version
            or existing.artifact_path != artifact
            or existing.source_kind not in {"working_tree", "git_blob"}
        ):
            raise ProfileSnapshotConflict("profile snapshot metadata conflicts with its digest")
        # Always verify an existing row's artifact before reuse.
        _write_artifact(root, digest, source.raw)
        _artifact_bytes(root, digest)
        return existing

    row = CompanyProfileSnapshot(
        digest=digest,
        version=version,
        source_kind=source.source_kind,
        source_ref=source.source_ref,
        artifact_path=artifact,
        created_at=utc_now(),
    )
    try:
        # Establish the DB identity first, then finalize the content-addressed
        # artifact in the caller's transaction.  Do not create/release a
        # nested transaction here: callers must retain control of commit and
        # a later caller rollback must remove this row.  An artifact can remain
        # orphaned after that rollback because its content address makes it
        # safe to verify and reuse on the next attempt.
        session.add(row)
        session.flush()
        _write_artifact(root, digest, source.raw)
    except (IntegrityError, OperationalError):
        session.rollback()
        existing = session.scalar(
            select(CompanyProfileSnapshot).where(CompanyProfileSnapshot.digest == digest)
        )
        if existing is None:
            raise ProfileSnapshotConflict("profile snapshot could not be persisted") from None
        _artifact_bytes(root, digest)
        return existing
    except ProfileSnapshotError:
        # Artifact finalization failed after the row was flushed.  Leave no
        # uncommitted identity in the session, while allowing any fully
        # written content-addressed artifact to be reused safely.
        session.rollback()
        raise
    return row


def get_profile_snapshot(
    session: Session,
    *,
    digest: str | None = None,
    version: str | None = None,
) -> CompanyProfileSnapshot:
    """Fetch one snapshot by digest or version without exposing its body."""

    if (digest is None) == (version is None):
        raise ProfileSnapshotError("provide exactly one profile snapshot identity")
    statement = select(CompanyProfileSnapshot)
    if digest is not None:
        if not _HEX64_RE.fullmatch(digest):
            raise ProfileSnapshotError("profile digest is invalid")
        statement = statement.where(CompanyProfileSnapshot.digest == digest)
    else:
        assert version is not None
        if not version.startswith("company-profile.sha256:"):
            raise ProfileSnapshotError("profile version is invalid")
        value = version.removeprefix("company-profile.sha256:")
        if not _HEX64_RE.fullmatch(value):
            raise ProfileSnapshotError("profile version is invalid")
        statement = statement.where(CompanyProfileSnapshot.version == version)
    row = session.scalar(statement)
    if row is None:
        raise ProfileSnapshotError("profile snapshot was not found")
    return row


def read_profile_snapshot(
    session: Session,
    *,
    digest: str | None = None,
    version: str | None = None,
    project_root: Path | None = None,
) -> bytes:
    """Read and verify the immutable artifact bytes for a DB snapshot."""

    row = get_profile_snapshot(session, digest=digest, version=version)
    root = _project_root(project_root)
    expected = _artifact_relative(row.digest)
    if row.artifact_path != expected:
        raise ProfileSnapshotConflict("profile snapshot artifact metadata is invalid")
    return _artifact_bytes(root, row.digest)


# Short aliases make the repository useful to callers that treat snapshot
# creation as a verb, while keeping the explicit names above for API code.
snapshot_profile = create_profile_snapshot
read_snapshot = read_profile_snapshot
read_artifact = read_profile_snapshot


def snapshot_current(
    session: Session,
    *,
    project_root: Path | None = None,
) -> CompanyProfileSnapshot:
    return create_profile_snapshot(session, source_kind="working_tree", project_root=project_root)


def snapshot_git_blob(
    session: Session,
    *,
    commit: str = BASELINE_COMMIT,
    project_root: Path | None = None,
) -> CompanyProfileSnapshot:
    return create_profile_snapshot(
        session,
        source_kind="git_blob",
        commit=commit,
        project_root=project_root,
    )


class ProfileSnapshotRepository:
    """Small object facade for callers that keep a repository per session."""

    def __init__(self, session: Session, *, project_root: Path | None = None):
        self.session = session
        self.project_root = project_root

    def create(
        self,
        *,
        source_kind: str = "working_tree",
        commit: str = BASELINE_COMMIT,
        source_ref: str | None = None,
        profile_source: str | None = None,
        source: str | None = None,
    ) -> CompanyProfileSnapshot:
        return create_profile_snapshot(
            self.session,
            source_kind=source_kind,
            commit=commit,
            source_ref=source_ref,
            profile_source=profile_source,
            source=source,
            project_root=self.project_root,
        )

    snapshot = create
    create_snapshot = create

    def create_current(self) -> CompanyProfileSnapshot:
        return self.create(source_kind="working_tree")

    def create_baseline(self) -> CompanyProfileSnapshot:
        return self.create(source_kind="git_blob", commit=BASELINE_COMMIT)

    def get(self, *, digest: str | None = None, version: str | None = None) -> CompanyProfileSnapshot:
        return get_profile_snapshot(self.session, digest=digest, version=version)

    def read(self, *, digest: str | None = None, version: str | None = None) -> bytes:
        return read_profile_snapshot(
            self.session,
            digest=digest,
            version=version,
            project_root=self.project_root,
        )


ProfileSnapshotStore = ProfileSnapshotRepository


__all__ = [
    "BASELINE_COMMIT",
    "BASELINE_PROFILE_PATH",
    "BASELINE_PROFILE_SHA256",
    "PROFILE_SOURCE_PATH",
    "GIT_TIMEOUT_SECONDS",
    "ProfileSnapshotConflict",
    "ProfileSnapshotError",
    "ProfileSnapshotRepository",
    "ProfileSnapshotStore",
    "ProfileSource",
    "SnapshotConflict",
    "SnapshotError",
    "create_profile_snapshot",
    "get_profile_snapshot",
    "profile_artifact_path",
    "read_git_source",
    "read_profile_snapshot",
    "read_snapshot",
    "read_artifact",
    "read_working_tree_source",
    "snapshot_profile",
    "snapshot_current",
    "snapshot_git_blob",
]
