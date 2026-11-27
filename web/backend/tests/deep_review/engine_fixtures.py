"""Synthetic DB + object-store fixture for both in-process and isolated live E2E.

Call seed_engine_input(session) against an empty migrated test database. Existing
company registration/activation services write the synthetic source via the
configured object store, so MinIO and filesystem tests exercise the same seam.
"""

from datetime import datetime, UTC
import hashlib
import json
import io
import zipfile
from xml.sax.saxutils import escape
from pathlib import Path
from app.deep_review.document_mcp.hwpx import extract_hwpx, extractor_info
from app.deep_review.document_mcp.safety import ProcessorOptions
from app.deep_review.document_mcp.contracts import validate_structure
from uuid import uuid4
from sqlalchemy.orm import Session
from app.lifecycle.models import Notice
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentVersion,
    DocumentStructure,
    DocumentBlock,
    DocumentBundle,
    DocumentBundleItem,
)
from app.deep_review.services.company_knowledge import (
    import_company_knowledge,
    activate_company_knowledge,
)
from app.deep_review.services import assets
from tests.deep_review.test_company_knowledge import _prepared_real

ELIGIBILITY = "중소기업확인서를 제출해야 한다."
REQUIREMENT = "웹사이트 통합검색 기능을 제공한다."


def synthetic_engine_hwpx():
    """A deterministic real HWPX container with eligibility and a detail table."""

    def para(text):
        return "<hp:p><hp:run><hp:t>" + escape(text) + "</hp:t></hp:run></hp:p>"

    rows = [
        ("요구사항 고유번호", "SFR-001"),
        ("요구사항 명칭", "통합검색"),
        ("세부 내용", REQUIREMENT),
    ]
    table = (
        '<hp:tbl rowCnt="3" colCnt="2">'
        + "".join(
            "<hp:tr>"
            + "".join("<hp:tc>" + para(cell) + "</hp:tc>" for cell in row)
            + "</hp:tr>"
            for row in rows
        )
        + "</hp:tbl>"
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        + para("Ⅰ. 사업개요")
        + para("합성 홈페이지 유지관리 사업")
        + para("Ⅱ. 참가자격")
        + para(ELIGIBILITY)
        + para("Ⅲ. 요구사항")
        + table
        + "</hs:sec>"
    ).encode()
    original = (
        Path(__file__).parents[1]
        / "fixtures/deep_review/prespec-run/attachments/rfp.hwpx"
    ).read_bytes()
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(original)) as source,
        zipfile.ZipFile(output, "w") as target,
    ):
        for member in source.infolist():
            info = zipfile.ZipInfo(member.filename, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = member.compress_type
            target.writestr(
                info,
                xml
                if member.filename == "Contents/section0.xml"
                else source.read(member.filename),
            )
    return output.getvalue()


def seed_engine_input(session: Session, *, register_company=True):
    company = None
    if register_company:
        prepared = _prepared_real(slug="engine-synthetic", name="엔진 검증 합성회사")
        company = import_company_knowledge(session, prepared, actor="engine-e2e")
        activate_company_knowledge(
            session,
            company_id=company.company_id,
            graph_version_id=company.graph_version_id,
            actor="engine-e2e",
        )
    notice = Notice(
        notice_key=f"engine-fixture:{uuid4()}",
        source_type="pre_spec",
        title="엔진 합성 검증 사전규격",
    )
    session.add(notice)
    session.flush()
    # Valid original HWPX bytes, parsed with the existing bounded extractor.
    source = synthetic_engine_hwpx()
    digest = hashlib.sha256(source).hexdigest()
    pages, extracted, warnings = extract_hwpx(source, ProcessorOptions())
    _, meta = assets.store_named(
        "source", f"source/engine-fixture/{uuid4()}.hwpx", source
    )
    content = ContentObject(
        id=uuid4(),
        sha256=digest,
        size_bytes=len(source),
        detected_mime="application/hwp+zip",
        retention_class="document-source",
    )
    session.add(content)
    session.flush()
    session.add(
        ContentObjectLocation(
            id=uuid4(),
            content_object_id=content.id,
            namespace_key="source",
            object_key=meta.object_key,
            object_version_id=meta.object_version_id,
            status="verified",
            etag=meta.etag,
            verified_at=datetime.now(UTC),
        )
    )
    session.add(ContentScan(
        content_object_id=content.id, scanner="fixture", scanner_version="1",
        status="clean", safe_result={},
    ))
    doc = DocumentVersion(
        id=uuid4(),
        notice_id=notice.id,
        content_object_id=content.id,
        version=1,
        source_kind="manual",
        original_filename="synthetic.hwpx",
        role="제안요청서",
        is_current=True,
        safety_status="safe",
    )
    session.add(doc)
    session.flush()
    structure_id = uuid4()
    payload = validate_structure(
        {
            "schema": "bidops.document-structure.v1",
            "structure_id": str(structure_id),
            "document_version_id": str(doc.id),
            "source_sha256": digest,
            "media_type": "application/hwp+zip",
            "extractor": extractor_info(),
            "pages": pages,
            "blocks": extracted,
            "warnings": warnings,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    sh = hashlib.sha256(raw).hexdigest()
    _, sm = assets.store_named(
        "structure", f"structure/engine-fixture/{uuid4()}.json", raw
    )
    sc = ContentObject(
        id=uuid4(),
        sha256=sh,
        size_bytes=len(raw),
        detected_mime="application/json",
        retention_class="derived",
    )
    session.add(sc)
    session.flush()
    session.add(
        ContentObjectLocation(
            id=uuid4(),
            content_object_id=sc.id,
            namespace_key="structure",
            object_key=sm.object_key,
            object_version_id=sm.object_version_id,
            status="verified",
            etag=sm.etag,
            verified_at=datetime.now(UTC),
        )
    )
    structure = DocumentStructure(
        id=structure_id,
        document_version_id=doc.id,
        source_sha256=digest,
        media_type="application/hwp+zip",
        extractor_name=payload["extractor"]["name"],
        extractor_version=payload["extractor"]["version"],
        payload_content_object_id=sc.id,
        payload_sha256=sh,
        page_count=len(pages),
        block_count=len(extracted),
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    for block in extracted:
        session.add(
            DocumentBlock(
                id=uuid4(),
                structure_id=structure.id,
                block_key=block["block_key"],
                parent_block_key=block["parent_block_key"],
                block_type=block["type"],
                page=block["page"],
                content=block["text"],
                attributes=block["attributes"],
            )
        )
    bundle = DocumentBundle(
        id=uuid4(),
        notice_id=notice.id,
        revision=1,
        version=1,
        status="ready",
        issues_snapshot=[],
        confirmed_by_name="engine-e2e",
        confirmed_at=datetime.now(UTC),
    )
    session.add(bundle)
    session.flush()
    session.add(
        DocumentBundleItem(
            bundle_id=bundle.id,
            document_version_id=doc.id,
            ordinal=1,
            document_version_version=1,
            content_object_id=content.id,
            content_sha256=digest,
            detected_mime="application/hwp+zip",
            size_bytes=len(source),
            original_filename="synthetic.hwpx",
            source_kind="manual",
            role_at_confirmation="제안요청서",
            is_current_at_confirmation=True,
            safety_status_at_confirmation="safe",
            structure_id_at_confirmation=structure.id,
            structure_payload_sha256=sh,
        )
    )
    session.commit()
    return {
        "company_id": company.company_id if company else None,
        "notice_id": notice.id,
        "bundle_id": bundle.id,
    }
