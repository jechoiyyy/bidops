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
