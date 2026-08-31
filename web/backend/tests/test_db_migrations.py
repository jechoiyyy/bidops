"""PostgreSQL migration contract for the merged screening/deep-review lineage.

The T15 branch built the screening runtime through four SQLite revisions whose
DDL (``RAISE(ABORT)`` triggers, ``PRAGMA writable_schema`` rewrites, and CHECK
constraints calling per-connection Python UDFs) has no PostgreSQL form.  The
merged lineage replaces them with ``0003_screening_runtime_pg``, so these tests
assert what that lineage actually guarantees rather than replaying the removed
incremental SQLite history.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import ALEMBIC_HEAD
from app.ingest.contracts import NoticeContract
from app.ingest.loader import ObservationSnapshotConflictError, _upsert_notice
from app.models import (
    ATTACHMENT_FETCH_TABLES,
    IDENTITY_TABLES,
    LEGACY_TABLES,
    NEW_TABLES,
    REVISION_TABLES,
    PRESPEC_OVERVIEW_TABLES,
    SCREENING_RUNTIME_TABLES,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)
from app.screening.generation_config import GenerationConfig, legacy_generation_config
from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database

pytestmark = requires_postgres

LEAN_V1_HEAD = "0002_screening_basis_text"
OBSERVATION_SNAPSHOT_BASE = "0008_prespec_attachment_fetch"
OPPORTUNITY_INTEGRITY_BASE = "0009_observation_snapshot_retention"
ALL_TABLES = frozenset(
    LEGACY_TABLES + NEW_TABLES + SCREENING_RUNTIME_TABLES + IDENTITY_TABLES
    + ATTACHMENT_FETCH_TABLES + REVISION_TABLES
    + PRESPEC_OVERVIEW_TABLES
)


def _scalars(engine, sql: str, **params) -> list:
    with engine.connect() as connection:
        return list(connection.scalars(text(sql), params))


def _scalar(engine, sql: str, **params):
    with engine.connect() as connection:
        return connection.scalar(text(sql), params)


def _tables(engine) -> set[str]:
    return set(
        _scalars(
            engine,
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'bidops'",
        )
    )


def test_clean_database_migrates_to_a_single_head() -> None:
    with migrated_engine() as engine:
        assert _scalar(engine, "SELECT version_num FROM bidops.alembic_version") == ALEMBIC_HEAD
        assert _tables(engine) == ALL_TABLES | {"alembic_version"}


def test_alembic_reports_exactly_one_head() -> None:
    with temporary_database(upgrade_to=None) as database_url:
        result = run_alembic(database_url, "heads")
        assert result.returncode == 0, result.stderr
        heads = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(heads) == 1, result.stdout
        assert ALEMBIC_HEAD in heads[0]


def test_existing_lean_v1_database_upgrades_without_recreating_tables() -> None:
    """The screening tables belong to 0003 only, so neither path creates them twice."""

    with temporary_database(upgrade_to=LEAN_V1_HEAD) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        lean_tables = _tables(engine)
        assert lean_tables == set(LEGACY_TABLES + NEW_TABLES) | {"alembic_version"}
        assert not lean_tables & set(SCREENING_RUNTIME_TABLES)

        # A long legacy basis must survive the upgrade untruncated.
        basis = "근거 " * 40
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.run"
                    " (id, window_from, window_to, timezone, generated_at, screening_basis,"
                    "  status, counts_json)"
                    " VALUES ('legacy-run', '2026-08-01', '2026-08-02', 'Asia/Seoul',"
                    "         now(), :basis, 'active', '{}')"
                ),
                {"basis": basis},
            )

        upgraded = run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr

        assert _tables(engine) == ALL_TABLES | {"alembic_version"}
        assert _scalar(engine, "SELECT version_num FROM bidops.alembic_version") == ALEMBIC_HEAD
        assert (
            _scalar(engine, "SELECT screening_basis FROM bidops.run WHERE id = 'legacy-run'")
            == basis
        )
        engine.dispose()


def test_clean_and_upgraded_databases_have_the_same_schema() -> None:
    column_sql = (
        "SELECT table_name || '.' || column_name || ':' || data_type"
        " FROM information_schema.columns WHERE table_schema = 'bidops' ORDER BY 1"
    )
    with migrated_engine() as clean:
        clean_columns = _scalars(clean, column_sql)
    with temporary_database(upgrade_to=LEAN_V1_HEAD) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        assert run_alembic(database_url, "upgrade", "head").returncode == 0
        upgraded_columns = _scalars(engine, column_sql)
        engine.dispose()
    assert clean_columns == upgraded_columns


def test_0009_preserves_legacy_observations_without_guessing_snapshots() -> None:
    with temporary_database(upgrade_to=OBSERVATION_SNAPSHOT_BASE) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.run"
                    " (id, timezone, generated_at, status, counts_json)"
                    " VALUES ('legacy-observation-run', 'Asia/Seoul', now(), 'active', '{}')"
                )
            )
            connection.execute(
                text("INSERT INTO bidops.notice (notice_key) VALUES ('legacy-observation')")
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.notice_observation"
                    " (notice_id, run_id, observed_at, changed_fields_json)"
                    " SELECT id, 'legacy-observation-run', now(), '[]'::jsonb"
                    " FROM bidops.notice WHERE notice_key = 'legacy-observation'"
                )
            )

        upgraded = run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr + upgraded.stdout
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT snapshot_schema_version, snapshot_jsonb, source_sha256"
                    " FROM bidops.notice_observation"
                )
            ).one()
        assert row == (None, None, None)
        engine.dispose()


@pytest.mark.parametrize("digest", [None, "A" * 64], ids=["partial", "uppercase"])
def test_observation_snapshot_constraints_reject_partial_or_invalid_hashes(
    digest: str | None,
) -> None:
    with migrated_engine() as engine:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.run"
                    " (id, timezone, generated_at, status, counts_json)"
                    " VALUES ('snapshot-constraint-run', 'Asia/Seoul', now(), 'active', '{}')"
                )
            )
            connection.execute(
                text("INSERT INTO bidops.notice (notice_key) VALUES ('snapshot-constraint')")
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.notice_observation"
                        " (notice_id, run_id, observed_at, changed_fields_json,"
                        "  snapshot_schema_version, snapshot_jsonb, source_sha256)"
                        " SELECT id, 'snapshot-constraint-run', now(), '[]'::jsonb,"
                        "  'bidops.notice-observation-snapshot.v1', '{}'::jsonb, :digest"
                        " FROM bidops.notice WHERE notice_key = 'snapshot-constraint'"
                    ),
                    {"digest": digest},
                )


def test_postgres_loader_snapshot_replay_is_idempotent_and_conflict_rolls_back() -> None:
    with migrated_engine() as engine, Session(engine) as session:
        run = Run(
            id="postgres-snapshot-replay",
            generated_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        )
        session.add(run)
        session.commit()
        original = NoticeContract(
            notice_id="bid:POSTGRES:SNAPSHOT",
            title="고정 입력",
            unknown_fields=["qualification"],
            raw_source={"raw_ref": "raw/postgres-snapshot.json"},
        )
        first = _upsert_notice(session, run.id, original, {}, "Asia/Seoul")
        session.commit()
        assert first is not None
        observation = session.scalar(select(NoticeObservation))
        assert observation is not None and observation.source_sha256 is not None
        digest = observation.source_sha256

        assert _upsert_notice(session, run.id, original, {}, "Asia/Seoul") is first
        session.commit()
        assert session.scalar(select(NoticeObservation)).source_sha256 == digest

        with pytest.raises(ObservationSnapshotConflictError):
            _upsert_notice(
                session,
                run.id,
                NoticeContract(notice_id=original.notice_id, title="충돌 입력"),
                {},
                "Asia/Seoul",
            )
        session.rollback()
        stored = session.scalar(select(Notice))
        assert stored is not None and stored.title == "고정 입력"


def test_0010_preflight_rejects_existing_duplicate_authoritative_links() -> None:
    with temporary_database(upgrade_to=OPPORTUNITY_INTEGRITY_BASE) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.order_plan (order_plan_unty_no) "
                    "VALUES ('R26DD20999999')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.opportunity (first_registered_stage) "
                    "VALUES ('order_plan'), ('bid_notice')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.opportunity_link "
                    "(opportunity_id, order_plan_id, stage, link_type, status, "
                    " evidence_external_no) "
                    "SELECT opportunity.id, order_plan.id, 'order_plan', "
                    "       'official', '확정', order_plan.order_plan_unty_no "
                    "FROM bidops.opportunity CROSS JOIN bidops.order_plan"
                )
            )

        upgraded = run_alembic(database_url, "upgrade", "head")

        assert upgraded.returncode != 0
        output = upgraded.stderr + upgraded.stdout
        assert "duplicate authoritative opportunity links" in output
        assert "order_plan_id=1" in output
        assert "link_ids=[1, 2]" in output
        assert _scalar(
            engine, "SELECT version_num FROM bidops.alembic_version"
        ) == OPPORTUNITY_INTEGRITY_BASE
        engine.dispose()


def test_authoritative_partial_unique_index_rejects_accepted_candidate_duplicate() -> None:
    with migrated_engine() as engine, Session(engine) as session:
        plan = OrderPlan(order_plan_unty_no="R26DD20888888")
        official_owner = Opportunity(first_registered_stage="order_plan")
        candidate_owner = Opportunity(first_registered_stage="order_plan")
        session.add_all([plan, official_owner, candidate_owner])
        session.flush()
        session.add(
            OpportunityLink(
                opportunity=official_owner,
                order_plan=plan,
                stage="order_plan",
                link_type="official",
                status="확정",
                evidence_external_no=plan.order_plan_unty_no,
            )
        )
        session.commit()

        session.add(
            OpportunityLink(
                opportunity=candidate_owner,
                order_plan=plan,
                stage="order_plan",
                link_type="candidate",
                status="사람 확인 완료",
                human_decision="accepted",
                reviewer_name="migration-reviewer",
                reviewed_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
                review_reason="같은 계획으로 확인",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_fresh_database_seeds_only_the_runtime_singletons() -> None:
    """Migration must not seed policy or portal rows, and always-on stays off."""

    with migrated_engine() as engine:
        assert _scalar(engine, "SELECT count(*) FROM bidops.schedule_setting") == 1
        assert _scalar(engine, "SELECT count(*) FROM bidops.always_on_state") == 1
        assert _scalar(engine, "SELECT bool_or(enabled) FROM bidops.always_on_state") is False
        assert _scalar(engine, "SELECT count(*) FROM bidops.screening_policy") == 0
        assert _scalar(engine, "SELECT count(*) FROM bidops.agency_portal") == 0
        assert _scalar(engine, "SELECT count(*) FROM bidops.screening_execution") == 0


def test_migration_records_a_deterministic_audit_marker() -> None:
    with migrated_engine() as engine:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT event_id, actor, target_type, target_id, details_json"
                    " FROM bidops.screening_audit_event"
                    " WHERE event_type = 'db.migration' AND target_id = :revision"
                ),
                {"revision": ALEMBIC_HEAD},
            ).one()
        assert row.actor == "system:migration"
        assert row.target_type == "database"
        assert row.target_id == ALEMBIC_HEAD
        assert row.details_json == {
            "migration_revision": ALEMBIC_HEAD,
            "action": "upgrade",
        }


@pytest.mark.parametrize(
    "config", [GenerationConfig(), legacy_generation_config()], ids=["default", "legacy"]
)
def test_database_canonical_json_matches_the_python_contract(config: GenerationConfig) -> None:
    """The digest binding is only fail-closed if both sides agree byte for byte."""

    with migrated_engine() as engine:
        canonical = _scalar(
            engine,
            "SELECT bidops.generation_config_canonical_json(:value)",
            value=config.canonical_json(),
        )
        digest = _scalar(
            engine,
            "SELECT bidops.generation_config_digest(:value)",
            value=config.canonical_json(),
        )
    assert canonical == config.canonical_json()
    assert digest == config.digest()


def test_database_normalises_key_order_and_whitespace_to_one_digest() -> None:
    reordered = (
        '{ "think": false, "stream": false,'
        ' "schema_version": "bidops.generation-config.v1",'
        ' "num_predict": {"synthesis": 4096, "perspective": 2048, "counterargument": 2048},'
        ' "num_ctx": 16384 }'
    )
    with migrated_engine() as engine:
        assert (
            _scalar(engine, "SELECT bidops.generation_config_digest(:value)", value=reordered)
            == GenerationConfig().digest()
        )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param('{"num_ctx":16384}', id="missing-keys"),
        pytest.param("not json", id="malformed"),
        pytest.param(
            '{"num_ctx":16384.0,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":4096},"schema_version":"bidops.generation-config.v1",'
            '"stream":false,"think":false}',
            id="float-num-ctx",
        ),
        pytest.param(
            '{"num_ctx":16384,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":4096},"schema_version":"bidops.generation-config.v1",'
            '"stream":false,"think":true}',
            id="think-enabled",
        ),
        pytest.param(
            '{"num_ctx":16384,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":99999},"schema_version":"bidops.generation-config.v1",'
            '"stream":false,"think":false}',
            id="budget-over-context",
        ),
        pytest.param(
            '{"num_ctx":16384,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":4096},"schema_version":"bidops.generation-config.v2",'
            '"stream":false,"think":false}',
            id="unknown-schema",
        ),
    ],
)
def test_database_rejects_non_canonical_generation_config(value: str) -> None:
    with migrated_engine() as engine:
        assert _scalar(engine, "SELECT bidops.generation_config_digest(:value)", value=value) is None


def test_downgrade_removes_only_the_screening_runtime() -> None:
    with temporary_database() as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        result = run_alembic(database_url, "downgrade", LEAN_V1_HEAD)
        assert result.returncode == 0, result.stderr
        remaining = _tables(engine)
        assert remaining == set(LEGACY_TABLES + NEW_TABLES) | {"alembic_version"}
        assert not remaining & set(SCREENING_RUNTIME_TABLES)
        engine.dispose()


def test_every_revision_identifier_fits_the_version_column() -> None:
    """Guard the defect that made ``upgrade head`` impossible on PostgreSQL.

    Alembic hard-codes ``version_num VARCHAR(32)`` when it creates its own
    version table, and two identifiers in this lineage are longer than that.
    PostgreSQL enforces the declared length while SQLite ignores it, so an
    over-long identifier fails only on the canonical store -- and, because
    PostgreSQL DDL is transactional, it fails the whole run without leaving a
    version table behind.  ``alembic/env.py`` therefore creates the table at
    ``VERSION_NUM_WIDTH``; this test keeps the identifiers inside it.
    """

    import re
    from pathlib import Path

    from app.db import ALEMBIC_VERSION_NUM_WIDTH as VERSION_NUM_WIDTH

    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    pattern = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
    identifiers = []
    for path in sorted(versions.glob("*.py")):
        if path.name.startswith("_"):
            continue
        match = pattern.search(path.read_text(encoding="utf-8"))
        assert match is not None, f"{path.name} has no revision identifier"
        identifiers.append(match.group(1))

    assert identifiers, "no Alembic revisions were found"
    too_long = {value: len(value) for value in identifiers if len(value) > VERSION_NUM_WIDTH}
    assert not too_long, f"revision identifiers exceed VARCHAR({VERSION_NUM_WIDTH}): {too_long}"
