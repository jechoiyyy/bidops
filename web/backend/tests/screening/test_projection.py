"""screening이 lifecycle에 제공하는 판정 projection과 deep_review seam (명세 §6.1·§6.3)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.constants import GRADE_ORDER
from app.core.db import init_db
from app.lifecycle import JudgmentProjection, RunIngestHook
from app.models import (
    Judgment,
    JudgmentRevision,
    Notice,
    NoticeObservation,
    Perspective,
    Review,
    Run,
    VerificationItem,
)
from app.screening import (
    CorrectedGrade,
    JudgmentSummary,
    ScreeningJudgmentProjection,
    ScreeningRunIngestHook,
    current_judgment,
    current_judgments,
    latest_corrected_grade,
)
from app.services.revisions import append_judgment_revision

NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with Session(engine) as session:
        run = Run(id="proj-run", window_from=date(2026, 8, 17), window_to=date(2026, 8, 23), generated_at=NOW)
        other = Run(id="proj-other", window_from=date(2026, 8, 10), window_to=date(2026, 8, 16), generated_at=NOW - timedelta(days=7))
        notices = [
            Notice(run=run, notice_key="bid:P:000", title="우선", sample_role="analysis", deadline_at=NOW + timedelta(days=1)),
            Notice(run=run, notice_key="bid:P:001", title="권장", sample_role="analysis"),
            Notice(run=run, notice_key="bid:P:002", title="제외", sample_role="analysis"),
            Notice(run=run, notice_key="bid:P:003", title="판정 없음", sample_role="analysis"),
            Notice(run=run, notice_key="bid:P:004", title="감사 누락", sample_role="audit"),
            Notice(run=other, notice_key="bid:P:005", title="다른 회차", sample_role="analysis"),
        ]
        session.add_all([run, other, *notices])
        session.flush()
        judgments = [
            Judgment(notice=notices[0], schema_version="bidops.decisions.v2", grade="우선 검토", readiness="부분 확인 필요", primary_focus="AI/데이터", summary="요약 0"),
            Judgment(notice=notices[1], schema_version="bidops.decisions.v2", grade="검토 권장", readiness="확인 완료", primary_focus="공공 SI·통합관리"),
            Judgment(notice=notices[2], schema_version="bidops.decisions.v2", grade="제외", readiness="해당 없음", primary_focus="해당 없음"),
            Judgment(notice=notices[4], schema_version="bidops.decisions.v2", grade="검토 권장", readiness="확인 완료", primary_focus="AI/데이터"),
            Judgment(notice=notices[5], schema_version="bidops.decisions.v2", grade="우선 검토", readiness="확인 완료", primary_focus="AI/데이터"),
        ]
        judgments[0].verification_items.append(VerificationItem(item="참가자격", why="회사 프로필 5.2의 조달 자격 항목이", blocking=True, status="미확인"))
        judgments[0].verification_items.append(VerificationItem(item="참고", why="참고", blocking=False, status="확인 완료"))
        judgments[0].perspectives.extend([Perspective(position=1, name="기술", assessment="적합"), Perspective(position=2, name="사업성", assessment="확인 불가")])
        session.add_all(judgments)
        session.add(
            Review(
                notice=notices[1],
                run=run,
                disposition="관찰",
                system_judgment_review="동의",
                corrected_grade="관찰 대상",
                corrected_readiness="확인 완료",
                reason="정정",
                reviewer="담당자",
                created_at=NOW,
                updated_at=NOW + timedelta(hours=1),
            )
        )
        session.add(Review(notice=notices[0], run=run, disposition="관찰", reviewer="담당자", created_at=NOW, updated_at=NOW))
        session.flush()
        append_judgment_revision(
            session,
            notice_id=notices[0].id,
            source_kind="legacy_import",
            run_id="proj-run",
            payload={"schema_version": "bidops.decisions.v2", "grade": "우선 검토", "readiness": "부분 확인 필요"},
        )
        session.commit()
        yield session


def _count_statements(session: Session):
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", record)
    return statements, lambda: event.remove(session.get_bind(), "before_cursor_execute", record)


def test_projection_and_hook_satisfy_the_lifecycle_protocols():
    assert isinstance(ScreeningJudgmentProjection(), JudgmentProjection)
    assert isinstance(ScreeningRunIngestHook(), RunIngestHook)


def test_notice_fields_and_grade_rank_cover_only_judged_notices(session):
    projection = ScreeningJudgmentProjection()
    ids = [notice.id for notice in session.query(Notice).order_by(Notice.id)]

    fields = projection.notice_fields(session, ids)
    assert fields[ids[0]] == {"grade": "우선 검토", "readiness": "부분 확인 필요", "focus": "AI/데이터"}
    assert ids[3] not in fields

    ranks = projection.grade_rank(session, ids)
    assert ranks[ids[0]] == GRADE_ORDER.index("우선 검토")
    assert ranks[ids[2]] == GRADE_ORDER.index("제외")
    # 판정이 없는 공고도 순위를 받는다. 알 수 없는 등급과 같은 마지막 자리다.
    assert ranks[ids[3]] == len(GRADE_ORDER)
    assert set(ranks) == set(ids)


def test_notice_ids_for_filters_distinguishes_no_restriction_from_zero_matches(session):
    projection = ScreeningJudgmentProjection()
    ids = [notice.id for notice in session.query(Notice).order_by(Notice.id)]

    # grade=all 이고 다른 필터가 없으면 집합을 제한하지 않는다.
    assert projection.notice_ids_for_filters(session, run_id="proj-run", grade="all") is None
    # 필터가 없으면 기본 조건 (grade != 제외) 이 projection의 일부다.
    default = set(projection.notice_ids_for_filters(session, run_id="proj-run"))
    assert default == {ids[0], ids[1], ids[4]}
    assert set(projection.notice_ids_for_filters(session, run_id="proj-run", grade="우선 검토")) == {ids[0]}
    assert set(projection.notice_ids_for_filters(session, run_id="proj-run", grade="all", readiness="확인 완료")) == {ids[1], ids[4]}
    assert set(projection.notice_ids_for_filters(session, run_id="proj-run", focus="공공 SI·통합관리")) == {ids[1]}
    zero = projection.notice_ids_for_filters(session, run_id="proj-run", grade="관찰 대상")
    assert zero is not None and tuple(zero) == ()
    # 다른 회차의 판정은 이 회차의 집합에 들어오지 않는다.
    assert ids[5] not in set(projection.notice_ids_for_filters(session, run_id="proj-run"))


def test_notice_detail_returns_lifecycle_dtos(session):
    projection = ScreeningJudgmentProjection()
    ids = [notice.id for notice in session.query(Notice).order_by(Notice.id)]

    detail = projection.notice_detail(session, ids[0])
    assert detail["judgment"].grade == "우선 검토"
    assert [item.item for item in detail["judgment"].verification_items] == ["참가자격", "참고"]
    assert [item.name for item in detail["judgment"].perspectives] == ["기술", "사업성"]
    assert [review.disposition for review in detail["reviews"]] == ["관찰"]
    assert projection.notice_detail(session, ids[3]) == {"judgment": None, "reviews": []}


def test_run_stats_fill_every_judgment_dependent_field(session):
    projection = ScreeningJudgmentProjection()
    ids = [notice.id for notice in session.query(Notice).order_by(Notice.id)]

    stats = projection.run_stats(session, "proj-run")
    assert stats["priority_review_count"] == 1
    assert stats["audit_missed_count"] == 1
    assert [(item.key, item.count) for item in stats["funnel"]] == [("review_queue", 2)]
    assert [(item.key, item.count) for item in stats["grade_distribution"]] == [("우선 검토", 1), ("검토 권장", 1), ("제외", 1)]
    assert [(item.key, item.count) for item in stats["readiness_distribution"]] == [("확인 완료", 1), ("부분 확인 필요", 1), ("해당 없음", 1)]
    assert [item.key for item in stats["focus_distribution"]] == ["AI/데이터", "공공 SI·통합관리", "해당 없음"]
    assert [(item.item, item.count, item.notice_pks, item.profile_sections) for item in stats["verification_requests"]] == [
        ("참가자격", 1, [ids[0]], ["5.2"])
    ]
    assert stats["blocking_verification_items"] == {ids[0]: ["참가자격"]}


def test_metrics_input_is_assembled_per_run(session):
    projection = ScreeningJudgmentProjection()

    metrics = projection.metrics_input(session, ["proj-run"])["proj-run"]
    assert [item.key for item in metrics] == [
        "reproducibility",
        "discriminative_power",
        "evidence_validity",
        "information_sufficiency",
        "perspective_split",
    ]
    assert metrics[1].basis.numerator == 1 and metrics[1].basis.denominator == 3
    assert metrics[2].status == "pass" and metrics[2].basis.denominator == 1
    assert metrics[4].value == 1.0


def test_projection_reads_a_run_in_a_constant_number_of_queries(session):
    projection = ScreeningJudgmentProjection()
    ids = [notice.id for notice in session.query(Notice).order_by(Notice.id)]
    statements, stop = _count_statements(session)
    try:
        projection.notice_fields(session, ids)
        projection.grade_rank(session, ids)
        projection.notice_ids_for_filters(session, run_id="proj-run")
        projection.run_stats(session, "proj-run")
        projection.notice_detail(session, ids[0])
    finally:
        stop()
    assert len(statements) <= 14


# --- deep_review seam (§6.3) ---------------------------------------------------


def test_current_judgment_and_batch_share_one_shape(session):
    ids = [notice.id for notice in session.query(Notice).order_by(Notice.id)]

    single = current_judgment(session, ids[0])
    assert single == JudgmentSummary(notice_id=ids[0], run_id="proj-run", grade="우선 검토", readiness="부분 확인 필요", focus="AI/데이터")
    assert current_judgment(session, ids[3]) is None

    statements, stop = _count_statements(session)
    try:
        batch = current_judgments(session, ids)
    finally:
        stop()
    assert set(batch) == {ids[0], ids[1], ids[2], ids[4], ids[5]}
    assert batch[ids[0]] == single
    # revision이 없는 판정은 run을 모른다.
    assert batch[ids[1]].run_id is None and batch[ids[1]].grade == "검토 권장"
    assert len(statements) <= 2
    assert current_judgments(session, []) == {}


def test_latest_corrected_grade_follows_the_newest_review_with_a_correction(session):
    ids = [notice.id for notice in session.query(Notice).order_by(Notice.id)]

    corrected = latest_corrected_grade(session, ids[1])
    review_id = session.query(Review.id).filter(Review.notice_id == ids[1]).scalar()
    assert corrected == CorrectedGrade(grade="관찰 대상", run_id="proj-run", review_id=review_id)
    # 정정 등급이 없는 리뷰는 세지 않는다.
    assert latest_corrected_grade(session, ids[0]) is None
    assert latest_corrected_grade(session, ids[3]) is None


def test_seam_values_are_immutable():
    summary = JudgmentSummary(notice_id=1, run_id=None, grade="제외", readiness=None, focus=None)
    with pytest.raises(AttributeError):
        summary.grade = "우선 검토"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        CorrectedGrade(grade="제외", run_id=None, review_id=1).grade = "x"  # type: ignore[misc]
    assert JudgmentRevision.__tablename__ == "judgment_revision"
