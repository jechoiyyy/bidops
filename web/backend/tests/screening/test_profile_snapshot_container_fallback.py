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


# 승인 baseline 원본은 회사 자료라 저장소에 없다(.gitignore). 대체 경로의 동작은 같은 위치의
# 합성 예시와 그 hash로 검사한다. 원본이 있는 운영 checkout에서도 결과는 같다.
EXAMPLE_BASELINE = BASELINE_PROFILE_PATH.with_name("baseline_company_profile.example.md")


def _use_example_baseline(monkeypatch) -> str:
    digest = hashlib.sha256(EXAMPLE_BASELINE.read_bytes()).hexdigest()
    monkeypatch.setattr(snapshot_module, "BASELINE_PROFILE_PATH", EXAMPLE_BASELINE)
    monkeypatch.setattr(snapshot_module, "BASELINE_PROFILE_SHA256", digest)
    return digest


def test_missing_git_uses_only_the_hash_verified_baseline(monkeypatch, tmp_path: Path):
    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    digest = _use_example_baseline(monkeypatch)
    monkeypatch.setattr(snapshot_module.subprocess, "run", missing_git)
    source = read_git_source(tmp_path, commit=BASELINE_COMMIT)

    assert source.source_kind == "git_blob"
    assert source.source_ref == BASELINE_COMMIT
    assert hashlib.sha256(source.raw).hexdigest() == digest
    assert source.raw == EXAMPLE_BASELINE.read_bytes()


def test_missing_vendored_baseline_fails_clearly_without_git(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(snapshot_module, "BASELINE_PROFILE_PATH", tmp_path / "baseline_company_profile.md")
    monkeypatch.setattr(
        snapshot_module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git")),
    )

    with pytest.raises(ProfileSnapshotError, match="vendored baseline profile is missing"):
        read_git_source(tmp_path, commit=BASELINE_COMMIT)


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


def test_source_checkout_compares_vendored_baseline_or_fails_closed():
    root = Path(__file__).resolve().parents[4]
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

    repo_top = Path(probe.stdout.decode().strip()).resolve()
    git_relative = (root.resolve().relative_to(repo_top) / PROFILE_SOURCE_PATH).as_posix()
    approved_spec = f"{BASELINE_COMMIT}:{git_relative}"
    blob_probe = subprocess.run(
        [git, "-C", str(root), "cat-file", "-t", approved_spec],
        check=False,
        capture_output=True,
    )
    if blob_probe.returncode != 0 or blob_probe.stdout.strip() != b"blob":
        with pytest.raises(ProfileSnapshotError, match="approved git profile blob is missing"):
            read_git_source(root)
        return

    expected = subprocess.run(
        [git, "-C", str(root), "show", approved_spec],
        check=True,
        capture_output=True,
    ).stdout
    if not BASELINE_PROFILE_PATH.is_file():
        with pytest.raises(ProfileSnapshotError, match="vendored baseline profile is missing"):
            read_git_source(root)
        return
    assert BASELINE_PROFILE_PATH.read_bytes() == expected
    assert read_git_source(root).raw == expected


def test_missing_current_working_tree_profile_fails_clearly(tmp_path: Path):
    with pytest.raises(ProfileSnapshotError, match="profile source"):
        read_working_tree_source(tmp_path)
