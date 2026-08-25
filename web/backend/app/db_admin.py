"""Explicit, operator-run SQLite backup, migration, and verification tools.

The application never imports this module during normal startup.  Every
operation is deliberately explicit so an operator can stop the service and
retain a recoverable backup when a migration fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from .config import get_settings
from .db import ALEMBIC_HEAD, MIGRATION_COMMAND

BACKEND = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "0001_existing_schema"
CORE_TABLES = ("run", "notice", "judgment", "review", "attachment")


class DBAdminError(RuntimeError):
    """An operator-actionable database administration error."""


def _database_path() -> Path:
    settings = get_settings()
    if settings.database_url:
        url = make_url(settings.database_url)
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            raise DBAdminError("db_admin requires a file-backed SQLite BIDOPS_DATABASE_URL")
        path = Path(url.database)
        return path if path.is_absolute() else Path.cwd() / path
    return settings.database_path


def _manifest_path(backup: Path) -> Path:
    return Path(str(backup) + ".manifest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_fingerprint(path: Path) -> str:
    """Hash the logical SQLite snapshot, independent of page layout/WAL files."""

    digest = hashlib.sha256()
    with sqlite3.connect(path) as connection:
        for statement in connection.iterdump():
            if statement not in {"BEGIN TRANSACTION;", "COMMIT;"}:
                digest.update(statement.encode("utf-8"))
                digest.update(b"\n")
    return digest.hexdigest()


def _sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as destination_connection:
        source_connection.backup(destination_connection)
        destination_connection.commit()


def _run_alembic(database: Path, *arguments: str) -> None:
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise DBAdminError(f"Alembic {' '.join(arguments)} failed: {detail}")


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _schema_signature(path: Path) -> dict[str, Any]:
    """Return a structural SQLite signature, excluding Alembic bookkeeping."""

    with sqlite3.connect(path) as connection:
        names = sorted(name for name in _tables(connection) if name != "alembic_version")
        objects = [
            (row[0], row[1], row[2], " ".join((row[4] or "").lower().split()))
            for row in connection.execute(
                "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' AND name <> 'alembic_version' "
                "ORDER BY type, name"
            )
        ]
        result: dict[str, Any] = {"tables": names, "objects": objects, "schemas": {}}
        for name in names:
            columns = [
                tuple(row)
                for row in connection.execute(f'PRAGMA table_info("{name}")')
            ]
            foreign_keys = [
                tuple(row)
                for row in connection.execute(f'PRAGMA foreign_key_list("{name}")')
            ]
            indexes: list[tuple[Any, ...]] = []
            for row in connection.execute(f'PRAGMA index_list("{name}")'):
                index_name, unique, origin, partial = row[1], row[2], row[3], row[4]
                index_columns = tuple(
                    item[2]
                    for item in connection.execute(f'PRAGMA index_info("{index_name}")')
                )
                indexes.append((index_name, unique, origin, partial, index_columns))
            sql_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            create_sql = " ".join((sql_row[0] or "").lower().split())
            result["schemas"][name] = {
                "columns": columns,
                "foreign_keys": foreign_keys,
                "indexes": sorted(indexes),
                "create_sql": create_sql,
            }
        return result


def _baseline_is_exact(path: Path) -> tuple[bool, str]:
    """Compare an unversioned DB with a schema produced by revision 0001."""

    with tempfile.TemporaryDirectory(prefix="bidops-baseline-") as temporary:
        expected = Path(temporary) / "expected.db"
        _run_alembic(expected, "upgrade", BASELINE_REVISION)
        actual_signature = _schema_signature(path)
        expected_signature = _schema_signature(expected)
    if actual_signature != expected_signature:
        return False, "existing tables, columns, indexes, foreign keys, or CHECK constraints differ from 0001"
    return True, "exact 0001 baseline"


def _revision(path: Path) -> str | None:
    with sqlite3.connect(path) as connection:
        if "alembic_version" not in _tables(connection):
            return None
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None


def _integrity(path: Path) -> tuple[list[tuple[Any, ...]], str]:
    with sqlite3.connect(path) as connection:
        foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        quick = connection.execute("PRAGMA quick_check").fetchone()
        return foreign_keys, str(quick[0] if quick else "")


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
            for table in CORE_TABLES
        }


def _validate_version(path: Path) -> str | None:
    revision = _revision(path)
    if revision not in {None, BASELINE_REVISION, ALEMBIC_HEAD}:
        raise DBAdminError(f"unknown database revision {revision!r}; no changes were made")
    return revision


def backup(output: Path) -> Path:
    source = _database_path().resolve()
    output = output.resolve()
    manifest_path = _manifest_path(output)
    if not source.is_file():
        raise DBAdminError(f"source database does not exist: {source}")
    if output.exists() or manifest_path.exists():
        raise DBAdminError(f"backup output already exists (no overwrite): {output}")
    if output == source:
        raise DBAdminError("backup output must differ from the source database")
    _sqlite_backup(source, output)
    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": "bidops.sqlite-backup.v1",
        "source_db_path": str(source),
        "backup_db_path": str(output),
        "source_sha256": _sha256(source),
        "backup_sha256": _sha256(output),
        "source_snapshot_fingerprint": _snapshot_fingerprint(output),
        "created_at": created_at,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"backup: {output}")
    print(f"manifest: {manifest_path}")
    return manifest_path


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DBAdminError(f"invalid backup manifest: {path}") from exc
    if not isinstance(value, dict):
        raise DBAdminError("backup manifest must be a JSON object")
    required = {
        "source_db_path",
        "backup_db_path",
        "source_sha256",
        "backup_sha256",
        "source_snapshot_fingerprint",
        "created_at",
    }
    if not required.issubset(value):
        raise DBAdminError("backup manifest is missing original path, digest, or creation time")
    try:
        created = datetime.fromisoformat(str(value["created_at"]))
    except ValueError as exc:
        raise DBAdminError("backup manifest created_at is not ISO-8601") from exc
    if created.tzinfo is None:
        raise DBAdminError("backup manifest created_at must include a timezone")
    return value


def _prepare_copy(path: Path, temporary: Path) -> str:
    revision = _validate_version(path)
    if revision is None:
        with sqlite3.connect(path) as connection:
            present = _tables(connection)
        if not present:
            raise DBAdminError("unversioned empty database cannot be baselined; use alembic upgrade head")
        exact, reason = _baseline_is_exact(path)
        if not exact:
            raise DBAdminError(f"unversioned database rejected: {reason}")
        _sqlite_backup(path, temporary)
        _run_alembic(temporary, "stamp", BASELINE_REVISION)
        revision = BASELINE_REVISION
    else:
        _sqlite_backup(path, temporary)
    _run_alembic(temporary, "upgrade", "head")
    return revision


def migrate(manifest_path: Path, confirm_service_stopped: bool) -> None:
    if not confirm_service_stopped:
        raise DBAdminError("refusing to migrate without --confirm-service-stopped; no changes were made")
    manifest = _read_manifest(manifest_path.resolve())
    source = _database_path().resolve()
    backup_path = Path(str(manifest["backup_db_path"])).resolve()
    if Path(str(manifest["source_db_path"])).resolve() != source:
        raise DBAdminError("backup manifest source DB path does not match configured DB; no changes were made")
    if not backup_path.is_file():
        raise DBAdminError(f"backup path is missing: {backup_path}")
    if _sha256(backup_path) != manifest["backup_sha256"]:
        raise DBAdminError(f"backup digest mismatch; backup remains at {backup_path}")
    try:
        backup_fingerprint = _snapshot_fingerprint(backup_path)
        source_fingerprint = _snapshot_fingerprint(source)
    except (OSError, sqlite3.Error) as exc:
        raise DBAdminError(f"database snapshot fingerprint cannot be verified; backup remains at {backup_path}") from exc
    if backup_fingerprint != manifest["source_snapshot_fingerprint"]:
        raise DBAdminError(f"backup snapshot fingerprint mismatch; backup remains at {backup_path}")
    if source_fingerprint != manifest["source_snapshot_fingerprint"]:
        raise DBAdminError(f"source DB changed since backup; backup remains at {backup_path}")
    if source == backup_path:
        raise DBAdminError("manifest source and backup paths must differ")

    try:
        before_counts = _counts(backup_path)
        source_counts = _counts(source)
    except sqlite3.Error as exc:
        raise DBAdminError(f"core table row counts cannot be read; backup remains at {backup_path}") from exc
    if source_counts != before_counts:
        raise DBAdminError(f"source and backup row counts differ; backup remains at {backup_path}")
    fk_before, quick_before = _integrity(backup_path)
    if fk_before or quick_before != "ok":
        raise DBAdminError(f"backup integrity check failed; backup remains at {backup_path}")
    source_fk_before, source_quick_before = _integrity(source)
    if source_fk_before or source_quick_before != "ok":
        raise DBAdminError(f"source integrity check failed; backup remains at {backup_path}")
    with tempfile.TemporaryDirectory(prefix="bidops-migrate-") as temporary:
        migrated_copy = Path(temporary) / "migrated.db"
        try:
            _prepare_copy(backup_path, migrated_copy)
        except DBAdminError as exc:
            raise DBAdminError(f"{exc}; backup remains at {backup_path}") from exc
        fk_after, quick_after = _integrity(migrated_copy)
        after_counts = _counts(migrated_copy)
        if fk_after or quick_after != "ok" or after_counts != before_counts:
            raise DBAdminError(f"migration copy validation failed; backup remains at {backup_path}")

        try:
            source_before_revision = _validate_version(source)
        except DBAdminError as exc:
            raise DBAdminError(f"{exc}; backup remains at {backup_path}") from exc
        if source_before_revision is None:
            exact, reason = _baseline_is_exact(source)
            if not exact:
                raise DBAdminError(f"source unversioned database rejected: {reason}; backup remains at {backup_path}")
            try:
                _run_alembic(source, "stamp", BASELINE_REVISION)
            except DBAdminError as exc:
                raise DBAdminError(f"{exc}; backup remains at {backup_path}") from exc
        try:
            _run_alembic(source, "upgrade", "head")
        except DBAdminError as exc:
            raise DBAdminError(f"{exc}; backup remains at {backup_path}") from exc
        if _revision(source) != ALEMBIC_HEAD or _counts(source) != before_counts:
            raise DBAdminError(f"live DB post-migration validation failed; backup remains at {backup_path}")
        fk_live, quick_live = _integrity(source)
        if fk_live or quick_live != "ok":
            raise DBAdminError(f"live DB integrity validation failed; backup remains at {backup_path}")
    print(f"migrated: {source} ({ALEMBIC_HEAD})")
    print(f"backup retained: {backup_path}")


def verify() -> None:
    path = _database_path().resolve()
    if not path.is_file():
        raise DBAdminError(f"database does not exist: {path}")
    revision = _revision(path)
    try:
        foreign_keys, quick = _integrity(path)
        counts = _counts(path)
    except sqlite3.Error as exc:
        raise DBAdminError(f"database structure cannot be verified: {path}") from exc
    print(f"revision: {revision or 'none'} (expected {ALEMBIC_HEAD})")
    print(f"foreign_key_check: {'ok' if not foreign_keys else foreign_keys}")
    print(f"quick_check: {quick}")
    for table, count in counts.items():
        print(f"{table}: {count}")
    if revision != ALEMBIC_HEAD or foreign_keys or quick != "ok":
        raise DBAdminError(f"database verification failed; run `{MIGRATION_COMMAND}` if revision is stale")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.db_admin")
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("--output", required=True, type=Path)
    migrate_parser = commands.add_parser("migrate")
    migrate_parser.add_argument("--backup-manifest", required=True, type=Path)
    migrate_parser.add_argument("--confirm-service-stopped", action="store_true")
    commands.add_parser("verify")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            backup(args.output)
        elif args.command == "migrate":
            migrate(args.backup_manifest, args.confirm_service_stopped)
        else:
            verify()
    except DBAdminError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
