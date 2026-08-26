from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

import app.screening.profile_snapshot as snapshot_module
from app.screening.profile_snapshot import (
    BASELINE_COMMIT,
    BASELINE_PROFILE_PATH,
    BASELINE_PROFILE_SHA256,
    PROFILE_SOURCE_PATH,
    ProfileSnapshotConflict,
    ProfileSnapshotError,
    read_git_source,
    read_working_tree_source,
)


def test_missing_git_uses_only_the_hash_verified_baseline(monkeypatch, tmp_path: Path):
    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(snapshot_module.subprocess, "run", missing_git)
    source = read_git_source(tmp_path, commit=BASELINE_COMMIT)

    assert source.source_kind == "git_blob"
    assert source.source_ref == BASELINE_COMMIT
    assert hashlib.sha256(source.raw).hexdigest() == BASELINE_PROFILE_SHA256
    assert source.raw == BASELINE_PROFILE_PATH.read_bytes()


def test_tampered_vendored_baseline_is_rejected_without_git(monkeypatch, tmp_path: Path):
    tampered = tmp_path / "baseline_company_profile.md"
    tampered.write_bytes(b"not the approved profile")
    monkeypatch.setattr(snapshot_module, "BASELINE_PROFILE_PATH", tampered)
    monkeypatch.setattr(
        snapshot_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git")),
    )

    with pytest.raises(ProfileSnapshotConflict, match="vendored baseline profile digest"):
        read_git_source(tmp_path, commit=BASELINE_COMMIT)


def test_other_commit_never_falls_back_to_the_baseline(tmp_path: Path):
    with pytest.raises(ProfileSnapshotError):
        read_git_source(tmp_path, commit="0" * 40)


def test_vendored_baseline_equals_git_show_in_a_source_checkout():
    root = Path(__file__).resolve().parents[3]
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is not installed in this runtime")
    probe = subprocess.run(
        [git, "-C", str(root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip("the runtime does not contain a source checkout")

    expected = subprocess.run(
        [
            git,
            "-C",
            str(root),
            "show",
            f"{BASELINE_COMMIT}:bidops-agent/{PROFILE_SOURCE_PATH}",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert BASELINE_PROFILE_PATH.read_bytes() == expected
    assert read_git_source(root).raw == expected


def test_missing_current_working_tree_profile_fails_clearly(tmp_path: Path):
    with pytest.raises(ProfileSnapshotError, match="profile source"):
        read_working_tree_source(tmp_path)
