"""Import an explicit SQLite backup into PostgreSQL with reconciliation.

This module intentionally does not open the live application SQLite path or an
attachment directory.  The caller supplies a read-only backup and a matching
file manifest, and receives the deterministic report contract from spec §14.3.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sqlite3
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import (
    Column,
    Date,
    Integer,
    JSON,
    MetaData,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.engine import Engine

from ..core import Base, schema_bound, settings
from ..core.models import AwareDateTime

# 대상 테이블(legacy·Lean v1)을 모두 등록한다. 조립 계층인 이 파일은 네 모듈의
# `models` 하위 모듈을 직접 import한다 (명세 §3).
from ..core import models as core_models  # noqa: F401
from ..lifecycle import models as lifecycle_models  # noqa: F401
from ..screening import models as screening_models  # noqa: F401
from ..deep_review import models as deep_review_models  # noqa: F401
from ..screening import (
    JUDGMENT_PAYLOAD_SCHEMA,
    REVIEW_PAYLOAD_SCHEMA,
    canonical_payload_and_hash,
    review_revision_payload,
)


LEGACY_COLUMNS: dict[str, tuple[str, ...]] = {
    "run": ("id", "window_from", "window_to", "timezone", "generated_at", "screening_basis", "status", "superseded_by", "counts_json"),
    "notice": ("id", "run_id", "notice_key", "bid_no", "bid_ord", "source_type", "title", "agency", "published_at", "deadline_at", "budget", "estimated_price", "method", "url", "sample_role", "sample_stratum", "collection_bucket", "procurement_class_json", "region_limit_json", "lifecycle_json", "qualification_flags_json", "focus_matches_json", "performance_matches_json", "performance_top_score", "candidate_sources_json", "unknown_fields_json", "raw_source"),
    "judgment": ("id", "notice_pk", "schema_version", "grade", "readiness", "primary_focus", "exclusion_category", "summary", "next_action"),
    "perspective": ("id", "judgment_id", "position", "name", "assessment", "reason"),
    "evidence": ("id", "perspective_id", "source", "status", "fact"),
    "counterargument": ("id", "judgment_id", "position", "text"),
    "verification_item": ("id", "judgment_id", "item", "why", "blocking", "status"),
    "matched_performance": ("id", "judgment_id", "name", "match_reason", "mismatch_or_limit", "source", "status"),
    "attachment": ("id", "notice_pk", "name", "url", "origin", "file_ext", "size_bytes", "stored_path", "extract_status", "created_at"),
    "agency_portal": ("id", "agency_pattern", "system_name", "search_url_template", "enabled", "note"),
    "review": ("id", "notice_pk", "run_id", "disposition", "system_judgment_review", "corrected_grade", "corrected_readiness", "weakest_perspective", "reason", "reviewer", "created_at", "updated_at"),
    "verification_answer": ("id", "review_id", "item", "answer"),
    "ingest_warning": ("id", "run_id", "level", "code", "message", "context_json"),
}

TARGET_TABLES = {
    "run": "run",
    "notice": "notice",
    "judgment": "judgment",
    "perspective": "perspective",
    "evidence": "screening_evidence",
    "counterargument": "counterargument",
    "verification_item": "verification_item",
    "matched_performance": "matched_performance",
    "attachment": "attachment",
    "agency_portal": "agency_portal",
    "review": "review",
    "verification_answer": "verification_answer",
    "ingest_warning": "ingest_warning",
}

RENAMES = {
    ("judgment", "notice_pk"): "notice_id",
    ("counterargument", "text"): "body",
    ("review", "notice_pk"): "notice_id",
    ("review", "reviewer"): "reviewer_snapshot",
    ("attachment", "notice_pk"): "notice_id",
    ("attachment", "url"): "source_url",
    ("attachment", "stored_path"): "legacy_stored_path",
    ("ingest_warning", "context_json"): "context_jsonb",
}

JSON_COLUMNS = {
    "counts_json", "procurement_class_json", "region_limit_json", "lifecycle_json",
    "qualification_flags_json", "focus_matches_json", "performance_matches_json",
    "candidate_sources_json", "unknown_fields_json", "raw_source", "context_json",
}

# ``notice.run_id`` existed only in the legacy SQLite snapshot.  The target
# PostgreSQL model stores that relationship in notice_observation instead of
# copying the run id onto the cumulative Notice row.
IGNORED_TARGET_COLUMNS = {("notice", "run_id")}

STAGING_SCHEMA = "migration_staging"


@dataclass(frozen=True)
class StagingContext:
    """Committed staging objects for one immutable SQLite snapshot."""

    metadata: MetaData
    import_batch: Table
    raw_row: Table
    batch_hash: str
    schema: str | None


class ImportContractError(ValueError):
    """Raised for a source/manifest contract violation before writes begin."""

    def __init__(self, code: str, message: str, *, table: str | None = None, column: str | None = None, attachment_id: int | None = None):
        super().__init__(message)
        self.code = code
        self.table = table
        self.column = column
        self.attachment_id = attachment_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(error: ImportContractError | Exception, *, code: str | None = None) -> dict[str, Any]:
    if isinstance(error, ImportContractError):
        return {"code": error.code, "table": error.table, "column": error.column, "attachment_id": error.attachment_id, "message": str(error)}
    return {"code": code or "import_error", "table": None, "column": None, "attachment_id": None, "message": str(error)}


def _empty_report(mode: str, source_sha256: str, started_at: str) -> dict[str, Any]:
    return {
        "schema": "bidops.sqlite-reconciliation.v1",
        "mode": mode,
        "source_sha256": source_sha256,
        "started_at": started_at,
        "completed_at": None,
        "success": False,
        "tables": [],
        "files": {"manifest_count": 0, "present_count": 0, "missing_count": 0, "url_only_count": 0, "size_match": False, "hash_match": False},
        "sequences": [],
        "errors": [],
    }


def _canonical_json_default(value: Any) -> Any:
    """Serialize snapshot values without introducing process-local ordering."""

    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"value of type {type(value).__name__} is not JSON serializable")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_canonical_json_default,
    ).encode("utf-8")


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(manifest)).hexdigest()


def _row_hash(source_table: str, row: Mapping[str, Any]) -> str:
    source_pk = str(row["id"])
    return hashlib.sha256(
        _canonical_json_bytes({"source_table": source_table, "source_pk": source_pk, "row": row})
    ).hexdigest()


def _batch_hash(source_sha256: str, manifest_sha256: str) -> str:
    return hashlib.sha256(
        _canonical_json_bytes({"source_sha256": source_sha256, "manifest_sha256": manifest_sha256})
    ).hexdigest()


def _read_manifest(path: Path, source_sha256: str) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ImportContractError("invalid_manifest_path", "file manifest must be an absolute regular file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportContractError("invalid_manifest", f"cannot read file manifest: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"schema", "snapshot_sha256", "created_at", "files"} or data.get("schema") != "bidops.sqlite-file-manifest.v1":
        raise ImportContractError("invalid_manifest_schema", "file manifest schema must be bidops.sqlite-file-manifest.v1")
    if not isinstance(data.get("created_at"), str):
        raise ImportContractError("invalid_manifest_created_at", "manifest created_at must be timezone-aware RFC3339")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", data["created_at"]) is None:
        raise ImportContractError("invalid_manifest_created_at", "manifest created_at must be timezone-aware RFC3339")
    try:
        created_at = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ImportContractError("invalid_manifest_created_at", "manifest created_at must be timezone-aware RFC3339") from exc
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ImportContractError("invalid_manifest_created_at", "manifest created_at must be timezone-aware RFC3339")
    if not isinstance(data.get("snapshot_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", data["snapshot_sha256"]) is None:
        raise ImportContractError("invalid_snapshot_sha256", "snapshot_sha256 must be a lowercase 64-character SHA-256")
    if data.get("snapshot_sha256") != source_sha256:
        raise ImportContractError("snapshot_hash_mismatch", "file manifest snapshot_sha256 does not match SQLite backup")
    files = data.get("files")
    if not isinstance(files, list):
        raise ImportContractError("invalid_manifest_files", "file manifest files must be an array")
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("attachment_id"), int) or isinstance(item.get("attachment_id"), bool):
            raise ImportContractError("invalid_manifest_item", "manifest item must include integer attachment_id")
        if set(item) != {"attachment_id", "relative_path", "state", "size_bytes", "sha256"}:
            raise ImportContractError("invalid_manifest_item_keys", "manifest item has unexpected or missing keys", attachment_id=item.get("attachment_id"))
        state = item.get("state")
        if state not in {"present", "missing", "url_only"}:
            raise ImportContractError("invalid_manifest_state", "manifest state must be present, missing, or url_only", attachment_id=item.get("attachment_id"))
        relative = item.get("relative_path")
        if relative is not None:
            if not isinstance(relative, str) or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
                raise ImportContractError("invalid_manifest_path", "manifest relative_path must stay below its root", attachment_id=item.get("attachment_id"))
        sha256 = item.get("sha256")
        if sha256 is not None and (not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None):
            raise ImportContractError("invalid_file_sha256", "file sha256 must be a lowercase 64-character SHA-256", attachment_id=item.get("attachment_id"))
        if state == "present":
            if relative is None or not isinstance(item.get("size_bytes"), int) or isinstance(item.get("size_bytes"), bool) or item["size_bytes"] < 0 or not isinstance(item.get("sha256"), str):
                raise ImportContractError("invalid_present_manifest_item", "present file requires relative_path, size_bytes, and sha256", attachment_id=item.get("attachment_id"))
        elif relative is not None or item.get("size_bytes") is not None or item.get("sha256") is not None:
            raise ImportContractError("invalid_absent_manifest_item", "missing/url_only item must not claim size or hash", attachment_id=item.get("attachment_id"))
    return data


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source_path(path: Path) -> None:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ImportContractError("invalid_sqlite_backup", "sqlite-backup must be an absolute regular backup file")
    live = Path(settings.database_path).resolve()
    attachments = Path(settings.attachments_dir).resolve()
    resolved = path.resolve()
    if resolved == live or attachments == resolved or attachments in resolved.parents:
        raise ImportContractError("live_sqlite_forbidden", "live SQLite database or attachment directory is not an import input")


def _validate_source_schema(connection: sqlite3.Connection) -> None:
    actual_tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if row[0] != "sqlite_sequence"
    }
    unknown_tables = sorted(actual_tables - set(LEGACY_COLUMNS))
    if unknown_tables:
        raise ImportContractError("unknown_legacy_table", f"unregistered source table: {unknown_tables[0]}", table=unknown_tables[0])
    for source_table, expected in LEGACY_COLUMNS.items():
        row = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (source_table,)).fetchone()
        if row is None:
            raise ImportContractError("missing_legacy_table", f"legacy table {source_table} is missing", table=source_table)
        actual = [item[1] for item in connection.execute(f'PRAGMA table_info("{source_table}")').fetchall()]
        unknown = [name for name in actual if name not in expected]
        if unknown:
            raise ImportContractError("unknown_legacy_column", f"unregistered source column(s): {', '.join(unknown)}", table=source_table, column=unknown[0])
        missing = [name for name in expected if name not in actual]
        if missing:
            raise ImportContractError("missing_legacy_column", f"required source column is missing: {missing[0]}", table=source_table, column=missing[0])


def _target_table(name: str) -> Table:
    matches = [table for table in Base.metadata.tables.values() if table.name == name]
    if not matches:
        raise ImportContractError("target_table_missing", f"target table {name} is not in the model", table=name)
    return matches[0]


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _coerce_target_value(value: Any, target_type: Any, *, table: str, column: str) -> Any:
    if value is None:
        return None
    if isinstance(target_type, AwareDateTime) and isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ImportContractError("legacy_datetime_invalid", "legacy datetime cannot be parsed as RFC3339", table=table, column=column) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ImportContractError("legacy_datetime_timezone_missing", "legacy datetime has no timezone", table=table, column=column)
        return parsed
    if isinstance(target_type, Date) and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ImportContractError("legacy_date_invalid", "legacy date cannot be parsed as ISO date", table=table, column=column) from exc
    return value


def _target_row(source_table: str, row: Mapping[str, Any], target: Table) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for source_column, value in row.items():
        if (source_table, source_column) in IGNORED_TARGET_COLUMNS:
            continue
        target_column = RENAMES.get((source_table, source_column), source_column)
        if target_column not in target.c:
            raise ImportContractError("target_column_missing", f"target column {target_column} is missing", table=source_table, column=target_column)
        if source_column in JSON_COLUMNS or isinstance(target.c[target_column].type, JSON):
            value = _decode_json(value)
        value = _coerce_target_value(value, target.c[target_column].type, table=source_table, column=target_column)
        converted[target_column] = value
    return converted


def _validate_target_row_types(row: Mapping[str, Any], target: Table, dialect: Any) -> None:
    for name, value in row.items():
        processor = target.c[name].type.bind_processor(dialect)
        if processor is None:
            continue
        try:
            processor(value)
        except Exception as exc:
            raise ImportContractError("target_type_mismatch", "legacy value cannot be bound to target column type", table=target.name, column=name) from exc


def _file_reconciliation(manifest: Mapping[str, Any], source_tables: Mapping[str, list[dict[str, Any]]], root: Path, report: dict[str, Any]) -> None:
    items = manifest["files"]
    output = report["files"]
    output["manifest_count"] = len(items)
    attachment_rows = {int(row["id"]): row for row in source_tables.get("attachment", [])}
    attachment_ids = set(attachment_rows)
    seen_attachment_ids: set[int] = set()
    size_match = True
    hash_match = True
    for item in items:
        attachment_id = int(item["attachment_id"])
        if attachment_id in seen_attachment_ids:
            report["errors"].append(_error(ImportContractError("duplicate_manifest_attachment", "file manifest contains duplicate attachment_id", attachment_id=attachment_id)))
            continue
        seen_attachment_ids.add(attachment_id)
        if attachment_id not in attachment_ids:
            report["errors"].append(_error(ImportContractError("manifest_attachment_missing", "file manifest references no legacy attachment", attachment_id=attachment_id)))
            continue
        state = item["state"]
        if state == "url_only":
            output["url_only_count"] += 1
            continue
        if state == "missing":
            output["missing_count"] += 1
            size_match = hash_match = False
            report["errors"].append(_error(ImportContractError("missing_attachment_file", "attachment file is missing from the supplied snapshot", attachment_id=attachment_id)))
            continue
        output["present_count"] += 1
        relative = item["relative_path"]
        raw_candidate = root / Path(relative)
        candidate = raw_candidate.resolve()
        if raw_candidate.is_symlink() or root.resolve() not in candidate.parents or not candidate.is_file():
            size_match = hash_match = False
            report["errors"].append(_error(ImportContractError("attachment_path_unavailable", "present manifest file is not a regular file below manifest root", attachment_id=attachment_id)))
            continue
        actual_size = candidate.stat().st_size
        actual_hash = _source_hash(candidate)
        if actual_size != item["size_bytes"]:
            size_match = False
            report["errors"].append(_error(ImportContractError("attachment_size_mismatch", "attachment size does not match manifest", attachment_id=attachment_id)))
        legacy_size = attachment_rows[attachment_id].get("size_bytes")
        if legacy_size is not None and actual_size != int(legacy_size):
            size_match = False
            report["errors"].append(_error(ImportContractError("legacy_attachment_size_mismatch", "attachment size does not match legacy metadata", attachment_id=attachment_id)))
        if actual_hash != item["sha256"]:
            hash_match = False
            report["errors"].append(_error(ImportContractError("attachment_hash_mismatch", "attachment SHA-256 does not match manifest", attachment_id=attachment_id)))
    output["size_match"] = size_match and output["missing_count"] == 0
    output["hash_match"] = hash_match and output["missing_count"] == 0
    for attachment_id in sorted(attachment_ids - seen_attachment_ids):
        report["errors"].append(_error(ImportContractError("manifest_attachment_uncovered", "legacy attachment has no manifest item", attachment_id=attachment_id)))


def _canonical_value(value: Any) -> Any:
    """Make SQLite/PG driver representations comparable without lossy casts."""

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and (value.endswith("Z") or "T" in value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else parsed.isoformat()
        except ValueError:
            pass
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (Decimal, int, float)):
        return format(Decimal(str(value)).normalize(), "f")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def _table_reconciliation(connection, source_table: str, target_table: Table, source_rows: list[dict[str, Any]], report: dict[str, Any], *, dry_run: bool = False) -> None:
    source_keys = {row["id"] for row in source_rows}
    target_rows = ([dict(row) for row in source_rows] if dry_run else connection.execute(select(target_table)).mappings().all())
    target_keys = {row["id"] for row in target_rows}
    target_source_count = len(target_rows)
    target_by_key = {row["id"]: row for row in target_rows}
    column_match = source_keys == target_keys
    if not dry_run:
        for source_row in source_rows:
            target_row = target_by_key.get(source_row["id"])
            if target_row is None:
                column_match = False
                continue
            for source_column, expected in source_row.items():
                if (source_table, source_column) in IGNORED_TARGET_COLUMNS:
                    continue
                target_column = RENAMES.get((source_table, source_column), source_column)
                actual = target_row.get(target_column)
                if _canonical_value(_decode_json(expected) if source_column in JSON_COLUMNS else expected) != _canonical_value(actual):
                    column_match = False
                    break
    if source_table == "review" and not dry_run:
        reviewer_match = all(
            _canonical_value(next((row.get("reviewer") for row in source_rows if row["id"] == target["id"]), object())) == _canonical_value(target.get("reviewer_snapshot"))
            for target in target_rows
        )
    else:
        reviewer_match = True
    if source_keys != target_keys:
        column_match = False
    report["tables"].append({
        "source_table": source_table,
        "target_table": target_table.name,
        "source_rows": len(source_rows),
        "target_rows": target_source_count,
        "pk_match": source_keys == target_keys,
        "column_match": column_match,
        "reviewer_match": reviewer_match,
    })


def _sequence_reconciliation(connection, target_table: Table, source_rows: list[dict[str, Any]], report: dict[str, Any], *, apply: bool) -> None:
    pk = list(target_table.primary_key.columns)
    if len(pk) != 1 or not isinstance(pk[0].type, Integer):
        return
    max_pk = max((int(row["id"]) for row in source_rows), default=0)
    next_value = max_pk + 1
    if connection is not None and connection.dialect.name == "postgresql" and apply:
        qualified = f"bidops.{target_table.name}"
        connection.execute(text("SELECT setval(pg_get_serial_sequence(:table_name, :pk_name), :value, false)"), {"table_name": qualified, "pk_name": pk[0].name, "value": next_value})
    report["sequences"].append({"table": target_table.name, "pk_column": pk[0].name, "max_pk": max_pk, "next_value": next_value})


def _staging_tables(*, schema: str | None = STAGING_SCHEMA) -> tuple[MetaData, Table, Table]:
    metadata = MetaData()
    import_batch = Table(
        "import_batch",
        metadata,
        Column("batch_hash", String(64), nullable=False),
        Column("source_sha256", String(64), nullable=False),
        Column("manifest_sha256", String(64), nullable=False),
        Column("source_row_count", Integer, nullable=False),
        PrimaryKeyConstraint("batch_hash", name="pk_migration_staging_import_batch"),
        UniqueConstraint("source_sha256", name="uq_migration_staging_source_sha256"),
        UniqueConstraint("source_sha256", "manifest_sha256", name="uq_migration_staging_input"),
        schema=schema,
    )
    raw_row = Table(
        "raw_row",
        metadata,
        Column("batch_hash", String(64), nullable=False),
        Column("source_table", String(64), nullable=False),
        Column("source_pk", String(255), nullable=False),
        Column("row_hash", String(64), nullable=False),
        Column("source_row", JSON, nullable=False),
        ForeignKeyConstraint(
            ["batch_hash"],
            [f"{schema}.import_batch.batch_hash" if schema else "import_batch.batch_hash"],
            name="fk_migration_staging_raw_row_batch",
        ),
        PrimaryKeyConstraint("batch_hash", "source_table", "source_pk", name="pk_migration_staging_raw_row"),
        UniqueConstraint("batch_hash", "source_table", "source_pk", "row_hash", name="uq_migration_staging_raw_row_hash"),
        schema=schema,
    )
    return metadata, import_batch, raw_row


def _create_staging_objects(connection, metadata: MetaData, *, schema: str | None) -> None:
    if schema is not None:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    metadata.create_all(connection, checkfirst=True)


def _drop_staging_objects(connection, context: StagingContext) -> None:
    if context.schema is not None:
        # The importer owns this dedicated schema. CASCADE is intentional so a
        # successful cutover leaves no staging object behind.
        connection.execute(text(f"DROP SCHEMA IF EXISTS {context.schema} CASCADE"))
    else:
        context.metadata.drop_all(connection, checkfirst=True)


def _expected_staging_rows(source_tables: Mapping[str, list[dict[str, Any]]]) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    expected: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for source_table in LEGACY_COLUMNS:
        for row in source_tables[source_table]:
            source_pk = str(row["id"])
            key = (source_table, source_pk)
            if key in expected:
                raise ImportContractError("duplicate_source_pk", "source snapshot contains duplicate legacy primary key", table=source_table)
            expected[key] = (_row_hash(source_table, row), row)
    return expected


def _stage_snapshot(
    destination: Engine,
    source_tables: Mapping[str, list[dict[str, Any]]],
    *,
    source_sha256: str,
    manifest_sha256: str,
    schema: str | None = STAGING_SCHEMA,
) -> StagingContext:
    """Commit a deterministic source batch before attempting target promotion."""

    metadata, import_batch, raw_row = _staging_tables(schema=schema)
    batch_hash = _batch_hash(source_sha256, manifest_sha256)
    expected = _expected_staging_rows(source_tables)
    context = StagingContext(metadata, import_batch, raw_row, batch_hash, schema)
    with destination.begin() as connection:
        _create_staging_objects(connection, metadata, schema=schema)
        existing_by_hash = connection.execute(
            select(import_batch).where(import_batch.c.batch_hash == batch_hash)
        ).mappings().first()
        existing_by_source = connection.execute(
            select(import_batch).where(import_batch.c.source_sha256 == source_sha256)
        ).mappings().first()
        existing_any = connection.execute(select(import_batch).limit(1)).mappings().first()
        if existing_any is not None and existing_any["source_sha256"] != source_sha256:
            raise ImportContractError(
                "staging_batch_conflict",
                "another SQLite snapshot is already staged for migration",
            )
        if existing_by_source is not None and (
            existing_by_source["batch_hash"] != batch_hash
            or existing_by_source["manifest_sha256"] != manifest_sha256
        ):
            raise ImportContractError(
                "staging_batch_conflict",
                "a different manifest is already staged for this SQLite snapshot",
            )
        if existing_by_hash is None:
            connection.execute(
                import_batch.insert(),
                {
                    "batch_hash": batch_hash,
                    "source_sha256": source_sha256,
                    "manifest_sha256": manifest_sha256,
                    "source_row_count": len(expected),
                },
            )
        elif (
            existing_by_hash["source_sha256"] != source_sha256
            or existing_by_hash["manifest_sha256"] != manifest_sha256
            or int(existing_by_hash["source_row_count"]) != len(expected)
        ):
            raise ImportContractError("staging_batch_conflict", "staged import batch metadata differs from this snapshot")

        existing_rows = connection.execute(
            select(raw_row.c.source_table, raw_row.c.source_pk, raw_row.c.row_hash)
            .where(raw_row.c.batch_hash == batch_hash)
        ).mappings().all()
        staged = {(row["source_table"], row["source_pk"]): row["row_hash"] for row in existing_rows}
        expected_hashes = {key: value[0] for key, value in expected.items()}
        if staged and staged != expected_hashes:
            raise ImportContractError("staging_row_conflict", "staged raw row differs from this snapshot")
        if not staged:
            connection.execute(
                raw_row.insert(),
                [
                    {
                        "batch_hash": batch_hash,
                        "source_table": source_table,
                        "source_pk": source_pk,
                        "row_hash": row_hash,
                        "source_row": row,
                    }
                    for (source_table, source_pk), (row_hash, row) in expected.items()
                ],
            )
    return context


def _load_staged_rows(connection, context: StagingContext) -> dict[str, list[dict[str, Any]]]:
    rows_by_table: dict[str, list[dict[str, Any]]] = {source_table: [] for source_table in LEGACY_COLUMNS}
    expected_count = connection.execute(
        select(context.import_batch.c.source_row_count).where(context.import_batch.c.batch_hash == context.batch_hash)
    ).scalar_one_or_none()
    if expected_count is None:
        raise ImportContractError("staging_batch_missing", "staged import batch metadata is missing")
    staged_rows = connection.execute(
        select(context.raw_row.c.source_table, context.raw_row.c.source_pk, context.raw_row.c.row_hash, context.raw_row.c.source_row)
        .where(context.raw_row.c.batch_hash == context.batch_hash)
    ).mappings().all()
    if len(staged_rows) != int(expected_count):
        raise ImportContractError("staging_row_conflict", "staged raw row count does not match its batch")
    seen: set[tuple[str, str]] = set()
    for staged in staged_rows:
        source_table = staged["source_table"]
        source_pk = staged["source_pk"]
        if source_table not in LEGACY_COLUMNS or (source_table, source_pk) in seen:
            raise ImportContractError("staging_row_conflict", "staged raw row key is not unique", table=source_table)
        row = dict(staged["source_row"])
        if str(row.get("id")) != source_pk or _row_hash(source_table, row) != staged["row_hash"]:
            raise ImportContractError("staging_row_conflict", "staged raw row hash does not match its payload", table=source_table)
        seen.add((source_table, source_pk))
        rows_by_table[source_table].append(row)
    return rows_by_table


def _target_rows_match(
    connection,
    translated_tables: Mapping[str, Table],
    source_tables: Mapping[str, list[dict[str, Any]]],
    report: dict[str, Any],
) -> bool:
    probe: dict[str, Any] = {"tables": []}
    for source_table in LEGACY_COLUMNS:
        _table_reconciliation(connection, source_table, translated_tables[source_table], source_tables[source_table], probe)
    matches = all(item["pk_match"] and item["column_match"] and item["reviewer_match"] for item in probe["tables"])
    if matches:
        report["tables"].extend(probe["tables"])
    return matches


def _legacy_judgment_payload(
    judgment: Mapping[str, Any],
    source_tables: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build the same ID-free actual-value snapshot as migration 0011."""

    judgment_id = judgment["id"]
    perspectives = sorted(
        (
            row
            for row in source_tables["perspective"]
            if row.get("judgment_id") == judgment_id
        ),
        key=lambda row: (
            row.get("position") is None,
            row.get("position") if row.get("position") is not None else 0,
            row["id"],
        ),
    )
    evidence_by_perspective: dict[Any, list[dict[str, Any]]] = {}
    for evidence in sorted(source_tables["evidence"], key=lambda row: row["id"]):
        evidence_by_perspective.setdefault(evidence.get("perspective_id"), []).append(
            evidence
        )

    counterarguments = sorted(
        (
            row
            for row in source_tables["counterargument"]
            if row.get("judgment_id") == judgment_id
        ),
        key=lambda row: (
            row.get("position") is None,
            row.get("position") if row.get("position") is not None else 0,
            row["id"],
        ),
    )
    verification_items = sorted(
        (
            row
            for row in source_tables["verification_item"]
            if row.get("judgment_id") == judgment_id
        ),
        key=lambda row: row["id"],
    )
    matched_performances = sorted(
        (
            row
            for row in source_tables["matched_performance"]
            if row.get("judgment_id") == judgment_id
        ),
        key=lambda row: row["id"],
    )
    return {
        "schema_version": judgment.get("schema_version"),
        "grade": judgment.get("grade"),
        "readiness": judgment.get("readiness"),
        "primary_focus": judgment.get("primary_focus"),
        "exclusion_category": judgment.get("exclusion_category"),
        "summary": judgment.get("summary"),
        "next_action": judgment.get("next_action"),
        "perspectives": [
            {
                "position": perspective.get("position"),
                "name": perspective.get("name"),
                "assessment": perspective.get("assessment"),
                "reason": perspective.get("reason"),
                "evidence": [
                    {
                        "source": evidence.get("source"),
                        "status": evidence.get("status"),
                        "fact": evidence.get("fact"),
                    }
                    for evidence in evidence_by_perspective.get(
                        perspective["id"], []
                    )
                ],
            }
            for perspective in perspectives
        ],
        "counterarguments": [
            {"position": row.get("position"), "text": row.get("text")}
            for row in counterarguments
        ],
        # The legacy projection never stored synthesis resolutions.  Preserve
        # that absence as unknown instead of deriving values from arguments.
        "counterargument_resolutions": None,
        "verification_items": [
            {
                "item": row.get("item"),
                "why": row.get("why"),
                "blocking": (
                    bool(row.get("blocking"))
                    if row.get("blocking") is not None
                    else None
                ),
                "status": row.get("status"),
            }
            for row in verification_items
        ],
        "matched_performances": [
            {
                "name": row.get("name"),
                "match_reason": row.get("match_reason"),
                "mismatch_or_limit": row.get("mismatch_or_limit"),
                "source": row.get("source"),
                "status": row.get("status"),
            }
            for row in matched_performances
        ],
    }


def _legacy_review_payload(
    review: Mapping[str, Any],
    source_tables: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    answers = sorted(
        (
            row
            for row in source_tables["verification_answer"]
            if row.get("review_id") == review["id"]
        ),
        key=lambda row: row["id"],
    )
    return review_revision_payload(
        disposition=review.get("disposition"),
        system_judgment_review=review.get("system_judgment_review"),
        corrected_grade=review.get("corrected_grade"),
        corrected_readiness=review.get("corrected_readiness"),
        weakest_perspective=review.get("weakest_perspective"),
        reason=review.get("reason"),
        reviewer=review.get("reviewer"),
        verification_answers=[
            (row.get("item"), row.get("answer")) for row in answers
        ],
    )


def _insert_or_validate_legacy_revision(
    connection,
    *,
    table: Table,
    notice_id: int,
    expected: Mapping[str, Any],
) -> None:
    """Insert one missing snapshot or prove the existing one is identical."""

    existing = connection.execute(
        select(table)
        .where(table.c.notice_id == notice_id)
        .order_by(table.c.sequence.asc())
    ).mappings().all()
    if existing:
        comparable = {
            key: value for key, value in expected.items() if key != "captured_at"
        }
        for row in existing:
            if all(
                _canonical_value(row.get(key)) == _canonical_value(value)
                for key, value in comparable.items()
            ):
                return
        raise ImportContractError(
            "legacy_revision_conflict",
            "existing revision history does not match the SQLite projection",
            table=table.name,
        )
    connection.execute(
        table.insert(),
        {**expected, "notice_id": notice_id, "sequence": 1},
    )


def _promote_legacy_revisions(
    connection,
    source_tables: Mapping[str, list[dict[str, Any]]],
) -> None:
    """Promote missing legacy snapshots without inferring historical lineage."""

    try:
        judgment_revision = Base.metadata.tables["judgment_revision"]
        review_revision = Base.metadata.tables["review_revision"]
        observation = Base.metadata.tables["notice_observation"]
    except KeyError as error:
        raise ImportContractError(
            "target_table_missing",
            "revision promotion table is not in the model",
            table=str(error.args[0]),
        ) from error

    captured_at = datetime.now(timezone.utc)
    for judgment in sorted(source_tables["judgment"], key=lambda row: row["id"]):
        payload, digest = canonical_payload_and_hash(
            _legacy_judgment_payload(judgment, source_tables)
        )
        _insert_or_validate_legacy_revision(
            connection,
            table=judgment_revision,
            notice_id=int(judgment["notice_pk"]),
            expected={
                "source_kind": "legacy_import",
                # The legacy judgment row had no direct run/execution/parent
                # binding.  Do not derive one from the notice projection.
                "run_id": None,
                "recording_execution_id": None,
                "source_revision_id": None,
                "payload_schema_version": JUDGMENT_PAYLOAD_SCHEMA,
                "payload_jsonb": payload,
                "payload_sha256": digest,
                "captured_at": captured_at,
            },
        )

    for review in sorted(source_tables["review"], key=lambda row: row["id"]):
        notice_id = int(review["notice_pk"])
        run_id = review.get("run_id")
        if run_id is not None:
            observed = connection.execute(
                select(observation.c.notice_id).where(
                    observation.c.notice_id == notice_id,
                    observation.c.run_id == run_id,
                )
            ).scalar_one_or_none()
            if observed is None:
                raise ImportContractError(
                    "legacy_review_observation_missing",
                    "legacy review run did not observe the same notice",
                    table="review",
                )
        payload, digest = canonical_payload_and_hash(
            _legacy_review_payload(review, source_tables)
        )
        review_captured_at = _coerce_target_value(
            review.get("updated_at"),
            review_revision.c.captured_at.type,
            table="review_revision",
            column="captured_at",
        )
        _insert_or_validate_legacy_revision(
            connection,
            table=review_revision,
            notice_id=notice_id,
            expected={
                "source_kind": "legacy_import",
                "run_id": run_id,
                # Historical judgment alignment is absent from SQLite and
                # must remain explicitly unknown.
                "judgment_revision_id": None,
                "payload_schema_version": REVIEW_PAYLOAD_SCHEMA,
                "payload_jsonb": payload,
                "payload_sha256": digest,
                "captured_at": review_captured_at,
            },
        )


def _promote_staged(
    destination: Engine,
    context: StagingContext,
    translated_tables: Mapping[str, Table],
    report: dict[str, Any],
) -> None:
    """Promote one committed batch, retaining staging if this transaction fails."""

    with destination.begin() as connection:
        source_tables = _load_staged_rows(connection, context)
        nonempty_target: str | None = None
        for target in translated_tables.values():
            if int(connection.execute(select(func.count()).select_from(target)).scalar_one()):
                nonempty_target = target.name
                break
        if nonempty_target is not None:
            if _target_rows_match(connection, translated_tables, source_tables, report):
                _promote_legacy_revisions(connection, source_tables)
                for source_table in LEGACY_COLUMNS:
                    _sequence_reconciliation(connection, translated_tables[source_table], source_tables[source_table], report, apply=False)
                _drop_staging_objects(connection, context)
                return
            raise ImportContractError("target_not_empty", "target table is not empty", table=nonempty_target)

        for source_table in LEGACY_COLUMNS:
            target = translated_tables[source_table]
            source_rows = source_tables[source_table]
            converted_rows = [_target_row(source_table, row, target) for row in source_rows]
            for converted in converted_rows:
                _validate_target_row_types(converted, target, connection.dialect)
            if converted_rows:
                connection.execute(target.insert(), converted_rows)
            _table_reconciliation(connection, source_table, target, source_rows, report)
            table_report = report["tables"][-1]
            if not all(table_report[key] for key in ("pk_match", "column_match", "reviewer_match")):
                raise ImportContractError("reconciliation_mismatch", "legacy table reconciliation failed", table=source_table)
        # The source snapshot's notice.run_id is migrated after all legacy
        # rows exist.  It is provenance for the imported row, not a column on
        # the cumulative Notice table.
        observation_table = Base.metadata.tables.get("notice_observation")
        if observation_table is None:
            raise ImportContractError("target_table_missing", "notice observation table is not in the model", table="notice_observation")
        run_generated_at = {
            str(row["id"]): row.get("generated_at")
            for row in source_tables["run"]
        }
        observation_rows = []
        for source_notice in source_tables["notice"]:
            run_id = source_notice.get("run_id")
            if not run_id:
                raise ImportContractError("notice_observation_missing_run", "legacy notice has no run id", table="notice")
            observed_at = run_generated_at.get(str(run_id))
            if not observed_at:
                raise ImportContractError("notice_observation_missing_run", "legacy notice references an unknown run", table="notice")
            observation_rows.append({
                "notice_id": source_notice["id"],
                "run_id": run_id,
                "observed_at": _coerce_target_value(
                    observed_at,
                    observation_table.c.observed_at.type,
                    table="notice_observation",
                    column="observed_at",
                ),
                "changed_fields_json": [],
            })
        if observation_rows:
            connection.execute(observation_table.insert(), observation_rows)
        _promote_legacy_revisions(connection, source_tables)
        # PostgreSQL sequences are non-transactional, so adjust them only after
        # every table has reconciled; a promotion failure retains staging.
        for source_table in LEGACY_COLUMNS:
            _sequence_reconciliation(connection, translated_tables[source_table], source_tables[source_table], report, apply=True)
        _drop_staging_objects(connection, context)


def run_import(*, sqlite_backup: Path, file_manifest: Path, mode: str, destination: Engine | None = None) -> dict[str, Any]:
    """Run ``dry-run`` or ``apply`` and return the stable reconciliation report."""

    if mode not in {"dry_run", "apply"}:
        raise ValueError("mode must be dry_run or apply")
    started = _now()
    report: dict[str, Any] | None = None
    try:
        _validate_source_path(sqlite_backup)
        source_sha256 = _source_hash(sqlite_backup)
        report = _empty_report(mode, source_sha256, started)
        manifest = _read_manifest(file_manifest, source_sha256)
        source_tables: dict[str, list[dict[str, Any]]] = {}
        with sqlite3.connect(f"file:{sqlite_backup}?mode=ro", uri=True) as source:
            source.row_factory = sqlite3.Row
            _validate_source_schema(source)
            for source_table in LEGACY_COLUMNS:
                source_tables[source_table] = [dict(row) for row in source.execute(f'SELECT * FROM "{source_table}"').fetchall()]
        _file_reconciliation(manifest, source_tables, file_manifest.parent, report)
        if report["errors"]:
            raise ImportContractError("preflight_reconciliation_failed", "source/file preflight reconciliation failed")

        translated_tables = {source_table: _target_table(target_name) for source_table, target_name in TARGET_TABLES.items()}
        manifest_sha256 = _manifest_sha256(manifest)
        validation_dialect = destination.dialect if destination is not None else None
        if mode == "dry_run":
            # Dry-run is deliberately destination-free. An explicitly supplied
            # isolated bind may validate its dialect, but no connection or
            # transaction is opened and no staging object is written.
            if validation_dialect is None:
                from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

                validation_dialect = postgresql_dialect()
            for source_table in LEGACY_COLUMNS:
                target = translated_tables[source_table]
                converted_rows = [_target_row(source_table, row, target) for row in source_tables[source_table]]
                for converted in converted_rows:
                    _validate_target_row_types(converted, target, validation_dialect)
                _table_reconciliation(None, source_table, target, source_tables[source_table], report, dry_run=True)
                table_report = report["tables"][-1]
                if not all(table_report[key] for key in ("pk_match", "column_match", "reviewer_match")):
                    raise ImportContractError("reconciliation_mismatch", "legacy table reconciliation failed", table=source_table)
                _sequence_reconciliation(None, target, source_tables[source_table], report, apply=False)
        else:
            if destination is None:
                from ..core import engine as application_engine

                destination = application_engine
            if destination.dialect.name != "postgresql":
                raise ImportContractError("postgresql_destination_required", "apply mode requires a PostgreSQL destination")
            destination = schema_bound(destination)
            context = _stage_snapshot(
                destination,
                source_tables,
                source_sha256=source_sha256,
                manifest_sha256=manifest_sha256,
            )
            _promote_staged(destination, context, translated_tables, report)
    except ImportContractError as exc:
        if report is None:
            source_hash = ""
            try:
                source_hash = _source_hash(sqlite_backup) if sqlite_backup.is_file() else ""
            except OSError:
                pass
            report = _empty_report(mode, source_hash, started)
        report["errors"].append(_error(exc))
    except OSError:
        if report is None:
            report = _empty_report(mode, "", started)
        report["errors"].append(_error(ImportContractError("snapshot_io_error", "snapshot or manifest could not be read")))
    except sqlite3.Error:
        if report is None:
            report = _empty_report(mode, "", started)
        report["errors"].append(_error(ImportContractError("sqlite_snapshot_error", "SQLite backup could not be opened or read")))
    except Exception:
        # Destination driver/constraint errors are reported without copying
        # DSNs, credentials, or internal paths into the reconciliation file.
        if report is None:
            report = _empty_report(mode, "", started)
        report["errors"].append(_error(ImportContractError("destination_error", "destination migration failed; inspect database logs")))
    assert report is not None
    report["completed_at"] = _now()
    report["success"] = not report["errors"] and all(item["pk_match"] and item["column_match"] and item["reviewer_match"] for item in report["tables"]) and report["files"]["size_match"] and report["files"]["hash_match"]
    return report


def write_report(report: Mapping[str, Any], path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("--report must be an absolute writable path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a read-only SQLite backup into PostgreSQL")
    parser.add_argument("--sqlite-backup", type=Path, required=True)
    parser.add_argument("--file-manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_const", dest="mode", const="dry_run")
    mode.add_argument("--apply", action="store_const", dest="mode", const="apply")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_import(sqlite_backup=args.sqlite_backup, file_manifest=args.file_manifest, mode=args.mode)
    write_report(report, args.report)
    return 0 if report["success"] else 2


if __name__ == "__main__":
    sys.exit(main())
