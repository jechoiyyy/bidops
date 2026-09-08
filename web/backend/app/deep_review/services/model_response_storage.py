"""Encrypted response persistence shared by overview and company-fit analysis."""
import hashlib
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import ContentObject, ContentObjectLocation


def store_raw_model_response(session: Session, raw: bytes, *, store: Any, clock: Callable[[], datetime]) -> str:
    """원응답을 암호화 저장소에 쓰고 DB에는 참조·hash만 남긴다."""

    try:
        retention_days = int(os.environ.get("BIDOPS_MODEL_RESPONSE_RETENTION_DAYS", "90"))
    except (TypeError, ValueError):
        retention_days = 90
    retention_days = min(max(retention_days, 1), 90)
    metadata = store.put_encrypted(
        raw, retention_days=retention_days, content_type="application/json"
    )
    if not isinstance(metadata, Mapping):
        raise ValueError("raw_response_metadata_invalid")
    digest = hashlib.sha256(raw).hexdigest()
    object_key = metadata.get("object_key")
    key_ref = metadata.get("encryption_key_ref")
    if (
        metadata.get("plaintext_sha256") != digest
        or metadata.get("plaintext_size_bytes") != len(raw)
        or not isinstance(object_key, str)
        or not object_key.startswith("model-response/")
        or ".." in object_key.split("/")
        or not isinstance(key_ref, str)
        or not key_ref.strip()
    ):
        raise ValueError("raw_response_metadata_invalid")
    content = session.scalar(
        select(ContentObject).where(ContentObject.sha256 == digest).limit(1)
    )
    if content is None:
        content = ContentObject(
            id=uuid4(),
            sha256=digest,
            size_bytes=len(raw),
            detected_mime="application/json",
            retention_class="model-response-90d",
        )
        session.add(content)
        session.flush()
    elif content.size_bytes != len(raw):
        raise ValueError("raw_response_metadata_invalid")
    existing = session.scalar(
        select(ContentObjectLocation)
        .where(
            ContentObjectLocation.namespace_key == "model-response",
            ContentObjectLocation.object_key == object_key,
        )
        .limit(1)
    )
    if existing is None:
        object_version_id = metadata.get("object_version_id")
        session.add(
            ContentObjectLocation(
                id=uuid4(),
                content_object_id=content.id,
                namespace_key="model-response",
                object_key=object_key,
                object_version_id=(
                    object_version_id if isinstance(object_version_id, str) else None
                ),
                status="verified",
                etag=str(metadata.get("etag") or digest),
                encryption_key_ref=key_ref,
                verified_at=clock(),
            )
        )
    elif existing.content_object_id != content.id:
        raise ValueError("raw_response_metadata_invalid")
    session.flush()
    return digest

