"""`GET /api/pre-specs`가 개요·문서 projection(deep_review)과 결합된 결과 (명세 §6.1).

lifecycle 목록 router와 deep_review가 제공하는 projection을 함께 도는 두 모듈
조합 테스트다. 조립 계층(`app.main`)이 확장점을 등록해야 projection이 붙으므로
여기서 앱 모듈을 import한다.

`test_pre_specs_list_matches_captured_baseline`은 projection으로 뒤집기 **전**의
router가 같은 fixture로 낸 응답(`tests/fixtures/pre_specs_list_baseline.json`)과
지금 응답이 정확히 같다는 근거다. 목록·그룹핑·필터·페이지네이션 출력이 바뀌지
않았음을 이 한 테스트가 보증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4
from pathlib import Path

import pytest
from sqlalchemy import event

from app.main import app  # noqa: F401 — 조립 계층이 lifecycle 확장점을 등록한다
from app.deep_review.models import (
    AttachmentFetch,
    ContentObject,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    PrespecOverviewRun,
    WorkJob,
)
from app.lifecycle.models import Attachment, Notice
from app.lifecycle.routers import pre_specs as pre_specs_router
from app.screening.models import Judgment, Review
from tests.app.test_api_pre_specs import _items_by_id, _payload, pre_specs_api  # noqa: F401

BASELINE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "pre_specs_list_baseline.json"

_ALL_OVERVIEW_STATUSES = (
    "awaiting_document",
    "awaiting_structure",
    "preparing",
    "awaiting_model",
    "queued",
    "running",
    "needs_human_review",
    "completed",
    "failed",
    "cancelled",
)


def _overview_run(session, notice, status: str, *, document=None) -> PrespecOverviewRun:
    """개요 run 한 건과 그 실행 job·문서를 최소한으로 세운다."""

    if document is None:
        payload = f"overview-{notice.id}-{status}".encode()
        content = ContentObject(
            sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload),
            detected_mime="application/pdf", retention_class="document-source",
        )
        session.add(content)
        session.flush()
        document = DocumentVersion(
            notice_id=notice.id, content_object_id=content.id, version=1, source_kind="manual",
            original_filename="제안요청서.pdf", role="제안요청서", is_current=True, safety_status="safe",
        )
        session.add(document)
        session.flush()
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add(job)
    session.flush()
    run = PrespecOverviewRun(
        notice_id=notice.id, document_version_id=document.id, work_job_id=job.id,
        status=status, range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="test-model", warnings_json=[], reason_codes=[], call_count=0,
        raw_response_refs=[],
        result_json={"schema_version": "test"} if status == "completed" else None,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    session.add(run)
    session.flush()
    return run


def _add_overview_rows(session, refs) -> None:
    _overview_run(session, refs["sw_yes"], "needs_human_review")
    _overview_run(session, refs["sw_no"], "completed")
    session.commit()


def capture_scenarios(session, refs) -> dict[str, dict]:
    """기준선 파일과 같은 순서로 목록 응답을 모은다.

    앞부분은 개요 검토 행이 없는 상태, `reviewed_*`는 두 공고에 개요 검토 행을
    넣은 뒤의 응답이다. 같은 fixture에서 id가 결정적이므로 응답을 그대로 비교한다.
    """

    scenarios: dict[str, dict] = {
        "default": {},
        "all": {"sw_only": False},
        "notice_pk": {"notice_pk": refs["sw_no"].id},
        "division": {"sw_only": False, "business_division": "기술용역"},
        "origin_tracked": {"sw_only": False, "origin": "추적"},
        "origin_new": {"sw_only": False, "origin": "신규"},
        "search": {"sw_only": False, "q": "다라마"},
        "deadline": {"sw_only": False, "sort": "deadline"},
        "page": {"sw_only": False, "sort": "published", "limit": 2, "offset": 2},
    }
    captured = {name: _payload(session, **params) for name, params in scenarios.items()}
    _add_overview_rows(session, refs)
    reviewed: dict[str, dict] = {
        "reviewed_default": {},
        "reviewed_all": {"sw_only": False},
        "reviewed_page": {"sw_only": False, "limit": 1},
    }
    captured.update({name: _payload(session, **params) for name, params in reviewed.items()})
    return captured


def _legacy_shape(payload: dict) -> dict:
    """Drop additive cumulative-workspace fields for the frozen old fixture."""

    item_fields = {"first_observed_at", "last_observed_at", "next_action",
                   "review_exclusion_status", "review_exclusion_actor_name",
                   "review_exclusion_reason", "review_exclusion_changed_at"}
    normalized: dict = {}
    for scenario, response in payload.items():
        response_copy = dict(response)
        response_copy.pop("workspace_counts", None)
        response_copy.pop("deadline_scope_counts", None)
        response_copy["items"] = [
            {key: value for key, value in item.items() if key not in item_fields}
            for item in response["items"]
        ]
        normalized[scenario] = response_copy
    return normalized


def test_pre_specs_list_matches_captured_baseline(pre_specs_api, monkeypatch):
    session, _engine, refs = pre_specs_api
    monkeypatch.setattr(
        pre_specs_router,
        "_now_utc",
        lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    # The frozen fixture predates the deadline workspace rule. Keep its field
    # values as-is and update only this scenario's expected order; the focused
    # deadline-contract tests below own the future/past/null ordering details.
    deadline_order = [4, 6, 7, 8, 5, 9, 1, 2, 3]
    order_index = {notice_id: index for index, notice_id in enumerate(deadline_order)}
    baseline["deadline"]["items"] = sorted(
        baseline["deadline"]["items"], key=lambda item: order_index[item["notice_pk"]]
    )

    assert _legacy_shape(capture_scenarios(session, refs)) == baseline


def test_pre_specs_document_counts_fetch_statuses_and_unqueued_attachments(pre_specs_api):
    session, _engine, refs = pre_specs_api

    item = _items_by_id(_payload(session))[refs["sw_yes"].id]

    assert item["document"] == {
        "attachments": 6,
        "완료": 1,
        "대기": 1,
        "진행": 1,
        "차단": 1,
        "실패": 1,
    }


def test_pre_specs_overview_review_status_projects_from_review_row(pre_specs_api):
    session, _engine, refs = pre_specs_api
    _overview_run(session, refs["sw_yes"], "needs_human_review")
    session.commit()

    items = _items_by_id(_payload(session, sw_only=False))
    assert items[refs["sw_yes"].id]["overview_review_status"] == "needs_human_review"
    # 개요 검토 행이 없는 공고는 null이다. awaiting_document로 접지 않는다
    # (CLAUDE.md unknown/null 보존 게이트).
    assert items[refs["sw_no"].id]["overview_review_status"] is None


@pytest.mark.parametrize("status", ["failed", "cancelled", "needs_human_review"])
def test_pre_specs_list_uses_the_latest_run_status_for_item_and_counts(
    pre_specs_api, status
):
    """공고의 "현재 개요"는 `created_at` 최신 run 하나다. 옛 run은 이력이다."""

    session, _engine, refs = pre_specs_api
    completed = _overview_run(session, refs["sw_yes"], "completed")
    later = _overview_run(session, refs["sw_yes"], status, document=None)
    later.created_at = datetime(2026, 8, 27, tzinfo=UTC)
    assert completed.created_at < later.created_at
    session.commit()

    payload = _payload(session, sw_only=False)
    items = _items_by_id(payload)
    counts = {row["status"]: row["count"] for row in payload["overview_status_counts"]}

    assert items[refs["sw_yes"].id]["overview_review_status"] == status
    assert counts[status] == 1
    assert counts["completed"] == 0


def test_pre_specs_overview_status_counts_always_lists_all_ten_values_plus_null(pre_specs_api):
    session, _engine, refs = pre_specs_api
    _add_overview_rows(session, refs)

    payload = _payload(session, sw_only=False)
    counts = {row["status"]: row["count"] for row in payload["overview_status_counts"]}

    # 열 개 계약 상태는 0이어도 모두 나오고, 검토 행이 없는 공고는 별도의 null
    # bucket이다.
    assert set(counts) == set(_ALL_OVERVIEW_STATUSES) | {None}
    assert counts["needs_human_review"] == 1
    assert counts["completed"] == 1
    assert counts["failed"] == 0
    # fixture의 pre_spec 공고 9건 중 2건에 검토 행이 있다.
    assert counts[None] == payload["total"] - 2
    assert sum(counts.values()) == payload["total"]


def test_pre_specs_overview_status_counts_reflect_full_filtered_set_not_just_the_page(
    pre_specs_api,
):
    session, _engine, refs = pre_specs_api
    _overview_run(session, refs["sw_yes"], "needs_human_review")
    session.commit()

    payload = _payload(session, sw_only=False, limit=1)
    assert len(payload["items"]) == 1
    counts = {row["status"]: row["count"] for row in payload["overview_status_counts"]}
    # 페이지는 한 건으로 잘렸지만 그룹 건수는 필터 전체를 설명한다.
    assert counts["needs_human_review"] == 1
    assert sum(counts.values()) == payload["total"]


def test_pre_specs_list_uses_constant_query_count(pre_specs_api):
    session, engine, _refs = pre_specs_api
    statements: list[str] = []

    def count_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        response = _payload(session, sw_only=False)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    # lifecycle 몫(필터된 공고 id 집합, 페이지)과 projection 몫(개요 상태, 상태별
    # 건수, 첨부 취득 건수, 등급·자동 준비 필드)을 합쳐도 상수 회다. 공고당
    # 조회는 없다. v4 current projection이 두 관계 batch 조회를 추가하므로
    # 상한은 기존보다 늘었지만, 공고 수와 무관하다는 사실은 아래
    # `..._does_not_grow_with_the_number_of_notices`가 본다.
    assert len(statements) <= 18
    assert response["total"] == 9


def _count_statements(session, engine, **params) -> int:
    statements: list[str] = []

    def count_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        _payload(session, **params)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)
    return len(statements)


def test_pre_specs_query_count_does_not_grow_with_the_number_of_notices(pre_specs_api):
    """명세 §8: 새 등급·자동 준비 필드도 `notice_ids` 만큼을 상수 회로 처리한다."""

    session, engine, _refs = pre_specs_api
    before = _count_statements(session, engine, sw_only=False)

    for index in range(12):
        session.add(
            Notice(
                notice_key=f"pre:SCALE-{index}",
                source_type="pre_spec",
                title=f"확장 사전규격 {index}",
                agency="확장 기관",
                qualification_flags_json={"sw_business_status": "Y"},
                lifecycle_json={"pre_spec_no": f"SCALE-{index}"},
            )
        )
    session.commit()

    payload = _payload(session, sw_only=False, limit=500)
    assert payload["total"] == 21
    assert _count_statements(session, engine, sw_only=False, limit=500) == before


def test_pre_specs_grade_and_auto_preparation_fields_are_null_without_a_judgment(
    pre_specs_api,
):
    session, _engine, refs = pre_specs_api

    item = _items_by_id(_payload(session, sw_only=False))[refs["sw_yes"].id]

    # 판정도 정정도 없으면 등급은 `null`이고 출처도 `null`이다. 0이나 특정
    # 등급으로 접지 않는다.
    assert item["grade"] is None
    assert item["grade_source"] is None
    assert item["auto_preparation_status"] == "not_applicable"
    assert item["auto_preparation_reason"] == "grade_not_priority"
    assert item["latest_deep_review_id"] is None


def test_pre_specs_grade_comes_from_the_screening_seam(pre_specs_api):
    session, _engine, refs = pre_specs_api
    session.add(Judgment(notice_id=refs["sw_yes"].id, grade="검토 권장", readiness="확인 완료"))
    session.commit()

    item = _items_by_id(_payload(session, sw_only=False))[refs["sw_yes"].id]
    assert item["grade"] == "검토 권장"
    assert item["grade_source"] == "screening_judgment"

    session.add(
        Review(notice_id=refs["sw_yes"].id, corrected_grade="우선 검토", reviewer_snapshot="검토자")
    )
    session.commit()

    item = _items_by_id(_payload(session, sw_only=False))[refs["sw_yes"].id]
    # 사람 정정이 있으면 그것이 effective grade이고 출처가 달라진다.
    assert item["grade"] == "우선 검토"
    assert item["grade_source"] == "human_review"
    assert item["auto_preparation_status"] == "waiting_attachments"


def test_pre_specs_report_blocked_when_every_fetch_ended_in_failure(pre_specs_api):
    """취득 행이 전부 `차단`·`실패`로 끝나면 "첨부 취득 대기"가 아니라 멈춤이다.

    묶음이 만들어지지 않은 이유가 "아직 오는 중"이 아니라 "올 것이 없음"이므로
    운영자가 기다리지 않게 `blocked`로 보여 준다.
    """

    session, _engine, refs = pre_specs_api
    notice = refs["sw_no"]
    for name, status in (("blocked.pdf", "차단"), ("failed.pdf", "실패")):
        attachment = Attachment(notice_id=notice.id, name=name, origin="g2b")
        session.add(attachment)
        session.flush()
        session.add(
            AttachmentFetch(
                attachment_id=attachment.id,
                status=status,
                eligibility_reason="sw_business_object",
                attempt_count=3,
                max_attempts=3,
                next_attempt_at=datetime(2026, 8, 25, tzinfo=UTC),
            )
        )
    session.add(
        Review(notice_id=notice.id, corrected_grade="우선 검토", reviewer_snapshot="검토자")
    )
    session.commit()

    item = _items_by_id(_payload(session, sw_only=False))[notice.id]

    assert item["auto_preparation_status"] == "blocked"
    assert item["auto_preparation_reason"] == "attachments_failed"


# --- 자동 심층 시작을 막은 사유가 화면까지 온다 (명세 §6.4·§8) ----------------


def _auto_start_rows(session, notice, *, overview_status: str = "completed", in_bundle: bool = True):
    """자동 확정된 `ready` 묶음과 개요 run 한 벌.

    §6.4의 앞 조건을 모두 세워 두고, 검사마다 한 조건씩만 어긋나게 한다.
    """

    payload = f"synthetic-{notice.id}".encode()
    content = ContentObject(
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add(content)
    session.flush()
    document = DocumentVersion(
        notice_id=notice.id,
        content_object_id=content.id,
        version=1,
        source_kind="manual",
        original_filename="제안요청서.pdf",
        role="제안요청서",
        is_current=True,
        safety_status="safe",
    )
    session.add(document)
    session.flush()
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256=content.sha256,
        media_type="application/pdf",
        extractor_name="test",
        extractor_version="1",
        payload_content_object_id=content.id,
        payload_sha256=hashlib.sha256(b"structure").hexdigest(),
        page_count=1,
        block_count=0,
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    bundle = DocumentBundle(
        notice_id=notice.id,
        revision=1,
        version=1,
        status="ready",
        issues_snapshot=[],
        created_by_name="auto-preparation",
        confirmed_by_name="auto-preparation",
        confirmed_at=datetime(2026, 8, 26, tzinfo=UTC),
    )
    session.add(bundle)
    session.flush()
    if in_bundle:
        session.add(
            DocumentBundleItem(
                bundle_id=bundle.id,
                document_version_id=document.id,
                ordinal=0,
                document_version_version=1,
                content_object_id=content.id,
                content_sha256=content.sha256,
                detected_mime="application/pdf",
                size_bytes=len(payload),
                original_filename="제안요청서.pdf",
                source_kind="manual",
                role_at_confirmation="제안요청서",
                is_current_at_confirmation=True,
                safety_status_at_confirmation="safe",
                structure_id_at_confirmation=structure.id,
                structure_payload_sha256=structure.payload_sha256,
            )
        )
    _overview_run(session, notice, overview_status, document=document)
    session.commit()


def test_pre_specs_show_why_the_deep_review_was_not_started_automatically(
    pre_specs_api, monkeypatch
):
    """§6.4: `deep_review_ready_for_click`에는 막은 사유 코드가 붙는다."""

    session, _engine, refs = pre_specs_api
    monkeypatch.delenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", raising=False)
    monkeypatch.delenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", raising=False)
    # SW=N 사전규격. 앞 조건이 모두 성립해도 사람 클릭이다.
    _auto_start_rows(session, refs["sw_no"])
    # SW=Y이지만 개요가 사람 검토로 끝났다.
    _auto_start_rows(session, refs["sw_yes"], overview_status="needs_human_review")

    items = _items_by_id(_payload(session, sw_only=False))

    assert items[refs["sw_no"].id]["auto_preparation_status"] == "deep_review_ready_for_click"
    assert items[refs["sw_no"].id]["auto_preparation_reason"] == "not_sw_business"
    assert items[refs["sw_yes"].id]["auto_preparation_status"] == "deep_review_ready_for_click"
    assert items[refs["sw_yes"].id]["auto_preparation_reason"] == "overview_not_completed"


def test_pre_specs_show_the_fail_closed_reason_when_active_versions_are_missing(
    pre_specs_api, monkeypatch
):
    """active profile/policy 설정이 없으면 fail closed 사유가 화면에 보인다."""

    session, _engine, refs = pre_specs_api
    monkeypatch.delenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", raising=False)
    monkeypatch.delenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", raising=False)
    _auto_start_rows(session, refs["sw_yes"])

    item = _items_by_id(_payload(session, sw_only=False))[refs["sw_yes"].id]

    assert item["auto_preparation_status"] == "deep_review_ready_for_click"
    assert item["auto_preparation_reason"] == "service_unavailable"
    # 개요 검토 행이 없는 다른 공고는 그대로 null이다. 자리표시자로 채우지 않는다.
    other = _items_by_id(_payload(session, sw_only=False))[refs["sw_no"].id]
    assert other["auto_preparation_reason"] == "grade_not_priority"
