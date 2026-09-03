from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base, get_db, init_db
from app.main import app
from app.core.models import AuditEvent
from app.lifecycle.models import AgencyPortal, Attachment, Notice, Run
from app.deep_review.services.attachments import MAX_ATTACHMENT_SIZE
from app.core.clamav import ClamAVUnavailable
from app.screening.policy import load_policy_file


SAFE_PDF = Path(__file__).parent / "fixtures/document_bundles/safe.pdf"
EICAR_PDF = Path(__file__).parent / "fixtures/document_bundles/eicar.pdf"


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
    headers = {"X-BidOps-Actor-Name": "attachment-reviewer"}

    extension_response = client.post(
        "/api/notices/1/attachments",
        files={"files": ("설명.txt", b"not allowed", "text/plain")},
        headers=headers,
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
        headers=headers,
    )
    assert too_large_response.status_code == 400
    assert "50MB" in too_large_response.json()["detail"]


def test_attachment_upload_uses_server_path_and_matching_portal_url(attachments_client, monkeypatch):
    client, session, root = attachments_client
    content = SAFE_PDF.read_bytes()
    monkeypatch.setattr("app.deep_review.services.attachments.ClamAVScanner.scan", lambda _self, _content: True)

    response = client.post(
        "/api/notices/1/attachments",
        files={"files": ("../../outside.pdf", content, "application/pdf")},
        headers={"X-BidOps-Actor-Name": "attachment-reviewer"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["attachments"][0]["origin"] == "manual"
    assert payload["attachments"][0]["file_ext"] == "PDF"
    assert "stored_path" not in payload["attachments"][0]
    attachment = session.query(Attachment).filter(Attachment.origin == "manual").one()
    stored_path = attachment.stored_path
    assert stored_path is not None
    assert stored_path.startswith("1/")
    assert (root / stored_path).is_file()
    assert not (root.parent / "outside.pdf").exists()
    assert "%2F" in payload["search_url"]
    assert "%20" in payload["search_url"]

    download = client.get(payload["attachments"][0]["url"])
    assert download.status_code == 200
    assert download.content == content

    listed = client.get("/api/notices/1/attachments")
    assert listed.status_code == 200
    assert all("stored_path" not in item for item in listed.json()["attachments"])
    detail = client.get("/api/notices/1")
    assert detail.status_code == 200
    assert all("stored_path" not in item for item in detail.json()["attachments"])


def test_attachment_upload_rejects_infected_content_without_local_artifact(attachments_client):
    client, session, root = attachments_client

    response = client.post(
        "/api/notices/1/attachments",
        files={"files": ("infected.pdf", EICAR_PDF.read_bytes(), "application/pdf")},
        headers={"X-BidOps-Actor-Name": "attachment-reviewer"},
    )

    assert response.status_code == 400
    assert "안전성 검사" in response.json()["detail"]
    assert session.query(Attachment).filter(Attachment.origin == "manual").count() == 0
    assert not any(path.is_file() for path in root.rglob("*"))


def test_attachment_upload_rejects_when_clamav_is_unavailable(attachments_client, monkeypatch):
    client, session, root = attachments_client

    def unavailable(_self, _content):
        raise ClamAVUnavailable

    monkeypatch.setattr("app.deep_review.services.attachments.ClamAVScanner.scan", unavailable)
    response = client.post(
        "/api/notices/1/attachments",
        files={"files": ("unscanned.pdf", SAFE_PDF.read_bytes(), "application/pdf")},
        headers={"X-BidOps-Actor-Name": "attachment-reviewer"},
    )

    assert response.status_code == 400
    assert "안전성 검사" in response.json()["detail"]
    assert session.query(Attachment).filter(Attachment.origin == "manual").count() == 0
    assert not any(path.is_file() for path in root.rglob("*"))


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
    delete_response = client.delete(
        f"/api/attachments/{g2b_id}",
        headers={"X-BidOps-Actor-Name": "attachment-reviewer"},
    )
    assert delete_response.status_code == 403
    assert "나라장터 제공" in delete_response.json()["detail"]


def test_legacy_mutations_require_actor_and_append_audit_events(attachments_client, monkeypatch):
    client, session, _root = attachments_client
    portal_id = session.query(AgencyPortal).one().id
    g2b_id = session.query(Attachment).filter(Attachment.origin == "g2b").one().id
    policy_body = load_policy_file()
    policy_body = {**policy_body, "policy_version": "a4-api-policy"}
    policy_body.pop("schema_version")
    policy_payload = {**policy_body, "created_by": "operator"}

    missing_actor = [
        client.post(
            "/api/portals",
            json={
                "agency_pattern": "A4 기관",
                "system_name": "A4 조달",
                "search_url_template": "https://example.test/{bid_no}",
            },
        ),
        client.patch(f"/api/portals/{portal_id}", json={"note": "변경"}),
        client.post("/api/policies", json=policy_payload),
        client.post(
            "/api/policies/a4-api-policy/candidate",
            json={"confirmed_by": "operator"},
        ),
        client.post(
            "/api/policies/a4-api-policy/activate",
            json={"quality_gate_result_id": "gateeval-" + "a" * 32, "confirmed_by": "operator"},
        ),
        client.post("/api/notices/1/attachments"),
        client.delete(f"/api/attachments/{g2b_id}"),
    ]
    assert [response.status_code for response in missing_actor] == [400] * 7
    assert all(response.json()["error"]["code"] == "actor_name_required" for response in missing_actor)

    actor_headers = {"X-BidOps-Actor-Name": "a4-reviewer"}
    created_portal = client.post(
        "/api/portals",
        headers=actor_headers,
        json={
            "agency_pattern": "A4 기관",
            "system_name": "A4 조달",
            "search_url_template": "https://example.test/{bid_no}",
        },
    )
    assert created_portal.status_code == 201
    created_portal_id = created_portal.json()["id"]
    updated_portal = client.patch(
        f"/api/portals/{created_portal_id}",
        headers=actor_headers,
        json={"enabled": False},
    )
    assert updated_portal.status_code == 200

    monkeypatch.setattr("app.deep_review.services.attachments.ClamAVScanner.scan", lambda _self, _content: True)
    uploaded = client.post(
        "/api/notices/1/attachments",
        headers=actor_headers,
        files={"files": ("a4.pdf", SAFE_PDF.read_bytes(), "application/pdf")},
    )
    assert uploaded.status_code == 200
    manual_id = session.query(Attachment).filter(Attachment.origin == "manual").one().id
    deleted = client.delete(f"/api/attachments/{manual_id}", headers=actor_headers)
    assert deleted.status_code == 204

    created_policy = client.post("/api/policies", headers=actor_headers, json=policy_payload)
    assert created_policy.status_code == 201
    candidate_policy = client.post(
        "/api/policies/a4-api-policy/candidate",
        headers=actor_headers,
        json={"confirmed_by": "operator"},
    )
    assert candidate_policy.status_code == 200

    audit_rows = session.query(AuditEvent).filter(AuditEvent.claimed_name == "a4-reviewer").all()
    actions = {row.action for row in audit_rows}
    assert {
        "agency_portal.create",
        "agency_portal.update",
        "attachment.upload",
        "attachment.delete",
        "screening_policy.create",
        "screening_policy.activation_candidate",
    } <= actions


def test_attachment_queue_includes_missing_notice_and_portal_context(attachments_client):
    client, _session, _root = attachments_client
    response = client.get("/api/attachments/queue", params={"run_id": "attachments-run"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["matched_portal"]["system_name"] == "테스트 조달시스템"
