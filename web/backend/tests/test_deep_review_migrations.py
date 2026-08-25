"""Synthetic contract tests for the PostgreSQL cutover boundary."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.db import Base, schema_bound
from app.migrations import import_sqlite
from app.migrations.import_sqlite import ImportContractError, run_import


TABLE_DDL = {
    "run": "CREATE TABLE run (id TEXT PRIMARY KEY, window_from TEXT, window_to TEXT, timezone TEXT, generated_at TEXT, screening_basis TEXT, status TEXT, superseded_by TEXT, counts_json TEXT)",
    "notice": "CREATE TABLE notice (id INTEGER PRIMARY KEY, run_id TEXT, notice_key TEXT, bid_no TEXT, bid_ord TEXT, source_type TEXT, title TEXT, agency TEXT, published_at TEXT, deadline_at TEXT, budget NUMERIC, estimated_price NUMERIC, method TEXT, url TEXT, sample_role TEXT, sample_stratum TEXT, collection_bucket TEXT, procurement_class_json TEXT, region_limit_json TEXT, lifecycle_json TEXT, qualification_flags_json TEXT, focus_matches_json TEXT, performance_matches_json TEXT, performance_top_score REAL, candidate_sources_json TEXT, unknown_fields_json TEXT, raw_source TEXT)",
    "judgment": "CREATE TABLE judgment (id INTEGER PRIMARY KEY, notice_pk INTEGER, schema_version TEXT, grade TEXT, readiness TEXT, primary_focus TEXT, exclusion_category TEXT, summary TEXT, next_action TEXT)",
    "perspective": "CREATE TABLE perspective (id INTEGER PRIMARY KEY, judgment_id INTEGER, position INTEGER, name TEXT, assessment TEXT, reason TEXT)",
    "evidence": "CREATE TABLE evidence (id INTEGER PRIMARY KEY, perspective_id INTEGER, source TEXT, status TEXT, fact TEXT)",
    "counterargument": "CREATE TABLE counterargument (id INTEGER PRIMARY KEY, judgment_id INTEGER, position INTEGER, text TEXT)",
    "verification_item": "CREATE TABLE verification_item (id INTEGER PRIMARY KEY, judgment_id INTEGER, item TEXT, why TEXT, blocking INTEGER, status TEXT)",
    "matched_performance": "CREATE TABLE matched_performance (id INTEGER PRIMARY KEY, judgment_id INTEGER, name TEXT, match_reason TEXT, mismatch_or_limit TEXT, source TEXT, status TEXT)",
    "attachment": "CREATE TABLE attachment (id INTEGER PRIMARY KEY, notice_pk INTEGER, name TEXT, url TEXT, origin TEXT, file_ext TEXT, size_bytes INTEGER, stored_path TEXT, extract_status TEXT, created_at TEXT)",
    "agency_portal": "CREATE TABLE agency_portal (id INTEGER PRIMARY KEY, agency_pattern TEXT, system_name TEXT, search_url_template TEXT, enabled INTEGER, note TEXT)",
    "review": "CREATE TABLE review (id INTEGER PRIMARY KEY, notice_pk INTEGER, run_id TEXT, disposition TEXT, system_judgment_review TEXT, corrected_grade TEXT, corrected_readiness TEXT, weakest_perspective TEXT, reason TEXT, reviewer TEXT, created_at TEXT, updated_at TEXT)",
    "verification_answer": "CREATE TABLE verification_answer (id INTEGER PRIMARY KEY, review_id INTEGER, item TEXT, answer TEXT)",
    "ingest_warning": "CREATE TABLE ingest_warning (id INTEGER PRIMARY KEY, run_id TEXT, level TEXT, code TEXT, message TEXT, context_json TEXT)",
}


def _build_snapshot(root: Path, *, unknown_column: bool = False) -> tuple[Path, Path]:
    backup = root / "snapshot.sqlite3"
    with sqlite3.connect(backup) as connection:
        for ddl in TABLE_DDL.values():
            connection.execute(ddl)
        if unknown_column:
            connection.execute("ALTER TABLE notice ADD COLUMN not_in_manifest TEXT")
        connection.execute("INSERT INTO run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("run-1", "2026-08-01", "2026-08-02", "Asia/Seoul", "2026-08-03T00:00:00Z", "basis", "active", None, '{"notices":1}'))
        notice_values = (1, "run-1", "notice-1", "B-1", "1", "g2b", "Synthetic", "Agency", "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z", 100, 90, "open", "https://example.invalid/bid", "sample", "stratum", "bucket", "{}", "{}", "{}", "{}", "{}", "{}", 0.5, "[]", "[]", "{}")
        if unknown_column:
            notice_values += (None,)
        connection.execute(f"INSERT INTO notice VALUES ({','.join('?' for _ in notice_values)})", notice_values)
        connection.execute("INSERT INTO judgment VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?)", ("v1", "우선 검토", "확인", "focus", None, "summary", "next"))
        connection.execute("INSERT INTO perspective VALUES (1, 1, 1, ?, ?, ?)", ("p", "ok", "reason"))
        connection.execute("INSERT INTO evidence VALUES (1, 1, ?, ?, ?)", ("synthetic", "confirmed", "fact"))
        connection.execute("INSERT INTO counterargument VALUES (1, 1, 1, ?)", ("body",))
        connection.execute("INSERT INTO verification_item VALUES (1, 1, ?, ?, ?, ?)", ("item", "why", 0, "unknown"))
        connection.execute("INSERT INTO matched_performance VALUES (1, 1, ?, ?, ?, ?, ?)", ("name", "match", "limit", "source", "unknown"))
        connection.execute("INSERT INTO attachment VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?, ?)", ("one.pdf", "https://example.invalid/one", "g2b", ".pdf", 9, "attachments/one.pdf", "pending", "2026-08-01T00:00:00Z"))
        connection.execute("INSERT INTO agency_portal VALUES (1, ?, ?, ?, ?, ?)", ("Agency", "Synthetic", "https://example.invalid", 1, "note"))
        connection.execute("INSERT INTO review VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("run-1", "보류", "review", None, None, None, "reason", "검토자", "2026-08-03T00:00:00Z", "2026-08-03T00:00:00Z"))
        connection.execute("INSERT INTO verification_answer VALUES (1, 1, ?, ?)", ("item", "unknown"))
        connection.execute("INSERT INTO ingest_warning VALUES (1, ?, ?, ?, ?, ?)", ("run-1", "warning", "CODE", "message", '{"field":"x"}'))

    attachment = root / "attachments" / "one.pdf"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"synthetic")
    source_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    manifest = root / "file-manifest.json"
    manifest.write_text(json.dumps({
        "schema": "bidops.sqlite-file-manifest.v1",
        "snapshot_sha256": source_hash,
        "created_at": "2026-08-03T00:00:00Z",
        "files": [{"attachment_id": 1, "relative_path": "attachments/one.pdf", "state": "present", "size_bytes": 9, "sha256": hashlib.sha256(b"synthetic").hexdigest()}],
    }), encoding="utf-8")
    return backup, manifest


@pytest.fixture
def target_engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def test_dry_run_reconciles_all_legacy_rows_and_files(tmp_path: Path, target_engine):
    backup, manifest = _build_snapshot(tmp_path)
    report = run_import(sqlite_backup=backup, file_manifest=manifest, mode="dry_run", destination=target_engine)

    assert report["success"] is True
    assert len(report["tables"]) == 13
    assert report["files"] == {"manifest_count": 1, "present_count": 1, "missing_count": 0, "url_only_count": 0, "size_match": True, "hash_match": True}
    assert any(item["target_table"] == "screening_evidence" for item in report["tables"])
    assert report["errors"] == []
    assert str(tmp_path) not in json.dumps(report, ensure_ascii=False)


def test_unregistered_legacy_column_stops_import(tmp_path: Path, target_engine):
    backup, manifest = _build_snapshot(tmp_path, unknown_column=True)
    report = run_import(sqlite_backup=backup, file_manifest=manifest, mode="dry_run", destination=target_engine)

    assert report["success"] is False
    assert report["errors"][0]["code"] == "unknown_legacy_column"
    assert report["errors"][0]["table"] == "notice"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda manifest: manifest.update({"unexpected": True}), "invalid_manifest_schema"),
        (lambda manifest: manifest["files"].append(dict(manifest["files"][0])), "duplicate_manifest_attachment"),
        (lambda manifest: manifest.update({"files": []}), "manifest_attachment_uncovered"),
        (lambda manifest: manifest["files"][0].update({"unexpected": True}), "invalid_manifest_item_keys"),
    ],
)
def test_manifest_shape_coverage_and_failure_before_write(tmp_path: Path, target_engine, mutation, code):
    backup, manifest_path = _build_snapshot(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutation(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_import(sqlite_backup=backup, file_manifest=manifest_path, mode="dry_run", destination=target_engine)

    assert report["success"] is False
    assert any(error["code"] == code for error in report["errors"])
    assert "migration_staging" not in inspect(target_engine).get_table_names()


def test_apply_requires_postgresql_destination(tmp_path: Path, target_engine):
    backup, manifest = _build_snapshot(tmp_path)
    report = run_import(sqlite_backup=backup, file_manifest=manifest, mode="apply", destination=target_engine)

    assert report["success"] is False
    assert report["errors"][0]["code"] == "postgresql_destination_required"


def test_model_has_exact_closed_table_set():
    from app.models import Base, LEGACY_TABLES, NEW_TABLES

    assert len(LEGACY_TABLES) == 13
    assert len(NEW_TABLES) == 25
    assert "actor" not in LEGACY_TABLES + NEW_TABLES
    assert len(Base.metadata.tables) == 38
    assert set(Base.metadata.tables) == set(LEGACY_TABLES + NEW_TABLES)
    assert "fk_evidence_document_bundle_scope" in {
        constraint.name for constraint in Base.metadata.tables["evidence_ref"].foreign_key_constraints
    }
    assert "fk_final_opinion_validation_snapshot" in {
        constraint.name for constraint in Base.metadata.tables["final_opinion"].foreign_key_constraints
    }


def test_approved_scope_and_provenance_constraints_are_closed():
    from app.models import DocumentBundleItem, DocumentVersion, EvidenceRef, FinalOpinion, ReportRevision, ValidationRun

    assert EvidenceRef.__table__.c.notice_id.nullable is False
    assert ValidationRun.__table__.c.deep_review_id.nullable is False
    assert FinalOpinion.__table__.c.deep_review_id.nullable is False
    assert any(c.name == "fk_evidence_notice_review_scope" for c in EvidenceRef.__table__.foreign_key_constraints)
    assert any(c.name == "fk_report_revision_parent_scope" for c in ReportRevision.__table__.foreign_key_constraints)
    assert any(c.name == "fk_validation_run_revision_scope" for c in ValidationRun.__table__.foreign_key_constraints)
    assert any(c.name == "fk_final_opinion_revision_scope" for c in FinalOpinion.__table__.foreign_key_constraints)
    assert any(c.name == "fk_final_opinion_validation_snapshot" for c in FinalOpinion.__table__.foreign_key_constraints)
    assert any(c.name == "fk_final_opinion_validation_revision_scope" for c in FinalOpinion.__table__.foreign_key_constraints)
    assert {c.name for c in ValidationRun.__table__.constraints} >= {
        "uq_validation_run_sequence",
        "uq_validation_run_scope",
        "uq_validation_run_revision_status_scope",
    }
    assert FinalOpinion.__table__.c.report_revision_id.nullable is False
    assert {c.name for c in DocumentVersion.__table__.constraints} >= {
        "ck_document_version_source_provenance",
        "ck_document_version_role",
        "ck_document_version_safety",
    }
    assert {c.name for c in DocumentBundleItem.__table__.constraints} >= {
        "ck_bundle_item_source_provenance",
        "ck_bundle_item_role",
        "ck_bundle_item_safety",
    }


def test_postgresql_schema_translation_is_applied_only_to_postgresql_binds():
    class FakeBind:
        dialect = SimpleNamespace(name="postgresql")

        def execution_options(self, **options):
            self.options = options
            return self

    fake = schema_bound(FakeBind())
    assert fake.options["schema_translate_map"] == {None: "bidops"}
    sqlite_bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    assert schema_bound(sqlite_bind) is sqlite_bind


def test_reconciliation_failure_rolls_back_staging_write(tmp_path: Path, target_engine, monkeypatch):
    backup, manifest = _build_snapshot(tmp_path)

    def fail_after_staging(*args, **kwargs):
        raise ImportContractError("forced_reconciliation_mismatch", "forced test mismatch", table="run")

    monkeypatch.setattr(import_sqlite, "_table_reconciliation", fail_after_staging)
    report = run_import(sqlite_backup=backup, file_manifest=manifest, mode="dry_run", destination=target_engine)

    assert report["success"] is False
    assert report["errors"][-1]["code"] == "forced_reconciliation_mismatch"
    assert "migration_staging" not in inspect(target_engine).get_table_names()


def _build_scope_constraint_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    tables = Base.metadata.tables
    review_ids = [uuid4(), uuid4()]
    bundle_ids = [uuid4(), uuid4()]
    profile_ids = [uuid4(), uuid4()]
    policy_ids = [uuid4(), uuid4()]
    with engine.begin() as connection:
        connection.execute(tables["run"].insert(), {"id": "scope-run", "timezone": "UTC", "generated_at": now, "status": "active"})
        connection.execute(tables["notice"].insert(), [
            {"id": 101, "run_id": "scope-run", "notice_key": "scope-101"},
            {"id": 102, "run_id": "scope-run", "notice_key": "scope-102"},
        ])
        connection.execute(tables["document_bundle"].insert(), [
            {"id": bundle_ids[0], "notice_id": 101, "revision": 1, "version": 1, "status": "draft", "issues_snapshot": {}},
            {"id": bundle_ids[1], "notice_id": 102, "revision": 1, "version": 1, "status": "draft", "issues_snapshot": {}},
        ])
        connection.execute(tables["profile_version"].insert(), [
            {"id": profile_ids[0], "version": 101, "label": "scope-101", "profile_payload": {}, "profile_sha256": "a" * 64, "source_kind": "fixture"},
            {"id": profile_ids[1], "version": 102, "label": "scope-102", "profile_payload": {}, "profile_sha256": "b" * 64, "source_kind": "fixture"},
        ])
        connection.execute(tables["analysis_policy_version"].insert(), [
            {"id": policy_ids[0], "version": 101, "label": "scope-101", "model_endpoint_ref": "fixture", "model_name": "fixture", "prompts": {}, "validation_rules": {}, "policy_sha256": "c" * 64},
            {"id": policy_ids[1], "version": 102, "label": "scope-102", "model_endpoint_ref": "fixture", "model_name": "fixture", "prompts": {}, "validation_rules": {}, "policy_sha256": "d" * 64},
        ])
        connection.execute(tables["deep_review"].insert(), [
            {"id": review_ids[0], "notice_id": 101, "bundle_id": bundle_ids[0], "profile_version_id": profile_ids[0], "policy_version_id": policy_ids[0], "effective_grade_at_start": "우선 검토", "status": "queued", "created_at": now},
            {"id": review_ids[1], "notice_id": 102, "bundle_id": bundle_ids[1], "profile_version_id": profile_ids[1], "policy_version_id": policy_ids[1], "effective_grade_at_start": "우선 검토", "status": "queued", "created_at": now},
        ])
    return engine, review_ids, now


def test_scope_composite_fks_reject_cross_review_parent_and_final_opinion_revision():
    engine, review_ids, now = _build_scope_constraint_engine()
    tables = Base.metadata.tables
    parent_id = uuid4()
    sibling_id = uuid4()
    validation_id = uuid4()
    with engine.begin() as connection:
        connection.execute(tables["report_revision"].insert(), {
            "id": parent_id,
            "deep_review_id": review_ids[0],
            "sequence": 1,
            "origin": "machine",
            "report_payload": {},
            "report_sha256": "e" * 64,
            "created_at": now,
        })
        connection.execute(tables["report_revision"].insert(), {
            "id": sibling_id,
            "deep_review_id": review_ids[0],
            "sequence": 2,
            "parent_revision_id": parent_id,
            "origin": "human",
            "report_payload": {},
            "report_sha256": "f" * 64,
            "change_reason": "fixture",
            "created_by_name": "reviewer",
            "created_at": now,
        })
        connection.execute(tables["validation_run"].insert(), {
            "id": validation_id,
            "deep_review_id": review_ids[0],
            "report_revision_id": parent_id,
            "sequence": 1,
            "status": "passed",
            "created_at": now,
        })

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(tables["report_revision"].insert(), {
                "id": uuid4(),
                "deep_review_id": review_ids[1],
                "sequence": 1,
                "parent_revision_id": parent_id,
                "origin": "human",
                "report_payload": {},
                "report_sha256": "1" * 64,
                "change_reason": "cross-review fixture",
                "created_by_name": "reviewer",
                "created_at": now,
            })

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(tables["final_opinion"].insert(), {
                "id": uuid4(),
                "deep_review_id": review_ids[0],
                "report_revision_id": sibling_id,
                "sequence": 1,
                "value": "추진",
                "reason": "fixture",
                "validation_run_id": validation_id,
                "validation_status_at_opinion": "passed",
                "acknowledged_validation_failure": False,
                "claimed_name": "reviewer",
                "created_at": now,
            })

    with engine.begin() as connection:
        connection.execute(tables["final_opinion"].insert(), {
            "id": uuid4(),
            "deep_review_id": review_ids[0],
            "report_revision_id": parent_id,
            "sequence": 1,
            "value": "추진",
            "reason": "same-scope fixture",
            "validation_run_id": validation_id,
            "validation_status_at_opinion": "passed",
            "acknowledged_validation_failure": False,
            "claimed_name": "reviewer",
            "created_at": now,
        })
