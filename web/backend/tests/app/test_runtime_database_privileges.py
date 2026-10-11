"""Runtime PostgreSQL role allow/deny contract.

The static checks run everywhere.  The role smoke test uses the disposable
PostgreSQL server provided by ``web/run-web-tests.sh`` and proves effective
privileges rather than trusting the grant text alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.db import schema_bound
from app.lifecycle import ingest_run
from app.lifecycle.models import Run
from app.screening.models import OrderPlanScreeningExecution
from tests.postgres import maintenance_url, requires_postgres, temporary_database


ROOT = Path(__file__).resolve().parents[4]
MIGRATE = (ROOT / "scripts/migrate.sh").read_text(encoding="utf-8")
POLICY_PATH = ROOT / "scripts/runtime-privileges.sql"
POLICY = POLICY_PATH.read_text(encoding="utf-8")


def _table_grants(role: str, privilege: str) -> set[str]:
    pattern = re.compile(
        rf"GRANT\s+{privilege}\s+ON\s+TABLE\s+([^;]*?)\s+TO\s+{role};",
        re.DOTALL,
    )
    return {
        table.removeprefix("bidops.")
        for match in pattern.finditer(POLICY)
        for table in (part.strip() for part in match.group(1).split(","))
    }


def _column_update_grant(role: str, table: str) -> set[str]:
    match = re.search(
        rf"GRANT\s+UPDATE\s*\(([^)]*)\)\s+ON\s+bidops\.{table}\s+TO\s+{role};",
        POLICY,
    )
    assert match is not None
    return {column.strip() for column in match.group(1).split(",")}


BID_DELTA_TABLES = {
    "bid_delta_comparison",
    "bid_delta_attempt",
    "bid_delta_item",
    "bid_delta_evidence",
    "bid_final_decision",
}


def test_bid_delta_runtime_grants_let_the_app_append_only_final_decisions() -> None:
    """The app reads the two queue projection tables and appends human decisions.

    ADR-0058 opens INSERT on ``bid_final_decision`` and a column-scoped
    ``UPDATE (id)`` so the decision tip can be locked with ``FOR UPDATE``; the
    append-only trigger still refuses every UPDATE and DELETE. Comparisons,
    attempts, items, and evidence keep no runtime DML, and the worker has no
    access at all. Keeping the complete five-table set here prevents a future
    broad grant from silently exposing the calculation lineage.
    """

    assert _table_grants("app", "SELECT") & BID_DELTA_TABLES == {
        "bid_delta_comparison",
        "bid_final_decision",
    }
    assert _table_grants("app", "INSERT") & BID_DELTA_TABLES == {"bid_final_decision"}
    assert {"idempotency_record", "audit_event"} <= _table_grants("app", "INSERT")
    assert _column_update_grant("app", "bid_final_decision") == {"id"}
    for role in ("app", "worker"):
        for privilege in ("UPDATE", "DELETE"):
            assert not _table_grants(role, privilege) & BID_DELTA_TABLES
        for table in sorted(BID_DELTA_TABLES):
            if (role, table) == ("app", "bid_final_decision"):
                continue
            assert (
                re.search(
                    rf"GRANT\s+UPDATE\s*\([^)]*\)\s+ON\s+bidops\.{table}\s+TO\s+{role};",
                    POLICY,
                )
                is None
            )
    for privilege in ("SELECT", "INSERT"):
        assert not _table_grants("worker", privilege) & BID_DELTA_TABLES


COLLECTION_INDEX_TABLES = {"collected_record_index", "collected_record_token"}
COMPANY_CONTEXT_TABLES = {
    "company",
    "company_opportunity_tracking",
    "company_tracking_event",
}
COMPANY_KNOWLEDGE_TABLES = {
    "knowledge_ontology_version",
    "company_knowledge_source",
    "company_knowledge_version",
    "company_knowledge_node",
    "company_knowledge_edge",
    "company_knowledge_binding",
    "company_knowledge_binding_event",
}


#: DEMO-03 company-fit enqueue/runner (worker credential) rebuilds and rechecks
#: the frozen company input, so it reads the knowledge lineage. The binding
#: event history is not needed and stays closed.
WORKER_COMPANY_KNOWLEDGE_READS = COMPANY_KNOWLEDGE_TABLES - {"company_knowledge_binding_event"}
COMPANY_FIT_POLICY_TABLES = {"company_fit_policy_version"}


def test_company_knowledge_grants_keep_lineage_append_only_and_worker_read_only() -> None:
    assert COMPANY_KNOWLEDGE_TABLES <= _table_grants("app", "SELECT")
    assert COMPANY_KNOWLEDGE_TABLES <= _table_grants("app", "INSERT")
    assert not COMPANY_KNOWLEDGE_TABLES & _table_grants("app", "UPDATE")
    assert not COMPANY_KNOWLEDGE_TABLES & _table_grants("app", "DELETE")
    assert _column_update_grant("app", "company_knowledge_binding") == {
        "graph_version_id", "profile_version_id", "revision", "updated_at", "actor"
    }
    assert COMPANY_KNOWLEDGE_TABLES & _table_grants("worker", "SELECT") == WORKER_COMPANY_KNOWLEDGE_READS
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert not COMPANY_KNOWLEDGE_TABLES & _table_grants("worker", privilege)
    for table in sorted(COMPANY_KNOWLEDGE_TABLES):
        assert (
            re.search(
                rf"GRANT\s+UPDATE\s*\([^)]*\)\s+ON\s+bidops\.{table}\s+TO\s+worker;",
                POLICY,
            )
            is None
        )


def test_company_fit_policy_and_attempt_grants_keep_insert_worker_only() -> None:
    assert COMPANY_FIT_POLICY_TABLES <= _table_grants("app", "SELECT")
    assert COMPANY_FIT_POLICY_TABLES <= _table_grants("app", "INSERT")
    assert COMPANY_FIT_POLICY_TABLES <= _table_grants("worker", "SELECT")
    assert not COMPANY_FIT_POLICY_TABLES & _table_grants("worker", "INSERT")
    for role in ("app", "worker"):
        for privilege in ("UPDATE", "DELETE"):
            assert not COMPANY_FIT_POLICY_TABLES & _table_grants(role, privilege)
    # The fit attempt INSERT stays a worker-only privilege (enqueue CLI runs as worker).
    assert "prespec_company_fit_attempt" in _table_grants("worker", "INSERT")
    assert "prespec_company_fit_attempt" not in _table_grants("app", "INSERT")
    assert "prespec_company_fit_attempt" not in _table_grants("app", "UPDATE")


def test_company_context_grants_match_registration_tracking_and_worker_reads() -> None:
    assert COMPANY_CONTEXT_TABLES <= _table_grants("app", "SELECT")
    assert COMPANY_CONTEXT_TABLES <= _table_grants("app", "INSERT")
    assert not COMPANY_CONTEXT_TABLES & _table_grants("app", "UPDATE")
    assert not COMPANY_CONTEXT_TABLES & _table_grants("app", "DELETE")
    assert _column_update_grant("app", "company_opportunity_tracking") == {
        "tracking_status",
        "reason",
        "selected_by",
        "selected_at",
        "revision",
    }
    assert _table_grants("worker", "SELECT") & COMPANY_CONTEXT_TABLES == {"company"}
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert not COMPANY_CONTEXT_TABLES & _table_grants("worker", privilege)



def test_collection_index_grants_match_the_ingest_paths() -> None:
    """수집 색인은 적재(app)가 쓰고 선별 결과 열만 갱신한다. worker는 색인만 읽는다."""

    assert COLLECTION_INDEX_TABLES <= _table_grants("app", "SELECT")
    assert COLLECTION_INDEX_TABLES <= _table_grants("app", "INSERT")
    for role in ("app", "worker"):
        assert not COLLECTION_INDEX_TABLES & _table_grants(role, "UPDATE")
        assert not COLLECTION_INDEX_TABLES & _table_grants(role, "DELETE")
    assert _column_update_grant("app", "collected_record_index") == {
        "selection_reason", "ingested_notice_id", "ingested_order_plan_id"
    }
    assert (
        re.search(
            r"GRANT\s+UPDATE\s*\([^)]*\)\s+ON\s+bidops\.collected_record_token\s+TO\s+\w+;",
            POLICY,
        )
        is None
    )
    assert _table_grants("worker", "SELECT") & COLLECTION_INDEX_TABLES == {"collected_record_index"}
    assert not COLLECTION_INDEX_TABLES & _table_grants("worker", "INSERT")
    # The loader writes the new notice projection column.
    assert "demand_agency" in _column_update_grant("app", "notice")
    assert _column_update_grant("worker", "notice") == {"id"}


def test_migrate_uses_a_separate_fail_closed_privilege_policy() -> None:
    assert "runtime-privileges.sql" in MIGRATE
    assert "SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" not in MIGRATE
    assert "SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" not in POLICY
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" not in POLICY
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA bidops REVOKE ALL" in POLICY
    default_grants = [
        line
        for line in POLICY.splitlines()
        if line.startswith("ALTER DEFAULT PRIVILEGES") and " GRANT " in line
    ]
    assert default_grants == [
        "ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON TABLES TO ro_backup;",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON SEQUENCES TO ro_backup;",
    ]


def test_sensitive_rows_are_not_in_broad_update_or_delete_groups() -> None:
    broad_mutation_section = POLICY.split(
        "-- Service-owned mutable state.", 1
    )[1].split("-- Deletes are limited", 1)[0]
    delete_section = POLICY.split("-- Deletes are limited", 1)[1].split(
        "-- Current integer identity", 1
    )[0]
    for table in (
        "notice_observation",
        "order_plan_observation",
        "profile_version",
        "profile_evidence",
        "analysis_policy_version",
        "company_profile_snapshot",
        "review",
        "judgment_revision",
        "review_revision",
        "quality_gate_review",
        "report_revision",
        "report_revision_evidence",
        "final_opinion",
        "audit_event",
        "screening_audit_event",
        "prespec_v4_pdf_snapshot",
    ):
        assert f"bidops.{table}" not in broad_mutation_section
        assert f"bidops.{table}" not in delete_section


def test_prespec_overview_run_grants_match_reviewed_runtime_paths() -> None:
    """개요 run은 두 runtime role이 읽고 쓴다. enqueue는 app, 실행은 worker다."""

    for role in ("app", "worker"):
        assert "prespec_overview_run" in _table_grants(role, "SELECT")
        assert "prespec_overview_run" in _table_grants(role, "INSERT")
        assert "prespec_overview_run" in _table_grants(role, "UPDATE")
        assert "prespec_overview_run" not in _table_grants(role, "DELETE")
    # 첨부 취득이 종결되면 worker 프로세스가 사람 경로와 같은 서비스 함수로 묶음을
    # 만들고 확정한 뒤 개요 run을 넣는다(명세 §6.2·§6.3). 그 경로의 묶음·큐·재생
    # 기록 INSERT가 함께 열려 있어야 성립하며, 어느 것도 삭제 권한을 얻지 않는다.
    auto_preparation_tables = {
        "document_bundle",
        "document_bundle_item",
        "idempotency_record",
        "work_job",
    }
    assert auto_preparation_tables <= _table_grants("worker", "INSERT")
    assert not auto_preparation_tables & _table_grants("worker", "DELETE")


def test_overview_worker_update_stays_column_scoped_for_source_rows() -> None:
    """Guard the worker grant against a future table-wide UPDATE expansion."""

    worker_updates = _table_grants("worker", "UPDATE")
    assert _column_update_grant("worker", "notice") == {"id"}
    assert _column_update_grant("worker", "attachment") == {"extract_status"}
    assert _column_update_grant("worker", "document_version") == {"is_current"}
    assert not {"notice", "attachment", "document_version"} & worker_updates
    # 자동 준비가 쓰는 묶음 열만 열린다. revision·notice_id·created_by_name 같은
    # 계보 열과 구조 상태는 worker에게 닫혀 있다.
    assert _column_update_grant("worker", "document_bundle") == {
        "issues_snapshot", "status", "version", "confirmed_by_name", "confirmed_at"
    }
    assert _column_update_grant("worker", "document_structure") == {"id"}
    assert not {"document_bundle", "document_structure"} & worker_updates
    # 제자리 갱신은 snapshot 열만 다시 쓴다. `ordinal`이 닫혀 있어야 worker가
    # 항목 순서를 바꿀 수 없다.
    item_columns = _column_update_grant("worker", "document_bundle_item")
    assert item_columns == {
        "document_version_version", "content_object_id", "content_sha256",
        "detected_mime", "size_bytes", "original_filename", "source_kind",
        "source_system", "source_attachment_key", "source_url",
        "role_at_confirmation", "effective_date_at_confirmation",
        "replaces_id_at_confirmation", "is_current_at_confirmation",
        "safety_status_at_confirmation", "structure_id_at_confirmation",
        "structure_payload_sha256",
    }
    assert "document_bundle_item" not in worker_updates
    # 준비 스냅샷은 append-only다. 어느 role도 UPDATE·DELETE를 갖지 않는다.
    for role in ("app", "worker"):
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "UPDATE")
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "DELETE")


def test_document_segment_grants_are_append_only_for_both_runtime_roles() -> None:
    """결정적 segment 저장소는 두 runtime role 모두 insert·select만 갖는다."""

    segment_tables = {
        "document_segment_manifest",
        "document_segment",
        "requirement_inventory_item",
    }
    for role in ("app", "worker"):
        assert segment_tables <= _table_grants(role, "SELECT")
        assert segment_tables <= _table_grants(role, "INSERT")
        assert not segment_tables & _table_grants(role, "UPDATE")
        assert not segment_tables & _table_grants(role, "DELETE")
        for table in sorted(segment_tables):
            assert (
                re.search(
                    rf"GRANT\s+UPDATE\s*\([^)]*\)\s+ON\s+bidops\.{table}\s+TO\s+{role};",
                    POLICY,
                )
                is None
            )


def test_c2_runtime_grants_are_role_specific_and_column_scoped() -> None:
    app_selects = _table_grants("app", "SELECT")
    app_inserts = _table_grants("app", "INSERT")
    app_deletes = _table_grants("app", "DELETE")
    worker_selects = _table_grants("worker", "SELECT")
    worker_inserts = _table_grants("worker", "INSERT")
    worker_deletes = _table_grants("worker", "DELETE")

    assert {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } <= app_selects
    assert {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } <= app_inserts
    assert not {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } & app_deletes

    assert {
        "order_plan",
        "order_plan_observation",
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_artifact",
    } <= worker_selects
    assert {
        "order_plan_screening_batch_attempt",
        "order_plan_screening_artifact",
        "order_plan_screening_result",
    } <= worker_inserts
    assert not {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_feedback",
    } & worker_inserts
    assert not {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } & worker_deletes

    assert _column_update_grant("app", "order_plan_screening_policy") == {
        "policy_status", "active_slot", "activated_at", "activated_by", "quality_gate_status"
    }
    assert _column_update_grant("app", "order_plan_screening_execution") == {
        "status", "active_slot", "partial_artifact", "candidate_count",
        "completed_count", "failure_count", "stage1_selected_count",
        "stage1_filtered_out_count", "stage1_failed_count", "stage2_relevant_count",
        "stage2_not_relevant_count", "stage2_uncertain_count", "stage2_failed_count",
        "stage2_rejected_count", "human_review_count", "error_code",
        "started_at", "finished_at",
    }
    assert _column_update_grant("worker", "order_plan_screening_batch_attempt") == {
        "attempt_status", "failure_type", "failure_code", "response_object_ref",
        "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens",
        "duration_ms", "started_at", "finished_at",
    }
    assert _column_update_grant("worker", "order_plan_screening_execution") == {
        "status", "active_slot", "partial_artifact", "candidate_count",
        "completed_count", "failure_count", "stage1_selected_count",
        "stage1_filtered_out_count", "stage1_failed_count", "stage2_relevant_count",
        "stage2_not_relevant_count", "stage2_uncertain_count", "stage2_failed_count",
        "stage2_rejected_count", "human_review_count", "error_code",
        "started_at", "finished_at", "heartbeat_at",
    }


C2_GATE_TABLES = {
    "order_plan_screening_quality_gate",
    "order_plan_screening_quality_evaluation",
    "order_plan_screening_audit_sample",
    "order_plan_screening_daily_trigger",
}


def test_c2_gate_tables_are_app_append_only_and_closed_to_the_worker() -> None:
    """0029의 4테이블은 app만 SELECT·INSERT한다. 실행 purpose는 어느 UPDATE 목록에도 없다."""

    assert C2_GATE_TABLES <= _table_grants("app", "SELECT")
    assert C2_GATE_TABLES <= _table_grants("app", "INSERT")
    for role in ("app", "worker"):
        for privilege in ("UPDATE", "DELETE"):
            assert not C2_GATE_TABLES & _table_grants(role, privilege)
        for table in sorted(C2_GATE_TABLES):
            assert (
                re.search(
                    rf"GRANT\s+UPDATE\s*\([^)]*\)\s+ON\s+bidops\.{table}\s+TO\s+{role};",
                    POLICY,
                )
                is None
            )
        assert "purpose" not in _column_update_grant(role, "order_plan_screening_execution")
    for privilege in ("SELECT", "INSERT"):
        assert not C2_GATE_TABLES & _table_grants("worker", privilege)
    assert (
        re.search(
            r"GRANT\s+UPDATE\s*\([^)]*\)\s+ON\s+bidops\.order_plan_screening_policy\s+TO\s+worker;",
            POLICY,
        )
        is None
    )


@pytest.fixture(autouse=True)
def _screening_registered(screening_extensions):
    """C-2 전용 디렉터리 인식과 적재는 screening hook이 등록돼 있을 때만 일어난다(명세 §6.2)."""


def _ensure_roles() -> None:
    url = maintenance_url()
    assert url is not None
    admin = create_engine(url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as connection:
            for role in ("app", "worker", "ro_backup"):
                exists = connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
                    {"role": role},
                )
                if exists is None:
                    connection.exec_driver_sql(f'CREATE ROLE "{role}"')
    finally:
        admin.dispose()


def _apply_policy(database_url: str):  # type: ignore[no-untyped-def]
    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        cursor = connection.connection.driver_connection.cursor()
        try:
            # Exercise the same atomic multi-statement file that psql runs.
            cursor.execute(POLICY, prepare=False)
        finally:
            cursor.close()
    return engine


def _table_privilege(connection, role: str, table: str, privilege: str) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        connection.scalar(
            text("SELECT has_table_privilege(:role, :table, :privilege)"),
            {"role": role, "table": f"bidops.{table}", "privilege": privilege},
        )
    )


def _column_privilege(
    connection, role: str, table: str, column: str, privilege: str  # type: ignore[no-untyped-def]
) -> bool:
    return bool(
        connection.scalar(
            text(
                "SELECT has_column_privilege(:role, :table, :column, :privilege)"
            ),
            {
                "role": role,
                "table": f"bidops.{table}",
                "column": column,
                "privilege": privilege,
            },
        )
    )


@requires_postgres
def test_effective_app_bid_delta_grants_and_worker_denial() -> None:
    """Apply the policy to PostgreSQL 17 and exercise the real role boundary."""

    from sqlalchemy.exc import DBAPIError

    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as connection:
                for table in BID_DELTA_TABLES:
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(connection, "worker", table, privilege)
                    assert not _table_privilege(connection, "app", table, "UPDATE")
                    assert not _table_privilege(connection, "app", table, "DELETE")
                    assert _table_privilege(connection, "app", table, "INSERT") == (
                        table == "bid_final_decision"
                    )
                    assert _table_privilege(connection, "app", table, "SELECT") == (
                        table in {"bid_delta_comparison", "bid_final_decision"}
                    )
                assert _column_privilege(connection, "app", "bid_final_decision", "id", "UPDATE")
                for column in ("decision", "reason", "basis_kind", "basis_notice_id", "comparison_id"):
                    assert not _column_privilege(
                        connection, "app", "bid_final_decision", column, "UPDATE"
                    )

            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE app")
                assert connection.scalar(text("SELECT current_user")) == "app"
                for table in ("bid_delta_comparison", "bid_final_decision"):
                    assert connection.scalar(
                        text(f"SELECT count(*) FROM bidops.{table}")
                    ) == 0

            for statement in (
                "INSERT INTO bidops.bid_delta_comparison DEFAULT VALUES",
                "UPDATE bidops.bid_delta_comparison SET id = id",
                "DELETE FROM bidops.bid_delta_comparison",
                "UPDATE bidops.bid_final_decision SET reason = reason",
                "DELETE FROM bidops.bid_final_decision",
            ):
                with pytest.raises(DBAPIError) as error:
                    with engine.begin() as connection:
                        connection.exec_driver_sql("SET LOCAL ROLE app")
                        connection.exec_driver_sql(statement)
                assert error.value.orig.sqlstate == "42501", statement
        finally:
            engine.dispose()


@requires_postgres
def test_effective_company_context_grants_are_minimal() -> None:
    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as connection:
                for table in sorted(COMPANY_CONTEXT_TABLES):
                    assert _table_privilege(connection, "app", table, "SELECT")
                    assert _table_privilege(connection, "app", table, "INSERT")
                    assert _table_privilege(connection, "ro_backup", table, "SELECT")
                    assert not _table_privilege(connection, "app", table, "DELETE")
                    assert not _table_privilege(connection, "worker", table, "INSERT")
                    assert not _table_privilege(connection, "worker", table, "UPDATE")
                    assert not _table_privilege(connection, "worker", table, "DELETE")
                assert _table_privilege(connection, "worker", "company", "SELECT")
                assert not _table_privilege(
                    connection, "worker", "company_opportunity_tracking", "SELECT"
                )
                assert not _table_privilege(
                    connection, "worker", "company_tracking_event", "SELECT"
                )
                for column in (
                    "tracking_status",
                    "reason",
                    "selected_by",
                    "selected_at",
                    "revision",
                ):
                    assert _column_privilege(
                        connection,
                        "app",
                        "company_opportunity_tracking",
                        column,
                        "UPDATE",
                    )
                for table in ("company", "company_tracking_event"):
                    assert not _table_privilege(connection, "app", table, "UPDATE")
        finally:
            engine.dispose()


@requires_postgres
def test_effective_company_knowledge_grants_are_minimal() -> None:
    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as connection:
                for table in sorted(COMPANY_KNOWLEDGE_TABLES):
                    assert _table_privilege(connection, "app", table, "SELECT")
                    assert _table_privilege(connection, "app", table, "INSERT")
                    assert _table_privilege(connection, "ro_backup", table, "SELECT")
                    assert not _table_privilege(connection, "app", table, "DELETE")
                    assert _table_privilege(connection, "worker", table, "SELECT") == (
                        table in WORKER_COMPANY_KNOWLEDGE_READS
                    )
                    for privilege in ("INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(connection, "worker", table, privilege)
                for table in sorted(COMPANY_FIT_POLICY_TABLES):
                    assert _table_privilege(connection, "app", table, "SELECT")
                    assert _table_privilege(connection, "app", table, "INSERT")
                    assert _table_privilege(connection, "worker", table, "SELECT")
                    assert _table_privilege(connection, "ro_backup", table, "SELECT")
                    for privilege in ("UPDATE", "DELETE"):
                        assert not _table_privilege(connection, "app", table, privilege)
                    for privilege in ("INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(connection, "worker", table, privilege)
                assert _table_privilege(connection, "worker", "prespec_company_fit_attempt", "INSERT")
                assert not _table_privilege(connection, "app", "prespec_company_fit_attempt", "INSERT")
                for table in ("deep_review_preview", "deep_review_approval"):
                    assert _column_privilege(connection, "app", table, "company_id", "INSERT")
                    assert _column_privilege(connection, "worker", table, "company_id", "SELECT")
                assert _column_privilege(connection, "app", "deep_review_preview", "provenance_jsonb", "INSERT")
                for table in COMPANY_KNOWLEDGE_TABLES - {"company_knowledge_binding"}:
                    assert not _table_privilege(connection, "app", table, "UPDATE")
                for column in (
                    "graph_version_id", "profile_version_id", "revision", "updated_at", "actor"
                ):
                    assert _column_privilege(
                        connection, "app", "company_knowledge_binding", column, "UPDATE"
                    )
                assert not _column_privilege(
                    connection, "app", "company_knowledge_binding", "company_id", "UPDATE"
                )
                assert not _table_privilege(
                    connection, "app", "company_knowledge_binding", "UPDATE"
                )
        finally:
            engine.dispose()


@requires_postgres
def test_effective_c2_gate_grants_deny_app_updates_and_every_worker_access() -> None:
    """정책을 PostgreSQL 17에 적용해 0029 4테이블의 실제 역할 경계를 확인한다."""

    from sqlalchemy.exc import DBAPIError

    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as connection:
                for table in sorted(C2_GATE_TABLES):
                    assert _table_privilege(connection, "app", table, "SELECT")
                    assert _table_privilege(connection, "app", table, "INSERT")
                    for privilege in ("UPDATE", "DELETE"):
                        assert not _table_privilege(connection, "app", table, privilege)
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(connection, "worker", table, privilege)
                assert _column_privilege(
                    connection, "app", "order_plan_screening_policy", "quality_gate_status", "UPDATE"
                )
                assert not _column_privilege(
                    connection, "worker", "order_plan_screening_policy", "quality_gate_status", "UPDATE"
                )
                for role in ("app", "worker"):
                    assert not _column_privilege(
                        connection, role, "order_plan_screening_execution", "purpose", "UPDATE"
                    )

            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE app")
                for table in sorted(C2_GATE_TABLES):
                    assert connection.scalar(text(f"SELECT count(*) FROM bidops.{table}")) == 0

            denied = [
                ("app", "UPDATE bidops.order_plan_screening_quality_gate SET created_by = created_by"),
                ("app", "UPDATE bidops.order_plan_screening_quality_evaluation SET evaluated_by = evaluated_by"),
                ("app", "DELETE FROM bidops.order_plan_screening_audit_sample"),
                ("app", "UPDATE bidops.order_plan_screening_daily_trigger SET enabled = enabled"),
                ("app", "UPDATE bidops.order_plan_screening_execution SET purpose = purpose"),
                ("worker", "UPDATE bidops.order_plan_screening_execution SET purpose = purpose"),
            ] + [("worker", f"SELECT 1 FROM bidops.{table}") for table in sorted(C2_GATE_TABLES)]
            for role, statement in denied:
                with pytest.raises(DBAPIError) as error:
                    with engine.begin() as connection:
                        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                        connection.exec_driver_sql(statement)
                assert error.value.orig.sqlstate == "42501", (role, statement)
        finally:
            engine.dispose()


@requires_postgres
def test_notice_final_decision_records_and_locks_with_the_app_runtime_role() -> None:
    """ADR-0058 decisions complete under the app credential, including the tip lock."""

    from uuid import UUID, uuid4

    from sqlalchemy.exc import DBAPIError

    from app.deep_review.models import BidFinalDecision
    from app.deep_review.schemas.bid_delta import BidNoticeFinalDecisionCreateRequest
    from app.deep_review.services.bid_delta import BidDeltaService
    from app.lifecycle.models import Notice, NoticeObservation, Opportunity, OpportunityLink

    _ensure_roles()
    with temporary_database() as database_url:
        policy_engine = _apply_policy(database_url)
        owner_engine = schema_bound(create_engine(database_url, future=True))
        app_engine = schema_bound(create_engine(database_url, future=True))
        try:
            observed = datetime(2026, 9, 16, 1, tzinfo=timezone.utc)
            with Session(owner_engine) as session:
                run = Run(id="privilege-final-decision", timezone="Asia/Seoul", generated_at=observed)
                opportunity = Opportunity(first_registered_stage="bid_notice")
                notice = Notice(
                    notice_key="bid:R26BK09999001:000", source_type="bid_notice",
                    bid_no="R26BK09999001", bid_ord="000", published_at=observed,
                )
                session.add_all([run, opportunity, notice])
                session.flush()
                session.add_all([
                    OpportunityLink(
                        opportunity_id=opportunity.id, notice_id=notice.id, stage="notice",
                        link_type="official", status="확정", evidence_external_no="R26BK09999001",
                    ),
                    NoticeObservation(
                        notice_id=notice.id, run_id=run.id, observed_at=observed,
                        snapshot_schema_version="fixture.v1", snapshot_jsonb={"fixture": True},
                        source_sha256="a" * 64,
                    ),
                ])
                session.commit()
                opportunity_id, notice_id = opportunity.id, notice.id

            def request(**overrides: object) -> BidNoticeFinalDecisionCreateRequest:
                values: dict[str, object] = {
                    "request_id": uuid4(), "expected_notice_id": notice_id,
                    "expected_observation_sha256": "a" * 64, "supersedes_final_decision_id": None,
                    "decision": "go", "reason": "권한 검사",
                }
                values.update(overrides)
                return BidNoticeFinalDecisionCreateRequest(**values)

            service = BidDeltaService()
            with Session(app_engine) as session:
                session.connection().exec_driver_sql("SET ROLE app")
                assert session.scalar(text("SELECT current_user")) == "app"
                first = service.record_notice_final_decision(session, opportunity_id, request(), "담당자")
                # The superseding decision locks the previous tip with SELECT ... FOR UPDATE.
                session.connection().exec_driver_sql("SET ROLE app")
                second = service.record_notice_final_decision(
                    session, opportunity_id,
                    request(decision="no_go", supersedes_final_decision_id=UUID(first["id"])),
                    "담당자",
                )
                assert (first["sequence"], second["sequence"]) == (1, 2)

            # The lock column is granted, but the append-only trigger still refuses it.
            with pytest.raises(DBAPIError) as error:
                with app_engine.begin() as connection:
                    connection.exec_driver_sql("SET LOCAL ROLE app")
                    connection.exec_driver_sql("UPDATE bidops.bid_final_decision SET id = id")
            assert error.value.orig.sqlstate == "23514"

            with Session(owner_engine) as session:
                rows = session.scalars(
                    select(BidFinalDecision).order_by(BidFinalDecision.sequence)
                ).all()
                assert [(row.basis_kind, row.decision) for row in rows] == [
                    ("notice_conditions", "go"),
                    ("notice_conditions", "no_go"),
                ]
        finally:
            app_engine.dispose()
            owner_engine.dispose()
            policy_engine.dispose()


@requires_postgres
def test_backup_reads_existing_and_future_sequences_without_mutation() -> None:
    from sqlalchemy.exc import DBAPIError

    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("CREATE SEQUENCE bidops.future_backup_probe START 41")
                sequences = conn.execute(text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='bidops' AND c.relkind='S' ORDER BY c.relname"
                )).scalars().all()
                assert "notice_id_seq" in sequences
                assert "future_backup_probe" in sequences
                for name in sequences:
                    privileges = conn.execute(text(
                        "SELECT has_sequence_privilege('ro_backup', :sequence, 'SELECT'), "
                        "has_sequence_privilege('ro_backup', :sequence, 'USAGE'), "
                        "has_sequence_privilege('ro_backup', :sequence, 'UPDATE')"
                    ), {"sequence": f"bidops.{name}"}).one()
                    assert privileges == (True, False, False)
                conn.exec_driver_sql("SET LOCAL ROLE ro_backup")
                for name in sequences:
                    assert conn.exec_driver_sql(
                        f'SELECT last_value, is_called FROM bidops."{name}"'
                    ).one() is not None
            for name in ("notice_id_seq", "future_backup_probe"):
                for operation in ("nextval(:sequence)", "setval(:sequence, 99)"):
                    with pytest.raises(DBAPIError) as error, engine.begin() as conn:
                        conn.exec_driver_sql("SET LOCAL ROLE ro_backup")
                        conn.execute(text(f"SELECT {operation}"), {"sequence": f"bidops.{name}"})
                    assert error.value.orig.sqlstate == "42501"
            with engine.begin() as conn:
                assert conn.exec_driver_sql(
                    "SELECT last_value, is_called FROM bidops.future_backup_probe"
                ).one() == (41, False)
                for role in ("app", "worker"):
                    assert conn.scalar(text(
                        "SELECT has_sequence_privilege(:role, 'bidops.future_backup_probe', 'USAGE,SELECT,UPDATE')"
                    ), {"role": role}) is False
        finally:
            engine.dispose()


@requires_postgres
def test_effective_runtime_role_matrix_and_future_defaults() -> None:
    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as connection:
                # App can create human and append-only history rows, but broad
                # mutation of those rows is absent.
                for table in (
                    "review",
                    "judgment_revision",
                    "review_revision",
                    "quality_gate_review",
                    "report_revision",
                    "final_opinion",
                    "audit_event",
                    "screening_audit_event",
                ):
                    assert _table_privilege(connection, "app", table, "INSERT")
                assert not _table_privilege(connection, "app", "review", "UPDATE")
                assert _column_privilege(
                    connection, "app", "review", "disposition", "UPDATE"
                )
                assert not _table_privilege(
                    connection, "app", "quality_gate_review", "UPDATE"
                )
                assert _column_privilege(
                    connection,
                    "app",
                    "quality_gate_review",
                    "evidence_judgment",
                    "UPDATE",
                )
                assert not _table_privilege(
                    connection, "app", "screening_policy", "UPDATE"
                )
                assert _column_privilege(
                    connection, "app", "screening_policy", "status", "UPDATE"
                )
                assert _column_privilege(
                    connection, "app", "notice", "title", "UPDATE"
                )
                # bundle confirm의 행 잠금에 필요한 최소 권한. 잠금 대상 한 열만
                # 열려 있고 구조 상태(`validation_status`)는 여전히 닫혀 있다.
                assert not _table_privilege(
                    connection, "app", "document_structure", "UPDATE"
                )
                assert _column_privilege(
                    connection, "app", "document_structure", "id", "UPDATE"
                )
                assert not _column_privilege(
                    connection, "app", "document_structure", "validation_status", "UPDATE"
                )
                for table, column in (("notice", "id"), ("attachment", "extract_status"), ("document_version", "is_current")):
                    assert _column_privilege(connection, "worker", table, column, "UPDATE")
                    assert not _table_privilege(connection, "worker", table, "UPDATE")
                for table, column in (("notice", "title"), ("attachment", "source_url"), ("document_version", "source_url")):
                    assert not _column_privilege(connection, "worker", table, column, "UPDATE")
                assert _table_privilege(connection, "app", "prespec_overview_run", "SELECT")
                assert _table_privilege(connection, "app", "prespec_overview_run", "INSERT")
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert _table_privilege(connection, "app", table, "SELECT")
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert _table_privilege(connection, "app", table, "INSERT")
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert not _table_privilege(connection, "app", table, "DELETE")
                assert _table_privilege(connection, "app", "prespec_overview_run", "UPDATE")
                assert not _table_privilege(connection, "app", "prespec_overview_run", "DELETE")
                for table in (
                    "notice_observation",
                    "judgment_revision",
                    "review_revision",
                    "profile_version",
                    "company_profile_snapshot",
                    "report_revision",
                    "final_opinion",
                    "audit_event",
                ):
                    assert not _table_privilege(connection, "app", table, "UPDATE")
                    assert not _table_privilege(connection, "app", table, "DELETE")

                # Worker writes only queue/stage/artifact results.  Its audit
                # and report history writes are append-only.
                for table in (
                    "attachment_fetch",
                    "deep_review",
                    "deep_review_attempt",
                    "deep_review_stage",
                    "work_job",
                ):
                    assert _table_privilege(connection, "worker", table, "UPDATE")
                for table in (
                    "content_object",
                    "document_structure",
                    "document_block",
                    "claim",
                    "evidence_ref",
                    "report_revision",
                    "validation_run",
                    "validation_check",
                    "audit_event",
                ):
                    assert _table_privilege(connection, "worker", table, "INSERT")
                assert not _table_privilege(
                    connection, "worker", "document_version", "UPDATE"
                )
                assert _column_privilege(
                    connection, "worker", "document_version", "is_current", "UPDATE"
                )
                assert _table_privilege(connection, "worker", "prespec_overview_run", "SELECT")
                assert _table_privilege(connection, "worker", "prespec_overview_run", "INSERT")
                for table in (
                    "order_plan",
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_artifact",
                ):
                    assert _table_privilege(connection, "worker", table, "SELECT")
                for table in (
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_artifact",
                    "order_plan_screening_result",
                ):
                    assert _table_privilege(connection, "worker", table, "INSERT")
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_feedback",
                ):
                    assert not _table_privilege(connection, "worker", table, "INSERT")
                assert not _table_privilege(
                    connection, "worker", "order_plan_screening_feedback", "SELECT"
                )
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert not _table_privilege(connection, "worker", table, "DELETE")
                assert _table_privilege(connection, "worker", "prespec_overview_run", "UPDATE")
                for table in (
                    "document_segment_manifest",
                    "document_segment",
                    "requirement_inventory_item",
                ):
                    for role in ("app", "worker"):
                        assert _table_privilege(connection, role, table, "SELECT")
                        assert _table_privilege(connection, role, table, "INSERT")
                        assert not _table_privilege(connection, role, table, "UPDATE")
                        assert not _table_privilege(connection, role, table, "DELETE")
                assert not _table_privilege(connection, "worker", "prespec_overview_run", "DELETE")
                for role in ("app", "worker"):
                    assert not _table_privilege(connection, role, "prespec_v4_pdf_snapshot", "UPDATE")
                    assert not _table_privilege(connection, role, "prespec_v4_pdf_snapshot", "DELETE")
                for table in (
                    "review",
                    "judgment_revision",
                    "review_revision",
                    "quality_gate_review",
                    "final_opinion",
                    "screening_policy",
                    "analysis_policy_version",
                    "profile_version",
                    "company_profile_snapshot",
                    "notice",
                    "notice_observation",
                ):
                    for privilege in ("INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(
                            connection, "worker", table, privilege
                        )
                for table in ("judgment", "judgment_revision", "review", "review_revision"):
                    assert _table_privilege(connection, "worker", table, "SELECT")
                for role in ("app", "worker"):
                    assert _table_privilege(connection, role, "prespec_v4_pdf_snapshot", "INSERT")
                for table in (
                    "report_revision",
                    "audit_event",
                    "screening_audit_event",
                ):
                    assert not _table_privilege(
                        connection, "worker", table, "UPDATE"
                    )
                    assert not _table_privilege(
                        connection, "worker", table, "DELETE"
                    )
                worker_deletes = connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.role_table_grants "
                        "WHERE grantee = 'worker' AND table_schema = 'bidops' "
                        "AND privilege_type = 'DELETE'"
                    )
                )
                assert worker_deletes == 0

                # Policy defaults are fail closed for runtime roles and
                # read-only for backup when a future migration adds a table.
                connection.exec_driver_sql(
                    "CREATE TABLE bidops.future_privilege_probe (id integer)"
                )
                for role in ("app", "worker"):
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(
                            connection, role, "future_privilege_probe", privilege
                        )
                assert _table_privilege(
                    connection, "ro_backup", "future_privilege_probe", "SELECT"
                )
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    assert not _table_privilege(
                        connection, "ro_backup", "future_privilege_probe", privilege
                    )
        finally:
            engine.dispose()


@requires_postgres
def test_effective_worker_auto_preparation_writes_without_deletes() -> None:
    """첨부 worker의 자동 준비 경로가 필요로 하는 쓰기만 실제로 열려 있다.

    묶음·item·큐 INSERT는 통과하고, 어느 것도 DELETE를 얻지 않으며, 묶음 UPDATE는
    확정에 쓰는 열에서만 성립한다.
    """

    from sqlalchemy.exc import DBAPIError

    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as connection:
                for table in ("document_bundle", "document_bundle_item", "work_job"):
                    assert _table_privilege(connection, "worker", table, "SELECT")
                    assert _table_privilege(connection, "worker", table, "INSERT")
                    assert not _table_privilege(connection, "worker", table, "DELETE")
                assert _table_privilege(connection, "worker", "idempotency_record", "INSERT")
                assert not _table_privilege(
                    connection, "worker", "idempotency_record", "DELETE"
                )
                assert not _table_privilege(connection, "worker", "document_bundle", "UPDATE")
                for column in (
                    "issues_snapshot",
                    "status",
                    "version",
                    "confirmed_by_name",
                    "confirmed_at",
                ):
                    assert _column_privilege(
                        connection, "worker", "document_bundle", column, "UPDATE"
                    )
                for column in ("revision", "notice_id", "created_by_name"):
                    assert not _column_privilege(
                        connection, "worker", "document_bundle", column, "UPDATE"
                    )
                assert not _table_privilege(
                    connection, "worker", "document_bundle_item", "UPDATE"
                )
                # 제자리 갱신이 다시 쓰는 snapshot 열만 열려 있고 순서 열은 닫혀 있다.
                for column in ("structure_id_at_confirmation", "content_sha256"):
                    assert _column_privilege(
                        connection, "worker", "document_bundle_item", column, "UPDATE"
                    )
                assert not _column_privilege(
                    connection, "worker", "document_bundle_item", "ordinal", "UPDATE"
                )
                # 구조 행은 잠금 대상일 뿐이다. 상태 열은 그대로 닫혀 있다.
                assert _column_privilege(
                    connection, "worker", "document_structure", "id", "UPDATE"
                )
                assert not _column_privilege(
                    connection, "worker", "document_structure", "validation_status", "UPDATE"
                )
            for table in ("document_bundle", "document_bundle_item", "work_job"):
                with pytest.raises(DBAPIError) as error:
                    with engine.begin() as connection:
                        connection.exec_driver_sql("SET LOCAL ROLE worker")
                        connection.exec_driver_sql(f"DELETE FROM bidops.{table}")
                assert error.value.orig.sqlstate == "42501"
        finally:
            engine.dispose()


@requires_postgres
def test_c2_ingest_completes_with_the_app_runtime_role(tmp_path) -> None:
    """The credential used by the ingest path can append the complete C-2 set."""

    from tests.c2_fixtures import write_c2_fixture as _write_c2_fixture

    _ensure_roles()
    with temporary_database() as database_url:
        owner_engine = schema_bound(create_engine(database_url, future=True))
        policy_engine = _apply_policy(database_url)
        try:
            run_dir, source_run_id = _write_c2_fixture(tmp_path)
            with Session(owner_engine) as session:
                session.add(
                    Run(
                        id=source_run_id,
                        timezone="Asia/Seoul",
                        generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    )
                )
                session.commit()

            app_engine = schema_bound(create_engine(database_url, future=True))
            try:
                with Session(app_engine) as session:
                    session.connection().exec_driver_sql("SET ROLE app")
                    result = ingest_run(run_dir, session)
                assert result.screening_executions == 1
                assert result.screening_attempts == 1
                assert result.screening_results == 1
                assert result.screening_artifacts == 6
            finally:
                app_engine.dispose()

            with Session(owner_engine) as session:
                assert session.scalar(
                    select(func.count()).select_from(OrderPlanScreeningExecution)
                ) == 1
        finally:
            policy_engine.dispose()
            owner_engine.dispose()


def _write_collection_run(root: Path) -> Path:
    """A minimal collected run: one plan, one SW pre-spec, a 1468 bid, an index-only bid."""

    run_dir = root / "runs" / "lifecycle-20260916-notices"
    run_dir.mkdir(parents=True)
    window = {"from": "2026-09-14", "to": "2026-09-16", "timezone": "Asia/Seoul"}
    generated_at = "2026-09-16T00:00:00+00:00"
    qualification = dict.fromkeys((
        "participation_limited", "industry_limited", "information_business", "general_service",
        "service_division", "joint_contract_method", "performance_restricted_competition",
        "pq_evaluation", "technical_evaluation", "technical_evaluation_rate", "successful_bid_method",
    ))

    def notice(notice_id: str, source_type: str, **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "notice_id": notice_id, "source_type": source_type, "title": "권한 검사 사업",
            "agency": "기관", "demand_agency": None, "published_at": "2026-09-15T10:00:00+09:00",
            "deadline_at": None, "budget": None, "estimated_price": None, "method": None, "url": None,
            "procurement_class": {"large": None, "middle": None, "detail": None, "code": None},
            "region_limit": {"basis": None, "joint_contract_regions": [], "joint_contract_rate": None, "regional_joint_contract_limit": None},
            "lifecycle": {"pre_spec_no": None, "re_notice": None, "changed_at": None, "change_reason": None, "unified_notice_no": None, "previous_failed_notice_no": None, "opening_at": None},
            "attachments": [], "qualification_flags": {**qualification, "sw_industry_1468": None},
            "focus_matches": [], "performance_matches": [], "performance_top_score": None,
            "candidate_sources": [], "collection_bucket": "audit_pool", "unknown_fields": [],
            "raw_source": "raw/page-001.json",
        }
        record.update(overrides)
        return record

    notices = [
        notice(
            "pre:R26BD00279001", "pre_spec", demand_agency="수요기관",
            lifecycle={"pre_spec_no": "R26BD00279001", "re_notice": None, "changed_at": None, "change_reason": None, "unified_notice_no": None, "previous_failed_notice_no": None, "opening_at": None, "bid_ntice_no_list": "R26BK01699001"},
            qualification_flags={**qualification, "sw_business_status": "Y", "business_division": "일반용역", "sw_industry_1468": None},
        ),
        notice(
            "bid:R26BK01699001:000", "bid_notice", method="일반경쟁",
            lifecycle={"pre_spec_no": "R26BD00279001", "order_plan_no": None, "re_notice": "N", "changed_at": None, "change_reason": None, "unified_notice_no": None, "previous_failed_notice_no": None, "opening_at": "2026-09-26T11:00:00+09:00"},
            qualification_flags={**qualification, "sw_industry_1468": "Y"},
        ),
        notice(
            "bid:R26BK01699002:000", "bid_notice", method="일반경쟁",
            lifecycle={"pre_spec_no": None, "order_plan_no": "R26DD20859001", "re_notice": "N", "changed_at": None, "change_reason": None, "unified_notice_no": None, "previous_failed_notice_no": None, "opening_at": None},
            qualification_flags={**qualification, "sw_industry_1468": "N"},
        ),
    ]
    (run_dir / "collected-notices.json").write_text(json.dumps({
        "schema_version": "bidops.collected.v2", "generated_at": generated_at,
        "source_window": window, "counts": {"total": 3}, "warnings": [],
        "metadata": {"sw_industry_1468": {"status": "complete", "total": 1, "pages": 1}},
        "notices": notices,
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "collected-order-plans.json").write_text(json.dumps({
        "schema_version": "bidops.collected-order-plans.v1", "generated_at": generated_at,
        "source_window": window, "counts": {"total": 1},
        "order_plans": [{
            "order_plan_unty_no": "R26DD20859001", "title": "권한 검사 발주계획",
            "agency_name": "기관", "published_at": "2026-09-10T09:00:00+09:00",
            "bid_ntice_no_list": "R26BK01699002000", "source_sha256": "b" * 64,
            "raw_source": "raw/page-00001.json",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    return run_dir


@requires_postgres
def test_collection_ingest_and_tracked_backfill_complete_with_the_app_runtime_role(tmp_path) -> None:
    """The ingest credential can index, select, and backfill; worker only reads the index."""

    from app.lifecycle.ingest.loader import tracked_backfill
    from app.lifecycle.models import (
        CollectedRecordIndex,
        Opportunity,
        OpportunityLink,
        OrderPlan,
    )
    from app.lifecycle.services.opportunity_tracking import set_tracking_status

    _ensure_roles()
    with temporary_database() as database_url:
        policy_engine = _apply_policy(database_url)
        app_engine = schema_bound(create_engine(database_url, future=True))
        try:
            with policy_engine.begin() as connection:
                for table in sorted(COLLECTION_INDEX_TABLES):
                    assert _table_privilege(connection, "app", table, "SELECT")
                    assert _table_privilege(connection, "app", table, "INSERT")
                    assert not _table_privilege(connection, "app", table, "UPDATE")
                    assert not _table_privilege(connection, "app", table, "DELETE")
                    for privilege in ("INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(connection, "worker", table, privilege)
                assert _table_privilege(connection, "worker", "collected_record_index", "SELECT")
                assert not _table_privilege(connection, "worker", "collected_record_token", "SELECT")
                assert _column_privilege(connection, "app", "collected_record_index", "selection_reason", "UPDATE")
                assert not _column_privilege(connection, "app", "collected_record_index", "record_key", "UPDATE")
                assert _column_privilege(connection, "app", "notice", "demand_agency", "UPDATE")
                assert _column_privilege(connection, "app", "opportunity_link", "search_target_kind", "UPDATE")

            run_dir = _write_collection_run(tmp_path)
            with Session(app_engine) as session:
                session.connection().exec_driver_sql("SET ROLE app")
                result = ingest_run(run_dir, session, selection="collection")
                assert result.selection["pre_spec"]["selected"]["pre_spec_sw"] == 1
                assert result.selection["bid_notice"]["selected"]["bid_sw_prespec_reference"] == 1
                assert result.selection["bid_notice"]["skipped"] == 1

                session.connection().exec_driver_sql("SET ROLE app")
                opportunity = session.scalars(
                    select(Opportunity)
                    .join(OpportunityLink, OpportunityLink.opportunity_id == Opportunity.id)
                    .join(OrderPlan, OrderPlan.id == OpportunityLink.order_plan_id)
                ).one()
                set_tracking_status(
                    session,
                    opportunity,
                    status="계속 추적",
                    reason="권한 검사",
                    selected_by="담당자",
                    selected_at=datetime(2026, 9, 16, 1, tzinfo=timezone.utc),
                )
                backfill = tracked_backfill(session, runs_root=run_dir.parent)
                session.commit()
                assert backfill["loaded"] == {"tracked_backfill": 1}

                session.connection().exec_driver_sql("SET ROLE app")
                assert set(
                    session.scalars(
                        select(CollectedRecordIndex.selection_reason).where(
                            CollectedRecordIndex.record_kind == "bid_notice"
                        )
                    )
                ) == {"bid_sw_prespec_reference", "tracked_backfill"}
        finally:
            app_engine.dispose()
            policy_engine.dispose()


def test_company_fit_runtime_privileges():
    assert "prespec_company_fit_attempt" in _table_grants("app", "SELECT")
    assert "prespec_company_fit_attempt" not in _table_grants("app", "INSERT")
    assert "prespec_company_fit_attempt" in _table_grants("worker", "SELECT")
    assert "prespec_company_fit_attempt" in _table_grants("worker", "INSERT")
    for role in ("app", "worker"):
        assert "prespec_company_fit_attempt" not in _table_grants(role, "UPDATE")
        assert "prespec_company_fit_attempt" not in _table_grants(role, "DELETE")


def test_v4_snapshot_runtime_privileges():
    assert "prespec_v4_pdf_snapshot" in _table_grants("app", "SELECT")
    assert "prespec_v4_pdf_snapshot" in _table_grants("worker", "SELECT")
    assert "prespec_v4_pdf_snapshot" in _table_grants("app", "INSERT")
    assert "prespec_v4_pdf_snapshot" in _table_grants("worker", "INSERT")
    for role in ("app", "worker"):
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "UPDATE")
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "DELETE")


@requires_postgres
def test_luna_consent_runtime_privileges():
    _ensure_roles()
    with temporary_database() as url:
        engine = _apply_policy(url)
        try:
            with engine.connect() as connection:
                for table in ('deep_review_preview', 'deep_review_approval'):
                    for role in ('app', 'worker'):
                        assert _table_privilege(connection,role,table,'SELECT')
                        assert _table_privilege(connection,role,table,'INSERT') == (role == 'app')
                        assert not _table_privilege(connection,role,table,'UPDATE')
                        assert not _table_privilege(connection,role,table,'DELETE')
        finally:
            engine.dispose()


@requires_postgres
def test_assumption_analysis_runtime_privileges():
    _ensure_roles()
    with temporary_database() as url:
        engine = _apply_policy(url)
        try:
            with engine.connect() as connection:
                for table in ('assumption_input_version', 'assumption_run', 'assumption_stage'):
                    for role in ('app', 'worker'):
                        assert _table_privilege(connection, role, table, 'SELECT')
                        assert _table_privilege(connection, role, table, 'INSERT') == ((role == 'worker') == (table == 'assumption_stage'))
                        assert not _table_privilege(connection, role, table, 'UPDATE')
                        assert not _table_privilege(connection, role, table, 'DELETE')
        finally:
            engine.dispose()
