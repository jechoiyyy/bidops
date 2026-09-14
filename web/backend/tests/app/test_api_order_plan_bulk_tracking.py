"""Bulk wire-contract tests; PostgreSQL lock evidence lives in lifecycle tests."""

from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.core.models import AuditEvent, IdempotencyRecord
from app.lifecycle.models import Opportunity, OpportunityLink, OrderPlan
from app.main import app
from tests.postgres import migrated_engine, requires_postgres

BASE = "/api/opportunities/order-plan-tracking"
HEADERS = {"X-BidOps-Actor-Name": "bulk-reviewer"}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def bulk_api(request):
    if request.param == "postgres":
        with migrated_engine() as engine:
            yield from _bulk_api_session(engine)
        return
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    try:
        init_db(engine)
        yield from _bulk_api_session(engine)
    finally:
        engine.dispose()


def _bulk_api_session(engine):
    with Session(engine) as session:
        owners = []
        plans = []
        for index, status in enumerate(("미선택", "계속 추적", "보류", "종료")):
            owner = Opportunity(first_registered_stage="order_plan", tracking_status=status)
            if status != "미선택":
                owner.tracking_reason = f"기존 판단 {status}"
                owner.tracking_selected_by = "original-reviewer"
                owner.tracking_selected_at = datetime(2026, 9, 1, 1, 2, 3, 123456, tzinfo=timezone.utc)
            plan = OrderPlan(order_plan_unty_no=f"BULK-API-{index}", title=f"테스트 계획 {index}")
            session.add_all([owner, plan])
            session.flush()
            session.add(OpportunityLink(
                opportunity_id=owner.id, order_plan_id=plan.id,
                stage="order_plan", link_type="official", status="확정",
                evidence_external_no=plan.order_plan_unty_no,
            ))
            owners.append(owner)
            plans.append(plan)
        duplicate = OrderPlan(order_plan_unty_no="BULK-API-DUP", title="동일 소유 계획")
        missing_owner = OrderPlan(order_plan_unty_no="BULK-API-ORPHAN", title="소유권 없음")
        candidate = OrderPlan(order_plan_unty_no="BULK-API-CANDIDATE", title="후보만 있음")
        session.add_all([duplicate, missing_owner, candidate])
        session.flush()
        session.add_all([
            OpportunityLink(opportunity_id=owners[0].id, order_plan_id=duplicate.id,
                            stage="order_plan", link_type="official", status="확정",
                            evidence_external_no=duplicate.order_plan_unty_no),
            OpportunityLink(opportunity_id=owners[0].id, order_plan_id=candidate.id,
                            stage="order_plan", link_type="candidate", status="후보 확인 대기"),
        ])
        session.commit()
        ids = [plan.id for plan in plans]
        extra_ids = [duplicate.id, missing_owner.id, candidate.id]
        owner_ids = [owner.id for owner in owners]

        def database():
            yield session

        app.dependency_overrides[get_db] = database
        try:
            with TestClient(app) as client:
                yield client, session, ids, extra_ids, owner_ids
        finally:
            app.dependency_overrides.pop(get_db, None)


def command(ids, request_id=None, reason="공통 추적 사유"):
    return {
        "schema_version": "order-plan-bulk-start-request.v1",
        "request_id": str(request_id or uuid4()),
        "order_plan_ids": ids,
        "reason": reason,
    }


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_bulk_preview_is_read_only_and_separates_plans_from_owners(bulk_api):
    client, session, ids, extras, _ = bulk_api
    selected = ids + extras + [999999, ids[0]]
    before = (count(session, AuditEvent), count(session, IdempotencyRecord))
    response = client.post(f"{BASE}/preview", json={
        "schema_version": "order-plan-bulk-preview-request.v1", "order_plan_ids": selected,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected_plan_count"] == 8
    assert body["unique_owner_count"] == 4
    assert body["eligible_plan_count"] == 2
    assert body["eligible_owner_count"] == 1
    assert body["failure_plan_count"] == 3
    for status in ("계속 추적", "보류", "종료"):
        assert body["excluded_by_status"][status] == {"plan_count": 1, "owner_count": 1}
    assert (count(session, AuditEvent), count(session, IdempotencyRecord)) == before


def test_bulk_mixed_results_preserve_prior_decisions_and_fan_out_one_audit(bulk_api):
    client, session, ids, extras, owner_ids = bulk_api
    def original_values():
        session.expire_all()
        return [(owner.tracking_status, owner.tracking_reason, owner.tracking_selected_by,
                 owner.tracking_selected_at, owner.recheck_signal_at,
                 owner.recheck_signal_link_id)
                for owner in [session.get(Opportunity, pk) for pk in owner_ids[1:]]]
    before = original_values()
    response = client.post(f"{BASE}/bulk-start", json=command(ids + extras + [999999, ids[0]]), headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "order-plan-bulk-start-response.v1"
    summary = body["summary"]
    assert summary["selected_plan_count"] == 8
    assert summary["succeeded_plan_count"] == 2
    assert summary["succeeded_owner_count"] == 1
    assert summary["excluded_plan_count"] == 3
    assert summary["failed_plan_count"] == 3
    items = {item["order_plan_id"]: item for item in body["items"]}
    assert items[ids[0]]["outcome"] == items[extras[0]]["outcome"] == "succeeded"
    assert items[ids[0]]["audit_event_id"] == items[extras[0]]["audit_event_id"]
    assert items[ids[0]]["audit_event_id"] is not None
    assert items[999999]["code"] == "order_plan_not_found"
    assert items[extras[1]]["code"] == "owning_opportunity_missing"
    assert items[extras[2]]["outcome"] == "failed"
    assert original_values() == before
    assert count(session, AuditEvent) == 1
    assert count(session, IdempotencyRecord) == 1


def test_receipt_replay_preserves_json_after_later_single_reset(bulk_api):
    client, session, ids, extras, owner_ids = bulk_api
    payload = command([extras[1], ids[0], ids[2]])
    first = client.post(f"{BASE}/bulk-start", json=payload, headers=HEADERS)
    assert first.status_code == 200, first.text
    with Session(session.get_bind()) as receipt_session:
        stored_receipt = receipt_session.scalar(select(IdempotencyRecord))
        snapshot = stored_receipt.response_snapshot
        assert stored_receipt.response_status == first.status_code
    assert snapshot == first.json()
    reset = client.patch(f"/api/opportunities/{owner_ids[0]}/tracking-status",
                         json={"tracking_status": "미선택", "reason": "단건 명시 초기화"}, headers=HEADERS)
    assert reset.status_code == 200
    audits = count(session, AuditEvent)
    replay = client.post(f"{BASE}/bulk-start", json=payload, headers=HEADERS)
    assert replay.status_code == first.status_code
    assert replay.json() == snapshot
    session.expire_all()
    assert session.get(Opportunity, owner_ids[0]).tracking_status == "미선택"
    assert count(session, AuditEvent) == audits
    assert count(session, IdempotencyRecord) == 1


@pytest.mark.parametrize("change", ["actor", "reason", "ids"])
def test_same_request_id_different_payload_is_conflict(bulk_api, change):
    client, session, ids, _extras, _owners = bulk_api
    payload = command([ids[0]])
    first = client.post(f"{BASE}/bulk-start", json=payload, headers=HEADERS)
    assert first.status_code == 200
    headers = HEADERS
    if change == "actor":
        headers = {"X-BidOps-Actor-Name": "different-reviewer"}
    elif change == "reason":
        payload["reason"] = "다른 사유"
    else:
        payload["order_plan_ids"] = [ids[1]]
    before = count(session, AuditEvent)
    response = client.post(f"{BASE}/bulk-start", json=payload, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert count(session, AuditEvent) == before


@pytest.mark.parametrize("bad_ids", [[], [True], [0], [-1], ["1"], [1.5]])
@pytest.mark.parametrize("endpoint", ["preview", "bulk-start"])
def test_strict_plan_ids_fail_before_any_write(bulk_api, bad_ids, endpoint):
    client, session, _ids, _extras, _owners = bulk_api
    payload = command(bad_ids) if endpoint == "bulk-start" else {
        "schema_version": "order-plan-bulk-preview-request.v1", "order_plan_ids": bad_ids,
    }
    response = client.post(f"{BASE}/{endpoint}", json=payload, headers=HEADERS)
    assert response.status_code == 422
    assert count(session, AuditEvent) == count(session, IdempotencyRecord) == 0


@pytest.mark.parametrize("field,value", [("reason", "  "), ("request_id", "not-a-uuid"), ("tracking_status", "종료")])
def test_invalid_bulk_body_cannot_write(bulk_api, field, value):
    client, session, ids, _extras, _owners = bulk_api
    payload = command(ids)
    payload[field] = value
    response = client.post(f"{BASE}/bulk-start", json=payload, headers=HEADERS)
    assert response.status_code == 422
    assert count(session, AuditEvent) == count(session, IdempotencyRecord) == 0


def test_bulk_actor_required_and_korean_actor_is_decoded(bulk_api):
    client, session, ids, _extras, _owners = bulk_api
    payload = command([ids[0]])
    missing = client.post(f"{BASE}/bulk-start", json=payload)
    assert missing.status_code == 400
    assert count(session, AuditEvent) == 0
    actor = "김검토"
    response = client.post(f"{BASE}/bulk-start", json=payload, headers={
        "X-BidOps-Actor-Name": f"UTF-8''{quote(actor, safe='')}",
        "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
    })
    assert response.status_code == 200, response.text
    assert session.scalar(select(AuditEvent)).claimed_name == actor


def test_preview_is_not_permission_to_overwrite_later_human_decision(bulk_api):
    client, session, ids, _extras, owners = bulk_api
    preview = client.post(f"{BASE}/preview", json={
        "schema_version": "order-plan-bulk-preview-request.v1", "order_plan_ids": [ids[0]],
    })
    assert preview.status_code == 200
    assert preview.json()["eligible_plan_count"] == 1
    later = client.patch(f"/api/opportunities/{owners[0]}/tracking-status",
                         json={"tracking_status": "보류", "reason": "나중에 확인"},
                         headers={"X-BidOps-Actor-Name": "later-reviewer"})
    assert later.status_code == 200
    response = client.post(f"{BASE}/bulk-start", json=command([ids[0]]), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["items"][0]["outcome"] == "excluded"
    session.expire_all()
    owner = session.get(Opportunity, owners[0])
    assert owner.tracking_status == "보류"
    assert owner.tracking_selected_by == "later-reviewer"
    assert owner.tracking_reason == "나중에 확인"
    assert count(session, AuditEvent) == 1


@pytest.mark.parametrize("corruption", ["uuid", "datetime", "missing", "extra", "summary", "status"])
def test_malformed_stored_receipt_fails_closed_without_repair_or_reexecution(bulk_api, corruption):
    client, session, ids, _extras, owners = bulk_api
    payload = command([ids[0]])
    first = client.post(f"{BASE}/bulk-start", json=payload, headers=HEADERS)
    assert first.status_code == 200
    record = session.scalar(select(IdempotencyRecord))
    snapshot = first.json()
    if corruption == "uuid":
        snapshot["items"][0]["audit_event_id"] = "invalid-uuid"
    elif corruption == "datetime":
        snapshot["completed_at"] = "yesterday"
    elif corruption == "missing":
        del snapshot["completed_at"]
    elif corruption == "extra":
        snapshot["private_debug"] = "must-not-leak"
    elif corruption == "summary":
        snapshot["summary"]["succeeded_plan_count"] = 99
    else:
        record.response_status = 201
    # Deliberately corrupt this isolated owner-role fixture, never a production receipt.
    record.response_snapshot = snapshot
    session.commit()
    before = count(session, AuditEvent)
    response = client.post(f"{BASE}/bulk-start", json=payload, headers=HEADERS)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "processing_failed"
    assert "must-not-leak" not in response.text
    session.expire_all()
    assert session.get(Opportunity, owners[0]).tracking_status == "계속 추적"
    assert session.scalar(select(IdempotencyRecord)).response_snapshot == snapshot
    assert count(session, AuditEvent) == before
    assert count(session, IdempotencyRecord) == 1
