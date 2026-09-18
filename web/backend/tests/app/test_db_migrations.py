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
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import ALEMBIC_HEAD
from app.lifecycle.ingest.contracts import NoticeContract
from app.lifecycle.ingest.loader import ObservationSnapshotConflictError, _upsert_notice
from app.core.models import CORE_LEAN_V1_TABLES
from app.deep_review.models import (
    ATTACHMENT_FETCH_TABLES,
    BID_DELTA_TABLES,
    DEEP_REVIEW_LEAN_V1_TABLES,
    DOCUMENT_SEGMENT_TABLES,
    PRESPEC_OVERVIEW_TABLES,
    PRESPEC_V4_TABLES,
)
from app.lifecycle.models import (
    IDENTITY_TABLES,
    LIFECYCLE_LEGACY_TABLES,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)
from app.screening.models import (
    ORDER_PLAN_SCREENING_TABLES,
    OrderPlanScreeningArtifact,
    OrderPlanScreeningExecution,
    OrderPlanScreeningPolicy,
    REVISION_TABLES,
    SCREENING_LEGACY_TABLES,
    SCREENING_RUNTIME_TABLES,
)
from app.core.generation_config import GenerationConfig, legacy_generation_config
from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database

pytestmark = requires_postgres

# 이주 전 `app/models.py`가 갖고 있던 Lean v1 두 tuple을 소유 모듈의 조각에서
# 다시 만든다 (명세 §5.1). 집합은 그대로이고 순서만 모듈별로 묶인다.
LEGACY_TABLES = LIFECYCLE_LEGACY_TABLES + SCREENING_LEGACY_TABLES
NEW_TABLES = DEEP_REVIEW_LEAN_V1_TABLES + CORE_LEAN_V1_TABLES

LEAN_V1_HEAD = "0002_screening_basis_text"
#: 0026 철거 직전 판. downgrade 왕복 검사는 여기까지만 올라간다.
PRE_TEARDOWN_HEAD = "0025_overview_claim_ledger"
OBSERVATION_SNAPSHOT_BASE = "0008_prespec_attachment_fetch"
OPPORTUNITY_INTEGRITY_BASE = "0009_observation_snapshot_retention"
ALL_TABLES = frozenset(
    LEGACY_TABLES + NEW_TABLES + SCREENING_RUNTIME_TABLES + IDENTITY_TABLES
    + ATTACHMENT_FETCH_TABLES + REVISION_TABLES
    + PRESPEC_OVERVIEW_TABLES
    + BID_DELTA_TABLES
    + ORDER_PLAN_SCREENING_TABLES
    + DOCUMENT_SEGMENT_TABLES
    + ("prespec_company_fit_attempt",)
    + PRESPEC_V4_TABLES
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
    # 0026이 그 아래 downgrade를 닫았으므로 철거 직전 판에서 내려간다.
    with temporary_database(upgrade_to=PRE_TEARDOWN_HEAD) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        result = run_alembic(database_url, "downgrade", LEAN_V1_HEAD)
        assert result.returncode == 0, result.stderr
        remaining = _tables(engine)
        assert remaining == set(LEGACY_TABLES + NEW_TABLES) | {"alembic_version"}
        assert not remaining & set(SCREENING_RUNTIME_TABLES)
        engine.dispose()


def test_c2_artifact_rows_are_append_only_in_postgresql() -> None:
    with migrated_engine() as engine, Session(engine) as session:
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        execution_id = uuid4()
        session.add_all(
            [
                Run(id="c2-migration-run", generated_at=now),
                OrderPlan(order_plan_unty_no="R26DD20999999", title="계획"),
                OrderPlanScreeningPolicy(
                    id=uuid4(),
                    policy_version="c2-migration-policy",
                    schema_version="bidops.order-plan-screening-policy.v1",
                    producer="phase0-contracts",
                    consumer="phase1-screening-pipeline",
                    policy_status="draft",
                    decision_scope="c2_order_plan_first_pass",
                    policy_payload_jsonb={},
                    binding_payload_jsonb={},
                    policy_sha256="a" * 64,
                    binding_sha256="b" * 64,
                    activation_metadata_jsonb={},
                    quality_gate_status="not_measured",
                    active_slot=None,
                    created_by="migration-test",
                    created_at=now,
                ),
            ]
        )
        session.flush()
        session.add(
            OrderPlanScreeningExecution(
                execution_id=execution_id,
                request_id=execution_id,
                schema_version="bidops.order-plan-screening-execution-row.v1",
                producer="screening-api",
                consumer="screening-worker-and-review-api",
                source_run_id="c2-migration-run",
                source_artifact_name="collected-order-plans.json",
                source_artifact_schema_version="bidops.collected-order-plans.v1",
                source_artifact_sha256="c" * 64,
                input_artifact_sha256="d" * 64,
                population_count=1,
                population_sha256="e" * 64,
                policy_version="c2-migration-policy",
                policy_sha256="a" * 64,
                binding_sha256="b" * 64,
                stage1_binding_version="bm25-v1",
                stage1_binding_sha256="f" * 64,
                stage2_binding_version="qwen-v1",
                stage2_binding_sha256="1" * 64,
                status="성공",
                active_slot=None,
                requested_by="migration-test",
                partial_artifact=False,
                candidate_count=0,
                completed_count=0,
                failure_count=0,
                stage1_selected_count=0,
                stage1_filtered_out_count=1,
                stage1_failed_count=0,
                stage2_relevant_count=0,
                stage2_not_relevant_count=0,
                stage2_uncertain_count=0,
                stage2_failed_count=0,
                stage2_rejected_count=0,
                human_review_count=0,
                queued_at=now,
                started_at=now,
                finished_at=now,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            OrderPlanScreeningArtifact(
                execution_id=execution_id,
                kind="input",
                schema_version="bidops.order-plan-screening-input.v1",
                producer="order-plan-screening-orchestrator",
                consumer="order-plan-screening-worker",
                sha256="1" * 64,
                byte_count=1,
                validation_status="valid",
                created_at=now,
            )
        )
        session.commit()

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.order_plan_screening_artifact "
                        "SET sha256 = :sha256 WHERE execution_id = :execution_id"
                    ),
                    {"sha256": "2" * 64, "execution_id": execution_id},
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.order_plan_screening_policy "
                        "SET activated_by = 'tampered' "
                        "WHERE policy_version = 'c2-migration-policy'"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.order_plan_screening_execution "
                        "SET failure_count = 1 WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": execution_id},
                )


# ---------------------------------------------------------------------------
# 0018 — 사전규격 자동 준비 자격, 개요 완료 조건, 결정적 segment 저장소
# ---------------------------------------------------------------------------

SEGMENT_SCHEMA_BASE = "0017_order_plan_screening_heartbeat"
#: 0018 왕복 검사는 이 판에 고정한다. 0026이 그 아래 downgrade를 닫았으므로
#: head에서 내려가는 왕복은 더 이상 성립하지 않는다.
SEGMENT_SCHEMA_HEAD = "0018_prespec_auto_preparation_segments"
SEED_AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _columns(engine, table: str) -> set[str]:
    return set(
        _scalars(
            engine,
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'bidops' AND table_name = :table",
            table=table,
        )
    )


def _check_clause(engine, name: str) -> str:
    return _scalar(
        engine,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name",
        name=name,
    )


def _seed_prespec_document(session: Session):
    """공고 → content object → 문서 version → 구조까지 최소 계보를 만든다."""

    from app.deep_review.models import ContentObject, DocumentStructure, DocumentVersion

    notice = Notice(
        notice_key=f"pre:0018:{uuid4()}",
        source_type="pre_spec",
        title="0018 사전규격 제안요청서",
    )
    session.add(notice)
    session.flush()
    content = ContentObject(
        sha256=uuid4().hex + uuid4().hex,
        size_bytes=10,
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
        original_filename="rfp.pdf",
        role="제안요청서",
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
    )
    session.add(document)
    session.flush()
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256="a" * 64,
        media_type="application/pdf",
        extractor_name="fixture",
        extractor_version="1",
        payload_content_object_id=content.id,
        payload_sha256="b" * 64,
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    return notice, document, structure


def _seed_priority_grade_fetch(session: Session) -> int:
    from app.deep_review.models import AttachmentFetch
    from app.lifecycle import register_manual_attachment

    notice = Notice(
        notice_key=f"pre:0018:{uuid4()}",
        source_type="pre_spec",
        title="0018 등급 자격 사전규격",
    )
    session.add(notice)
    session.flush()
    attachment = register_manual_attachment(
        session,
        notice,
        name="rfp.pdf",
        file_ext="PDF",
        size_bytes=10,
        stored_path=f"attachments/0018/{uuid4().hex}.pdf",
    )
    session.flush()
    session.add(
        AttachmentFetch(
            attachment_id=attachment.id,
            status="대기",
            eligibility_reason="priority_grade",
            attempt_count=0,
            max_attempts=3,
            next_attempt_at=SEED_AT,
        )
    )
    session.commit()
    return attachment.id


def test_0018_round_trips_between_the_segment_schema_and_0017() -> None:
    """빈 DB에서 0018까지 올라가고 0017로 내려갔다가 다시 올라온다."""

    with temporary_database(upgrade_to=SEGMENT_SCHEMA_HEAD) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        try:
            assert set(DOCUMENT_SEGMENT_TABLES) <= _tables(engine)
            assert {"lease_owner", "lease_expires_at"} <= _columns(
                engine, "prespec_overview_attempt"
            )
            assert "priority_grade" in _check_clause(
                engine, "ck_attachment_fetch_eligibility_reason"
            )
            assert "deployable" not in _check_clause(
                engine, "ck_prespec_overview_attempt_completed_binding"
            )

            result = run_alembic(database_url, "downgrade", SEGMENT_SCHEMA_BASE)
            assert result.returncode == 0, result.stderr
            assert not set(DOCUMENT_SEGMENT_TABLES) & _tables(engine)
            assert not {"lease_owner", "lease_expires_at"} & _columns(
                engine, "prespec_overview_attempt"
            )
            assert "priority_grade" not in _check_clause(
                engine, "ck_attachment_fetch_eligibility_reason"
            )
            assert "deployable" in _check_clause(
                engine, "ck_prespec_overview_attempt_completed_binding"
            )
            assert (
                _scalar(engine, "SELECT version_num FROM bidops.alembic_version")
                == SEGMENT_SCHEMA_BASE
            )

            result = run_alembic(database_url, "upgrade", SEGMENT_SCHEMA_HEAD)
            assert result.returncode == 0, result.stderr
            assert set(DOCUMENT_SEGMENT_TABLES) <= _tables(engine)
            assert (
                _scalar(engine, "SELECT version_num FROM bidops.alembic_version")
                == SEGMENT_SCHEMA_HEAD
            )
        finally:
            engine.dispose()


def test_attachment_fetch_accepts_priority_grade_and_rejects_an_unknown_reason() -> None:
    with migrated_engine() as engine, Session(engine) as session:
        attachment_id = _seed_priority_grade_fetch(session)
        assert (
            _scalar(
                engine,
                "SELECT eligibility_reason FROM bidops.attachment_fetch"
                " WHERE attachment_id = :id",
                id=attachment_id,
            )
            == "priority_grade"
        )
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "UPDATE bidops.attachment_fetch SET eligibility_reason = 'top_grade'"
                    " WHERE attachment_id = :id"
                ),
                {"id": attachment_id},
            )
        session.rollback()


def test_document_segment_rows_cascade_from_their_document_structure() -> None:
    from app.deep_review.models import (
        DocumentSegment,
        DocumentSegmentManifest,
        RequirementInventoryItem,
    )

    with migrated_engine() as engine, Session(engine) as session:
        _notice, document, structure = _seed_prespec_document(session)
        manifest = DocumentSegmentManifest(
            structure_id=structure.id,
            document_version_id=document.id,
            source_sha256="a" * 64,
            taxonomy_version="v1",
            extractor_binding={"name": "deterministic-segmenter", "version": "1"},
            extractor_binding_sha256="1" * 64,
            inventory_summary={"expected_ids": ["SYR-01"], "duplicate_ids": []},
            warnings=[],
            coverage={"gaps": [], "overlaps": []},
            payload_sha256="2" * 64,
        )
        session.add(manifest)
        session.flush()
        session.add(
            DocumentSegment(
                manifest_id=manifest.id,
                segment_id="seg-1",
                ordinal=1,
                taxonomy_labels=["technical_functional"],
                title="과업 내용",
                start_locator={"block_key": "b1", "page": 1, "ordinal": 1},
                end_locator={"block_key": "b2", "page": 1, "ordinal": 2},
                requirement_ids=["SYR-01"],
                source_block_keys=["b1"],
                classification_source="deterministic",
                confidence=Decimal("0.87500"),
                status="classified",
            )
        )
        session.add(
            RequirementInventoryItem(
                manifest_id=manifest.id,
                raw_id="SYR-01",
                normalized_id="SYR-01",
                locator={"block_key": "b1", "page": 1, "ordinal": 1},
                title="요구사항",
                ordinal=1,
            )
        )
        session.commit()

        # 같은 (구조, taxonomy, 추출기 binding)으로 두 번째 manifest를 만들 수 없다.
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO bidops.document_segment_manifest"
                    " (id, structure_id, document_version_id, source_sha256,"
                    "  taxonomy_version, extractor_binding, extractor_binding_sha256,"
                    "  inventory_summary, warnings, coverage, payload_sha256)"
                    " VALUES (:id, :structure_id, :document_version_id, :sha,"
                    "  'v1', CAST('{}' AS jsonb), :binding_sha,"
                    "  CAST('{}' AS jsonb), CAST('[]' AS jsonb), CAST('{}' AS jsonb), :sha)"
                ),
                {
                    "id": uuid4(),
                    "structure_id": structure.id,
                    "document_version_id": document.id,
                    "sha": "3" * 64,
                    "binding_sha": "1" * 64,
                },
            )
        session.rollback()

        session.execute(
            text("DELETE FROM bidops.document_structure WHERE id = :id"),
            {"id": structure.id},
        )
        session.commit()
        for table in DOCUMENT_SEGMENT_TABLES:
            assert _scalar(engine, f"SELECT count(*) FROM bidops.{table}") == 0


def test_document_segment_keeps_an_unresolved_label_without_a_confidence() -> None:
    """규칙이 label을 정하지 못한 구간은 `needs_human_review`로 남고 확신도가 없다."""

    from app.deep_review.models import DocumentSegmentManifest

    with migrated_engine() as engine, Session(engine) as session:
        _notice, document, structure = _seed_prespec_document(session)
        manifest = DocumentSegmentManifest(
            structure_id=structure.id,
            document_version_id=document.id,
            source_sha256="a" * 64,
            taxonomy_version="v1",
            extractor_binding={"name": "deterministic-segmenter", "version": "1"},
            extractor_binding_sha256="4" * 64,
            inventory_summary={"expected_ids": [], "ambiguous_items": ["seg-2"]},
            warnings=["prefix_conflict"],
            coverage={"gaps": [], "overlaps": []},
            payload_sha256="5" * 64,
        )
        session.add(manifest)
        session.commit()

        insert = text(
            "INSERT INTO bidops.document_segment"
            " (id, manifest_id, segment_id, ordinal, taxonomy_labels, title,"
            "  start_locator, end_locator, requirement_ids, source_block_keys,"
            "  classification_source, confidence, status)"
            " VALUES (:id, :manifest_id, :segment_id, :ordinal, CAST('[]' AS jsonb),"
            "  NULL, CAST('{}' AS jsonb), CAST('{}' AS jsonb), CAST('[]' AS jsonb),"
            "  CAST('[]' AS jsonb), :source, :confidence, :status)"
        )
        session.execute(
            insert,
            {
                "id": uuid4(),
                "manifest_id": manifest.id,
                "segment_id": "seg-2",
                "ordinal": 1,
                "source": "deterministic",
                "confidence": None,
                "status": "needs_human_review",
            },
        )
        session.commit()

        # 사람 검토가 필요한 구간에 확신도를 지어내지 못한다.
        with pytest.raises(IntegrityError):
            session.execute(
                insert,
                {
                    "id": uuid4(),
                    "manifest_id": manifest.id,
                    "segment_id": "seg-3",
                    "ordinal": 2,
                    "source": "deterministic",
                    "confidence": Decimal("0.5"),
                    "status": "needs_human_review",
                },
            )
        session.rollback()

        # 모델 분류는 없다.
        with pytest.raises(IntegrityError):
            session.execute(
                insert,
                {
                    "id": uuid4(),
                    "manifest_id": manifest.id,
                    "segment_id": "seg-4",
                    "ordinal": 3,
                    "source": "model",
                    "confidence": None,
                    "status": "classified",
                },
            )
        session.rollback()


def test_0018_downgrade_refuses_to_discard_priority_grade_or_segment_rows() -> None:
    with temporary_database(upgrade_to=SEGMENT_SCHEMA_HEAD) as database_url:
        from sqlalchemy import create_engine

        from app.core.db import schema_bound

        engine = schema_bound(create_engine(database_url, future=True))
        try:
            with Session(engine) as session:
                _seed_priority_grade_fetch(session)

            result = run_alembic(database_url, "downgrade", SEGMENT_SCHEMA_BASE)
            assert result.returncode != 0
            assert "priority_grade" in (result.stdout + result.stderr)
            assert set(DOCUMENT_SEGMENT_TABLES) <= _tables(engine)
            assert (
                _scalar(engine, "SELECT version_num FROM bidops.alembic_version")
                == SEGMENT_SCHEMA_HEAD
            )
        finally:
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

    from app.core.db import ALEMBIC_VERSION_NUM_WIDTH as VERSION_NUM_WIDTH

    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
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


# ---------------------------------------------------------------------------
# 0029 — C-2 품질 게이트·감사 표본·일일 스위치, 실행 purpose
# ---------------------------------------------------------------------------

C2_GATE_BASE = "0028_final_decision_basis"
C2_GATE_HEAD = "0029_c2_quality_gate"
#: 표 이름 → UPDATE 시도에 쓸 문자열 열.
C2_GATE_TABLES = {
    "order_plan_screening_quality_gate": "created_by",
    "order_plan_screening_quality_evaluation": "evaluated_by",
    "order_plan_screening_audit_sample": "drawn_by",
    "order_plan_screening_daily_trigger": "set_by",
}
C2_AT = datetime(2026, 9, 18, tzinfo=timezone.utc)
_POLICY_CASTS = {
    "policy_payload_jsonb": "jsonb",
    "binding_payload_jsonb": "jsonb",
    "activation_metadata_jsonb": "jsonb",
}
_GATE_CASTS = {"measurement_run_ids_json": "jsonb"}
_EVALUATION_CASTS = {
    "pass_execution_ids_json": "jsonb",
    "metrics_json": "jsonb",
    "reasons_json": "jsonb",
}


def _insert(connection, table: str, row: dict, casts: dict | None = None) -> None:
    """ORM 없이 열 이름을 직접 적는다. 0028 시점(purpose 열 없음)에도 쓴다."""

    casts = casts or {}
    columns = ", ".join(row)
    values = ", ".join(
        f"CAST(:{name} AS {casts[name]})" if name in casts else f":{name}" for name in row
    )
    connection.execute(text(f"INSERT INTO bidops.{table} ({columns}) VALUES ({values})"), row)


def _c2_policy_row(policy_version: str) -> dict:
    return {
        "id": uuid4(),
        "policy_version": policy_version,
        "schema_version": "bidops.order-plan-screening-policy.v1",
        "producer": "phase0-contracts",
        "consumer": "phase1-screening-pipeline",
        "policy_status": "draft",
        "decision_scope": "c2_order_plan_first_pass",
        "policy_payload_jsonb": "{}",
        "binding_payload_jsonb": "{}",
        "policy_sha256": "a" * 64,
        "binding_sha256": "b" * 64,
        "activation_metadata_jsonb": "{}",
        "quality_gate_status": None,
        "created_by": "migration-test",
        "created_at": C2_AT,
    }


def _c2_execution_row(policy_version: str, run_id: str) -> dict:
    execution_id = uuid4()
    return {
        "execution_id": execution_id,
        "request_id": execution_id,
        "schema_version": "bidops.order-plan-screening-execution-row.v1",
        "producer": "screening-api",
        "consumer": "screening-worker-and-review-api",
        "source_run_id": run_id,
        "source_artifact_name": "collected-order-plans.json",
        "source_artifact_schema_version": "bidops.collected-order-plans.v1",
        "source_artifact_sha256": "c" * 64,
        "input_artifact_sha256": "d" * 64,
        "population_count": 1,
        "population_sha256": "e" * 64,
        "policy_version": policy_version,
        "policy_sha256": "a" * 64,
        "binding_sha256": "b" * 64,
        "stage1_binding_version": "bm25-v1",
        "stage1_binding_sha256": "f" * 64,
        "stage2_binding_version": "qwen-v1",
        "stage2_binding_sha256": "1" * 64,
        "status": "성공",
        "requested_by": "migration-test",
        "partial_artifact": False,
        **dict.fromkeys(
            (
                "candidate_count", "completed_count", "failure_count",
                "stage1_selected_count", "stage1_filtered_out_count", "stage1_failed_count",
                "stage2_relevant_count", "stage2_not_relevant_count", "stage2_uncertain_count",
                "stage2_failed_count", "stage2_rejected_count", "human_review_count",
            ),
            0,
        ),
        "queued_at": C2_AT,
        "started_at": C2_AT,
        "finished_at": C2_AT,
        "created_at": C2_AT,
    }


def _seed_c2_execution(connection, *, policy_version: str, run_id: str) -> dict:
    connection.execute(
        text(
            "INSERT INTO bidops.run (id, timezone, generated_at, status)"
            " VALUES (:id, 'Asia/Seoul', :at, 'active')"
        ),
        {"id": run_id, "at": C2_AT},
    )
    _insert(connection, "order_plan_screening_policy", _c2_policy_row(policy_version), _POLICY_CASTS)
    execution = _c2_execution_row(policy_version, run_id)
    _insert(connection, "order_plan_screening_execution", execution)
    return execution


def _c2_gate_row(policy_version: str, **thresholds) -> dict:
    return {
        "gate_id": "c2gate-" + uuid4().hex,
        "policy_version": policy_version,
        "policy_sha256": "a" * 64,
        "binding_sha256": "b" * 64,
        "gold_manifest_sha256": "2" * 64,
        "gold_artifact_sha256": "3" * 64,
        "gold_status": "adjudicated",
        "scoring_input_sha256": "4" * 64,
        "evaluation_basis": "product_rerun",
        "scoring_unit": "per_published_day",
        "measurement_run_ids_json": json.dumps(["gold-day-1"]),
        "required_pass_count": 2,
        "threshold_recall_pct": thresholds.get("recall"),
        "threshold_precision_pct": thresholds.get("precision"),
        "threshold_important_missed_max": thresholds.get("missed"),
        "threshold_review_load_max": thresholds.get("load"),
        "created_by": "migration-test",
        "created_at": C2_AT,
    }


def _c2_evaluation_row(gate_id: str, result_status: str, revision: int = 1) -> dict:
    return {
        "evaluation_id": "c2gateeval-" + uuid4().hex,
        "gate_id": gate_id,
        "revision": revision,
        "result_status": result_status,
        "pass_execution_ids_json": json.dumps({"pass_1": [], "pass_2": []}),
        "metrics_json": "{}",
        "reasons_json": "[]",
        # artifact digest는 모든 evaluation에서 유일하다.
        "artifact_sha256": uuid4().hex * 2,
        "evaluated_by": "migration-test",
        "evaluated_at": C2_AT,
    }


def test_0029_round_trips_and_backfills_the_execution_purpose() -> None:
    """0028의 실행 행이 0029에서 ``operational``로 채워지고, 0028로 내려갔다 다시 올라온다."""

    with temporary_database(upgrade_to=C2_GATE_BASE) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as connection:
                execution = _seed_c2_execution(
                    connection, policy_version="c2-roundtrip", run_id="c2-roundtrip-run"
                )
            assert "purpose" not in _columns(engine, "order_plan_screening_execution")

            for _ in range(2):
                result = run_alembic(database_url, "upgrade", C2_GATE_HEAD)
                assert result.returncode == 0, result.stderr
                assert set(C2_GATE_TABLES) <= _tables(engine)
                assert _scalars(
                    engine, "SELECT purpose FROM bidops.order_plan_screening_execution"
                ) == ["operational"]
                assert _scalar(engine, "SELECT version_num FROM bidops.alembic_version") == C2_GATE_HEAD

                result = run_alembic(database_url, "downgrade", C2_GATE_BASE)
                assert result.returncode == 0, result.stderr
                assert not set(C2_GATE_TABLES) & _tables(engine)
                assert "purpose" not in _columns(engine, "order_plan_screening_execution")
                assert _scalar(engine, "SELECT version_num FROM bidops.alembic_version") == C2_GATE_BASE
                assert _scalars(
                    engine, "SELECT execution_id FROM bidops.order_plan_screening_execution"
                ) == [execution["execution_id"]]

            # 게이트 행이 생긴 뒤에는 downgrade가 그 행을 버리지 않는다.
            assert run_alembic(database_url, "upgrade", C2_GATE_HEAD).returncode == 0
            with engine.begin() as connection:
                _insert(
                    connection, "order_plan_screening_quality_gate",
                    _c2_gate_row("c2-roundtrip"), _GATE_CASTS,
                )
            result = run_alembic(database_url, "downgrade", C2_GATE_BASE)
            assert result.returncode != 0
            assert "0029 downgrade is blocked" in result.stderr
            assert _scalar(engine, "SELECT version_num FROM bidops.alembic_version") == C2_GATE_HEAD
        finally:
            engine.dispose()


def test_0029_gate_tables_are_append_only_and_undecided_thresholds_only_allow_unmeasured() -> None:
    with migrated_engine() as engine:
        with engine.begin() as connection:
            execution = _seed_c2_execution(connection, policy_version="c2-gate", run_id="c2-gate-run")
            order_plan_id = connection.scalar(
                text(
                    "INSERT INTO bidops.order_plan (order_plan_unty_no, title)"
                    " VALUES ('R26DD20999998', '계획') RETURNING id"
                )
            )
            # 검토량 한도만 비어 있어도 미결정이다.
            undecided = _c2_gate_row(
                "c2-gate", recall=Decimal("95"), precision=Decimal("60"), missed=0
            )
            decided = _c2_gate_row(
                "c2-gate", recall=Decimal("95"), precision=Decimal("60"), missed=0, load=40
            )
            for gate in (undecided, decided):
                _insert(connection, "order_plan_screening_quality_gate", gate, _GATE_CASTS)
            assert connection.scalar(
                text(
                    "SELECT purpose FROM bidops.order_plan_screening_execution"
                    " WHERE execution_id = :id"
                ),
                {"id": execution["execution_id"]},
            ) == "operational"

        # 임계값이 하나라도 NULL이면 `미측정`만 들어간다. 계산 불가를 통과로 바꾸지 않는다.
        for status in ("통과", "미달", "보류"):
            with pytest.raises(IntegrityError, match="thresholds are undecided"):
                with engine.begin() as connection:
                    _insert(
                        connection, "order_plan_screening_quality_evaluation",
                        _c2_evaluation_row(undecided["gate_id"], status), _EVALUATION_CASTS,
                    )
        with engine.begin() as connection:
            _insert(
                connection, "order_plan_screening_quality_evaluation",
                _c2_evaluation_row(undecided["gate_id"], "미측정"), _EVALUATION_CASTS,
            )
            _insert(
                connection, "order_plan_screening_quality_evaluation",
                _c2_evaluation_row(decided["gate_id"], "통과"), _EVALUATION_CASTS,
            )
            _insert(
                connection, "order_plan_screening_audit_sample",
                {
                    "id": uuid4(),
                    "execution_id": execution["execution_id"],
                    "order_plan_id": order_plan_id,
                    "stratum": "uniform_hash",
                    "selection_rank": 1,
                    "plan_id_sha256": "6" * 64,
                    "filtered_out_count": 1,
                    "max_per_execution": 5,
                    "review_cadence": "weekday",
                    "policy_version": "c2-gate",
                    "policy_sha256": "a" * 64,
                    "drawn_by": "migration-test",
                    "drawn_at": C2_AT,
                },
            )
            _insert(
                connection, "order_plan_screening_daily_trigger",
                {
                    "id": uuid4(),
                    "policy_version": "c2-gate",
                    "policy_sha256": "a" * 64,
                    "enabled": False,
                    "reason": None,
                    "set_by": "migration-test",
                    "set_at": C2_AT,
                    "request_id": uuid4(),
                },
            )

        for table, column in C2_GATE_TABLES.items():
            for statement in (
                f"UPDATE bidops.{table} SET {column} = 'tampered'",
                f"DELETE FROM bidops.{table}",
            ):
                with pytest.raises(IntegrityError, match="append-only"):
                    with engine.begin() as connection:
                        connection.execute(text(statement))

        # 고정값이 아닌 pass 수, 같은 revision의 재기록은 CHECK·UNIQUE가 거부한다.
        with pytest.raises(IntegrityError, match="ck_order_plan_screening_quality_gate_pass_count"):
            with engine.begin() as connection:
                _insert(
                    connection, "order_plan_screening_quality_gate",
                    {**_c2_gate_row("c2-gate"), "required_pass_count": 1}, _GATE_CASTS,
                )
        with pytest.raises(IntegrityError, match="uq_order_plan_screening_quality_evaluation_revision"):
            with engine.begin() as connection:
                _insert(
                    connection, "order_plan_screening_quality_evaluation",
                    _c2_evaluation_row(decided["gate_id"], "통과"), _EVALUATION_CASTS,
                )

        # 활성화가 artifact digest로 evaluation을 특정하므로 같은 digest는 두 번 들어가지 않는다.
        first = _c2_evaluation_row(decided["gate_id"], "미달", revision=2)
        with engine.begin() as connection:
            _insert(connection, "order_plan_screening_quality_evaluation", first, _EVALUATION_CASTS)
        with pytest.raises(IntegrityError, match="uq_order_plan_screening_quality_evaluation_artifact"):
            with engine.begin() as connection:
                _insert(
                    connection, "order_plan_screening_quality_evaluation",
                    {
                        **_c2_evaluation_row(decided["gate_id"], "미달", revision=3),
                        "artifact_sha256": first["artifact_sha256"],
                    },
                    _EVALUATION_CASTS,
                )

        # purpose: 두 값만 받고, INSERT 뒤에는 바꾸지 못한다.
        with pytest.raises(IntegrityError, match="ck_order_plan_screening_execution_purpose"):
            with engine.begin() as connection:
                _insert(
                    connection, "order_plan_screening_execution",
                    {**_c2_execution_row("c2-gate", "c2-gate-run"), "purpose": "reference"},
                )
        measurement = {
            **_c2_execution_row("c2-gate", "c2-gate-run"),
            "purpose": "gate_measurement",
            "status": "대기",
            "started_at": None,
            "finished_at": None,
        }
        with engine.begin() as connection:
            _insert(connection, "order_plan_screening_execution", measurement)
        with pytest.raises(IntegrityError, match="purpose is immutable"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.order_plan_screening_execution SET purpose = 'operational'"
                        " WHERE execution_id = :id"
                    ),
                    {"id": measurement["execution_id"]},
                )


def test_0029_policy_quality_gate_status_is_written_only_on_activation() -> None:
    activate = (
        "UPDATE bidops.order_plan_screening_policy SET policy_status = 'active',"
        " active_slot = 1, activated_by = 'migration-test', activated_at = now(),"
        " quality_gate_status = :status WHERE policy_version = 'c2-activate'"
    )
    with migrated_engine() as engine:
        with engine.begin() as connection:
            _insert(connection, "order_plan_screening_policy", _c2_policy_row("c2-activate"), _POLICY_CASTS)

        with pytest.raises(IntegrityError, match="written only on activation"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.order_plan_screening_policy SET quality_gate_status = 'passed'"
                        " WHERE policy_version = 'c2-activate'"
                    )
                )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE bidops.order_plan_screening_policy"
                    " SET policy_status = 'activation_candidate'"
                    " WHERE policy_version = 'c2-activate'"
                )
            )
        with pytest.raises(IntegrityError, match="written only on activation"):
            with engine.begin() as connection:
                connection.execute(text(activate), {"status": "failed"})
        # 게이트 통과 기록 없이는 active로 올라가지 못한다(명세 §3.3 9번).
        with pytest.raises(IntegrityError, match="requires quality_gate_status passed"):
            with engine.begin() as connection:
                connection.execute(text(activate), {"status": None})
        with engine.begin() as connection:
            connection.execute(text(activate), {"status": "passed"})
        assert _scalar(
            engine,
            "SELECT quality_gate_status FROM bidops.order_plan_screening_policy"
            " WHERE policy_version = 'c2-activate'",
        ) == "passed"
        # 다른 payload 열의 불변 조건은 0016 그대로다.
        with pytest.raises(IntegrityError, match="payload is immutable"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.order_plan_screening_policy SET created_by = 'tampered'"
                        " WHERE policy_version = 'c2-activate'"
                    )
                )
