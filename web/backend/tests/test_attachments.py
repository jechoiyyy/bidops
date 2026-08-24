from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db, init_db
from app.main import app
from app.models import AgencyPortal, Attachment, Notice, Run
from app.services.attachments import MAX_ATTACHMENT_SIZE


@pytest.fixture
def attachments_client(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    settings = get_settings()
    previous_attachments_dir = settings.attachments_dir
    settings.attachments_dir = tmp_path / "attachments"

    with Session(engine) as session:
        run = Run(
            id="attachments-run",
            window_from=date(2026, 8, 17),
            window_to=date(2026, 8, 23),
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
        notice = Notice(
            run=run,
            notice_key="bid:ATTACH:000",
            bid_no="A/1",
            title="공고 제목",
            agency="테스트 기관 산하기관",
            sample_role="analysis",
        )
        g2b_notice = Notice(
            run=run,
            notice_key="bid:ATTACH:001",
            agency="테스트 기관",
            sample_role="analysis",
        )
        g2b_notice.attachments.append(Attachment(name="원문.pdf", origin="g2b"))
        session.add(
            AgencyPortal(
                agency_pattern="테스트 기관",
                system_name="테스트 조달시스템",
                search_url_template="https://example.test/search?bid={bid_no}&title={title}",
            )
        )
        session.add(run)
        session.commit()

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client, session, settings.attachments_dir
        finally:
            app.dependency_overrides.pop(get_db, None)
            settings.attachments_dir = previous_attachments_dir


def test_attachment_upload_rejects_extension_and_too_large_file(attachments_client):
    client, _session, _root = attachments_client

    extension_response = client.post(
        "/api/notices/1/attachments",
        files={"files": ("설명.txt", b"not allowed", "text/plain")},
    )
    assert extension_response.status_code == 400
    assert "허용되지 않는 확장자" in extension_response.json()["detail"]

    too_large_response = client.post(
        "/api/notices/1/attachments",
        files={
            "files": (
                "large.pdf",
                b"x" * (MAX_ATTACHMENT_SIZE + 1),
                "application/pdf",
            )
        },
    )
    assert too_large_response.status_code == 400
    assert "50MB" in too_large_response.json()["detail"]


def test_attachment_upload_uses_server_path_and_matching_portal_url(attachments_client):
    client, _session, root = attachments_client

    response = client.post(
        "/api/notices/1/attachments",
        files={"files": ("../../outside.pdf", b"pdf body", "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["attachments"][0]["origin"] == "manual"
    assert payload["attachments"][0]["file_ext"] == "PDF"
    stored_path = payload["attachments"][0]["stored_path"]
    assert stored_path.startswith("1/")
    assert (root / stored_path).is_file()
    assert not (root.parent / "outside.pdf").exists()
    assert "%2F" in payload["search_url"]
    assert "%20" in payload["search_url"]

    download = client.get(payload["attachments"][0]["url"])
    assert download.status_code == 200
    assert download.content == b"pdf body"


def test_attachment_download_rejects_path_escape_and_g2b_delete(attachments_client):
    client, session, _root = attachments_client
    escaped = Attachment(
        notice_pk=1,
        name="escape.pdf",
        origin="manual",
        file_ext="PDF",
        stored_path="../escape.pdf",
    )
    session.add(escaped)
    session.commit()

    escaped_response = client.get(f"/api/attachments/{escaped.id}/download")
    assert escaped_response.status_code == 404

    g2b_id = session.query(Attachment).filter(Attachment.origin == "g2b").one().id
    delete_response = client.delete(f"/api/attachments/{g2b_id}")
    assert delete_response.status_code == 403
    assert "나라장터 제공" in delete_response.json()["detail"]


def test_attachment_queue_includes_missing_notice_and_portal_context(attachments_client):
    client, _session, _root = attachments_client
    response = client.get("/api/attachments/queue", params={"run_id": "attachments-run"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["matched_portal"]["system_name"] == "테스트 조달시스템"

