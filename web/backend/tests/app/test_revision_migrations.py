from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.db import ALEMBIC_HEAD  # noqa: F401
from app.screening.services.revisions import canonical_payload_sha256
from tests.postgres import requires_postgres, run_alembic, temporary_database


pytestmark = requires_postgres
REVISION_BASE = "0010_opportunity_link_integrity"


def _scalar(engine, sql: str):
    with engine.connect() as connection:
        return connection.scalar(text(sql))


def _seed_notice(connection, *, key: str = "revision-notice") -> int:
    return connection.scalar(
        text(
            "INSERT INTO bidops.notice (notice_key) VALUES (:key) RETURNING id"
        ),
        {"key": key},
    )


def test_0011_preflight_rejects_review_run_outside_notice_observation() -> None:
    with temporary_database(upgrade_to=REVISION_BASE) as database_url:
        engine = create_engine(database_url, future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.run"
                    " (id, timezone, generated_at, status, counts_json) VALUES"
                    " ('observed-run', 'Asia/Seoul', now(), 'active', '{}'),"
                    " ('wrong-run', 'Asia/Seoul', now(), 'active', '{}')"
                )
            )
            notice_id = _seed_notice(connection)
            connection.execute(
                text(
                    "INSERT INTO bidops.notice_observation"
                    " (notice_id, run_id, observed_at, changed_fields_json)"
                    " VALUES (:notice_id, 'observed-run', now(), '[]')"
                ),
                {"notice_id": notice_id},
            )
            review_id = connection.scalar(
                text(
                    "INSERT INTO bidops.review"
                    " (notice_id, run_id, created_at, updated_at)"
                    " VALUES (:notice_id, 'wrong-run', now(), now()) RETURNING id"
                ),
                {"notice_id": notice_id},
            )

        upgraded = run_alembic(database_url, "upgrade", "head")

        assert upgraded.returncode != 0
        output = upgraded.stdout + upgraded.stderr
        assert "did not observe the same notice" in output
        assert f"review_id={review_id}" in output
        assert f"notice_id={notice_id}" in output
        assert "run_id='wrong-run'" in output
        assert _scalar(
            engine, "SELECT version_num FROM bidops.alembic_version"
        ) == REVISION_BASE
        engine.dispose()


def test_0011_backfills_id_free_payloads_and_preserves_nulls() -> None:
    updated_at = datetime(2026, 8, 30, 4, 5, tzinfo=timezone.utc)
    with temporary_database(upgrade_to=REVISION_BASE) as database_url:
        engine = create_engine(database_url, future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.run"
                    " (id, timezone, generated_at, status, counts_json)"
                    " VALUES ('backfill-run', 'Asia/Seoul', now(), 'active', '{}')"
                )
            )
            notice_id = _seed_notice(connection, key="revision-backfill")
            connection.execute(
                text(
                    "INSERT INTO bidops.notice_observation"
                    " (notice_id, run_id, observed_at, changed_fields_json)"
                    " VALUES (:notice_id, 'backfill-run', now(), '[]')"
                ),
                {"notice_id": notice_id},
            )
            judgment_id = connection.scalar(
                text(
                    "INSERT INTO bidops.judgment"
                    " (notice_id, schema_version, grade, readiness, primary_focus,"
                    "  exclusion_category, summary, next_action)"
                    " VALUES (:notice_id, 'bidops.decisions.v2', NULL, '부분 확인 필요',"
                    "         NULL, NULL, 'legacy summary', NULL) RETURNING id"
                ),
                {"notice_id": notice_id},
            )
            perspective_id = connection.scalar(
                text(
                    "INSERT INTO bidops.perspective"
                    " (judgment_id, position, name, assessment, reason)"
                    " VALUES (:judgment_id, 1, '기술 적합성', NULL, '근거 대기')"
                    " RETURNING id"
                ),
                {"judgment_id": judgment_id},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.screening_evidence"
                    " (perspective_id, source, status, fact)"
                    " VALUES (:perspective_id, NULL, 'unknown', NULL)"
                ),
                {"perspective_id": perspective_id},
            )
            review_id = connection.scalar(
                text(
                    "INSERT INTO bidops.review"
                    " (notice_id, run_id, disposition, system_judgment_review,"
                    "  corrected_grade, corrected_readiness, weakest_perspective,"
                    "  reason, reviewer_snapshot, created_at, updated_at)"
                    " VALUES (:notice_id, 'backfill-run', NULL, '확인 필요', NULL,"
                    "         NULL, NULL, NULL, 'legacy reviewer', :updated_at, :updated_at)"
                    " RETURNING id"
                ),
                {"notice_id": notice_id, "updated_at": updated_at},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.verification_answer (review_id, item, answer)"
                    " VALUES (:review_id, '자격', NULL)"
                ),
                {"review_id": review_id},
            )

        upgraded = run_alembic(
            database_url, "upgrade", "0011_judgment_review_revisions"
        )
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        with engine.connect() as connection:
            judgment = connection.execute(
                text("SELECT * FROM bidops.judgment_revision")
            ).mappings().one()
            review = connection.execute(
                text("SELECT * FROM bidops.review_revision")
            ).mappings().one()

        assert judgment["sequence"] == 1
        assert judgment["source_kind"] == "legacy_import"
        assert judgment["run_id"] is None
        assert judgment["recording_execution_id"] is None
        assert judgment["source_revision_id"] is None
        assert judgment["payload_jsonb"]["grade"] is None
        assert judgment["payload_jsonb"]["next_action"] is None
        assert judgment["payload_jsonb"]["counterargument_resolutions"] is None
        assert judgment["payload_jsonb"]["perspectives"] == [
            {
                "position": 1,
                "name": "기술 적합성",
                "assessment": None,
                "reason": "근거 대기",
                "evidence": [{"source": None, "status": "unknown", "fact": None}],
            }
        ]
        assert "id" not in judgment["payload_jsonb"]
        assert "id" not in judgment["payload_jsonb"]["perspectives"][0]
        assert judgment["payload_sha256"] == canonical_payload_sha256(
            judgment["payload_jsonb"]
        )

        assert review["sequence"] == 1
        assert review["source_kind"] == "legacy_import"
        assert review["run_id"] == "backfill-run"
        assert review["judgment_revision_id"] is None
        assert review["captured_at"] == updated_at
        assert review["payload_jsonb"]["disposition"] is None
        assert review["payload_jsonb"]["verification_answers"] == [
            {"item": "자격", "answer": None}
        ]
        assert review["payload_sha256"] == canonical_payload_sha256(
            review["payload_jsonb"]
        )
        assert _scalar(
            engine, "SELECT version_num FROM bidops.alembic_version"
        ) == "0011_judgment_review_revisions"
        engine.dispose()


def test_revision_source_and_same_notice_scope_constraints_are_database_enforced() -> None:
    with temporary_database() as database_url:
        engine = create_engine(database_url, future=True)
        empty_hash = canonical_payload_sha256({})
        with engine.begin() as connection:
            first_notice = _seed_notice(connection, key="revision-scope-one")
            second_notice = _seed_notice(connection, key="revision-scope-two")
            first_revision = connection.scalar(
                text(
                    "INSERT INTO bidops.judgment_revision"
                    " (notice_id, sequence, source_kind, payload_schema_version,"
                    "  payload_jsonb, payload_sha256, captured_at)"
                    " VALUES (:notice_id, 1, 'legacy_import', 'schema.v1', '{}',"
                    "         :digest, now()) RETURNING id"
                ),
                {"notice_id": first_notice, "digest": empty_hash},
            )
            second_revision = connection.scalar(
                text(
                    "INSERT INTO bidops.judgment_revision"
                    " (notice_id, sequence, source_kind, payload_schema_version,"
                    "  payload_jsonb, payload_sha256, captured_at)"
                    " VALUES (:notice_id, 1, 'legacy_import', 'schema.v1', '{}',"
                    "         :digest, now()) RETURNING id"
                ),
                {"notice_id": second_notice, "digest": empty_hash},
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.judgment_revision"
                        " (notice_id, sequence, source_kind, payload_schema_version,"
                        "  payload_jsonb, payload_sha256, captured_at)"
                        " VALUES (:notice_id, 2, 'runtime', 'schema.v1', '{}',"
                        "         :digest, now())"
                    ),
                    {"notice_id": first_notice, "digest": empty_hash},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.review_revision"
                        " (notice_id, sequence, source_kind, judgment_revision_id,"
                        "  payload_schema_version, payload_jsonb, payload_sha256, captured_at)"
                        " VALUES (:notice_id, 1, 'legacy_import', :wrong_revision,"
                        "         'schema.v1', '{}', :digest, now())"
                    ),
                    {
                        "notice_id": first_notice,
                        "wrong_revision": second_revision,
                        "digest": empty_hash,
                    },
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.review_revision"
                        " (notice_id, sequence, source_kind, payload_schema_version,"
                        "  payload_jsonb, payload_sha256, captured_at)"
                        " VALUES (:notice_id, 1, 'human', 'schema.v1', '{}',"
                        "         :digest, now())"
                    ),
                    {"notice_id": second_notice, "digest": empty_hash},
                )
        assert first_revision is not None
        engine.dispose()


@pytest.mark.parametrize("table", ["judgment_revision", "review_revision"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_revision_rows_reject_update_and_delete(table: str, operation: str) -> None:
    with temporary_database() as database_url:
        engine = create_engine(database_url, future=True)
        digest = canonical_payload_sha256({})
        with engine.begin() as connection:
            notice_id = _seed_notice(connection, key=f"append-only-{table}-{operation}")
            connection.execute(
                text(
                    f"INSERT INTO bidops.{table}"
                    " (notice_id, sequence, source_kind, payload_schema_version,"
                    "  payload_jsonb, payload_sha256, captured_at)"
                    " VALUES (:notice_id, 1, 'legacy_import', 'schema.v1', '{}',"
                    "         :digest, now())"
                ),
                {"notice_id": notice_id, "digest": digest},
            )

        statement = (
            f"UPDATE bidops.{table} SET payload_schema_version = 'schema.v2'"
            if operation == "UPDATE"
            else f"DELETE FROM bidops.{table}"
        )
        with pytest.raises(IntegrityError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(text(statement))
        engine.dispose()


def test_0011_downgrade_refuses_when_any_revision_history_exists() -> None:
    # 0026이 그 아래 downgrade를 닫았으므로 0011 거부는 0011 판에서 본다.
    with temporary_database(upgrade_to="0011_judgment_review_revisions") as database_url:
        engine = create_engine(database_url, future=True)
        digest = canonical_payload_sha256({})
        with engine.begin() as connection:
            notice_id = _seed_notice(connection, key="downgrade-refusal")
            connection.execute(
                text(
                    "INSERT INTO bidops.judgment_revision"
                    " (notice_id, sequence, source_kind, payload_schema_version,"
                    "  payload_jsonb, payload_sha256, captured_at)"
                    " VALUES (:notice_id, 1, 'legacy_import', 'schema.v1', '{}',"
                    "         :digest, now())"
                ),
                {"notice_id": notice_id, "digest": digest},
            )

        downgraded = run_alembic(database_url, "downgrade", REVISION_BASE)

        assert downgraded.returncode != 0
        assert "refuses to discard judgment or review revision history" in (
            downgraded.stdout + downgraded.stderr
        )
        assert _scalar(
            engine, "SELECT version_num FROM bidops.alembic_version"
        ) == "0011_judgment_review_revisions"
        engine.dispose()
