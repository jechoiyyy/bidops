"""Migration, input scope, terminal immutability and rollback on PostgreSQL 17."""
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.db import schema_bound
from app.deep_review.services.company_fit import digest
from tests.postgres import requires_postgres, temporary_database, run_alembic
from tests.deep_review.test_company_fit import setup_inputs, enqueue, output


@requires_postgres
def test_company_fit_database_guards(tmp_path, monkeypatch):
    with temporary_database() as url:
        engine = schema_bound(create_engine(url))
        with Session(engine) as session:
            source, _, _, inputs = setup_inputs(session, tmp_path, monkeypatch)
            row = enqueue(session, inputs)
            row_id = row.id
        for sql in [
            "UPDATE bidops.prespec_company_fit_attempt SET input_jsonb='{}' WHERE id=:id",
            "UPDATE bidops.prespec_company_fit_attempt SET profile_version_id=profile_version_id, model_name='other' WHERE id=:id",
            "DELETE FROM bidops.prespec_company_fit_attempt WHERE id=:id",
        ]:
            with pytest.raises(DBAPIError):
                with engine.begin() as conn:
                    conn.execute(text(sql), {"id": row_id})
        # A source from another notice cannot enter by direct SQL.
        with engine.begin() as conn:
            other = conn.scalar(text("INSERT INTO bidops.notice (notice_key,source_type,title) VALUES (:key,'pre_spec','synthetic') RETURNING id"), {"key": str(uuid4())})
        with pytest.raises(DBAPIError):
            with engine.begin() as conn:
                conn.execute(text("""INSERT INTO bidops.prespec_company_fit_attempt
                    SELECT (jsonb_populate_record(NULL::bidops.prespec_company_fit_attempt,
                    to_jsonb(r) || CAST(:patch AS jsonb))).* FROM bidops.prespec_company_fit_attempt r WHERE id=:id"""),
                    {"id": row_id, "patch": json.dumps({"id": str(uuid4()), "notice_id": other, "input_sha256": "e"*64})})
        now = datetime.now(UTC)
        with engine.begin() as conn:
            conn.execute(text("UPDATE bidops.prespec_company_fit_attempt SET status='running',lease_owner='test',lease_expires_at=:end WHERE id=:id"),
                         {"id": row_id, "end": now + timedelta(seconds=600)})
        result = output("mismatch")
        with engine.begin() as conn:
            conn.execute(text("""UPDATE bidops.prespec_company_fit_attempt SET status='completed',lease_owner=NULL,
                lease_expires_at=NULL,completed_at=:now,result_jsonb=CAST(:result AS jsonb),result_sha256=:sha WHERE id=:id"""),
                {"id": row_id, "now": now, "result": json.dumps(result), "sha": digest(result)})
        with pytest.raises(DBAPIError, match="terminal"):
            with engine.begin() as conn:
                conn.execute(text("UPDATE bidops.prespec_company_fit_attempt SET error_code='rewrite' WHERE id=:id"), {"id": row_id})
        # 0026은 되돌리지 않는다. 그 아래로 내려가려는 시도는 실패해야 한다.
        downgrade = run_alembic(url, "downgrade", "0019_prespec_page_overview")
        assert downgrade.returncode != 0
        engine.dispose()
    get_settings.cache_clear()


# --- PS-01 T11: 사업 범위 카드 lineage (0044) ---------------------------------

_FRESH = {"status": "queued", "result_jsonb": None, "result_sha256": None, "completed_at": None,
          "raw_response_sha256": None, "lease_owner": None, "lease_expires_at": None,
          "prompt_tokens": None, "output_tokens": None, "latency_ms": None, "error_code": None}


def _copy(engine, row_id, patch):
    """기존 행을 복사해 패치한 새 행을 직접 SQL로 넣는다(ORM 검사를 거치지 않는다)."""

    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO bidops.prespec_company_fit_attempt
            SELECT (jsonb_populate_record(NULL::bidops.prespec_company_fit_attempt,
            to_jsonb(r) || CAST(:patch AS jsonb))).* FROM bidops.prespec_company_fit_attempt r WHERE id=:id"""),
            {"id": row_id, "patch": json.dumps({**_FRESH, "id": str(uuid4()), "input_sha256": uuid4().hex * 2,
                                                **patch})})


def _patched_input(engine, row_id, **changes):
    with engine.connect() as conn:
        value = conn.scalar(text("SELECT input_jsonb FROM bidops.prespec_company_fit_attempt WHERE id=:id"),
                            {"id": row_id})
    value.update(changes)
    return value


@requires_postgres
def test_card_lineage_database_guards(tmp_path, monkeypatch):
    from tests.deep_review.company_fit_card_fixtures import add_notice, card_env, card_input, store_card_attempt

    with temporary_database() as url:
        engine = schema_bound(create_engine(url))
        with Session(engine) as session:
            _source, profile, policy, inputs = setup_inputs(session, tmp_path, monkeypatch)
            profile_id = enqueue(session, inputs).id
            card_env(monkeypatch, tmp_path)
            notice = add_notice(session)
            session.commit()
            card = store_card_attempt(session, card_input(session, notice), status="completed")
            card_id, card_sha, profile_version = card.id, card.card_sha256, str(profile.id)
            deep_policy = str(policy.id)
        # 세 lineage 중 프로필·카드 행이 들어갔다(회사 lineage는 test_company_analysis가 본다).
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, card_sha256, profile_version_id FROM bidops.prespec_company_fit_attempt")).all()
        assert {(row.id, row.card_sha256 is None) for row in rows} == {(profile_id, True), (card_id, False)}
        # 일관된 카드 복사본은 들어간다(아래 거부 검사의 기준).
        _copy(engine, card_id, {})
        rejected = [
            ({"profile_version_id": profile_version}, "ck_prespec_company_fit_policy_scope"),
            ({"deep_policy_version_id": deep_policy}, "ck_prespec_company_fit_policy_scope"),
            ({"card_sha256": "c" * 64}, "card input scope rejected"),
            ({"input_jsonb": _patched_input(engine, card_id, schema_version="bidops.prespec-company-fit-input.v1")},
             "card input scope rejected"),
            ({"input_jsonb": _patched_input(engine, card_id, prompt_version="prespec-company-fit-v1")},
             "card input scope rejected"),
            ({"input_jsonb": _patched_input(engine, card_id, judged_by="human")}, "card input scope rejected"),
            ({"input_jsonb": _patched_input(engine, card_id, policy_digest="d" * 64)}, "card input scope rejected"),
            ({"card_sha256": card_sha.upper(), "input_jsonb": _patched_input(engine, card_id, card_sha256=card_sha.upper())},
             "card input scope rejected"),
        ]
        for patch, message in rejected:
            with pytest.raises(DBAPIError, match=message):
                _copy(engine, card_id, patch)
        # v1 입력에 카드 열만 붙인 행은 카드 분기에서 거부된다.
        with pytest.raises(DBAPIError, match="card input scope rejected|ck_prespec_company_fit_policy_scope"):
            _copy(engine, profile_id, {"card_sha256": card_sha, "card_version": "bidops.business-scope-card.v1.2"})
        # 카드 열은 동결 값이다. 종결 행은 바뀌지 않고 삭제되지 않는다.
        for sql in [
            "UPDATE bidops.prespec_company_fit_attempt SET card_sha256=:sha WHERE id=:id",
            "UPDATE bidops.prespec_company_fit_attempt SET error_code='rewrite' WHERE id=:id",
            "DELETE FROM bidops.prespec_company_fit_attempt WHERE id=:id",
        ]:
            with pytest.raises(DBAPIError):
                with engine.begin() as conn:
                    conn.execute(text(sql), {"id": card_id, "sha": "e" * 64})
        # 카드 행이 있으면 0044 downgrade를 거부한다.
        downgrade = run_alembic(url, "downgrade", "0043_company_wiki_ingest")
        assert downgrade.returncode != 0
        assert "card lineage history must be preserved" in downgrade.stderr + downgrade.stdout
        engine.dispose()
    get_settings.cache_clear()


@requires_postgres
def test_0044_round_trips_without_card_rows():
    with temporary_database() as url:
        assert run_alembic(url, "downgrade", "0043_company_wiki_ingest").returncode == 0
        engine = create_engine(url)
        with engine.connect() as conn:
            columns = set(conn.scalars(text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='bidops'"
                " AND table_name='prespec_company_fit_attempt'")))
            nullable = conn.scalar(text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_schema='bidops'"
                " AND table_name='prespec_company_fit_attempt' AND column_name='profile_version_id'"))
        engine.dispose()
        assert "card_sha256" not in columns and nullable == "NO"
        assert run_alembic(url, "upgrade", "head").returncode == 0
