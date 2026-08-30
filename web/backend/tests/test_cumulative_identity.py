from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, init_db
from app.ingest.contracts import NoticeContract
from app.ingest.loader import _remove_judgments_without_screening, _upsert_notice
from app.models import (
    Judgment,
    Notice,
    NoticeObservation,
    OrderPlan,
    OrderPlanObservation,
    Review,
    Run,
)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_notice_identity_is_global_and_run_relationship_is_observation_backed():
    assert "run_id" not in Notice.__table__.c
    assert "uq_notice_key" in {item.name for item in Notice.__table__.constraints}
    assert "delete-orphan" not in str(Run.notices.property.cascade)
    assert "delete-orphan" not in str(Run.reviews.property.cascade)
    assert NoticeObservation.__table__.c.run_id.nullable is False
    assert Review.__table__.c.run_id.nullable is True
    assert next(iter(Review.__table__.c.run_id.foreign_keys)).ondelete == "SET NULL"
    assert any(
        constraint.name == "uq_review_notice"
        and [column.name for column in constraint.columns] == ["notice_id"]
        for constraint in Review.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    )


def test_loader_upserts_one_notice_and_appends_changed_observations():
    engine = _engine()
    init_db(engine)
    with Session(engine) as session:
        first_run = Run(id="identity-run-1", generated_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        second_run = Run(id="identity-run-2", generated_at=datetime(2026, 8, 2, tzinfo=timezone.utc))
        session.add_all([first_run, second_run])
        session.flush()

        first = NoticeContract(notice_id="bid:IDENTITY:000", title="처음 제목", agency="기관")
        second = NoticeContract(notice_id="bid:IDENTITY:000", title="바뀐 제목", agency="기관")
        _upsert_notice(session, first_run.id, first, {}, "Asia/Seoul")
        _upsert_notice(session, second_run.id, second, {}, "Asia/Seoul")
        session.commit()

        notices = session.scalars(select(Notice)).all()
        observations = session.scalars(
            select(NoticeObservation).order_by(NoticeObservation.run_id)
        ).all()
        assert len(notices) == 1
        assert notices[0].title == "바뀐 제목"
        assert len(observations) == 2
        assert observations[0].changed_fields_json == []
        assert observations[1].changed_fields_json == ["title"]


def test_order_plan_has_separate_identity_and_observation_tables():
    engine = _engine()
    init_db(engine)
    assert {"order_plan", "order_plan_observation"} <= set(Base.metadata.tables)
    assert "order_plan_unty_no" in OrderPlan.__table__.c
    assert "run_id" in OrderPlanObservation.__table__.c
    assert "ofcl_nm" not in OrderPlan.__table__.c


def test_deleting_run_preserves_notice_and_review_but_removes_observation():
    engine = _engine()
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    init_db(engine)
    with Session(engine) as session:
        run = Run(
            id="identity-delete-run",
            generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
        notice = Notice(run=run, notice_key="bid:IDENTITY:DELETE")
        review = Review(notice=notice, run=run, disposition="보류")
        session.add(run)
        session.commit()

        session.delete(run)
        session.commit()

        assert session.scalar(select(Notice).where(Notice.notice_key == notice.notice_key)) is not None
        stored_review = session.scalar(select(Review).where(Review.notice_id == notice.id))
        assert stored_review is not None and stored_review.run_id is None
        assert session.scalar(
            select(NoticeObservation).where(NoticeObservation.notice_id == notice.id)
        ) is None


def test_incomplete_new_observation_does_not_delete_canonical_judgment():
    engine = _engine()
    init_db(engine)
    with Session(engine) as session:
        run = Run(
            id="identity-incomplete-run",
            generated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        )
        notice = Notice(notice_key="bid:IDENTITY:INCOMPLETE")
        notice.observations.append(NoticeObservation(run=run, changed_fields_json=[]))
        notice.judgment = Judgment(grade="검토 권장", readiness="확인 완료")
        session.add(run)
        session.commit()

        _remove_judgments_without_screening(session, {notice.notice_key: notice})
        session.commit()

        stored = session.scalar(select(Judgment).where(Judgment.notice_id == notice.id))
        assert stored is not None and stored.grade == "검토 권장"
