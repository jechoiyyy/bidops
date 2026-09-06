from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError

from app.core.config import Settings
from app.core.db import _json_serializer, schema_bound
from app.core.generation_config import GenerationConfig
from tests.postgres import requires_postgres, run_alembic, temporary_database

pytestmark = requires_postgres

DIGEST = "a" * 64
PROFILE_VERSION = f"company-profile.sha256:{DIGEST}"
MODEL_DIGEST = "b" * 64
GENERATION_CONFIG_DIGEST = GenerationConfig().digest()


class _Rows:
    """Small DB-API-shaped result for the two SQLite PRAGMAs in old tests."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._rows)

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self._rows[0] if self._rows else None

    def fetchall(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


_DATABASES: dict[Path, tuple[Any, str]] = {}
_PRINTF = re.compile(r"printf\('%032d',\s*(?P<number>\d+)\)", re.IGNORECASE)
_PRAGMA_TABLE_INFO = re.compile(
    r"^\s*pragma\s+table_info\(\s*(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$",
    re.IGNORECASE,
)


def _postgres_sql(statement: str) -> str:
    statement = re.sub(r"\benabled\s*=\s*1\b", "enabled=TRUE", statement, flags=re.IGNORECASE)
    statement = re.sub(r"\benabled\s*=\s*0\b", "enabled=FALSE", statement, flags=re.IGNORECASE)
    statement = _PRINTF.sub(
        lambda match: f"lpad('{match.group('number')}', 32, '0')", statement
    )
    statement = re.sub(
        r"\border\s+by\s+rowid\b",
        "ORDER BY occurred_at, CASE WHEN actor = 'system:quality-gate' THEN 1 ELSE 0 END, event_id",
        statement,
        flags=re.IGNORECASE,
    )
    return statement.replace("?", "%s")


class _PostgresConnection:
    """Translate the legacy raw-SQL test surface to PostgreSQL 17."""

    def __init__(self, connection: Any, engine: Any, boundary: Any) -> None:
        self._connection = connection
        self._engine = engine
        self._boundary = boundary

    def __enter__(self) -> "_PostgresConnection":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # type: ignore[no-untyped-def]
        self._connection.close()
        self._engine.dispose()
        self._boundary.__exit__(exc_type, exc_value, traceback)

    def commit(self) -> None:
        self._connection.commit()

    def execute(self, statement: str, parameters: Any = ()) -> Any:
        if statement.strip().lower().startswith("pragma foreign_keys"):
            return _Rows([])

        pragma = _PRAGMA_TABLE_INFO.fullmatch(statement)
        if pragma:
            result = self._run(
                "SELECT ordinal_position - 1, column_name, data_type, "
                "CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END, column_default, 0 "
                "FROM information_schema.columns "
                "WHERE table_schema = 'bidops' AND table_name = %s "
                "ORDER BY ordinal_position",
                (pragma.group("table"),),
            )
            return _Rows(result.fetchall())

        return self._run(_postgres_sql(statement), parameters)

    def _run(self, statement: str, parameters: Any = ()) -> Any:
        savepoint = self._connection.begin_nested()
        try:
            if parameters:
                result = self._connection.exec_driver_sql(statement, parameters)
            else:
                result = self._connection.exec_driver_sql(statement)
            savepoint.commit()
            return result
        except SQLAlchemyIntegrityError as exc:
            savepoint.rollback()
            raise sqlite3.IntegrityError(str(exc)) from exc
        except Exception:
            savepoint.rollback()
            raise


def upgrade(database: Path) -> None:
    boundary = temporary_database()
    database_url = boundary.__enter__()
    result = run_alembic(database_url, "upgrade", "head")
    if result.returncode != 0:
        boundary.__exit__(None, None, None)
        raise AssertionError(result.stderr + result.stdout)
    _DATABASES[Path(database)] = (boundary, database_url)


def validated_connect(database: Path | str) -> _PostgresConnection:
    boundary, database_url = _DATABASES.pop(Path(database))
    engine = schema_bound(
        create_engine(database_url, json_serializer=_json_serializer, future=True)
    )
    connection = engine.connect()
    connection.exec_driver_sql("SET search_path TO bidops")
    return _PostgresConnection(connection, engine, boundary)


def seed_base(connection: _PostgresConnection) -> None:
    now = "2026-01-01T00:00:00+00:00"
    connection.execute("insert into run(id, timezone, generated_at, status) values ('r1', 'Asia/Seoul', ?, 'active')", (now,))
    # ``0004_cumulative_external_identity`` moved run dependency off ``notice``
    # and onto ``notice_observation``; the notice itself is now cumulative.
    connection.execute("insert into notice(notice_key) values ('notice-1')")
    connection.execute(
        "insert into notice_observation(notice_id, run_id, observed_at, changed_fields_json)"
        " select id, 'r1', ?, '[]' from notice where notice_key='notice-1'",
        (now,),
    )
    connection.execute("insert into company_profile_snapshot(digest, version, source_kind, source_ref, artifact_path, created_at) values (?, ?, 'working_tree', 'docs/reference/company-profile.md', ?, ?)", (DIGEST, PROFILE_VERSION, f"web/data/profile-snapshots/{DIGEST}.md", now))
    body = "{}"
    connection.execute("insert into screening_policy(policy_version, schema_version, prompt_version, content_digest, status, perspective_prompts_json, counterargument_prompt_json, synthesis_prompt_json, candidate_selection_json, thresholds_json, created_at, created_by) values ('p1', 'bidops.screening-policy.v1', 'prompt-1', ?, 'draft', ?, ?, ?, ?, ?, ?, 'tester')", (DIGEST, body, body, body, body, body, now))
    connection.commit()


def add_execution(connection: _PostgresConnection, execution_id: str, suffix: str) -> None:
    connection.execute("insert into screening_execution(execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, queued_at) values (?, 'manual_run', 'r1', 'full_run', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, ?, ?, ?, ?)", (execution_id, MODEL_DIGEST, PROFILE_VERSION, DIGEST, f"runs/{suffix}.json", DIGEST, f"runs/{suffix}", "2026-01-01T00:00:00+00:00"))


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
            connection.execute("insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, completed_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '완료', '통과', 'r1', '/absolute/sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')", ("gate-" + "0" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}", "[]"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, completed_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '완료', '통과', 'r1', 'sample.json', ?, '../decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')", ("gate-" + "0" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}", "[]"))
        connection.execute("insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, completed_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '완료', '통과', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')", ("gate-" + "1" * 32, DIGEST, DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "scr-" + "1" * 32, "scr-" + "2" * 32, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "{}", "[]"))
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
            connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, generation_config_digest=?, policy_version='p1', model_name='qwen3.8-27B', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", (gateeval, GENERATION_CONFIG_DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, generation_config_digest=?, policy_version='p1', model_name='qwen3.8-27B', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", ("gateeval-" + "2" * 32, GENERATION_CONFIG_DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("update always_on_state set model_digest=? where singleton_id=1", ("c" * 64,))
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 3, '통과', '{\"passed\": 1}', '[\"ok\"]', 0, 0, ?)",
            ("gateeval-" + "3" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"),
        )
        assert connection.execute("select result_status, metrics_json, reasons_json from quality_gate where gate_id=?", ("gate-" + "1" * 32,)).fetchone() == ("통과", {"passed": 1}, ["ok"])
        assert connection.execute("select enabled from always_on_state where singleton_id=1").fetchone()[0] == 1
        assert connection.execute("select status, quality_gate_result_id from screening_policy where policy_version='p1'").fetchone() == ("active", "gateeval-" + "2" * 32)
        connection.execute(
            "update screening_policy set status='activation_candidate', active_slot=NULL, activated_at=NULL, activated_by=NULL, quality_gate_result_id=NULL where policy_version='p1'"
        )
        assert connection.execute("select enabled from always_on_state where singleton_id=1").fetchone()[0] == 0
        policy_disable_audits = connection.execute(
            "select event_type, actor, target_type, target_id, details_json from screening_audit_event where event_type='schedule.always_on_disabled'"
        ).fetchall()
        assert len(policy_disable_audits) == 1
        assert policy_disable_audits[0] == (
            "schedule.always_on_disabled",
            "system:policy",
            "schedule",
            "1",
            {"reason": "policy_inactive"},
        )
        assert "secret" not in policy_disable_audits[0][-1]
        connection.execute(
            "update screening_policy set status='active', active_slot=1, activated_at=?, activated_by='tester', quality_gate_result_id=? where policy_version='p1'",
            ("2026-01-01T00:00:00+00:00", "gateeval-" + "3" * 32),
        )
        connection.execute("update always_on_state set enabled=1, quality_gate_result_id=?, generation_config_digest=?, policy_version='p1', model_name='qwen3.8-27B', model_digest=?, prompt_version='prompt-1', company_profile_version=?, company_profile_digest=?, updated_at=?, updated_by='tester' where singleton_id=1", ("gateeval-" + "3" * 32, GENERATION_CONFIG_DIGEST, MODEL_DIGEST, PROFILE_VERSION, DIGEST, "2026-01-01T00:00:00+00:00"))
        connection.execute(
            "insert into quality_gate_evaluation(evaluation_id, gate_id, revision, result_status, metrics_json, reasons_json, valid_review_count, distinct_notice_review_count, created_at) values (?, ?, 4, '미달', '{\"passed\": 0}', '[\"failed\"]', 0, 0, ?)",
            ("gateeval-" + "4" * 32, "gate-" + "1" * 32, "2026-01-01T00:00:00+00:00"),
        )
        assert connection.execute("select enabled from always_on_state where singleton_id=1").fetchone()[0] == 0
        assert connection.execute("select result_status, metrics_json, reasons_json from quality_gate where gate_id=?", ("gate-" + "1" * 32,)).fetchone() == ("미달", {"passed": 0}, ["failed"])
        quality_disable_audits = connection.execute(
            "select event_type, actor, target_type, target_id, details_json from screening_audit_event where event_type='schedule.always_on_disabled' order by rowid"
        ).fetchall()
        assert len(quality_disable_audits) == 2
        assert quality_disable_audits[-1] == (
            "schedule.always_on_disabled",
            "system:quality-gate",
            "schedule",
            "1",
            {"reason": "quality_gate_not_passing"},
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
            "insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, metrics_json, reasons_json, created_by) values (?, 'model_comparison', '대기', '미측정', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, ?, ?, ?, ?, ?, 'tester')",
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
                "values (?, 'cli_single', 'r1', 'single_notice', ?, 'wrong-notice', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, 'runs/single.json', ?, 'runs/single', ?)",
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
                "values (?, 'cli_single', 'r2', 'single_notice', ?, 'notice-1', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, 'runs/mismatch.json', ?, 'runs/mismatch', ?)",
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
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, active_slot, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_reason, queued_at) values (?, 'manual_run', 'r1', 'full_run', '중지 요청', 1, 'tester', 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, 'runs/stop-a.json', ?, 'runs/stop-a', 'user_requested', ?)",
                ("scr-" + "6" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, active_slot, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_requested_at, queued_at) values (?, 'manual_run', 'r1', 'full_run', '실행 중', 1, 'tester', 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, 'runs/stop-b.json', ?, 'runs/stop-b', ?, ?)",
                ("scr-" + "7" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_reason, queued_at) values (?, 'manual_run', 'r1', 'full_run', '대기', 'tester', 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, 'runs/stop-c.json', ?, 'runs/stop-c', 'user_requested', ?)",
                ("scr-" + "8" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00"),
            )
        connection.execute(
            "insert into screening_execution(execution_id, trigger, source_run_id, scope, status, active_slot, requested_by, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, input_artifact_path, input_artifact_digest, artifact_dir, stop_requested_at, stop_requested_by, stop_reason, queued_at) values (?, 'manual_run', 'r1', 'full_run', '중지 요청', 1, 'tester', 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, 'runs/stop-d.json', ?, 'runs/stop-d', ?, 'tester', 'user_requested', ?)",
            ("scr-" + "9" * 32, MODEL_DIGEST, PROFILE_VERSION, DIGEST, DIGEST, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )


def test_audit_details_must_be_an_object(tmp_path: Path) -> None:
    database = tmp_path / "runtime.db"
    upgrade(database)
    with validated_connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "insert into screening_audit_event(event_id, event_type, actor, target_type, target_id, occurred_at, details_json) "
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
            "values (?, 'operational_approval', '완료', '통과', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tester')",
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
            "insert into quality_gate(gate_id, purpose, execution_status, result_status, baseline_run_id, sample_artifact_path, sample_artifact_digest, baseline_decisions_path, baseline_decisions_digest, policy_version, prompt_version, model_name, model_digest, company_profile_version, company_profile_digest, pass_a_execution_id, pass_b_execution_id, created_at, metrics_json, reasons_json, created_by) values (?, 'operational_approval', '실행 중', '통과', 'r1', 'sample.json', ?, 'decisions.json', ?, 'p1', 'prompt-1', 'qwen3.8-27B', ?, ?, ?, ?, ?, ?, '{}', '[]', 'tester')",
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
    for name in ("BIDOPS_OLLAMA_ENDPOINT", "BIDOPS_MODEL_BASE_URL", "BIDOPS_HEARTBEAT_SECONDS", "BIDOPS_STALE_SECONDS", "BIDOPS_LIVE_TEST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BIDOPS_SCREEN_HEARTBEAT_SECONDS", "5")
    monkeypatch.setenv("BIDOPS_SCREEN_STALE_AFTER_SECONDS", "60")
    monkeypatch.setenv("BIDOPS_SCREENING_CONTEXT_SIZE", "16384")
    defaults = Settings()
    assert defaults.vllm_screening_model == "qwen3.8-27B"
    assert defaults.screening_provider == "vllm"
    assert defaults.model_context == 16384
    assert defaults.model_max_output == 2048
    assert defaults.screen_concurrency == 1
    assert defaults.schedule_daily_time == "02:00"
    assert defaults.schedule_weekly_time == "06:00"
    assert defaults.schedule_prespec is False
    with pytest.raises(ValueError):
        Settings(heartbeat_seconds=20, stale_seconds=30)
    with pytest.raises(ValueError):
        Settings(screen_concurrency=2)
    with pytest.raises(ValueError):
        Settings(model_context=0)
    with pytest.raises(ValueError):
        Settings(model_max_output=0)
    with pytest.raises(ValueError):
        Settings(schedule_daily_time="24:00")
