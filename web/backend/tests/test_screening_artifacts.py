from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.screening.artifacts import ArtifactError, ArtifactStore
from app.screening.worker import ScreeningWorker, WorkerError


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
