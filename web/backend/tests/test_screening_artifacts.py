from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.screening import artifacts as artifact_module
from app.screening.artifacts import ArtifactError, ArtifactStore, ExecutionWorkspace
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


def test_remove_execution_preserves_unknown_children_and_unlinks_owned_files(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    workspace.write_json("owned.json", {"owned": True})
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    (target / "leak.txt").symlink_to(sentinel)
    nested = target / "nested"
    nested.mkdir()
    (nested / "safe.txt").write_text("remove", encoding="utf-8")
    with pytest.raises(ArtifactError):
        store.remove_execution(workspace)
    workspace.close()
    assert target.exists()
    assert not (target / "owned.json").exists()
    assert (target / "nested" / "safe.txt").exists()
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
        store.create_execution_workspace(EXECUTION_ID)
    assert (outside / "sentinel.txt").read_text(encoding="utf-8") == "keep"


def test_renameat2_capability_guard_precedes_execution_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    monkeypatch.setattr(artifact_module, "_RENAMEAT2", None)
    with pytest.raises(ArtifactError, match="renameat2"):
        store.create_execution_workspace(EXECUTION_ID)
    assert not (tmp_path / "data/screening-executions" / EXECUTION_ID).exists()


def test_workspace_tree_is_application_owned_0700(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    base = tmp_path / "data/screening-executions"
    assert (base.stat().st_mode & 0o777) == 0o700
    assert (base / EXECUTION_ID).stat().st_mode & 0o777 == 0o700
    store.remove_execution(workspace)


def test_renameat2_capability_guard_precedes_workspace_deletion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    monkeypatch.setattr(artifact_module, "_RENAMEAT2", None)
    with pytest.raises(ArtifactError, match="renameat2"):
        store.remove_execution(workspace)
    assert (tmp_path / "data/screening-executions" / EXECUTION_ID).is_dir()
    workspace.close()


def test_remove_execution_does_not_delete_replacement_after_name_swap(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    owned_away = target.with_name(EXECUTION_ID + "-owned-away")
    target.rename(owned_away)
    replacement = target.with_name(EXECUTION_ID + "-replacement")
    replacement.mkdir()
    sentinel = replacement / "must-survive.txt"
    sentinel.write_text("keep", encoding="utf-8")
    replacement.rename(target)
    store.remove_execution(workspace)
    assert (target / "must-survive.txt").read_text(encoding="utf-8") == "keep"
    assert target.is_dir()
    assert not owned_away.exists()
    workspace.close()


def test_remove_execution_root_quarantine_preserves_pre_rmdir_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    base = tmp_path / "data/screening-executions"
    target = base / EXECUTION_ID
    owned_away = base / (EXECUTION_ID + "-owned-away")
    target.rename(owned_away)
    real_move = artifact_module._rename_noreplace
    swapped = False

    def swap_before_root_delete(source, destination, *args, **kwargs):
        nonlocal swapped
        result = real_move(source, destination, *args, **kwargs)
        if source == owned_away.name and kwargs.get("src_dir_fd") == workspace.base_fd and not swapped:
            swapped = True
            owned_away.mkdir()
            (owned_away / "must-survive.txt").write_text("keep", encoding="utf-8")
        return result

    monkeypatch.setattr(artifact_module, "_rename_noreplace", swap_before_root_delete)
    store.remove_execution(workspace)
    assert swapped
    assert not target.exists()
    assert (owned_away / "must-survive.txt").read_text(encoding="utf-8") == "keep"
    workspace.close()


def test_create_workspace_rejects_preexisting_sibling_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    base = tmp_path / "data/screening-executions"
    base.mkdir(parents=True)
    sibling = base / "preexisting-sibling"
    sibling.mkdir()
    sentinel = sibling / "must-survive.txt"
    sentinel.write_text("keep", encoding="utf-8")
    real_open = os.open
    moved = base / (EXECUTION_ID + "-moved")

    def swap_between_mkdir_and_open(path, flags, *args, **kwargs):
        if path == EXECUTION_ID and kwargs.get("dir_fd") is not None:
            (base / EXECUTION_ID).rename(moved)
            sibling.rename(base / EXECUTION_ID)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_between_mkdir_and_open)
    with pytest.raises(ArtifactError):
        store.create_execution_workspace(EXECUTION_ID)
    assert (base / EXECUTION_ID / "must-survive.txt").read_text(encoding="utf-8") == "keep"
    assert not moved.exists()


def test_workspace_fsync_failure_removes_fresh_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)

    def fail_fsync(_fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(ArtifactError):
        store.create_execution_workspace(EXECUTION_ID)
    assert not (tmp_path / "data/screening-executions" / EXECUTION_ID).exists()


def test_workspace_created_stat_failure_recovers_unique_fresh_inode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    real_stat = os.stat
    failed = False

    def fail_created_stat(path, *args, **kwargs):
        nonlocal failed
        if path == EXECUTION_ID and kwargs.get("dir_fd") is not None and not failed:
            failed = True
            raise OSError("injected created-stat failure")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", fail_created_stat)
    with pytest.raises(ArtifactError):
        store.create_execution_workspace(EXECUTION_ID)
    assert failed
    assert not (tmp_path / "data/screening-executions" / EXECUTION_ID).exists()


def test_workspace_is_empty_failure_with_unknown_child_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    target = tmp_path / "data/screening-executions" / EXECUTION_ID

    def fail_empty(workspace: ExecutionWorkspace):
        (target / "unknown.json").write_text("preserve", encoding="utf-8")
        raise ArtifactError("injected empty-scan failure")

    monkeypatch.setattr(ExecutionWorkspace, "is_empty", fail_empty)
    with pytest.raises(ArtifactError):
        store.create_execution_workspace(EXECUTION_ID)
    assert (target / "unknown.json").read_text(encoding="utf-8") == "preserve"


def test_workspace_lifecycle_closes_all_descriptors(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    before = {entry.name for entry in Path("/proc/self/fd").iterdir()}
    for index in range(8):
        execution_id = "scr-" + f"{index:032x}"
        workspace = store.create_execution_workspace(execution_id)
        workspace.write_json("screening-input.json", {"index": index})
        workspace.close()
        workspace.close()
    after = {entry.name for entry in Path("/proc/self/fd").iterdir()}
    assert after == before


def test_registered_child_swap_preserves_replacement(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    workspace.write_json("owned.json", {"owned": True})
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    owned_away = target / "owned-away.json"
    (target / "owned.json").rename(owned_away)
    replacement = target / "owned.json"
    replacement.write_text("unrelated", encoding="utf-8")
    with pytest.raises(ArtifactError):
        store.remove_execution(workspace)
    assert replacement.read_text(encoding="utf-8") == "unrelated"
    assert not owned_away.exists()
    workspace.close()


def test_registered_child_quarantine_boundary_preserves_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    workspace.write_json("owned.json", {"owned": True})
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    owned_away = target / "owned-away.json"
    real_rename = artifact_module._rename_noreplace
    real_os_rename = os.rename
    swapped = False

    def swap_at_quarantine_boundary(source, destination, *args, **kwargs):
        nonlocal swapped
        if source == "owned.json" and kwargs.get("src_dir_fd") == workspace.directory_fd and not swapped:
            swapped = True
            real_os_rename(target / "owned.json", owned_away)
            (target / "owned.json").write_text("replacement", encoding="utf-8")
        return real_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(artifact_module, "_rename_noreplace", swap_at_quarantine_boundary)
    with pytest.raises(ArtifactError):
        store.remove_execution(workspace)
    assert swapped
    assert owned_away.read_text(encoding="utf-8") != "replacement"
    assert (target / "owned.json").read_text(encoding="utf-8") == "replacement"
    assert target.is_dir()
    workspace.close()


def test_registered_child_final_unlink_boundary_never_targets_old_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    workspace.write_json("owned.json", {"owned": True})
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    real_unlink = os.unlink
    swapped = False

    def swap_old_name_before_final_unlink(path, *args, **kwargs):
        nonlocal swapped
        if isinstance(path, str) and path.startswith(".rollback-sink-") and kwargs.get("dir_fd") == workspace.directory_fd and not swapped:
            swapped = True
            (target / "owned.json").write_text("replacement", encoding="utf-8")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", swap_old_name_before_final_unlink)
    with pytest.raises(ArtifactError):
        store.remove_execution(workspace)
    assert swapped
    assert (target / "owned.json").read_text(encoding="utf-8") == "replacement"
    workspace.close()


def test_quarantine_sink_failure_restores_owned_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    workspace.write_json("owned.json", {"owned": True})
    target = tmp_path / "data/screening-executions" / EXECUTION_ID

    def fail_sink(_directory_fd):
        raise ArtifactError("injected sink failure")

    monkeypatch.setattr(ArtifactStore, "_create_quarantine_file", staticmethod(fail_sink))
    with pytest.raises(ArtifactError):
        store.remove_execution(workspace)
    assert (target / "owned.json").is_file()
    workspace.close()


def test_quarantine_exchange_failure_restores_owned_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    target = tmp_path / "data/screening-executions" / EXECUTION_ID

    def fail_exchange(*_args, **_kwargs):
        raise ArtifactError("injected exchange failure")

    monkeypatch.setattr(artifact_module, "_rename_exchange", fail_exchange)
    with pytest.raises(ArtifactError):
        store.remove_execution(workspace)
    assert target.is_dir()
    workspace.close()


def test_final_identity_open_failure_tracks_pending_inode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    real_open = os.open
    opens = 0

    def fail_final_open(path, flags, *args, **kwargs):
        nonlocal opens
        if path == "screening-input.json" and kwargs.get("dir_fd") == workspace.directory_fd and flags & getattr(os, "O_ACCMODE", 3) == os.O_RDONLY:
            opens += 1
            if opens == 2:
                raise OSError("injected final identity-open failure")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_final_open)
    with pytest.raises(ArtifactError):
        workspace.write_json("screening-input.json", {"pending": True})
    store.remove_execution(workspace)
    assert not (tmp_path / "data/screening-executions" / EXECUTION_ID).exists()
    workspace.close()


def test_workspace_write_after_name_swap_targets_owned_inode(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    workspace = store.create_execution_workspace(EXECUTION_ID)
    target = tmp_path / "data/screening-executions" / EXECUTION_ID
    owned_away = target.with_name(EXECUTION_ID + "-owned-away")
    target.rename(owned_away)
    replacement = target.with_name(EXECUTION_ID + "-replacement")
    replacement.mkdir()
    replacement.rename(target)

    workspace.write_json("screening-input.json", {"owned": True})
    assert (owned_away / "screening-input.json").is_file()
    assert not (target / "screening-input.json").exists()
    store.remove_execution(workspace)
    workspace.close()
    assert target.is_dir()
    assert not owned_away.exists()


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
