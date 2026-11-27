"""Assembled tracking and workload API contracts for the engine review."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.deep_review.models import EngineReviewRequest
from app.deep_review.services import engine_runs
from app.deep_review.services.prespec_attachments import refresh_fetch_eligibility
from app.lifecycle.models import Opportunity
from app.main import create_app
from tests.deep_review.test_engine_review import (
    HEADERS, add_attachment, approve, bind, change_tracking, company_bundle, count, db, error, linked, pg, ready,
    ready_for_approval, request,
)
from tests.postgres import requires_postgres


def test_rules_2_and_10_tracking_start_is_independent_and_failed_request_can_retry(
    db, company_bundle, empty_extensions, monkeypatch,
):
    app = create_app(modules=("lifecycle", "deep_review"), mount_frontend=False)
    app.dependency_overrides[get_db] = lambda: db
    notice_id, owner_id = linked(db, tracking="미선택")
    bid_id, bid_owner_id = linked(db, tracking="미선택", source_type="bid_notice")
    from app.lifecycle.routers import opportunities
    monkeypatch.setattr(opportunities, "_backfill_tracked_records", lambda *_: None)
    with TestClient(app) as client:
        for opportunity_id in (owner_id, bid_owner_id):
            response = client.patch(f"/api/opportunities/{opportunity_id}/tracking-status",
                                    json={"status": "계속 추적"}, headers=HEADERS)
            assert response.status_code == 200, response.text
        assert count(db, EngineReviewRequest) == 0
        original = company_bundle / "acme.yaml"
        source = original.read_text()
        original.unlink()
        error(request(client, notice_id, origin="tracking_start"), 409, "company_bundle_unavailable")
        assert db.get(Opportunity, owner_id).tracking_status == "계속 추적"
        original.write_text(source)
        assert request(client, notice_id, origin="tracking_start").status_code == 201
        error(request(client, bid_id, origin="tracking_start"), 404, "not_found")
        assert count(db, EngineReviewRequest) == 1


def test_workload_http_counts_same_actions_and_off_is_null(db, ready, empty_extensions, monkeypatch):
    notice_id, _ = ready
    app = create_app(modules=("lifecycle", "screening", "deep_review"), mount_frontend=False)
    app.dependency_overrides[get_db] = lambda: db
    keys = ("engine_approval_pending", "engine_result_pending")

    def counts(client):
        response = client.get("/api/workload")
        assert response.status_code == 200, response.text
        items = {item["key"]: item["count"] for item in response.json()["items"]}
        return tuple(items[key] for key in keys)

    with TestClient(app) as client:
        frozen = ready_for_approval(client, notice_id)
        assert counts(client) == (1, 0)
        assert approve(client, notice_id, frozen).status_code == 202
        assert engine_runs.run_once(db, "workload-test")
        assert counts(client) == (0, 1)
        monkeypatch.setenv("BIDOPS_ENGINE_REVIEW_MODE", "off")
        get_settings.cache_clear()
        assert counts(client) == (None, None)


@pytest.mark.parametrize("bind", ["sqlite", pytest.param("postgres", marks=requires_postgres)], indirect=True)
def test_open_review_request_enables_preparation_in_prespec_list(bind, db, empty_extensions):
    notice_id, owner_id = linked(db, registration="R-review-preparation")
    app = create_app(modules=("lifecycle", "screening", "deep_review"), mount_frontend=False)

    def request_session():
        with Session(bind) as session:
            yield session

    app.dependency_overrides[get_db] = request_session

    with TestClient(app) as client:
        def listed(**params):
            response = client.get("/api/pre-specs", params={"notice_pk": notice_id, "sw_only": "false", **params})
            assert response.status_code == 200, response.text
            return response.json()["items"]

        before, = listed()
        assert before["auto_preparation_status"] == "not_applicable"
        assert before["auto_preparation_reason"] == "grade_not_priority"
        assert request(client, notice_id).status_code == 201
        pending, = listed()
        assert pending["auto_preparation_status"] == "waiting_attachments"
        assert pending["auto_preparation_reason"] == "engine_review_request"
        assert pending["overview_review_status"] is None
        assert listed(auto_preparation_status="waiting_attachments") == [pending]

        add_attachment(db, notice_id)
        assert refresh_fetch_eligibility(db, notice_ids=[notice_id]) == 1
        db.commit()
        pending, = listed()
        assert pending["auto_preparation_status"] == "waiting_attachments"
        assert pending["auto_preparation_reason"] == "awaiting_fetch"

        change_tracking(db, owner_id, "종료")
        assert listed(auto_preparation_status="waiting_attachments") == []
        ended, = listed()
        assert ended["auto_preparation_status"] == "not_applicable"


def test_rule_8_restart_cannot_reuse_request_from_ended_tracking(
    db, ready, empty_extensions, monkeypatch,
):
    from app.lifecycle.routers import opportunities
    from tests.deep_review.test_engine_review import get_state

    app = create_app(modules=("lifecycle", "deep_review"), mount_frontend=False)
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(opportunities, "_backfill_tracked_records", lambda *_: None)
    notice_id, owner_id = ready
    with TestClient(app) as client:
        frozen = ready_for_approval(client, notice_id)
        for status in ("종료", "계속 추적"):
            response = client.patch(f"/api/opportunities/{owner_id}/tracking-status",
                                    json={"status": status, "reason": "검토"}, headers=HEADERS)
            assert response.status_code == 200, response.text
        assert get_state(client, notice_id)["state"] == "not_requested"
        error(approve(client, notice_id, frozen), 409, "request_required")
        assert request(client, notice_id).status_code == 201
        assert count(db, EngineReviewRequest) == 2


@requires_postgres
def test_postgres_review_commands_and_mock_worker_use_runtime_roles(pg):
    from uuid import uuid4

    from sqlalchemy.orm import Session

    from app.deep_review.schemas import engine_review as wire
    from app.deep_review.services import engine_review
    from tests.app.test_runtime_database_privileges import POLICY, _ensure_roles
    from tests.deep_review.engine_fixtures import seed_engine_input

    _ensure_roles()
    with pg.connect() as connection:
        cursor = connection.connection.driver_connection.cursor()
        try:
            cursor.execute(POLICY, prepare=False)
        finally:
            cursor.close()
        connection.commit()
        with Session(connection) as session:
            notice_id, owner_id = linked(
                session, notice_id=seed_engine_input(session, register_company=False)["notice_id"],
            )
            assert session.get(Opportunity, owner_id).tracking_status == "계속 추적"

        try:
            connection.exec_driver_sql("SET ROLE app")
            connection.commit()
            with Session(connection) as session:
                engine_review.request_review(
                    session, notice_id, wire.RequestCommand(request_id=uuid4(), origin="manual"), "reviewer",
                )
                frozen = engine_review.create_preview(
                    session, notice_id, wire.Command(request_id=uuid4()), "reviewer",
                )
                approval = engine_review.approve(
                    session, notice_id, wire.ApprovalCommand(
                        request_id=uuid4(), preview_id=frozen.preview_id, manifest_sha256=frozen.manifest_sha256,
                    ), "reviewer",
                )
            connection.exec_driver_sql("RESET ROLE")
            connection.exec_driver_sql("SET ROLE worker")
            connection.commit()
            with Session(connection) as session:
                assert engine_runs.run_once(session, "review-runtime-role")
            connection.exec_driver_sql("RESET ROLE")
            connection.exec_driver_sql("SET ROLE app")
            connection.commit()
            with Session(connection) as session:
                assert engine_review.review_state(session, notice_id).state == "result_ready"
                result = engine_review.acknowledge(
                    session, notice_id, wire.AcknowledgmentCommand(request_id=uuid4(), result_id=approval.run_id),
                    "reviewer",
                )
                assert result.result_id == approval.run_id
        finally:
            connection.rollback()
            connection.exec_driver_sql("RESET ROLE")
            connection.commit()
