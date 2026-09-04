"""Focused API and worker-contract tests for R-08 (B)."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.main import app
from app.core.models import AuditEvent, IdempotencyRecord
from app.deep_review.models import (
    BidDeltaAttempt,
    BidDeltaComparison,
    BidFinalDecision,
    ContentObject,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
)
from app.lifecycle.models import Notice, Opportunity, OpportunityLink
from app.deep_review.services.bid_delta import BID_DELTA_CATEGORIES, BidDeltaService, BidDeltaServiceError


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _input(session: Session, opportunity: Opportunity, label: str, source_type: str, role: str, published_at: datetime | None):
    source_sha = _sha(f"{label}:source")
    payload_sha = _sha(f"{label}:structure")
    notice = Notice(
        notice_key=f"bid-delta-api:{label}:{uuid4()}",
        source_type=source_type,
        bid_ord=None if source_type == "pre_spec" else "not-an-ordinal",
        published_at=published_at,
    )
    session.add(notice)
    session.flush()
    link = OpportunityLink(
        opportunity_id=opportunity.id,
        notice_id=notice.id,
        stage="notice",
        link_type="official",
        status="확정",
        evidence_external_no=f"external:{label}",
    )
    content = ContentObject(
        sha256=source_sha,
        size_bytes=10,
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add_all([link, content])
    session.flush()
    document = DocumentVersion(
        notice_id=notice.id,
        content_object_id=content.id,
        version=1,
        source_kind="manual",
        original_filename=f"{label}.pdf",
        role=role,
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
    )
    session.add(document)
    session.flush()
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256=source_sha,
        media_type="application/pdf",
        extractor_name="fixture",
        extractor_version="1",
        payload_content_object_id=content.id,
        payload_sha256=payload_sha,
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    bundle = DocumentBundle(
        notice_id=notice.id,
        revision=1,
        version=1,
        status="ready",
        issues_snapshot=[],
    )
    session.add_all([structure, bundle])
    session.flush()
    item = DocumentBundleItem(
        bundle_id=bundle.id,
        document_version_id=document.id,
        ordinal=1,
        document_version_version=1,
        content_object_id=content.id,
        content_sha256=source_sha,
        detected_mime="application/pdf",
        size_bytes=10,
        original_filename=f"{label}.pdf",
        source_kind="manual",
        role_at_confirmation=role,
        is_current_at_confirmation=True,
        safety_status_at_confirmation="safe",
        structure_id_at_confirmation=structure.id,
        structure_payload_sha256=payload_sha,
    )
    session.add(item)
    session.flush()
    return {"notice": notice, "link": link, "content": content, "document": document, "structure": structure, "bundle": bundle, "item": item}


@pytest.fixture
def bid_delta_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    init_db(engine)
    session = Session(engine)
    opportunity = Opportunity(first_registered_stage="pre_spec")
    session.add(opportunity)
    session.flush()
    baseline = _input(session, opportunity, "baseline", "pre_spec", "제안요청서", datetime(2026, 8, 20, tzinfo=UTC))
    comparison = _input(session, opportunity, "comparison", "bid_notice", "공고", datetime(2026, 8, 25, tzinfo=UTC))
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, session, opportunity, baseline, comparison
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def _fence(candidate: dict) -> dict:
    return {
        key: candidate[key]
        for key in (
            "opportunity_link_id",
            "notice_id",
            "bundle_id",
            "bundle_revision",
            "bundle_version",
            "document_version_id",
            "document_version_version",
            "structure_id",
            "source_sha256",
            "structure_payload_sha256",
        )
    }


def _create_payload(workspace: dict, *, request_id: UUID | None = None) -> dict:
    return {
        "schema_version": "bidops.bid-delta-comparison-create.v1",
        "request_id": str(request_id or uuid4()),
        "category_policy_version": "bid-delta-policy.v1",
        "baseline": _fence(workspace["baseline_candidates"][0]),
        "comparison": _fence(workspace["comparison_candidates"][0]),
    }


def _create(client: TestClient, workspace: dict, *, request_id: UUID | None = None) -> dict:
    payload = _create_payload(workspace, request_id=request_id)
    response = client.post(
        f"/api/opportunities/{workspace['opportunity_id']}/bid-delta/comparisons",
        json=payload,
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_candidates_and_create_are_exact_and_append_only(bid_delta_api):
    client, session, opportunity, _baseline, _comparison = bid_delta_api
    workspace_response = client.get(f"/api/opportunities/{opportunity.id}/bid-delta")
    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert len(workspace["baseline_candidates"]) == 1
    assert len(workspace["comparison_candidates"]) == 1
    assert workspace["comparison_candidates"][0]["bid_ordinal"] == "not-an-ordinal"

    created = _create(client, workspace)
    assert created["calculation_status"] == "pending"
    assert created["result_status"] is None
    assert len(created["attempts"]) == 1
    assert session.query(BidDeltaComparison).count() == 1
    assert session.query(IdempotencyRecord).count() == 1
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "bid_delta.comparison_requested"))
    assert audit is not None
    assert "reviewer" not in str(audit.safe_metadata)
    assert "prompt" not in str(audit.safe_metadata)


def test_create_rejects_unsupported_policy_and_input_type(bid_delta_api):
    client, _session, opportunity, _baseline, _comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    payload = {
        "schema_version": "bidops.bid-delta-comparison-create.v1",
        "request_id": str(uuid4()),
        "category_policy_version": "unsupported",
        "baseline": _fence(workspace["comparison_candidates"][0]),
        "comparison": _fence(workspace["comparison_candidates"][0]),
    }
    response = client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons",
        json=payload,
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "bid_delta_category_policy_invalid"

    payload["category_policy_version"] = "bid-delta-policy.v1"
    payload["baseline"] = _fence(workspace["comparison_candidates"][0])
    response = client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons",
        json=payload,
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "bid_delta_baseline_type_invalid"


def test_worker_aggregation_and_final_decision_boundary(bid_delta_api):
    client, session, opportunity, baseline, comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    created = _create(client, workspace)
    attempt_id = UUID(created["attempts"][0]["id"])
    service = BidDeltaService()
    service.start_attempt(session, attempt_id, 0)
    items = []
    for ordinal, category in enumerate(BID_DELTA_CATEGORIES, start=1):
        if category == "eligibility":
            items.append({"category": category, "ordinal": ordinal, "result_status": "unknown", "materiality": "unknown", "error_code": "evidence_missing"})
            continue
        evidence = {
            "baseline_evidence": [{"document_version_id": str(baseline["document"].id), "structure_id": str(baseline["structure"].id), "source_sha256": baseline["content"].sha256, "locator_type": "page", "locator": {"page": 1}, "verification_status": "verified", "quote": "safe"}],
            "comparison_evidence": [{"document_version_id": str(comparison["document"].id), "structure_id": str(comparison["structure"].id), "source_sha256": comparison["content"].sha256, "locator_type": "page", "locator": {"page": 1}, "verification_status": "verified", "quote": "safe"}],
        }
        items.append({"category": category, "ordinal": ordinal, "result_status": "unchanged", "materiality": "non_material", **evidence})
    completed = service.complete_attempt(session, attempt_id, items)
    assert completed.result_status == "unknown"
    assert completed.materiality == "unknown"

    detail = client.get(f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{completed.id}").json()
    decision_payload = {
        "schema_version": "bidops.bid-final-decision-create.v1",
        "request_id": str(uuid4()),
        "expected_comparison_version": completed.version,
        "expected_result_sha256": completed.result_sha256,
        "baseline_document_version_id": str(baseline["document"].id),
        "comparison_document_version_id": str(comparison["document"].id),
        "supersedes_final_decision_id": None,
        "decision": "go",
        "reason": "검토 완료",
    }
    final = client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{completed.id}/final-decisions",
        json=decision_payload,
        headers={"X-BidOps-Actor-Name": "UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99", "X-BidOps-Actor-Name-Format": "utf-8-percent-v1"},
    )
    assert final.status_code == 201, final.text
    assert final.json()["claimed_name"] == "홍길동"
    assert session.query(BidFinalDecision).count() == 1
    assert detail["result_status"] == "unknown"


def test_replay_and_reason_validation_are_safe(bid_delta_api):
    client, session, opportunity, _baseline, _comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    request_id = uuid4()
    first = _create(client, workspace, request_id=request_id)
    replay = _create(client, workspace, request_id=request_id)
    assert replay == first
    assert session.query(BidDeltaComparison).count() == 1
    assert client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{first['id']}/final-decisions",
        json={
            "schema_version": "bidops.bid-final-decision-create.v1",
            "request_id": str(uuid4()),
            "expected_comparison_version": 1,
            "expected_result_sha256": "a" * 64,
            "baseline_document_version_id": first["baseline"]["document_version_id"],
            "comparison_document_version_id": first["comparison"]["document_version_id"],
            "supersedes_final_decision_id": None,
            "decision": "go",
            "reason": "   ",
        },
        headers={"X-BidOps-Actor-Name": "reviewer"},
    ).json()["error"]["code"] == "final_decision_reason_required"


def test_workspace_excludes_non_authoritative_links(bid_delta_api):
    client, session, opportunity, baseline, comparison = bid_delta_api
    # An official link must stay 확정, so a non-authoritative link is a
    # candidate that is still pending or was rejected by a human.
    baseline["link"].link_type = "candidate"
    baseline["link"].status = "후보 확인 대기"
    comparison["link"].link_type = "candidate"
    comparison["link"].status = "사람 확인 완료"
    comparison["link"].human_decision = "rejected"
    comparison["link"].reviewer_name = "검토자"
    comparison["link"].reviewed_at = datetime(2026, 8, 30, tzinfo=UTC)
    comparison["link"].review_reason = "다른 사업으로 확인됨"
    session.commit()

    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta")
    assert workspace.status_code == 200
    assert workspace.json()["baseline_candidates"] == []
    assert workspace.json()["comparison_candidates"] == []


def test_workspace_keeps_all_bid_notice_and_correction_candidates(bid_delta_api):
    client, session, opportunity, _baseline, _comparison = bid_delta_api
    for index, role in enumerate(("공고", "정정", "정정"), start=2):
        _input(
            session,
            opportunity,
            f"candidate-{index}",
            "bid_notice",
            role,
            datetime(2026, 8, 25 + index, tzinfo=UTC),
        )
    session.commit()

    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    candidates = workspace["comparison_candidates"]
    assert len(candidates) == 4
    assert {candidate["document_role"] for candidate in candidates} == {"공고", "정정"}
    assert all("selected" not in candidate for candidate in candidates)
    assert all(candidate["bid_ordinal"] == "not-an-ordinal" for candidate in candidates)


def test_create_version_race_returns_conflict_without_comparison(bid_delta_api):
    client, session, opportunity, baseline, _comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    payload = _create_payload(workspace)
    baseline["document"].version = 2
    session.commit()

    response = client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons",
        json=payload,
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "bid_delta_input_version_conflict"
    assert session.query(BidDeltaComparison).count() == 0


def test_create_rejects_inputs_from_different_opportunity(bid_delta_api):
    client, session, opportunity, _baseline, _comparison = bid_delta_api
    other_opportunity = Opportunity(first_registered_stage="pre_spec")
    session.add(other_opportunity)
    session.flush()
    _input(session, other_opportunity, "other-baseline", "pre_spec", "제안요청서", datetime(2026, 8, 20, tzinfo=UTC))
    _input(session, other_opportunity, "other-comparison", "bid_notice", "공고", datetime(2026, 8, 25, tzinfo=UTC))
    session.commit()
    primary = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    other = client.get(f"/api/opportunities/{other_opportunity.id}/bid-delta").json()
    payload = _create_payload(primary)
    payload["baseline"] = _fence(other["baseline_candidates"][0])

    response = client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons",
        json=payload,
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "bid_delta_input_scope_conflict"
    assert session.query(BidDeltaComparison).count() == 0


def test_create_fails_closed_without_internal_binding(bid_delta_api, monkeypatch):
    client, session, opportunity, _baseline, _comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()

    def unavailable():
        raise BidDeltaServiceError(
            "bid_delta_service_unavailable",
            "unavailable",
            status_code=503,
        )

    monkeypatch.setattr("app.deep_review.services.bid_delta.resolve_runtime_binding", unavailable)
    response = client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons",
        json=_create_payload(workspace),
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "bid_delta_service_unavailable"
    assert session.query(BidDeltaComparison).count() == 0
    assert session.query(IdempotencyRecord).count() == 0


def test_failed_comparison_retry_preserves_attempt_and_queues_new_one(bid_delta_api):
    client, session, opportunity, _baseline, _comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    created = _create(client, workspace)
    first_attempt_id = UUID(created["attempts"][0]["id"])
    BidDeltaService().fail_attempt(session, first_attempt_id, "model_timeout")

    response = client.post(
        f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{created['id']}/attempts",
        json={
            "schema_version": "bidops.bid-delta-attempt-create.v1",
            "request_id": str(uuid4()),
            "expected_comparison_version": 1,
        },
        headers={"X-BidOps-Actor-Name": "reviewer"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["version"] == 2
    assert [(attempt["sequence"], attempt["status"]) for attempt in body["attempts"]] == [(1, "failed"), (2, "queued")]
    assert session.query(BidDeltaAttempt).count() == 2


def _complete(session, client, opportunity, baseline, comparison, workspace):
    """Drive one comparison to a completed state through the worker contract."""

    created = _create(client, workspace)
    attempt_id = UUID(created["attempts"][0]["id"])
    service = BidDeltaService()
    service.start_attempt(session, attempt_id, 0)
    items = []
    for ordinal, category in enumerate(BID_DELTA_CATEGORIES, start=1):
        items.append(
            {
                "category": category,
                "ordinal": ordinal,
                "result_status": "unchanged",
                "materiality": "non_material",
                "baseline_evidence": [_evidence(baseline)],
                "comparison_evidence": [_evidence(comparison)],
            }
        )
    return service, service.complete_attempt(session, attempt_id, items)


def _evidence(side: dict, *, verification_status: str = "verified") -> dict:
    return {
        "document_version_id": str(side["document"].id),
        "structure_id": str(side["structure"].id),
        "source_sha256": side["content"].sha256,
        "locator_type": "page",
        "locator": {"page": 1},
        "verification_status": verification_status,
        "quote": "safe",
    }


def _decision_payload(completed, baseline, comparison, **overrides) -> dict:
    payload = {
        "schema_version": "bidops.bid-final-decision-create.v1",
        "request_id": str(uuid4()),
        "expected_comparison_version": completed.version,
        "expected_result_sha256": completed.result_sha256,
        "baseline_document_version_id": str(baseline["document"].id),
        "comparison_document_version_id": str(comparison["document"].id),
        "supersedes_final_decision_id": None,
        "decision": "go",
        "reason": "검토 완료",
    }
    payload.update(overrides)
    return payload


def test_complete_rejects_item_without_matching_verified_evidence(bid_delta_api):
    client, session, opportunity, baseline, comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    created = _create(client, workspace)
    attempt_id = UUID(created["attempts"][0]["id"])
    service = BidDeltaService()
    service.start_attempt(session, attempt_id, 0)

    # One side carries a hash that does not match the compared snapshot, so the
    # item cannot be promoted to a changed/unchanged result.
    mismatched = dict(_evidence(comparison))
    mismatched["source_sha256"] = _sha("other-document")
    items = []
    for ordinal, category in enumerate(BID_DELTA_CATEGORIES, start=1):
        evidence = mismatched if category == "eligibility" else _evidence(comparison)
        items.append(
            {
                "category": category,
                "ordinal": ordinal,
                "result_status": "changed",
                "materiality": "material",
                "baseline_evidence": [_evidence(baseline)],
                "comparison_evidence": [evidence],
            }
        )
    with pytest.raises(BidDeltaServiceError) as error:
        service.complete_attempt(session, attempt_id, items)
    assert error.value.code == "bid_delta_evidence_invalid"
    assert session.get(BidDeltaComparison, UUID(created["id"])).calculation_status == "running"


def test_final_decision_rejects_stale_version_digest_and_document_fence(bid_delta_api):
    client, session, opportunity, baseline, comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    _service, completed = _complete(session, client, opportunity, baseline, comparison, workspace)
    url = f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{completed.id}/final-decisions"
    headers = {"X-BidOps-Actor-Name": "reviewer"}

    for overrides, expected_status, expected_code in (
        ({"expected_comparison_version": completed.version + 1}, 409, "bid_delta_version_conflict"),
        ({"expected_result_sha256": "b" * 64}, 409, "bid_delta_result_digest_conflict"),
        ({"baseline_document_version_id": str(uuid4())}, 422, "final_decision_input_fence_invalid"),
        ({"decision": "hold"}, 422, None),
        ({"supersedes_final_decision_id": str(uuid4())}, 404, "final_decision_not_found"),
    ):
        response = client.post(url, json=_decision_payload(completed, baseline, comparison, **overrides), headers=headers)
        assert response.status_code == expected_status, (overrides, response.text)
        if expected_code is not None:
            assert response.json()["error"]["code"] == expected_code
    assert session.query(BidFinalDecision).count() == 0


def test_final_decision_rejects_malformed_actor_and_idempotency_conflict(bid_delta_api):
    client, session, opportunity, baseline, comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    _service, completed = _complete(session, client, opportunity, baseline, comparison, workspace)
    url = f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{completed.id}/final-decisions"

    missing = client.post(url, json=_decision_payload(completed, baseline, comparison))
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "actor_name_required"
    control = client.post(
        url,
        json=_decision_payload(completed, baseline, comparison),
        headers={"X-BidOps-Actor-Name": "bad\nactor"},
    )
    assert control.status_code == 400
    assert control.json()["error"]["code"] == "actor_name_invalid"
    assert session.query(BidFinalDecision).count() == 0

    request_id = uuid4()
    headers = {"X-BidOps-Actor-Name": "reviewer"}
    first = client.post(url, json=_decision_payload(completed, baseline, comparison, request_id=str(request_id)), headers=headers)
    assert first.status_code == 201, first.text
    replay = client.post(url, json=_decision_payload(completed, baseline, comparison, request_id=str(request_id)), headers=headers)
    assert replay.status_code == 201
    assert replay.json() == first.json()
    conflict = client.post(
        url,
        json=_decision_payload(completed, baseline, comparison, request_id=str(request_id), decision="no_go", reason="다른 이유"),
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert session.query(BidFinalDecision).count() == 1


def test_new_authoritative_bid_notice_makes_the_comparison_stale(bid_delta_api):
    client, session, opportunity, baseline, comparison = bid_delta_api
    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    _service, completed = _complete(session, client, opportunity, baseline, comparison, workspace)
    url = f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{completed.id}/final-decisions"
    headers = {"X-BidOps-Actor-Name": "reviewer"}

    _input(session, opportunity, "correction", "bid_notice", "정정", datetime(2026, 9, 2, tzinfo=UTC))
    session.commit()

    stale = client.post(url, json=_decision_payload(completed, baseline, comparison), headers=headers)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "bid_delta_comparison_stale"
    assert session.query(BidFinalDecision).count() == 0

    detail = client.get(f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{completed.id}").json()
    assert detail["decision_currentness"] == "unknown"
    assert detail["currentness_reasons"] == ["no_final_decision"]
    # The system result never becomes a human decision on its own.
    assert detail["final_decisions"] == []
    assert detail["result_sha256"] == completed.result_sha256


def test_responses_never_expose_object_keys_or_internal_paths(bid_delta_api):
    client, session, opportunity, baseline, comparison = bid_delta_api
    workspace_response = client.get(f"/api/opportunities/{opportunity.id}/bid-delta")
    _service, completed = _complete(session, client, opportunity, baseline, comparison, workspace_response.json())
    detail = client.get(f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{completed.id}")
    missing = client.get(f"/api/opportunities/{opportunity.id}/bid-delta/comparisons/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["details"] is None

    for response in (workspace_response, detail, missing):
        body = response.text
        for forbidden in ("/home/", "object_key", "signed_url", "prompt", "SELECT ", "bidops/"):
            assert forbidden not in body, (forbidden, response.url)


def test_workspace_offers_boq_and_submission_form_candidates_on_both_sides(bid_delta_api):
    """2026-08-31 확정 allowlist. 내역서·제출서식이 없으면 예산·제출 범주가 근거를 못 가진다."""

    client, session, opportunity, _baseline, _comparison = bid_delta_api
    _input(session, opportunity, "baseline-boq", "pre_spec", "내역서", None)
    _input(session, opportunity, "baseline-form", "pre_spec", "제출서식", None)
    _input(session, opportunity, "bid-boq", "bid_notice", "내역서", datetime(2026, 8, 28, tzinfo=UTC))
    _input(session, opportunity, "bid-form", "bid_notice", "제출서식", datetime(2026, 8, 29, tzinfo=UTC))
    session.commit()

    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    baseline_roles = {candidate["document_role"] for candidate in workspace["baseline_candidates"]}
    comparison_roles = {candidate["document_role"] for candidate in workspace["comparison_candidates"]}
    assert {"내역서", "제출서식"} <= baseline_roles
    assert {"내역서", "제출서식"} <= comparison_roles


def test_workspace_still_excludes_appendix_and_other_roles(bid_delta_api):
    """부록·기타는 allowlist 밖이다. 확정 범위가 넓어지지 않았는지 고정한다."""

    client, session, opportunity, _baseline, _comparison = bid_delta_api
    _input(session, opportunity, "baseline-appendix", "pre_spec", "부록", None)
    _input(session, opportunity, "bid-other", "bid_notice", "기타", datetime(2026, 8, 28, tzinfo=UTC))
    session.commit()

    workspace = client.get(f"/api/opportunities/{opportunity.id}/bid-delta").json()
    roles = {candidate["document_role"] for candidate in workspace["baseline_candidates"]}
    roles |= {candidate["document_role"] for candidate in workspace["comparison_candidates"]}
    assert "부록" not in roles
    assert "기타" not in roles
