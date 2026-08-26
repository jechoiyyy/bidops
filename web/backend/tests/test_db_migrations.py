from __future__ import annotations

import os
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


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
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0005_generation_config_binding"
        migration_event = connection.execute(
            "select event_id, actor, target_id, details_json from audit_event "
            "where event_type = 'db.migration'"
        ).fetchone()
        assert migration_event[0] == "audit-e7854deca36d619ac1921856bb9bdbcd"
        assert migration_event[1:] == (
            "system:migration",
            "0004_migration_audit",
            '{"migration_revision":"0004_migration_audit","action":"upgrade"}',
        )
    check = run_alembic(database, "check")
    assert check.returncode == 0, check.stderr + check.stdout


def test_generation_config_migration_backfills_and_freezes_execution_rows(tmp_path: Path) -> None:
    database = tmp_path / "generation-config.db"
    assert run_alembic(database, "upgrade", "0004_migration_audit").returncode == 0
    digest = "a" * 64

    def add_execution(connection: sqlite3.Connection, suffix: str, *, config: str | None = None) -> None:
        values = {
            "execution_id": "scr-" + suffix,
            "input_path": f"runs/{suffix}.json",
            "artifact_dir": f"runs/{suffix}",
            "digest": digest,
        }
        columns = "execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at"
        placeholders = ":execution_id, 'manual_run', 'r1', 'full_run', '대기', 'migration-test', 'p1', 'prompt-1', 'qwen3.8:27b', :digest, 'company-profile.sha256:' || :digest, :digest, :input_path, :digest, :artifact_dir, '2026-01-01T00:00:00+00:00'"
        if config is not None:
            columns += ", generation_config_json, generation_config_digest"
            placeholders += ", :config, :digest"
        connection.execute(f"insert into screening_execution({columns}) values ({placeholders})", {**values, "config": config})

    with sqlite3.connect(database) as connection:
        connection.execute("insert into run(id, timezone, generated_at, status) values ('r1', 'UTC', '2026-01-01T00:00:00+00:00', '성공')")
        connection.execute(
            "insert into company_profile_snapshot(digest, version, source_kind, source_ref, artifact_path, created_at) values (?, ?, 'working_tree', 'migration-test', ?, '2026-01-01T00:00:00+00:00')",
            (digest, "company-profile.sha256:" + digest, "web/data/profile-snapshots/" + digest + ".md"),
        )
        add_execution(connection, "1" * 32)
        connection.commit()

    assert run_alembic(database, "upgrade", "head").returncode == 0
    legacy_json = {
        "num_ctx": 16384,
        "num_predict": {"counterargument": 2048, "perspective": 2048, "synthesis": 2048},
        "schema_version": "bidops.generation-config.v1",
        "stream": False,
        "think": False,
    }
    with sqlite3.connect(database) as connection:
        row = connection.execute("select generation_config_json, generation_config_digest from screening_execution where execution_id=?", ("scr-" + "1" * 32,)).fetchone()
        assert json.loads(row[0]) == legacy_json
        assert row[1] == "f5005da40315a4d24edba05b9394e71dba6c1c3c5790c84e5cc43673215134aa"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update screening_execution set generation_config_digest=? where execution_id=?", ("b" * 64, "scr-" + "1" * 32))
        with pytest.raises(sqlite3.IntegrityError):
            add_execution(connection, "2" * 32, config="[]")
        trigger_names = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='trigger'")
        }
        assert {
            "screening_execution_generation_config_immutable",
            "screening_execution_generation_shape_insert",
            "quality_gate_generation_config_immutable",
            "quality_gate_generation_shape_insert",
            "quality_gate_generation_binding_insert",
            "quality_gate_generation_binding_update",
            "quality_gate_evaluation_generation_binding",
            "quality_gate_evaluation_generation_binding_update",
        } <= trigger_names


def test_migration_audit_is_idempotent_from_0003_and_safe_to_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration-audit.db"
    assert run_alembic(database, "upgrade", "0003_schedule_skipped_recovery").returncode == 0
    assert run_alembic(database, "upgrade", "head").returncode == 0
    assert run_alembic(database, "upgrade", "head").returncode == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0005_generation_config_binding"
        assert connection.execute(
            "select count(*) from audit_event where event_id = 'audit-e7854deca36d619ac1921856bb9bdbcd'"
        ).fetchone()[0] == 1
        assert connection.execute("pragma quick_check").fetchone()[0] == "ok"

    assert run_alembic(database, "downgrade", "0003_schedule_skipped_recovery").returncode == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from audit_event where event_id = 'audit-e7854deca36d619ac1921856bb9bdbcd'").fetchone()[0] == 0
    assert run_alembic(database, "upgrade", "head").returncode == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0005_generation_config_binding"
        assert connection.execute("select count(*) from audit_event where event_id = 'audit-e7854deca36d619ac1921856bb9bdbcd'").fetchone()[0] == 1


def test_skipped_recovery_trigger_upgrades_from_0002_and_downgrades(tmp_path: Path) -> None:
    database = tmp_path / "schedule-recovery.db"

    def add_skipped_execution(connection: sqlite3.Connection, number: int) -> tuple[str, str]:
        day = f"202608{number:02d}"
        run_key = f"{day}-{day}"
        target_id = "sched-" + f"{number:032x}"
        connection.execute(
            "insert into schedule_reservation(run_key, job_kind, window_from, window_to, timezone, created_at) "
            "values (?, 'daily', ?, ?, 'Asia/Seoul', ?)",
            (run_key, f"2026-08-{number:02d}", f"2026-08-{number:02d}", "2026-08-26T00:00:00+00:00"),
        )
        connection.execute(
            "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, skip_reason, requested_by) "
            "values (?, ?, 'daily', 'schedule', '건너뜀', 'duplicate reservation', 'system:scheduler')",
            (target_id, run_key),
        )
        return run_key, target_id

    def add_recovery(connection: sqlite3.Connection, run_key: str, target_id: str, number: int) -> None:
        connection.execute(
            "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, recovery_of_execution_id, requested_by) "
            "values (?, ?, 'daily', 'manual', '예약', ?, 'operator:test')",
            ("sched-" + f"{number:032x}", run_key, target_id),
        )

    assert run_alembic(database, "upgrade", "0002_screening_runtime").returncode == 0
    with sqlite3.connect(database) as connection:
        run_key, target_id = add_skipped_execution(connection, 1)
        with pytest.raises(sqlite3.IntegrityError):
            add_recovery(connection, run_key, target_id, 2)
        connection.commit()
        projection_sql = {
            row[0]: row[1]
            for row in connection.execute(
                "select name, sql from sqlite_master where type='trigger' and name in ('screening_policy_projection_changed', 'quality_gate_evaluation_projection_changed')"
            )
        }
        assert all("audit_event" not in sql for sql in projection_sql.values())

    # An already deployed 0002 database receives the new trigger semantics.
    upgraded = run_alembic(database, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(database) as connection:
        run_key, target_id = add_skipped_execution(connection, 3)
        add_recovery(connection, run_key, target_id, 4)
        connection.commit()
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0005_generation_config_binding"
        projection_sql = {
            row[0]: row[1]
            for row in connection.execute(
                "select name, sql from sqlite_master where type='trigger' and name in ('screening_policy_projection_changed', 'quality_gate_evaluation_projection_changed')"
            )
        }
        assert set(projection_sql) == {
            "screening_policy_projection_changed",
            "quality_gate_evaluation_projection_changed",
        }
        assert all("audit_event" in sql for sql in projection_sql.values())

    downgraded = run_alembic(database, "downgrade", "0002_screening_runtime")
    assert downgraded.returncode == 0, downgraded.stderr
    with sqlite3.connect(database) as connection:
        run_key, target_id = add_skipped_execution(connection, 5)
        with pytest.raises(sqlite3.IntegrityError):
            add_recovery(connection, run_key, target_id, 6)
        connection.rollback()
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0002_screening_runtime"
        projection_sql = {
            row[0]: row[1]
            for row in connection.execute(
                "select name, sql from sqlite_master where type='trigger' and name in ('screening_policy_projection_changed', 'quality_gate_evaluation_projection_changed')"
            )
        }
        assert all("audit_event" not in sql for sql in projection_sql.values())


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
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_data["source_snapshot_fingerprint"]
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


def test_migrate_rejects_source_changed_after_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "database.db"
    backup = tmp_path / "backup.db"
    assert run_alembic(database, "upgrade", "head").returncode == 0
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    with sqlite3.connect(database) as connection:
        connection.execute("pragma journal_mode=wal")
        connection.execute(
            "insert into audit_event(event_id, event_type, actor, target_type, target_id, occurred_at, details_json) values ('audit-' || printf('%032d', 1), 'test', 'tester', 'run', 'r1', ?, '{}')",
            ("2026-01-01T00:00:00+00:00",),
        )
        connection.commit()
    assert subprocess.run([sys.executable, "-m", "app.db_admin", "backup", "--output", str(backup)], cwd=BACKEND, env=env, text=True, capture_output=True).returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute(
            "update audit_event set details_json=? where event_id='audit-' || printf('%032d', 1)",
            ('{"changed": true}',),
        )
        connection.commit()
    result = subprocess.run([sys.executable, "-m", "app.db_admin", "migrate", "--backup-manifest", str(backup) + ".manifest.json", "--confirm-service-stopped"], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "source DB changed since backup" in result.stderr


def test_migrate_missing_source_does_not_recreate_deleted_database(tmp_path: Path) -> None:
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
    database.unlink()
    result = subprocess.run(
        [sys.executable, "-m", "app.db_admin", "migrate", "--backup-manifest", str(backup) + ".manifest.json", "--confirm-service-stopped"],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert not database.exists()
    assert "source DB does not exist" in result.stderr


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


def test_unversioned_baseline_with_extra_sqlite_objects_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "database.db"
    backup = tmp_path / "backup.db"
    assert run_alembic(database, "upgrade", "0001_existing_schema").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("delete from alembic_version")
        connection.execute("create trigger legacy_extra_trigger after insert on run begin select 1; end")
        connection.execute("create view legacy_extra_view as select id from run")
        connection.commit()
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    assert subprocess.run([sys.executable, "-m", "app.db_admin", "backup", "--output", str(backup)], cwd=BACKEND, env=env, text=True, capture_output=True).returncode == 0
    result = subprocess.run([sys.executable, "-m", "app.db_admin", "migrate", "--backup-manifest", str(backup) + ".manifest.json", "--confirm-service-stopped"], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "backup remains" in result.stderr


def test_startup_check_does_not_create_missing_database(tmp_path: Path) -> None:
    database = tmp_path / "not-created.db"
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    probe = subprocess.run([sys.executable, "-c", "from app.db import init_db; init_db()"], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert probe.returncode != 0
    assert not database.exists()
    assert "alembic upgrade head" in probe.stderr


def test_startup_empty_database_allows_explicit_upgrade_guidance(tmp_path: Path) -> None:
    database = tmp_path / "empty-existing.db"
    database.touch()
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    probe = subprocess.run([sys.executable, "-c", "from app.db import init_db; init_db()"], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert probe.returncode != 0
    assert "alembic upgrade head" in probe.stderr
    assert database.exists()


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
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0005_generation_config_binding"
        assert [connection.execute(f"select count(*) from {table}").fetchone()[0] for table in ("run", "notice", "judgment", "review", "attachment")] == [1, 1, 1, 1, 1]
        assert connection.execute("pragma foreign_key_check").fetchall() == []
        assert connection.execute("pragma quick_check").fetchone()[0] == "ok"
