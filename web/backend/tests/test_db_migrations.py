from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


def run_alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )


def test_empty_database_upgrade_creates_runtime_tables(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    result = run_alembic(database, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        assert "alembic_version" in tables
        assert "screening_execution" in tables
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0002_screening_runtime"


def test_startup_does_not_upgrade_a_behind_database(tmp_path: Path) -> None:
    database = tmp_path / "behind.db"
    assert run_alembic(database, "upgrade", "0001_existing_schema").returncode == 0
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    probe = subprocess.run(
        [sys.executable, "-c", "from app.db import init_db; init_db()"],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert probe.returncode != 0
    assert "alembic upgrade head" in probe.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0001_existing_schema"


def test_unknown_revision_is_rejected_without_change(tmp_path: Path) -> None:
    database = tmp_path / "unknown.db"
    assert run_alembic(database, "upgrade", "head").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("update alembic_version set version_num='not-known'")
        connection.commit()
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    probe = subprocess.run(
        [sys.executable, "-m", "app.db_admin", "migrate", "--backup-manifest", str(database) + ".manifest.json", "--confirm-service-stopped"],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert probe.returncode != 0


def test_manifest_and_confirmation_are_required_before_migration(tmp_path: Path) -> None:
    database = tmp_path / "database.db"
    backup = tmp_path / "backup.db"
    assert run_alembic(database, "upgrade", "head").returncode == 0
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    backup_result = subprocess.run(
        [sys.executable, "-m", "app.db_admin", "backup", "--output", str(backup)],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert backup_result.returncode == 0, backup_result.stderr
    manifest = Path(str(backup) + ".manifest.json")
    before = database.read_bytes()
    no_confirm = subprocess.run(
        [sys.executable, "-m", "app.db_admin", "migrate", "--backup-manifest", str(manifest)],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert no_confirm.returncode != 0
    assert database.read_bytes() == before


def test_partial_unversioned_baseline_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "database.db"
    backup = tmp_path / "backup.db"
    assert run_alembic(database, "upgrade", "0001_existing_schema").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE attachment")
        connection.execute("DELETE FROM alembic_version")
        connection.commit()
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    # The backup itself is valid SQLite but the source shape is intentionally
    # partial; migrate must refuse it before stamping or creating new tables.
    backup_result = subprocess.run(
        [sys.executable, "-m", "app.db_admin", "backup", "--output", str(backup)],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert backup_result.returncode == 0
    result = subprocess.run(
        [sys.executable, "-m", "app.db_admin", "migrate", "--backup-manifest", str(backup) + ".manifest.json", "--confirm-service-stopped"],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("select name from sqlite_master where type='table' and name='screening_execution'").fetchone() is None


def test_unversioned_exact_baseline_migrates_a_backup_copy_and_preserves_core_rows(tmp_path: Path) -> None:
    database = tmp_path / "database.db"
    backup = tmp_path / "backup.db"
    assert run_alembic(database, "upgrade", "0001_existing_schema").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("insert into run(id, timezone, generated_at, status) values ('r1', 'Asia/Seoul', '2026-01-01T00:00:00+00:00', 'active')")
        connection.execute("insert into notice(run_id, notice_key) values ('r1', 'n1')")
        notice_pk = connection.execute("select id from notice where notice_key='n1'").fetchone()[0]
        connection.execute("insert into judgment(notice_pk) values (?)", (notice_pk,))
        connection.execute("insert into review(notice_pk, run_id, created_at, updated_at) values (?, 'r1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')", (notice_pk,))
        connection.execute("insert into attachment(notice_pk, created_at) values (?, '2026-01-01T00:00:00+00:00')", (notice_pk,))
        connection.execute("delete from alembic_version")
        connection.commit()
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    assert subprocess.run([sys.executable, "-m", "app.db_admin", "backup", "--output", str(backup)], cwd=BACKEND, env=env, text=True, capture_output=True).returncode == 0
    result = subprocess.run([sys.executable, "-m", "app.db_admin", "migrate", "--backup-manifest", str(backup) + ".manifest.json", "--confirm-service-stopped"], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0002_screening_runtime"
        assert [connection.execute(f"select count(*) from {table}").fetchone()[0] for table in ("run", "notice", "judgment", "review", "attachment")] == [1, 1, 1, 1, 1]
