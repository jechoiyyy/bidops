from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.core.db as db
from app.core.db import Base, init_db
from app.core.models import CORE_LEAN_V1_TABLES
from app.deep_review.models import (
    ATTACHMENT_FETCH_TABLES,
    BID_DELTA_TABLES,
    DEEP_REVIEW_LEAN_V1_TABLES,
    DOCUMENT_SEGMENT_TABLES,
    PRESPEC_OVERVIEW_TABLES,
)
from app.lifecycle.models import (
    IDENTITY_TABLES,
    LIFECYCLE_LEGACY_TABLES,
    Notice,
    Run,
)
from app.screening.models import (
    Evidence,
    Judgment,
    ORDER_PLAN_SCREENING_TABLES,
    Perspective,
    REVISION_TABLES,
    SCREENING_LEGACY_TABLES,
    SCREENING_RUNTIME_TABLES,
)

# 이주 전 `app/models.py`가 갖고 있던 Lean v1 두 tuple을 소유 모듈의 조각에서
# 다시 만든다 (명세 §5.1). 집합은 그대로이고 순서만 모듈별로 묶인다.
LEGACY_TABLES = LIFECYCLE_LEGACY_TABLES + SCREENING_LEGACY_TABLES
NEW_TABLES = DEEP_REVIEW_LEAN_V1_TABLES + CORE_LEAN_V1_TABLES


EXPECTED_TABLES = set(
    LEGACY_TABLES + NEW_TABLES + SCREENING_RUNTIME_TABLES + IDENTITY_TABLES
    + ATTACHMENT_FETCH_TABLES + REVISION_TABLES
    + PRESPEC_OVERVIEW_TABLES + BID_DELTA_TABLES + ORDER_PLAN_SCREENING_TABLES
    + DOCUMENT_SEGMENT_TABLES
)


def make_test_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_configured_sqlite_requires_the_explicit_isolated_test_boundary(monkeypatch):
    monkeypatch.setattr(db, "DATABASE_URL", "sqlite:////tmp/bidops-runtime-test.db")
    monkeypatch.setattr(db, "engine", make_test_engine())
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("BIDOPS_TEST_MODE", raising=False)

    with pytest.raises(RuntimeError, match="PostgreSQL 17"):
        db.assert_postgresql_runtime()
    with pytest.raises(RuntimeError, match="PostgreSQL 17"):
        db.init_db()

    monkeypatch.setenv("BIDOPS_TEST_MODE", "1")
    db.init_db()
    assert db.isolated_test_boundary_active()


def test_init_db_creates_all_declared_tables_and_indexes():
    test_engine = make_test_engine()
    init_db(test_engine)

    inspector = inspect(test_engine)
    assert set(inspector.get_table_names()) == EXPECTED_TABLES

    notice_indexes = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("notice")
    }
    assert ("collection_bucket", "sample_role") in notice_indexes
    assert ("notice_key",) in notice_indexes
    assert ("deadline_at",) in notice_indexes

    judgment_constraints = inspector.get_unique_constraints("judgment")
    assert any(constraint["column_names"] == ["notice_id"] for constraint in judgment_constraints)

    review_constraints = inspector.get_unique_constraints("review")
    assert any(
        constraint["column_names"] == ["notice_id"]
        for constraint in review_constraints
    )


def test_basic_model_relationships_and_json_columns_work():
    test_engine = make_test_engine()
    Base.metadata.create_all(test_engine)

    generated_at = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    run = Run(
        id="20260817-20260823--20260824T090000Z",
        window_from=date(2026, 8, 17),
        window_to=date(2026, 8, 23),
        generated_at=generated_at,
        counts_json={"notices": 1},
    )
    notice = Notice(
        run=run,
        notice_key="bid:R26BK01689645:000",
        title="테스트 공고",
        raw_source={"notice_id": "bid:R26BK01689645:000"},
    )
    judgment = Judgment(
        notice=notice,
        schema_version="bidops.decisions.v2",
        grade="적합",
        readiness="ready",
    )
    perspective = Perspective(
        judgment=judgment,
        position=1,
        name="제목·API 메타데이터 적합성",
        assessment="확인",
    )
    perspective.evidence.append(
        Evidence(
            source="notice.json",
            status="confirmed",
            fact="공고 식별자가 존재한다.",
        )
    )

    with Session(test_engine) as session:
        # 공고는 판정으로 향하는 relationship 을 갖지 않으므로(명세 §4) 판정을
        # 따로 세션에 넣고, 연결은 판정 쪽 외래키로 확인한다.
        session.add_all([run, judgment])
        session.commit()
        session.refresh(notice)

        assert notice.id is not None
        assert notice.run.id == run.id
        assert judgment.notice_id == notice.id
        assert judgment.perspectives[0].evidence[0].status == "confirmed"
        assert run.generated_at.tzinfo is not None
        assert notice.raw_source == {"notice_id": "bid:R26BK01689645:000"}
