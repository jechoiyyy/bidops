from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.screening.artifacts import ArtifactError, ArtifactStore, ExecutionOwnership
from app.config import Settings
from app.screening.worker import ScreeningWorker, WorkerError, _open_run_fds


EXECUTION_ID = "scr-" + "a" * 32


def test_artifacts_reject_traversal_and_symlink_components(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    store.execution_dir(EXECUTION_ID, create=True)
    with pytest.raises(ArtifactError):
        store.write_json(EXECUTION_ID, "../outside.json", {"safe": True})
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "data/screening-executions" / EXECUTION_ID / "responses").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactError):
        store.write_json(EXECUTION_ID, "responses/leak.json", {"secret": "no"})


def test_remove_execution_unlinks_symlinks_without_following_them(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    store.execution_dir(EXECUTION_ID, create=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    (target / "leak.txt").symlink_to(sentinel)
    nested = target / "nested"
    nested.mkdir()
    (nested / "safe.txt").write_text("remove", encoding="utf-8")
    ownership = store.capture_execution_ownership(EXECUTION_ID)
    store.remove_execution(EXECUTION_ID, ownership)
    assert not target.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_remove_execution_refuses_symlinked_target_path(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    base = tmp_path / "data/screening-executions"
    base.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("keep", encoding="utf-8")
    (base / EXECUTION_ID).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactError):
        store.remove_execution(EXECUTION_ID, ExecutionOwnership(EXECUTION_ID, 0, 0))
    assert (outside / "sentinel.txt").read_text(encoding="utf-8") == "keep"


def test_remove_execution_does_not_delete_replacement_after_name_swap(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    store.execution_dir(EXECUTION_ID, create=True)
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    ownership = store.capture_execution_ownership(EXECUTION_ID)
    owned_away = target.with_name(EXECUTION_ID + "-owned-away")
    target.rename(owned_away)
    replacement = target.with_name(EXECUTION_ID + "-replacement")
    replacement.mkdir()
    sentinel = replacement / "must-survive.txt"
    sentinel.write_text("keep", encoding="utf-8")
    replacement.rename(target)
    with pytest.raises(ArtifactError):
        store.remove_execution(EXECUTION_ID, ownership)
    assert (target / "must-survive.txt").read_text(encoding="utf-8") == "keep"
    assert target.is_dir()
    assert owned_away.is_dir()


def test_append_jsonl_is_exact_and_atomic_write_failure_is_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    store.execution_dir(EXECUTION_ID, create=True)
    path, _digest = store.append_jsonl(EXECUTION_ID, "screening-telemetry.jsonl", {"b": 2, "a": 1})
    assert Path(tmp_path / path).read_bytes() == b'{"a":1,"b":2}\n'

    def fail_link(*_args, **_kwargs):
        raise OSError("injected")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(ArtifactError):
        store.write_bytes(EXECUTION_ID, "atomic.json", b"content")
    assert not (tmp_path / "data/screening-executions" / EXECUTION_ID / "atomic.json").exists()


def test_publication_copy_never_dereferences_source_symlink(tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    outside = tmp_path / "outside.txt"
    source.mkdir()
    outside.write_text("do not copy", encoding="utf-8")
    (source / "leak.txt").symlink_to(outside)
    with pytest.raises(WorkerError):
        ScreeningWorker._copy_tree_nofollow(source, destination)
    assert not destination.exists() or not (destination / "leak.txt").exists()


def test_publication_source_chain_rejects_intermediate_symlink(tmp_path: Path):
    runs = tmp_path / "data/runs"
    source = runs / "run-1"
    source.mkdir(parents=True)
    settings = Settings(bidops_root=tmp_path, data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'db.sqlite'}")
    opened = _open_run_fds(settings, "run-1")
    for fd in reversed(opened):
        os.close(fd)
    real_runs = runs.with_name("runs-real")
    runs.rename(real_runs)
    runs.symlink_to(real_runs, target_is_directory=True)
    with pytest.raises(WorkerError):
        _open_run_fds(settings, "run-1")
