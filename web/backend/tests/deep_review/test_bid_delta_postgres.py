"""PostgreSQL 17 migration and trigger checks for R-08."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database


pytestmark = requires_postgres
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _tables(engine):
    with engine.connect() as connection:
        return set(
            connection.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'bidops'"
                )
            )
        )


def _seed_scope(engine, label: str):
    baseline = {"source": _hash(f"{label}:baseline:source"), "payload": _hash(f"{label}:baseline:payload")}
    comparison = {"source": _hash(f"{label}:comparison:source"), "payload": _hash(f"{label}:comparison:payload")}
    ids = {name: uuid4() for name in ("baseline_content", "comparison_content", "baseline_doc", "comparison_doc", "baseline_structure", "comparison_structure", "baseline_bundle", "comparison_bundle")}
    with engine.begin() as connection:
        opportunity_id = connection.scalar(
            text(
                "INSERT INTO bidops.opportunity (first_registered_stage) "
                "VALUES ('pre_spec') RETURNING id"
            )
        )
        baseline_notice_id = connection.scalar(
            text(
                "INSERT INTO bidops.notice (notice_key, source_type) "
                "VALUES (:key, 'pre_spec') RETURNING id"
            ),
            {"key": f"bid-delta-pg:{label}:baseline:{uuid4()}"},
        )
        comparison_notice_id = connection.scalar(
            text(
                "INSERT INTO bidops.notice (notice_key, source_type) "
                "VALUES (:key, 'bid_notice') RETURNING id"
            ),
            {"key": f"bid-delta-pg:{label}:comparison:{uuid4()}"},
        )
        baseline_link_id = connection.scalar(
            text(
                "INSERT INTO bidops.opportunity_link "
                "(opportunity_id, notice_id, stage, link_type, status, evidence_external_no) "
                "VALUES (:opportunity_id, :notice_id, 'notice', 'official', '확정', :evidence) "
                "RETURNING id"
            ),
            {"opportunity_id": opportunity_id, "notice_id": baseline_notice_id, "evidence": f"baseline-{label}"},
        )
        comparison_link_id = connection.scalar(
            text(
                "INSERT INTO bidops.opportunity_link "
                "(opportunity_id, notice_id, stage, link_type, status, evidence_external_no) "
                "VALUES (:opportunity_id, :notice_id, 'notice', 'official', '확정', :evidence) "
                "RETURNING id"
            ),
            {"opportunity_id": opportunity_id, "notice_id": comparison_notice_id, "evidence": f"comparison-{label}"},
        )
        for side, content_id, values in (
            ("baseline", ids["baseline_content"], baseline),
            ("comparison", ids["comparison_content"], comparison),
        ):
            connection.execute(
                text(
                    "INSERT INTO bidops.content_object "
                    "(id, sha256, size_bytes, detected_mime, retention_class, created_at) "
                    "VALUES (:id, :sha256, 1, 'application/pdf', 'document-source', :created_at)"
                ),
                {"id": content_id, "sha256": values["source"], "created_at": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.document_version "
                    "(id, notice_id, content_object_id, version, source_kind, "
                    "original_filename, role, is_current, safety_status, needs_human_review, created_at) "
                    "VALUES (:id, :notice_id, :content_id, 1, 'manual', :filename, :role, "
                    "true, 'safe', false, :created_at)"
                ),
                {
                    "id": ids[f"{side}_doc"],
                    "notice_id": baseline_notice_id if side == "baseline" else comparison_notice_id,
                    "content_id": content_id,
                    "filename": f"{side}.pdf",
                    "role": "제안요청서" if side == "baseline" else "공고",
                    "created_at": NOW,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.document_structure "
                    "(id, document_version_id, source_sha256, media_type, extractor_name, "
                    "extractor_version, payload_content_object_id, payload_sha256, page_count, "
                    "block_count, validation_status, created_at) "
                    "VALUES (:id, :document_id, :source_sha256, 'application/pdf', 'test', '1', "
                    ":content_id, :payload_sha256, 1, 1, 'ready', :created_at)"
                ),
                {
                    "id": ids[f"{side}_structure"],
                    "document_id": ids[f"{side}_doc"],
                    "source_sha256": values["source"],
                    "content_id": content_id,
                    "payload_sha256": values["payload"],
                    "created_at": NOW,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.document_bundle "
                    "(id, notice_id, revision, version, status, issues_snapshot, created_at) "
                    "VALUES (:id, :notice_id, 1, 1, 'ready', '[]'::jsonb, :created_at)"
                ),
                {
                    "id": ids[f"{side}_bundle"],
                    "notice_id": baseline_notice_id if side == "baseline" else comparison_notice_id,
                    "created_at": NOW,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.document_bundle_item "
                    "(bundle_id, document_version_id, ordinal, document_version_version, "
                    "content_object_id, content_sha256, detected_mime, size_bytes, original_filename, "
                    "source_kind, role_at_confirmation, is_current_at_confirmation, "
                    "safety_status_at_confirmation, structure_id_at_confirmation, structure_payload_sha256) "
                    "VALUES (:bundle_id, :document_id, 1, 1, :content_id, :content_sha256, "
                    "'application/pdf', 1, :filename, 'manual', :role, true, 'safe', "
                    ":structure_id, :payload_sha256)"
                ),
                {
                    "bundle_id": ids[f"{side}_bundle"],
                    "document_id": ids[f"{side}_doc"],
                    "content_id": content_id,
                    "content_sha256": values["source"],
                    "filename": f"{side}.pdf",
                    "role": "제안요청서" if side == "baseline" else "공고",
                    "structure_id": ids[f"{side}_structure"],
                    "payload_sha256": values["payload"],
                },
            )

        comparison_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO bidops.bid_delta_comparison "
                "(id, opportunity_id, sequence, category_policy_version, "
                "baseline_link_id, baseline_notice_id, baseline_bundle_id, baseline_bundle_revision, baseline_bundle_version, "
                "baseline_document_version_id, baseline_document_version_version, baseline_structure_id, baseline_source_sha256, baseline_structure_payload_sha256, "
                "comparison_link_id, comparison_notice_id, comparison_bundle_id, comparison_bundle_revision, comparison_bundle_version, "
                "comparison_document_version_id, comparison_document_version_version, comparison_structure_id, comparison_source_sha256, comparison_structure_payload_sha256, "
                "calculation_status, materiality, created_by_name, created_at) "
                "VALUES (:id, :opportunity_id, 1, :policy, :baseline_link, :baseline_notice, :baseline_bundle, 1, 1, "
                ":baseline_doc, 1, :baseline_structure, :baseline_source, :baseline_payload, :comparison_link, :comparison_notice, "
                ":comparison_bundle, 1, 1, :comparison_doc, 1, :comparison_structure, :comparison_source, :comparison_payload, "
                "'pending', 'unknown', 'pg-tester', :created_at)"
            ),
            {
                "id": comparison_id,
                "opportunity_id": opportunity_id,
                "policy": f"policy-{label}",
                "baseline_link": baseline_link_id,
                "baseline_notice": baseline_notice_id,
                "baseline_bundle": ids["baseline_bundle"],
                "baseline_doc": ids["baseline_doc"],
                "baseline_structure": ids["baseline_structure"],
                "baseline_source": baseline["source"],
                "baseline_payload": baseline["payload"],
                "comparison_link": comparison_link_id,
                "comparison_notice": comparison_notice_id,
                "comparison_bundle": ids["comparison_bundle"],
                "comparison_doc": ids["comparison_doc"],
                "comparison_structure": ids["comparison_structure"],
                "comparison_source": comparison["source"],
                "comparison_payload": comparison["payload"],
                "created_at": NOW,
            },
        )
    return {
        "opportunity_id": opportunity_id,
        "baseline_notice_id": baseline_notice_id,
        "comparison_notice_id": comparison_notice_id,
        "baseline_link_id": baseline_link_id,
        "comparison_link_id": comparison_link_id,
        "baseline_bundle_id": ids["baseline_bundle"],
        "comparison_bundle_id": ids["comparison_bundle"],
        "baseline_doc": ids["baseline_doc"],
        "comparison_doc": ids["comparison_doc"],
        "baseline_structure": ids["baseline_structure"],
        "comparison_structure": ids["comparison_structure"],
        "comparison_id": comparison_id,
        "baseline_source": baseline["source"],
        "comparison_source": comparison["source"],
    }


def test_empty_database_upgrade_creates_all_bid_delta_tables():
    with migrated_engine() as engine:
        assert {
            "bid_delta_comparison",
            "bid_delta_attempt",
            "bid_delta_item",
            "bid_delta_evidence",
            "bid_final_decision",
        } <= _tables(engine)


def test_0014_to_0015_and_back_to_0014():
    with temporary_database(upgrade_to="0014_prespec_overview_attempt_result") as database_url:
        engine = create_engine(database_url, future=True)
        assert not {
            "bid_delta_comparison",
            "bid_delta_attempt",
            "bid_delta_item",
            "bid_delta_evidence",
            "bid_final_decision",
        } & _tables(engine)
        upgraded = run_alembic(database_url, "upgrade", "0015_bid_delta_final_decision")
        assert upgraded.returncode == 0, upgraded.stderr
        assert "bid_delta_comparison" in _tables(engine)
        downgraded = run_alembic(database_url, "downgrade", "0014_prespec_overview_attempt_result")
        assert downgraded.returncode == 0, downgraded.stderr
        assert not {
            "bid_delta_comparison",
            "bid_delta_attempt",
            "bid_delta_item",
            "bid_delta_evidence",
            "bid_final_decision",
        } & _tables(engine)
        engine.dispose()


def test_postgres_append_only_triggers_cover_final_item_and_evidence():
    with migrated_engine() as engine:
        scope = _seed_scope(engine, "append-only")
        attempt_id = uuid4()
        item_id = uuid4()
        evidence_id = uuid4()
        decision_id = uuid4()
        request_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.bid_delta_attempt "
                    "(id, comparison_id, sequence, status, created_at) "
                    "VALUES (:id, :comparison_id, 1, 'queued', :created_at)"
                ),
                {"id": attempt_id, "comparison_id": scope["comparison_id"], "created_at": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.bid_delta_item "
                    "(id, comparison_id, attempt_id, category, ordinal, result_status, materiality, created_at) "
                    "VALUES (:id, :comparison_id, :attempt_id, 'eligibility', 1, 'changed', 'material', :created_at)"
                ),
                {"id": item_id, "comparison_id": scope["comparison_id"], "attempt_id": attempt_id, "created_at": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.bid_delta_evidence "
                    "(id, item_id, side, ordinal, document_version_id, structure_id, source_sha256, locator, locator_type, verification_status, created_at) "
                    "VALUES (:id, :item_id, 'baseline', 1, :document_id, :structure_id, :source_sha256, CAST(:locator AS jsonb), 'page', 'verified', :created_at)"
                ),
                {"id": evidence_id, "item_id": item_id, "document_id": scope["baseline_doc"], "structure_id": scope["baseline_structure"], "source_sha256": scope["baseline_source"], "locator": '{"page": 1}', "created_at": NOW},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.bid_final_decision "
                    "(id, opportunity_id, sequence, basis_kind, comparison_id, comparison_version, result_sha256, baseline_document_version_id, comparison_document_version_id, decision, reason, claimed_name, request_id, created_at) "
                    "VALUES (:id, :opportunity_id, 1, 'comparison', :comparison_id, 1, :result_sha256, :baseline_doc, :comparison_doc, 'go', 'reason', 'actor', :request_id, :created_at)"
                ),
                {"id": decision_id, "opportunity_id": scope["opportunity_id"], "comparison_id": scope["comparison_id"], "result_sha256": "a" * 64, "baseline_doc": scope["baseline_doc"], "comparison_doc": scope["comparison_doc"], "request_id": request_id, "created_at": NOW},
            )
        for statement, params in (
            ("UPDATE bidops.bid_final_decision SET reason = 'changed' WHERE id = :id", {"id": decision_id}),
            ("DELETE FROM bidops.bid_final_decision WHERE id = :id", {"id": decision_id}),
            ("UPDATE bidops.bid_delta_item SET summary = 'changed' WHERE id = :id", {"id": item_id}),
            ("DELETE FROM bidops.bid_delta_item WHERE id = :id", {"id": item_id}),
            ("UPDATE bidops.bid_delta_evidence SET quote = 'changed' WHERE id = :id", {"id": evidence_id}),
            ("DELETE FROM bidops.bid_delta_evidence WHERE id = :id", {"id": evidence_id}),
        ):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text(statement), params)


def test_postgres_comparison_fence_and_failed_to_pending_transition():
    with migrated_engine() as engine:
        scope = _seed_scope(engine, "comparison-fence")
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.bid_delta_comparison SET baseline_bundle_version = 2 "
                        "WHERE id = :id"
                    ),
                    {"id": scope["comparison_id"]},
                )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE bidops.bid_delta_comparison SET calculation_status = 'failed', "
                    "result_status = 'failed', materiality = 'unknown', completed_at = :completed_at, "
                    "last_error_code = 'failed' WHERE id = :id"
                ),
                {"id": scope["comparison_id"], "completed_at": NOW},
            )
            connection.execute(
                text(
                    "UPDATE bidops.bid_delta_comparison SET calculation_status = 'pending', "
                    "result_status = NULL, completed_at = NULL, last_error_code = NULL WHERE id = :id"
                ),
                {"id": scope["comparison_id"]},
            )


def test_postgres_composite_scope_and_active_attempt_constraints():
    with migrated_engine() as engine:
        scope = _seed_scope(engine, "scope")
        other = _seed_scope(engine, "other")
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.bid_delta_comparison "
                        "(id, opportunity_id, sequence, category_policy_version, baseline_link_id, baseline_notice_id, baseline_bundle_id, baseline_bundle_revision, baseline_bundle_version, baseline_document_version_id, baseline_document_version_version, baseline_structure_id, baseline_source_sha256, baseline_structure_payload_sha256, comparison_link_id, comparison_notice_id, comparison_bundle_id, comparison_bundle_revision, comparison_bundle_version, comparison_document_version_id, comparison_document_version_version, comparison_structure_id, comparison_source_sha256, comparison_structure_payload_sha256, calculation_status, materiality, created_by_name, created_at) "
                        "SELECT :id, :opportunity_id, 2, 'cross-scope-policy', :other_link, baseline_notice_id, baseline_bundle_id, baseline_bundle_revision, baseline_bundle_version, baseline_document_version_id, baseline_document_version_version, baseline_structure_id, baseline_source_sha256, baseline_structure_payload_sha256, comparison_link_id, comparison_notice_id, comparison_bundle_id, comparison_bundle_revision, comparison_bundle_version, comparison_document_version_id, comparison_document_version_version, comparison_structure_id, comparison_source_sha256, comparison_structure_payload_sha256, 'pending', 'unknown', 'tester', :created_at FROM bidops.bid_delta_comparison WHERE id = :source_id"
                    ),
                    {"id": uuid4(), "opportunity_id": scope["opportunity_id"], "other_link": other["baseline_link_id"], "source_id": scope["comparison_id"], "created_at": NOW},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.bid_delta_comparison "
                        "(id, opportunity_id, sequence, category_policy_version, baseline_link_id, baseline_notice_id, baseline_bundle_id, baseline_bundle_revision, baseline_bundle_version, baseline_document_version_id, baseline_document_version_version, baseline_structure_id, baseline_source_sha256, baseline_structure_payload_sha256, comparison_link_id, comparison_notice_id, comparison_bundle_id, comparison_bundle_revision, comparison_bundle_version, comparison_document_version_id, comparison_document_version_version, comparison_structure_id, comparison_source_sha256, comparison_structure_payload_sha256, calculation_status, materiality, created_by_name, created_at) "
                        "SELECT :id, :opportunity_id, 3, 'cross-bundle-policy', baseline_link_id, baseline_notice_id, :other_bundle, baseline_bundle_revision, baseline_bundle_version, baseline_document_version_id, baseline_document_version_version, baseline_structure_id, baseline_source_sha256, baseline_structure_payload_sha256, comparison_link_id, comparison_notice_id, comparison_bundle_id, comparison_bundle_revision, comparison_bundle_version, comparison_document_version_id, comparison_document_version_version, comparison_structure_id, comparison_source_sha256, comparison_structure_payload_sha256, 'pending', 'unknown', 'tester', :created_at FROM bidops.bid_delta_comparison WHERE id = :source_id"
                    ),
                    {"id": uuid4(), "opportunity_id": scope["opportunity_id"], "other_bundle": other["baseline_bundle_id"], "source_id": scope["comparison_id"], "created_at": NOW},
                )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.bid_delta_attempt (id, comparison_id, sequence, status, created_at) "
                    "VALUES (:id, :comparison_id, 1, 'queued', :created_at)"
                ),
                {"id": uuid4(), "comparison_id": scope["comparison_id"], "created_at": NOW},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.bid_delta_attempt (id, comparison_id, sequence, status, created_at) "
                        "VALUES (:id, :comparison_id, 2, 'running', :created_at)"
                    ),
                    {"id": uuid4(), "comparison_id": scope["comparison_id"], "created_at": NOW},
                )


_DECISION_INSERT = (
    "INSERT INTO bidops.bid_final_decision "
    "(id, opportunity_id, sequence, {basis_columns}decision, reason, claimed_name, request_id, created_at) "
    "VALUES (:id, :opportunity_id, :sequence, {basis_values}'go', 'reason', 'actor', :request_id, :created_at)"
)
_COMPARISON_BASIS = (
    "comparison_id, comparison_version, result_sha256, baseline_document_version_id, comparison_document_version_id, ",
    ":comparison_id, 1, :result_sha256, :baseline_doc, :comparison_doc, ",
)


def _insert_decision(connection, scope, sequence, columns="", values="", **extra):
    connection.execute(
        text(_DECISION_INSERT.format(basis_columns=columns, basis_values=values)),
        {
            "id": uuid4(),
            "opportunity_id": scope["opportunity_id"],
            "sequence": sequence,
            "comparison_id": scope["comparison_id"],
            "result_sha256": "a" * 64,
            "baseline_doc": scope["baseline_doc"],
            "comparison_doc": scope["comparison_doc"],
            "notice_id": scope["comparison_notice_id"],
            "hash": "b" * 64,
            "request_id": uuid4(),
            "created_at": NOW,
            **extra,
        },
    )


def _column_facts(engine, column):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'bidops' AND table_name = 'bid_final_decision' "
                "AND column_name = :column"
            ),
            {"column": column},
        ).one()


def test_postgres_final_decision_basis_checks_both_ways():
    """ADR-0058: the database rejects partial or mixed decision bases."""

    with migrated_engine() as engine:
        scope = _seed_scope(engine, "basis-check")
        comparison_columns = ("basis_kind, " + _COMPARISON_BASIS[0], "'comparison', " + _COMPARISON_BASIS[1])
        notice_columns = (
            "basis_kind, basis_notice_id, basis_observation_sha256, ",
            "'notice_conditions', :notice_id, :hash, ",
        )
        with engine.begin() as connection:
            _insert_decision(connection, scope, 1, *notice_columns)
            _insert_decision(connection, scope, 2, *comparison_columns)
        rejected = (
            # basis_kind has no default: a new row must state its basis.
            _COMPARISON_BASIS,
            (notice_columns[0] + _COMPARISON_BASIS[0], notice_columns[1] + _COMPARISON_BASIS[1]),
            ("basis_kind, basis_observation_sha256, ", "'notice_conditions', :hash, "),
            (notice_columns[0], notice_columns[1].replace(":hash", "'" + "B" * 64 + "'")),
            (comparison_columns[0] + "basis_notice_id, ", comparison_columns[1] + ":notice_id, "),
            ("basis_kind, comparison_id, comparison_version, ", "'comparison', :comparison_id, 1, "),
            ("basis_kind, " + _COMPARISON_BASIS[0], "'manual', " + _COMPARISON_BASIS[1]),
        )
        for columns, values in rejected:
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    _insert_decision(connection, scope, 3, columns, values)
        assert _column_facts(engine, "basis_kind") == ("NO", None)
        assert _column_facts(engine, "comparison_id") == ("YES", None)


def test_0027_comparison_decisions_backfill_round_trip_and_guard_notice_basis():
    with temporary_database(upgrade_to="0027_collection_index_and_linkage") as database_url:
        engine = create_engine(database_url, future=True)
        try:
            scope = _seed_scope(engine, "basis-upgrade")
            with engine.begin() as connection:
                _insert_decision(connection, scope, 1, *_COMPARISON_BASIS)

            upgraded = run_alembic(database_url, "upgrade", "0028_final_decision_basis")
            assert upgraded.returncode == 0, upgraded.stderr
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT basis_kind FROM bidops.bid_final_decision")) == "comparison"
            assert _column_facts(engine, "basis_kind") == ("NO", None)

            downgraded = run_alembic(database_url, "downgrade", "0027_collection_index_and_linkage")
            assert downgraded.returncode == 0, downgraded.stderr
            assert _column_facts(engine, "comparison_id") == ("NO", None)
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT count(*) FROM bidops.bid_final_decision")) == 1

            assert run_alembic(database_url, "upgrade", "0028_final_decision_basis").returncode == 0
            with engine.begin() as connection:
                _insert_decision(
                    connection,
                    scope,
                    2,
                    "basis_kind, basis_notice_id, basis_observation_sha256, ",
                    "'notice_conditions', :notice_id, :hash, ",
                )
            refused = run_alembic(database_url, "downgrade", "0027_collection_index_and_linkage")
            assert refused.returncode != 0
            assert "notice_conditions" in refused.stdout + refused.stderr
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT version_num FROM bidops.alembic_version")) == (
                    "0028_final_decision_basis"
                )
                assert connection.scalar(text("SELECT count(*) FROM bidops.bid_final_decision")) == 2
        finally:
            engine.dispose()
