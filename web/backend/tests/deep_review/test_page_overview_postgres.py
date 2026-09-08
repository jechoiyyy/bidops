"""Real Alembic/JSONB/immutability and idempotency checks on disposable PostgreSQL."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError
from app.core.db import schema_bound
from app.core.object_store import FilesystemObjectStore
from app.deep_review.services.page_overview import import_page_overview, list_page_overviews
from tests.postgres import requires_postgres, temporary_database, run_alembic
from tests.deep_review.test_page_overview import seed, Scanner


@requires_postgres
def test_migration_import_and_database_immutability(tmp_path):
    with temporary_database() as url:
        engine = schema_bound(create_engine(url))
        with Session(engine) as session:
            data = seed(session)
            store = FilesystemObjectStore(tmp_path)
            row, created = import_page_overview(session, **data, store=store, scanner=Scanner(), actor='test')
            session.commit()
            row_id, notice_id = row.id, row.notice_id
            assert created and list_page_overviews(session, notice_id).reviews[0].validation_status == 'failed'
            same, created = import_page_overview(session, **data, store=store, scanner=Scanner(), actor='test')
            assert not created and same.id == row_id
        for statement in (
            'UPDATE bidops.prespec_page_overview SET quality_status=quality_status WHERE id=:id',
            'DELETE FROM bidops.prespec_page_overview WHERE id=:id',
        ):
            with pytest.raises(DBAPIError, match='append-only'):
                with engine.begin() as connection:
                    connection.execute(text(statement), {'id': row_id})
        # A copy cannot bypass schema, evidence status, or cross-notice scope constraints.
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO bidops.prespec_page_overview SELECT * FROM bidops.prespec_page_overview"))
        for patch in ({"schema_version": "wrong"}, {"quality_status": "measured"},
                      {"pdf_page_count": 0}, {"pdf_sha256": "bad"},
                      {"validation_status": "passed", "evidence_check_status": "failed"}):
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text("""INSERT INTO bidops.prespec_page_overview
                        SELECT (jsonb_populate_record(NULL::bidops.prespec_page_overview,
                        to_jsonb(r) || CAST(:patch AS jsonb))).*
                        FROM bidops.prespec_page_overview r WHERE id=:id"""),
                        {"id": row_id, "patch": json.dumps({"id": str(uuid4()), "run_id": str(uuid4()), **patch})})
        result = run_alembic(url, 'downgrade', '0018_prespec_auto_preparation_segments')
        assert result.returncode != 0 and 'downgrade refused' in result.stderr
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM bidops.prespec_page_overview')) == 1
            assert connection.scalar(text('SELECT count(*) FROM bidops.prespec_overview_review')) == 0
        engine.dispose()
