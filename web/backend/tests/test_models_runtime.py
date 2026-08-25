from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings


BACKEND = Path(__file__).resolve().parents[1]


def upgrade(database: Path) -> None:
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_tables_and_constraints_are_present(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
        assert {
            "screening_execution",
            "screening_attempt",
            "company_profile_snapshot",
            "screening_policy",
            "quality_gate",
            "quality_gate_evaluation",
            "quality_gate_review",
            "schedule_setting",
            "schedule_reservation",
            "schedule_execution",
            "always_on_state",
            "audit_event",
        } <= tables
        assert connection.execute("select daily_time, weekly_time, prespec_enabled from schedule_setting").fetchone() == ("02:00", "06:00", 0)
        assert connection.execute("select enabled, updated_by from always_on_state").fetchone() == (0, "system:migration")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, scope, status, requested_by, queued_at) "
                "values ('scr-NOT-LOWER', 'manual_run', 'full_run', '대기', 'tester', '2026-01-01T00:00:00+00:00')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into company_profile_snapshot(digest, version, source_kind, source_ref, artifact_path, created_at) "
                "values ('a'||printf('%064d', 1), 'company-profile.sha256:wrong', 'working_tree', 'HEAD', 'profile.md', '2026-01-01T00:00:00+00:00')"
            )


def test_model_defaults_and_heartbeat_invariant() -> None:
    settings = Settings()
    assert settings.model_name == "qwen3.8:27b"
    assert settings.model_base_url == "http://192.168.0.139:11434"
    assert settings.model_timeout == 180
    assert settings.model_keep_alive == "30m"
    assert settings.model_context == 16384
    assert settings.model_max_output == 2048
    assert settings.screen_concurrency == 1
    assert settings.heartbeat_seconds < settings.stale_seconds
    assert settings.stale_seconds >= settings.heartbeat_seconds * 3
    with pytest.raises(ValueError):
        Settings(heartbeat_seconds=20, stale_seconds=30)
    with pytest.raises(ValueError):
        Settings(screen_concurrency=2)
