from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.screening.generation_config import register_sqlite_functions

BACKEND = Path(__file__).resolve().parents[1]
DIGEST = "a" * 64
PROFILE_VERSION = f"company-profile.sha256:{DIGEST}"
MODEL_DIGEST = "b" * 64


def validated_connect(database: Path | str) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    register_sqlite_functions(connection)
    return connection


def upgrade(database: Path) -> None:
    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = f"sqlite:///{database}"
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def seed_base(connection: sqlite3.Connection) -> None:
    now = "2026-01-01T00:00:00+00:00"
    connection.execute("insert into run(id, timezone, generated_at, status) values ('r1', 'Asia/Seoul', ?, 'active')", (now,))
    connection.execute("insert into notice(run_id, notice_key) values ('r1', 'notice-1')")
    connection.execute("insert into company_profile_snapshot(digest, version, source_kind, source_ref, artifact_path, created_at) values (?, ?, 'working_tree', 'docs/reference/company-profile.md', ?, ?)", (DIGEST, PROFILE_VERSION, f"web/data/profile-snapshots/{DIGEST}.md", now))
    body = "{}"
    connection.execute("insert into screening_policy(policy_version, prompt_version, content_digest, status, perspective_prompts_json, counterargument_prompt_json, synthesis_prompt_json, candidate_selection_json, thresholds_json, created_at, created_by) values ('p1', 'prompt-1', ?, 'draft', ?, ?, ?, ?, ?, ?, 'tester')", (DIGEST, body, body, body, body, body, now))
    connection.commit()


def add_execution(connection: sqlite3.Connection, execution_id: str, suffix: str) -> None:
    connection.execute("insert into screening_execution(execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at) values (?, 'manual_run', 'r1', 'full_run', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, ?)", (execution_id, MODEL_DIGEST, PROFILE_VERSION, DIGEST, f"runs/{suffix}.json", DIGEST, f"runs/{suffix}", "2026-01-01T00:00:00+00:00"))


def test_exact_columns_nullability_and_ids(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
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


def test_runtime_fk_delete_actions_are_explicit(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        connection.execute("pragma foreign_keys=on")
        seed_base(connection)
        add_execution(connection, "scr-" + "1" * 32, "a")
        connection.execute(
            "insert into screening_attempt(execution_id, notice_id, stage, attempt_no, status, trace_id, span_id, started_at, finished_at, response_artifact_path) "
            "values (?, 'notice-1', '기술 적합성', 1, 'success', 'trace', 'span', ?, ?, 'responses/a.json')",
            ("scr-" + "1" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("delete from run where id='r1'")
        connection.execute("delete from screening_execution where execution_id=?", ("scr-" + "1" * 32,))
        assert connection.execute("select count(*) from screening_attempt").fetchone()[0] == 0


def test_gate_evaluation_append_and_input_immutability(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        seed_base(connection)
        add_execution(connection, "scr-" + "1" * 32, "a")
        add_execution(connection, "scr-" + "2" * 32, "b")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, completed_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '완료', '통과', 'r1', '/absolute/sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')", ("gate-" + "0" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}", "[]"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, completed_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '완료', '통과', 'r1', 'sample.json', ?, '../decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')", ("gate-" + "0" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}", "[]"))
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
        connection.execute(
            "update screening_policy set status='active', active_slot=1, activated_at=?, activated_by='tester', quality_gate_result_id=? where policy_version='p1'",
            ("2026-01-01T00:00:00+00:00", "gateeval-" + "2" * 32),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, policy_version='p1', model_name='qwen3.8:27b', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", (gateeval, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, policy_version='p1', model_name='qwen3.8:27b', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", ("gateeval-" + "2" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update always_on_state set model_digest=? where singleton_id=1", ("c" * 64,))
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 3, '통과', '{\"passed\": 1}', '[\"ok\"]', 0, 0, ?)",
            ("gateeval-" + "3" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"),
        )
        assert connection.execute("select result_status, metrics_json, reasons_json from quality_gate where gate_id=?", ("gate-" + "1" * 32,)).fetchone() == ("통과", '{"passed": 1}', '["ok"]')
        assert connection.execute("select enabled from always_on_state where singleton_id=1").fetchone()[0] == 1
        assert connection.execute("select status, quality_gate_result_id from screening_policy where policy_version='p1'").fetchone() == ("active", "gateeval-" + "2" * 32)
        connection.execute(
            "update screening_policy set status='activation_candidate', active_slot=NULL, activated_at=NULL, activated_by=NULL, quality_gate_result_id=NULL where policy_version='p1'"
        )
        assert connection.execute("select enabled from always_on_state where singleton_id=1").fetchone()[0] == 0
        policy_disable_audits = connection.execute(
            "select event_type, actor, target_type, target_id, details_json from audit_event where event_type='schedule.always_on_disabled'"
        ).fetchall()
        assert len(policy_disable_audits) == 1
        assert policy_disable_audits[0] == (
            "schedule.always_on_disabled",
            "system:policy",
            "schedule",
            "1",
            '{"reason":"policy_inactive"}',
        )
        assert "secret" not in policy_disable_audits[0][-1]
        connection.execute(
            "update screening_policy set status='active', active_slot=1, activated_at=?, activated_by='tester', quality_gate_result_id=? where policy_version='p1'",
            ("2026-01-01T00:00:00+00:00", "gateeval-" + "3" * 32),
        )
        connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, policy_version='p1', model_name='qwen3.8:27b', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", ("gateeval-" + "3" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 4, '미달', '{\"passed\": 0}', '[\"failed\"]', 0, 0, ?)",
            ("gateeval-" + "4" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"),
        )
        assert connection.execute("select enabled from always_on_state where singleton_id=1").fetchone()[0] == 0
        assert connection.execute("select result_status, metrics_json, reasons_json from quality_gate where gate_id=?", ("gate-" + "1" * 32,)).fetchone() == ("미달", '{"passed": 0}', '["failed"]')
        quality_disable_audits = connection.execute(
            "select event_type, actor, target_type, target_id, details_json from audit_event where event_type='schedule.always_on_disabled' order by rowid"
        ).fetchall()
        assert len(quality_disable_audits) == 2
        assert quality_disable_audits[-1] == (
            "schedule.always_on_disabled",
            "system:quality-gate",
            "schedule",
            "1",
            '{"reason":"quality_gate_not_passing"}',
        )
        assert all("secret" not in row[-1] for row in quality_disable_audits)


def test_quality_gate_delete_cascades_evaluations(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        connection.execute("pragma foreign_keys=on")
        seed_base(connection)
        add_execution(connection, "scr-" + "1" * 32, "a")
        add_execution(connection, "scr-" + "2" * 32, "b")
        connection.execute(
            "insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, metrics_json, reasons_json, created_by) values (?, 'model_comparison', '대기', '미측정', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, ?, ?, 'tester')",
            ("gate-" + "9" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "{}", "[]"),
        )
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values ('gateeval-' || printf('%032d', 9), ?, 1, '미측정', '{}', '[]', 0, 0, ?)",
            ("gate-" + "9" * 32, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute("delete from quality_gate where gate_id=?", ("gate-" + "9" * 32,))
        assert connection.execute("select count(*) from quality_gate_evaluation where gate_id=?", ("gate-" + "9" * 32,)).fetchone()[0] == 0


def test_policy_body_and_single_notice_identity_are_protected(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
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


def test_single_notice_source_run_and_nonblank_identifiers_are_protected(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        seed_base(connection)
        connection.execute("insert into run(id, timezone, generated_at, status) values ('r2', 'Asia/Seoul', '2026-01-01T00:00:00+00:00', 'active')")
        notice_pk = connection.execute("select id from notice where notice_key='notice-1'").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, notice_pk, notice_id, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at) "
                "values (?, 'cli_single', 'r2', 'single_notice', ?, 'notice-1', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, 'runs/mismatch.json', ?, 'runs/mismatch', ?)",
                ("scr-" + "4" * 32, notice_pk, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at) "
                "values (?, 'manual_run', 'r1', 'full_run', '대기', 'tester', 'p1', 'prompt-1', ' ', ?, ?, ?, 'runs/nonblank.json', ?, 'runs/nonblank', ?)",
                ("scr-" + "5" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"),
            )


def test_screening_stop_metadata_is_consistent(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        seed_base(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, active_slot, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_reason, queued_at) values (?, 'manual_run', 'r1', 'full_run', '중지 요청', 1, 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, 'runs/stop-a.json', ?, 'runs/stop-a', 'user_requested', ?)",
                ("scr-" + "6" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, active_slot, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_requested_at, queued_at) values (?, 'manual_run', 'r1', 'full_run', '실행 중', 1, 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, 'runs/stop-b.json', ?, 'runs/stop-b', ?, ?)",
                ("scr-" + "7" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_reason, queued_at) values (?, 'manual_run', 'r1', 'full_run', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, 'runs/stop-c.json', ?, 'runs/stop-c', 'user_requested', ?)",
                ("scr-" + "8" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"),
            )
        connection.execute(
            "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, active_slot, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_requested_at, stop_requested_by, stop_reason, queued_at) values (?, 'manual_run', 'r1', 'full_run', '중지 요청', 1, 'tester', 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, 'runs/stop-d.json', ?, 'runs/stop-d', ?, 'tester', 'user_requested', ?)",
            ("scr-" + "9" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )


def test_audit_details_must_be_an_object(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into audit_event(event_id, event_type, actor, target_type, target_id, occurred_at, details_json) "
                "values (?, 'test', 'tester', 'run', 'r1', ?, ?)",
                ("audit-" + "1" * 32, "2026-01-01T00:00:00+00:00", "[]"),
            )


def test_profile_snapshot_ref_and_path_contract(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into company_profile_snapshot(digest, version, source_kind, source_ref, artifact_path, created_at) "
                "values (?, ?, 'git_blob', 'HEAD', ?, ?)",
                ("c" * 64, "company-profile.sha256:" + "c" * 64, "web/data/profile-snapshots/" + "c" * 64 + ".md", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into company_profile_snapshot(digest, version, source_kind, source_ref, artifact_path, created_at) "
                "values (?, ?, 'working_tree', 'docs/reference/company-profile.md', 'profile.md', ?)",
                ("d" * 64, "company-profile.sha256:" + "d" * 64, "2026-01-01T00:00:00+00:00"),
            )


def test_active_policy_requires_latest_passing_operational_gate(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        seed_base(connection)
        add_execution(connection, "scr-" + "1" * 32, "a")
        add_execution(connection, "scr-" + "2" * 32, "b")
        connection.execute(
            "insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, completed_at, metrics_json, reasons_json, created_by) "
            "values (?, 'operational_approval', '완료', '통과', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')",
            ("gate-" + "1" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}", "[]"),
        )
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) "
            "values (?, ?, 1, '통과', '{}', '[]', 0, 0, ?)",
            ("gateeval-" + "1" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) "
            "values (?, ?, 2, '미달', '{}', '[]', 0, 0, ?)",
            ("gateeval-" + "2" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "update screening_policy set status='active', active_slot=1, activated_at=?, activated_by='tester', quality_gate_result_id=? where policy_version='p1'",
                ("2026-01-01T00:00:00+00:00", "gateeval-" + "1" * 32),
            )


def test_active_policy_requires_completed_operational_gate(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        seed_base(connection)
        add_execution(connection, "scr-" + "1" * 32, "a")
        add_execution(connection, "scr-" + "2" * 32, "b")
        connection.execute(
            "insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '실행 중', '통과', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8:27b', ?, ?, ?, ?, ?, ?, '{}', '[]', 'tester')",
            ("gate-" + "8" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 1, '통과', '{}', '[]', 0, 0, ?)",
            ("gateeval-" + "8" * 32, "gate-" + "8" * 32, "2026-01-01T00:00:00+00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "update screening_policy set status='active', active_slot=1, activated_at=?, activated_by='tester', quality_gate_result_id=? where policy_version='p1'",
                ("2026-01-01T00:00:00+00:00", "gateeval-" + "8" * 32),
            )


def test_schedule_duplicate_and_recovery_relationships_are_restricted(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        connection.execute(
            "insert into schedule_reservation(run_key, job_kind, window_from, window_to, timezone, created_at) values ('rk-daily', 'daily', '2026-01-01', '2026-01-01', 'Asia/Seoul', ?)",
            ("2026-01-01T00:00:00+00:00",),
        )
        connection.execute(
            "insert into schedule_reservation(run_key, job_kind, window_from, window_to, timezone, created_at) values ('rk-weekly', 'weekly', '2026-01-01', '2026-01-07', 'Asia/Seoul', ?)",
            ("2026-01-01T00:00:00+00:00",),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, requested_by) values ('sched-' || printf('%032d', 9), 'rk-daily', 'daily', 'schedule', '성공', 'tester')"
            )
        connection.execute(
            "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, requested_by) values ('sched-' || printf('%032d', 1), 'rk-daily', 'daily', 'schedule', '성공', 'system:scheduler')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, duplicate_of_execution_id, requested_by, skip_reason) values ('sched-' || printf('%032d', 2), 'rk-weekly', 'weekly', 'schedule', '건너뜀', 'sched-' || printf('%032d', 1), 'system:scheduler', 'duplicate')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, recovery_of_execution_id, requested_by, failure_reason) values ('sched-' || printf('%032d', 3), 'rk-daily', 'daily', 'schedule', '실패', 'sched-' || printf('%032d', 1), 'system:scheduler', 'recovery')"
            )
        connection.execute(
            "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, requested_by, failure_reason) values ('sched-' || printf('%032d', 4), 'rk-daily', 'daily', 'schedule', '실패', 'system:scheduler', 'failed')"
        )
        connection.execute(
            "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, recovery_of_execution_id, requested_by, failure_reason) values ('sched-' || printf('%032d', 5), 'rk-daily', 'daily', 'manual', '실패', 'sched-' || printf('%032d', 4), 'tester', 'recovery')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, recovery_of_execution_id, requested_by, failure_reason) values ('sched-' || printf('%032d', 6), 'rk-daily', 'daily', 'schedule', '실패', 'sched-' || printf('%032d', 4), 'system:scheduler', 'recovery')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into schedule_execution(execution_id, run_key, job_kind, trigger, status, duplicate_of_execution_id, requested_by, skip_reason) values ('sched-' || printf('%032d', 7), 'rk-daily', 'daily', 'schedule', '성공', 'sched-' || printf('%032d', 4), 'system:scheduler', 'duplicate')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update schedule_execution set status='성공' where execution_id='sched-' || printf('%032d', 4)")


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
