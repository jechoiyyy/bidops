"""Review exclusion API, transactions, observations and workspace contracts."""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db, schema_bound, ensure_database_current
from app.core.models import AuditEvent
from app.lifecycle.models import Notice, Run
from app.lifecycle.routers.pre_specs import router
from app.lifecycle.ingest.contracts import NoticeContract
from app.lifecycle.ingest.loader import _upsert_notice
from tests.app.test_api_pre_specs_workspaces import (
    _list, _notice, _observe, _run, _tracking_link, _Projection,
    registry, SEOUL_RECENT_NOW,
)
from tests.postgres import migrated_engine, requires_postgres, temporary_database, run_alembic
from tests.app.test_runtime_database_privileges import _ensure_roles, _apply_policy


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as value:
            yield value
    else:
        value = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        init_db(value)
        try:
            yield value
        finally:
            value.dispose()


@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(router)
    def db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = db
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value


def payload(ids, status="excluded", **kwargs):
    return dict(notice_ids=ids, status=status, actor_name=" 담당자 ", reason=" 검토 범위 밖 ", **kwargs)


def seed(engine, n=2):
    with Session(engine) as session:
        notices = [_notice(session, str(i)) for i in range(n)]
        ids = [row.id for row in notices]
        session.commit()
        return ids


def post(client, value):
    return client.post("/api/pre-specs/review-exclusions", json=value)


def test_bulk_single_restore_unchanged_and_audit(client, engine):
    ids = seed(engine)
    initial = client.get('/api/pre-specs', params={'sw_only': False}).json()['items'][0]
    assert initial['review_exclusion_status'] == 'included'
    assert all(initial[key] is None for key in ('review_exclusion_actor_name', 'review_exclusion_reason', 'review_exclusion_changed_at'))
    response = post(client, payload(ids[::-1]))
    assert response.status_code == 200
    assert response.json() == {'items': [{'notice_id': id, 'status': 'excluded', 'outcome': 'changed'} for id in ids[::-1]]}
    with Session(engine) as session:
        before = session.get(Notice, ids[0]).review_exclusion_changed_at
        audits = session.scalars(select(AuditEvent)).all()
        assert len(audits) == 2
        assert audits[0].safe_metadata['previous_status'] == 'included'
        assert audits[0].safe_metadata['reason'] == '검토 범위 밖'
        assert audits[0].claimed_name == '담당자'
    changed_request = payload(ids)
    changed_request.update(actor_name='다른 담당자', reason='다른 사유')
    assert all(x['outcome'] == 'unchanged' for x in post(client, changed_request).json()['items'])
    with Session(engine) as session:
        row = session.get(Notice, ids[0])
        assert row.review_exclusion_changed_at == before
        assert row.review_exclusion_actor_name == '담당자'
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 2
    assert post(client, payload([ids[0]], 'included')).json()['items'][0]['outcome'] == 'changed'
    assert [x['outcome'] for x in post(client, payload(ids, 'included')).json()['items']] == ['unchanged', 'changed']
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 4


@pytest.mark.parametrize('override', [
    {'notice_ids': []}, {'notice_ids': [1, 1]}, {'notice_ids': [0]},
    {'notice_ids': [-1]}, {'notice_ids': [True]}, {'notice_ids': ['1']},
    {'notice_ids': [2147483648]}, {'notice_ids': list(range(1, 202))},
    {'actor_name': ' \n '}, {'actor_name': '가'*129}, {'reason': '\t'},
    {'reason': '가'*2001}, {'status': 'hidden'}, {'actor_name': None},
])
def test_validation_is_atomic(client, engine, override):
    ids = seed(engine)
    value = payload(ids)
    value.update(override)
    assert post(client, value).status_code == 422
    with Session(engine) as session:
        assert session.get(Notice, ids[0]).review_exclusion_status == 'included'
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.parametrize('missing', ['actor_name', 'reason', 'status', 'notice_ids'])
def test_required(client, engine, missing):
    value = payload(seed(engine))
    del value[missing]
    assert post(client, value).status_code == 422


def test_unknown_and_non_prespec_reject_whole_request(client, engine):
    ids = seed(engine)
    with Session(engine) as session:
        row = Notice(notice_key='bid:other', source_type='bid_notice')
        session.add(row)
        session.commit()
        other = row.id
    for target in [other, 2147483647]:
        assert post(client, payload([ids[0], target])).status_code == 422
    with Session(engine) as session:
        assert session.get(Notice, ids[0]).review_exclusion_status == 'included'
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_200_and_trimmed_limits(client, engine):
    ids = seed(engine, 200)
    value = payload(ids)
    value.update(actor_name=' '+ '가'*128 +' ', reason=' '+ '가'*2000 +' ')
    assert len(post(client, value).json()['items']) == 200


def test_audit_failure_rolls_back_all_rows(client, engine):
    ids = seed(engine)
    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith('INSERT INTO') and 'audit_event' in statement:
            raise RuntimeError('test audit write failure')
    event.listen(engine, 'before_cursor_execute', fail)
    try:
        assert post(client, payload(ids)).status_code == 500
    finally:
        event.remove(engine, 'before_cursor_execute', fail)
    with Session(engine) as session:
        assert all(session.get(Notice, id).review_exclusion_status == 'included' for id in ids)
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_reobservation_preserves_human_state(client, engine):
    raw = dict(notice_id='pre:observation', source_type='pre_spec', title='첫 제목')
    with Session(engine) as session:
        session.add(Run(id='first', generated_at=datetime(2026, 9, 1, tzinfo=UTC)))
        session.flush()
        row = _upsert_notice(session, 'first', NoticeContract(**raw), raw, 'Asia/Seoul')
        id = row.id
        session.commit()
    assert post(client, payload([id])).status_code == 200
    with Session(engine) as session:
        session.add(Run(id='second', generated_at=datetime(2026, 9, 2, tzinfo=UTC)))
        session.flush()
        raw['title'] = '새 제목'
        row = _upsert_notice(session, 'second', NoticeContract(**raw), raw, 'Asia/Seoul')
        session.commit()
        assert row.title == '새 제목'
        assert row.review_exclusion_status == 'excluded'
        assert row.review_exclusion_reason == '검토 범위 밖'


def test_workspace_counts_pages_and_tracking_unchanged(client, engine, registry, monkeypatch):
    from app.lifecycle.routers import pre_specs
    monkeypatch.setattr(pre_specs, '_now_utc', lambda: SEOUL_RECENT_NOW)
    projection = _Projection()
    registry.register_overview_document_projection(projection, owner="test")
    with Session(engine) as session:
        rows = [_notice(session, str(i)) for i in range(4)]
        run = _run(session, 'workspace')
        for row in rows:
            _observe(session, row, run, SEOUL_RECENT_NOW)
        from tests.app.test_api_pre_specs import _add_order_plan_path
        rows[0].qualification_flags_json = {'sw_business_status': 'N'}
        owner = _add_order_plan_path(session, rows[0], tracking_status='계속 추적')
        owner_id = owner.id
        projection.statuses.update({rows[0].id: 'needs_human_review', rows[1].id: 'completed', rows[3].id: 'needs_human_review'})
        projection.fields[rows[2].id] = {'auto_preparation_status': 'deep_review_ready_for_click'}
        _tracking_link(session, rows[1])
        ids = [row.id for row in rows]
        session.commit()
    assert post(client, payload(ids[:3])).status_code == 200
    with Session(engine) as session:
        for workspace in ['actionable', 'recent']:
            data = _list(session, workspace=workspace, limit=1, sw_only=True)
            assert data['total'] == 1
            assert data['items'][0]['notice_pk'] == ids[3]
            assert sum(x['count'] for x in data['overview_status_counts']) == 1
            assert data['workspace_counts'] == dict(actionable=1, recent=1, tracking=1, all=4)
            assert _list(session, workspace=workspace, review_exclusion='excluded')['total'] == 0
            assert _list(session, workspace=workspace, offset=1)['items'] == []
        assert _list(session, workspace='tracking')['items'][0]['review_exclusion_status'] == 'excluded'
        assert _list(session, review_exclusion='excluded', limit=1, offset=2)['total'] == 3
        assert _list(session, review_exclusion='included')['total'] == 1
        from app.lifecycle.models import Opportunity
        assert session.get(Opportunity, owner_id).tracking_status == '계속 추적'


@requires_postgres
def test_upgrade_existing_database_and_app_role():
    _ensure_roles()
    with temporary_database(upgrade_to='0029_c2_quality_gate') as url:
        engine = create_engine(url)
        with engine.begin() as connection:
            # Reconstruct the actual pre-feature schema (bootstrap uses live ORM).
            for name in ('review_exclusion_status', 'review_exclusion_actor_name', 'review_exclusion_reason', 'review_exclusion_changed_at'):
                connection.execute(text(f'ALTER TABLE bidops.notice DROP COLUMN {name} CASCADE'))
            id = connection.scalar(text("INSERT INTO bidops.notice (notice_key, source_type) VALUES ('pre:old', 'pre_spec') RETURNING id"))
        result = run_alembic(url, 'upgrade', 'head')
        assert result.returncode == 0, result.stderr
        policy_engine = _apply_policy(url)
        policy_engine.dispose()
        bound = schema_bound(engine)
        ensure_database_current(bound)
        with Session(bound) as session:
            session.execute(text('SET LOCAL ROLE app'))
            row = session.get(Notice, id)
            assert row.review_exclusion_status == 'included'
            assert row.review_exclusion_changed_at is None
            from app.lifecycle.routers.pre_specs import update_review_exclusions
            from app.lifecycle.schemas.pre_specs import PreSpecReviewExclusionRequest
            result = update_review_exclusions(PreSpecReviewExclusionRequest(**payload([id])), session)
            assert result.items[0].outcome == 'changed'
        with Session(bound) as session:
            assert session.get(Notice, id).review_exclusion_status == 'excluded'
            assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        engine.dispose()


@requires_postgres
def test_concurrent_overlapping_requests_change_each_row_once():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.lifecycle.routers.pre_specs import update_review_exclusions
    from app.lifecycle.schemas.pre_specs import PreSpecReviewExclusionRequest
    with migrated_engine() as engine:
        ids = seed(engine)
        start = Barrier(2)
        def change(values):
            with Session(engine) as session:
                start.wait(timeout=5)
                return update_review_exclusions(PreSpecReviewExclusionRequest(**payload(values)), session)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(change, [ids, ids[::-1]]))
        assert sorted([item.outcome for response in responses for item in response.items]) == ['changed', 'changed', 'unchanged', 'unchanged']
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(AuditEvent)) == 2
