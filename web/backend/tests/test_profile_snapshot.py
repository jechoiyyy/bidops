from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import CompanyProfileSnapshot
from app.screening.profile_snapshot import (
    BASELINE_COMMIT,
    PROFILE_SOURCE_PATH,
    ProfileSnapshotConflict,
    ProfileSnapshotError,
    create_profile_snapshot,
    read_profile_snapshot,
    read_git_source,
)
import app.screening.profile_snapshot as snapshot_module


def session_for(*tables):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[table.__table__ for table in tables])
    return Session(engine)


def project(tmp_path: Path, raw: bytes = b"# profile\n") -> Path:
    source = tmp_path / PROFILE_SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes(raw)
    return tmp_path


def test_current_snapshot_uses_raw_bytes_and_is_reusable(tmp_path: Path):
    root = project(tmp_path, b"\xef\xbb\xbfprofile\r\n")
    session = session_for(CompanyProfileSnapshot)
    first = create_profile_snapshot(session, project_root=root)
    second = create_profile_snapshot(session, project_root=root)

    digest = hashlib.sha256(b"\xef\xbb\xbfprofile\r\n").hexdigest()
    assert first is second
    assert first.digest == digest
    assert first.version == f"company-profile.sha256:{digest}"
    assert first.source_kind == "working_tree"
    assert first.source_ref == PROFILE_SOURCE_PATH
    artifact = root / "web/data/profile-snapshots" / f"{digest}.md"
    assert artifact.read_bytes() == b"\xef\xbb\xbfprofile\r\n"
    assert read_profile_snapshot(session, digest=digest, project_root=root) == artifact.read_bytes()


def test_baseline_git_snapshot_and_source_validation():
    root = Path(__file__).resolve().parents[3]
    session = session_for(CompanyProfileSnapshot)
    row = create_profile_snapshot(
        session,
        source_kind="git_blob",
        source_ref=BASELINE_COMMIT,
        project_root=root,
    )
    expected = subprocess.run(
        ["git", "-C", str(root), "show", f"{BASELINE_COMMIT}:bidops-agent/{PROFILE_SOURCE_PATH}"],
        check=True,
        capture_output=True,
    ).stdout
    assert row.digest == hashlib.sha256(expected).hexdigest()
    with pytest.raises(ProfileSnapshotError):
        create_profile_snapshot(session, source_kind="git_blob", source_ref="HEAD", project_root=root)
    with pytest.raises(ProfileSnapshotError):
        create_profile_snapshot(session, source_kind="working_tree", source_ref="../escape", project_root=root)


def test_tampered_artifact_is_rejected_on_read(tmp_path: Path):
    root = project(tmp_path)
    session = session_for(CompanyProfileSnapshot)
    row = create_profile_snapshot(session, project_root=root)
    session.flush()
    (root / row.artifact_path).write_bytes(b"tampered")
    with pytest.raises(ProfileSnapshotConflict):
        read_profile_snapshot(session, digest=row.digest, project_root=root)


def test_snapshot_caller_rollback_removes_row_and_reuses_orphan_artifact(tmp_path: Path):
    root = project(tmp_path, b"rollback-safe\n")
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[CompanyProfileSnapshot.__table__])
    session = Session(engine)

    first = create_profile_snapshot(session, project_root=root)
    digest = first.digest
    artifact = root / first.artifact_path
    assert artifact.read_bytes() == b"rollback-safe\n"

    session.rollback()
    assert session.scalar(select(CompanyProfileSnapshot)) is None
    with Session(engine) as verification:
        assert verification.scalar(select(CompanyProfileSnapshot)) is None

    retried = create_profile_snapshot(session, project_root=root)
    assert retried.digest == digest
    assert artifact.read_bytes() == b"rollback-safe\n"
    session.commit()
    with Session(engine) as verification:
        persisted = verification.scalar(select(CompanyProfileSnapshot))
        assert persisted is not None
        assert persisted.digest == digest


def test_profile_source_component_symlink_is_rejected_even_inside_root(tmp_path: Path):
    root = tmp_path
    target = root / "docs" / "profile-ref"
    target.mkdir(parents=True)
    (target / "company-profile.md").write_bytes(b"profile")
    (root / "docs" / "reference").symlink_to(target, target_is_directory=True)
    session = session_for(CompanyProfileSnapshot)
    with pytest.raises(ProfileSnapshotError):
        create_profile_snapshot(session, project_root=root)


def test_git_timeout_is_operator_safe(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(snapshot_module.subprocess, "run", timeout)
    with pytest.raises(ProfileSnapshotError, match="timed out"):
        read_git_source(Path(__file__).resolve().parents[3])


def test_artifact_failure_rolls_back_new_identity_and_leaves_no_partial_file(tmp_path: Path, monkeypatch):
    root = project(tmp_path)
    session = session_for(CompanyProfileSnapshot)

    def fail_link(*args, **kwargs):
        raise OSError("simulated install failure")

    monkeypatch.setattr(snapshot_module.os, "link", fail_link)
    with pytest.raises(ProfileSnapshotError):
        create_profile_snapshot(session, project_root=root)
    assert session.scalar(select(CompanyProfileSnapshot)) is None
    artifact_dir = root / "web/data/profile-snapshots"
    assert not list(artifact_dir.glob("*.md"))
    assert not list(artifact_dir.glob(".*.tmp"))
