from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
DIGEST = "a" * 64
PROFILE_VERSION = f"company-profile.sha256:{DIGEST}"
MODEL_DIGEST = "b" * 64


def upgrade(database: Path) -> None:
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def seed_base(connection: sqlite3.Connection) -> None:
    now = "2026-01-01T00:00:00+00:00"
    connection.execute("insert into run(id, timezone, generated_at, status) values ('r1', 'Asia/Seoul', ?, 'active')", (now,))
    connection.execute("insert into notice(run_id, notice_key) values ('r1', 'notice-1')")
    connection.execute("insert into company_profile_snapshot(digest, version, source_kind, source_ref, artifact_path, created_at) values (?, ?, 'working_tree', 'HEAD', 'profile.md', ?)", (DIGEST, PROFILE_VERSION, now))
    body = "{}"
    connection.execute("insert into screening_policy(policy_version, prompt_version, content_digest, status, perspective_prompts_json, counterargument_prompt_json, synthesis_prompt_json, candidate_selection_json, thresholds_json, created_at, created_by) values ('p1', 'prompt-1', ?, 'draft', ?, ?, ?, ?, ?, ?, 'tester')", (DIGEST, body, body, body, body, body, now))
    connection.commit()


def add_execution(connection: sqlite3.Connection, execution_id: str, suffix: str) -> None:
    connection.execute("insert into screening_execution(execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at) values (?, 'manual_run', 'r1', 'full_run', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, ?)", (execution_id, MODEL_DIGEST, PROFILE_VERSION, DIGEST, f"runs/{suffix}.json", DIGEST, f"runs/{suffix}", "2026-01-01T00:00:00+00:00"))


def test_exact_columns_nullability_and_ids(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with sqlite3.connect(database) as connection:
        seed_base(connection)
        add_execution(connection, "scr-" + "1" * 32, "a")
        add_execution(connection, "scr-" + "2" * 32, "b")
        columns = {row[1]: row[3] for row in connection.execute("pragma table_info(screening_execution)")}
        assert columns["source_run_id"] == 1
        assert columns["policy_version"] == 1
        assert columns["model_digest"] == 1
        assert columns["input_artifact_path"] == 1
        assert "input_metadata" not in columns
        assert {row[1] for row in connection.execute("pragma table_info(screening_attempt)")} >= {"attempt_id", "started_at", "finished_at", "prompt_eval_duration_ns", "total_duration_ns", "error_summary"}
        assert connection.execute("pragma table_info(quality_gate_evaluation)").fetchall()[0][1] == "evaluation_id"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("insert into screening_execution(execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at) values ('scr-' || printf('%032d', 3), 'manual_run', 'r1', 'full_run', 'bogus', 'tester', 'p1', 'prompt-1', 'm', ?, ?, ?, 'runs/c.json', ?, 'runs/c', ?)", (MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"))


def test_gate_evaluation_append_and_input_immutability(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with sqlite3.connect(database) as connection:
        seed_base(connection)
        add_execution(connection, "scr-" + "1" * 32, "a")
        add_execution(connection, "scr-" + "2" * 32, "b")
        connection.execute("insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, completed_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '완료', '통과', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')", ("gate-" + "1" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}", "[]"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update quality_gate set prompt_version='changed' where gate_id=?", ("gate-" + "1" * 32,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update quality_gate set purpose='model_comparison' where gate_id=?", ("gate-" + "1" * 32,))
        gateeval = "gateeval-" + "1" * 32
        connection.execute("insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 1, '통과', '{}', '[]', 0, 0, ?)", (gateeval, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 3, '통과', '{}', '[]', 0, 0, ?)", ("gateeval-" + "2" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"))
        connection.execute("insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 2, '통과', '{}', '[]', 0, 0, ?)", ("gateeval-" + "2" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update quality_gate_evaluation set result_status='미달'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("delete from quality_gate_evaluation")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, policy_version='p1', model_name='qwen3.8:27b', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", (gateeval, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, policy_version='p1', model_name='qwen3.8:27b', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", ("gateeval-" + "2" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update always_on_state set model_digest=? where singleton_id=1", ("c" * 64,))


def test_policy_body_and_single_notice_identity_are_protected(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with sqlite3.connect(database) as connection:
        seed_base(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update screening_policy set perspective_prompts_json=? where policy_version='p1'", ('{"changed": true}',))
        notice_pk = connection.execute("select id from notice where notice_key='notice-1'").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, notice_pk, notice_id, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at) "
                "values (?, 'cli_single', 'r1', 'single_notice', ?, 'wrong-notice', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, 'runs/single.json', ?, 'runs/single', ?)",
                ("scr-" + "3" * 32, notice_pk, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"),
            )


def test_exact_environment_names_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BIDOPS_OLLAMA_ENDPOINT", "BIDOPS_MODEL_BASE_URL", "BIDOPS_HEARTBEAT_SECONDS", "BIDOPS_STALE_SECONDS", "BIDOPS_LIVE_TEST", "BIDOPS_OLLAMA_THINK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BIDOPS_OLLAMA_BASE_URL", "http://example:11434")
    monkeypatch.setenv("BIDOPS_SCREEN_HEARTBEAT_SECONDS", "5")
    monkeypatch.setenv("BIDOPS_SCREEN_STALE_AFTER_SECONDS", "60")
    assert Settings().model_base_url == "http://example:11434"
    defaults = Settings()
    assert defaults.model_name == "qwen3.8:27b"
    assert defaults.model_timeout == 180
    assert defaults.model_context == 16384
    assert defaults.model_max_output == 2048
    assert defaults.screen_concurrency == 1
    assert defaults.schedule_daily_time == "02:00"
    assert defaults.schedule_weekly_time == "06:00"
    assert defaults.schedule_prespec is False
    assert defaults.live_test is False
    with pytest.raises(ValueError):
        Settings(heartbeat_seconds=20, stale_seconds=30)
    with pytest.raises(ValueError):
        Settings(screen_concurrency=2)
    with pytest.raises(ValueError):
        Settings(model_timeout=0)
    with pytest.raises(ValueError):
        Settings(model_context=0)
    with pytest.raises(ValueError):
        Settings(model_max_output=0)
    with pytest.raises(ValueError):
        Settings(schedule_daily_time="24:00")
