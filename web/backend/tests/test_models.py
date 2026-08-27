from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.db import Base, init_db
from app.models import (
    Evidence,
    Judgment,
    LEGACY_TABLES,
    NEW_TABLES,
    SCREENING_RUNTIME_TABLES,
    Notice,
    Perspective,
    Run,
)


EXPECTED_TABLES = set(LEGACY_TABLES + NEW_TABLES + SCREENING_RUNTIME_TABLES)


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
    assert ("run_id", "collection_bucket", "sample_role") in notice_indexes
    assert ("notice_key",) in notice_indexes
    assert ("deadline_at",) in notice_indexes

    judgment_constraints = inspector.get_unique_constraints("judgment")
    assert any(constraint["column_names"] == ["notice_id"] for constraint in judgment_constraints)

    review_constraints = inspector.get_unique_constraints("review")
    assert any(
        constraint["column_names"] == ["notice_id", "run_id"]
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
        session.add(run)
        session.commit()
        session.refresh(notice)

        assert notice.id is not None
        assert notice.run.id == run.id
        assert notice.judgment is judgment
        assert judgment.perspectives[0].evidence[0].status == "confirmed"
        assert run.generated_at.tzinfo is not None
        assert notice.raw_source == {"notice_id": "bid:R26BK01689645:000"}
