"""Legacy attachment acquisition must keep object identity in the object fields.

``acquire_legacy_attachment`` once passed nine positional arguments to the
twelve-field :class:`~app.deep_review.services.assets.QuarantinedAsset`, which shifted the
quarantine object key into ``source_system``, the version id into
``source_attachment_key`` and the etag into ``source_url`` while leaving
``object_key`` unset.  On a filesystem object store the local copy survives the
put, so ``read_quarantine`` fell back to the path and every test passed.  On
any other backend the local copy is removed after the put and the bytes became
unreadable -- which is the configured production backend.

These tests exercise both store shapes so the fallback cannot hide the defect
again.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.deep_review.services import assets
from app.core.object_store import FilesystemObjectStore, ObjectMetadata


PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


class _RemoteObjectStore:
    """An object store that is not a FilesystemObjectStore.

    ``acquire_legacy_attachment`` deletes the local quarantine copy for exactly
    this case, so a caller can only reach the bytes through ``object_key``.
    """

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put(self, namespace: str, object_key: str, data: bytes, *, content_type: str) -> ObjectMetadata:  # noqa: ARG002
        self.objects[(namespace, object_key)] = data
        digest = hashlib.sha256(data).hexdigest()
        return ObjectMetadata(namespace, object_key, digest, digest, len(data))

    def get(self, namespace: str, object_key: str, *, max_bytes: int = 1 << 30) -> tuple[bytes, ObjectMetadata]:
        data = self.objects[(namespace, object_key)]
        digest = hashlib.sha256(data).hexdigest()
        return data, ObjectMetadata(namespace, object_key, digest, digest, len(data))

    def head(self, namespace: str, object_key: str) -> ObjectMetadata:
        return self.get(namespace, object_key)[1]


def _legacy_source(root: Path) -> str:
    notice_dir = root / "notice-1"
    notice_dir.mkdir(parents=True, exist_ok=True)
    (notice_dir / "legacy.pdf").write_bytes(PDF)
    return "notice-1/legacy.pdf"


@pytest.fixture()
def remote_store(monkeypatch: pytest.MonkeyPatch) -> _RemoteObjectStore:
    store = _RemoteObjectStore()
    monkeypatch.setattr(assets, "object_store", lambda *args, **kwargs: store)
    return store


def test_legacy_acquisition_keeps_object_identity_out_of_provenance(tmp_path: Path) -> None:
    stored_path = _legacy_source(tmp_path)

    asset = assets.acquire_legacy_attachment(
        stored_path=stored_path, filename="legacy.pdf", root=tmp_path
    )

    assert asset.source_kind == "manual"
    # A manual attachment has no provider provenance.  These three staying
    # None is what ck_document_version_source_provenance requires.
    assert asset.source_system is None
    assert asset.source_attachment_key is None
    assert asset.source_url is None
    # The object identity belongs here and nowhere else.
    assert asset.object_key and asset.object_key.startswith("quarantine/")
    assert asset.object_version_id
    assert asset.object_etag
    assert asset.sha256 == hashlib.sha256(PDF).hexdigest()
    assert asset.size_bytes == len(PDF)


def test_legacy_quarantine_is_readable_when_the_store_is_not_a_filesystem(
    tmp_path: Path, remote_store: _RemoteObjectStore
) -> None:
    """The production backend removes the local copy after the put."""

    stored_path = _legacy_source(tmp_path)

    asset = assets.acquire_legacy_attachment(
        stored_path=stored_path, filename="legacy.pdf", root=tmp_path
    )

    assert not asset.path.exists(), "the local quarantine copy is removed for a remote store"
    assert asset.object_key is not None
    assert ("quarantine", asset.object_key) in remote_store.objects
    assert assets.read_quarantine(asset) == PDF


def test_legacy_source_file_is_never_replaced_or_removed(tmp_path: Path) -> None:
    stored_path = _legacy_source(tmp_path)
    source = tmp_path / stored_path

    assets.acquire_legacy_attachment(stored_path=stored_path, filename="legacy.pdf", root=tmp_path)

    assert source.read_bytes() == PDF


def test_quarantined_asset_rejects_positional_construction() -> None:
    """The field order is no longer part of any caller's contract."""

    with pytest.raises(TypeError):
        assets.QuarantinedAsset(  # type: ignore[misc]
            Path("/tmp/x"), "x.pdf", 1, "a" * 64, None, "manual"
        )
