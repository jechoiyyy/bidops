"""사업 추적 구역·감사 이력의 SQL 분류와 사람 저장 계약."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.core.models import AuditEvent
from app.lifecycle.models import Notice, Opportunity, OpportunityLink
from app.lifecycle.routers.opportunities import router
from tests.postgres import migrated_engine, requires_postgres

NOW = datetime(2026, 9, 7, tzinfo=UTC)


@pytest.fixture
def workspace(empty_extensions):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    init_db(engine)
    with Session(engine) as session:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: session
        with TestClient(app) as client:
            yield client, session, empty_extensions, engine
    engine.dispose()


def add_opportunity(session, *, stage='pre_spec', status='미선택'):
    item = Opportunity(first_registered_stage=stage, tracking_status=status, created_at=NOW)
    if status != '미선택':
        item.tracking_reason = '검토 결과'
        item.tracking_selected_by = '담당자'
        item.tracking_selected_at = NOW
    session.add(item)
    session.flush()
    return item


def add_link(session, opportunity, *, status='확정'):
    notice = Notice(notice_key=f'pre:fixture-{uuid4()}', source_type='pre_spec', title='합성 사업')
    session.add(notice)
    session.flush()
    link = OpportunityLink(opportunity_id=opportunity.id, notice_id=notice.id, stage='notice',
                           link_type='official' if status == '확정' else 'candidate', status=status,
                           evidence_external_no=notice.notice_key)
    session.add(link)
    session.flush()
    return link


class BlockingProjection:
    def __init__(self, counts):
        self.counts = counts
        self.requested = []

    def notice_ids_with_open_blocking_items(self, session):
        return list(self.counts)

    def open_blocking_item_counts(self, session, notice_ids):
        self.requested.append(tuple(notice_ids))
        return {pk: self.counts[pk] for pk in notice_ids if pk in self.counts}


def test_sections_are_first_match_and_counts_cover_all_filtered_rows(workspace):
    client, session, registry, _ = workspace
    undecided = add_opportunity(session)
    plan = add_opportunity(session, stage='order_plan')
    bid = add_opportunity(session, stage='bid_notice')
    tracked = add_opportunity(session, status='계속 추적')
    held = add_opportunity(session, status='보류')
    closed = add_opportunity(session, status='종료')
    signaled = add_opportunity(session, status='종료')
    signal_link = add_link(session, signaled)
    signaled.recheck_signal_at = NOW
    signaled.recheck_signal_link_id = signal_link.id
    pending = add_opportunity(session, status='보류')
    add_link(session, pending, status='후보 확인 대기')
    blocked = add_opportunity(session, status='계속 추적')
    blocking_link = add_link(session, blocked)
    registry.register_judgment_projection(BlockingProjection({blocking_link.notice_id: 2}), owner='test')
    searched = add_opportunity(session, status='종료')
    session.add(OpportunityLink(opportunity_id=searched.id, stage='notice', link_type='candidate',
                                status='검색 미확인', attempted_strategies_json=['full']))
    merged = add_opportunity(session, stage='bid_notice')
    merged.merged_into_opportunity_id = tracked.id
    merged.merged_at = NOW
    merged.merge_reason = '합성 병합'
    session.commit()

    body = client.get('/api/opportunities').json()
    expected = {undecided.id: None, plan.id: None, bid.id: '조치 필요', tracked.id: '추적 중',
                held.id: '보류', closed.id: '추적 종료', signaled.id: '조치 필요',
                pending.id: '조치 필요', blocked.id: '조치 필요', searched.id: '추적 종료'}
    assert {row['id']: row['section'] for row in body['items']} == expected
    assert body['section_counts'] == {'조치 필요': 4, '추적 중': 1, '보류': 1, '추적 종료': 2, '미결정': 2}
    assert sum(body['section_counts'].values()) == body['total'] == 10
    rows = {row['id']: row for row in body['items']}
    assert rows[pending.id]['pending_candidate_link_count'] == 1
    assert rows[blocked.id]['open_blocking_item_count'] == 2
    assert rows[searched.id]['pending_candidate_link_count'] == 0
    for pk, section in expected.items():
        detail = client.get(f'/api/opportunities/{pk}').json()
        assert detail['section'] == section
        assert detail['open_blocking_item_count'] == rows[pk]['open_blocking_item_count']
        assert detail['pending_candidate_link_count'] == rows[pk]['pending_candidate_link_count']

    action = client.get('/api/opportunities', params={'section': '조치 필요', 'limit': 1, 'offset': 1}).json()
    assert action['total'] == 4 and len(action['items']) == 1
    assert action['section_counts'] == body['section_counts']
    combined = client.get('/api/opportunities', params={'section': '조치 필요', 'tracking_status': '보류'}).json()
    assert [row['id'] for row in combined['items']] == [pending.id]
    assert combined['section_counts'] == {'조치 필요': 1, '추적 중': 0, '보류': 1, '추적 종료': 0, '미결정': 0}
    stage = client.get('/api/opportunities', params={'section': '조치 필요', 'first_registered_stage': 'order_plan'}).json()
    assert stage['total'] == 0 and stage['section_counts']['미결정'] == 1
    assert client.get('/api/opportunities', params={'section': '미결정'}).status_code == 422


def test_history_reads_only_matching_audits_in_reverse_time_and_preserves_nulls(workspace):
    client, session, _, _ = workspace
    opportunity = add_opportunity(session)
    old = AuditEvent(actor_kind='human', claimed_name='과거 담당자', action='opportunity.tracking_status.changed',
                     aggregate_type='opportunity', aggregate_id=str(opportunity.id), created_at=NOW,
                     safe_metadata={'tracking_status': '계속 추적'})
    latest = AuditEvent(actor_kind='human', claimed_name='현재 담당자', action='opportunity.tracking_status.changed',
                        aggregate_type='opportunity', aggregate_id=str(opportunity.id), created_at=NOW + timedelta(hours=1),
                        safe_metadata={'tracking_status': '보류', 'previous_tracking_status': '계속 추적',
                                       'reason': '조건 확인', 'cleared_recheck_signal_link_id': 123, 'private_extra': '/private/hidden'})
    session.add_all([old, latest, AuditEvent(actor_kind='system', action='opportunity.recheck_signal.created',
                    aggregate_type='opportunity', aggregate_id=str(opportunity.id), safe_metadata={}),
                    AuditEvent(actor_kind='human', claimed_name='다른 담당자', action='opportunity.tracking_status.changed',
                    aggregate_type='other', aggregate_id=str(opportunity.id), safe_metadata={'tracking_status': '종료'})])
    session.commit()
    response = client.get(f'/api/opportunities/{opportunity.id}/tracking-decisions')
    assert response.status_code == 200
    body = response.json()
    assert body['opportunity_id'] == opportunity.id
    assert [item['audit_event_id'] for item in body['items']] == [str(latest.id), str(old.id)]
    assert body['items'][0]['reason'] == '조건 확인'
    assert body['items'][0]['cleared_recheck_signal'] is True
    assert body['items'][1]['reason'] is None
    assert body['items'][1]['previous_tracking_status'] is None
    assert body['items'][1]['cleared_recheck_signal'] is False
    assert '/private/hidden' not in response.text
    assert client.get('/api/opportunities/999999/tracking-decisions').status_code == 404


@pytest.mark.parametrize('status', ['계속 추적', '보류', '종료', '미선택'])
def test_human_save_clears_signal_even_for_same_status_and_preserves_audit(workspace, status):
    client, session, _, _ = workspace
    opportunity = add_opportunity(session, status=status)
    link = add_link(session, opportunity)
    opportunity.recheck_signal_at = NOW
    opportunity.recheck_signal_link_id = link.id
    session.commit()
    response = client.patch(f'/api/opportunities/{opportunity.id}/tracking-status',
                            headers={'X-BidOps-Actor-Name': 'operator'},
                            json={'tracking_status': status, 'reason': '  재검토 완료  '})
    assert response.status_code == 200
    body = response.json()
    assert body['tracking_status'] == status
    assert body['recheck_signal'] is False
    assert body['recheck_signal_at'] is None and body['recheck_signal_link_id'] is None
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == 'opportunity.tracking_status.changed'))
    assert audit.safe_metadata['reason'] == '재검토 완료'
    assert audit.safe_metadata['previous_tracking_status'] == status
    assert audit.safe_metadata['cleared_recheck_signal_link_id'] == link.id
    original = dict(audit.safe_metadata)
    client.patch(f'/api/opportunities/{opportunity.id}/tracking-status', headers={'X-BidOps-Actor-Name': 'operator'},
                 json={'tracking_status': status, 'reason': '두 번째 확인'})
    session.refresh(audit)
    assert audit.safe_metadata == original
    history = client.get(f'/api/opportunities/{opportunity.id}/tracking-decisions').json()['items']
    assert len(history) == 2 and history[0]['cleared_recheck_signal'] is False


@pytest.mark.parametrize('headers,code', [({}, 'actor_name_required'), ({'X-BidOps-Actor-Name': 'system'}, 'actor_name_invalid'),
                                        ({'X-BidOps-Actor-Name': '%ZZ', 'X-BidOps-Actor-Name-Format': 'utf-8-percent-v1'}, 'actor_name_invalid')])
def test_invalid_actor_keeps_signal_and_appends_no_audit(workspace, headers, code):
    client, session, _, _ = workspace
    opportunity = add_opportunity(session, status='종료')
    link = add_link(session, opportunity)
    opportunity.recheck_signal_at, opportunity.recheck_signal_link_id = NOW, link.id
    session.commit()
    response = client.patch(f'/api/opportunities/{opportunity.id}/tracking-status', headers=headers,
                            json={'tracking_status': '종료', 'reason': '확인'})
    assert response.status_code == 400 and response.json()['error']['code'] == code
    session.refresh(opportunity)
    assert opportunity.recheck_signal_at == NOW and opportunity.recheck_signal_link_id == link.id
    assert session.scalar(select(AuditEvent)) is None


def test_list_query_count_does_not_grow_with_rows_and_uses_page_batch(workspace):
    client, session, registry, engine = workspace
    counts = {}
    provider = BlockingProjection(counts)
    registry.register_judgment_projection(provider, owner='test')
    query_counts = []
    for size in (3, 21):
        while len(counts) < size:
            opportunity = add_opportunity(session, status='계속 추적')
            link = add_link(session, opportunity)
            counts[link.notice_id] = 2
        session.commit()
        session.expunge_all()
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            body = client.get('/api/opportunities', params={'section': '조치 필요', 'limit': 500}).json()
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert body['total'] == size and len(body['items']) == size
        assert all(row['open_blocking_item_count'] == 2 for row in body['items'])
        assert len(provider.requested[-1]) == size
        assert any('CASE' in sql and 'GROUP BY' in sql for sql in statements)
        assert any('LIMIT' in sql and 'CASE' in sql for sql in statements)
        query_counts.append(len(statements))
    assert query_counts[0] == query_counts[1]
    assert query_counts[0] <= 7


def test_blocking_uses_all_linked_notices_once_including_rejected_history(workspace):
    client, session, registry, _ = workspace
    opportunity = add_opportunity(session, status='종료')
    official = add_link(session, opportunity)
    session.add(OpportunityLink(opportunity_id=opportunity.id, notice_id=official.notice_id,
                                stage='notice', link_type='candidate', status='사람 확인 완료',
                                human_decision='rejected', reviewer_name='담당자', reviewed_at=NOW,
                                review_reason='연결 이력'))
    other_notice = Notice(notice_key='pre:rejected-only', source_type='pre_spec')
    session.add(other_notice)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity.id, notice_id=other_notice.id,
                                stage='notice', link_type='candidate', status='사람 확인 완료',
                                human_decision='rejected', reviewer_name='담당자', reviewed_at=NOW,
                                review_reason='연결 거절'))
    session.add(OpportunityLink(opportunity_id=opportunity.id, stage='notice', link_type='candidate',
                                status='검색 미확인', attempted_strategies_json=['full']))
    registry.register_judgment_projection(BlockingProjection({official.notice_id: 2, other_notice.id: 3}), owner='test')
    session.commit()
    body = client.get('/api/opportunities', params={'section': '조치 필요'}).json()
    assert body['total'] == 1
    assert body['items'][0]['pending_candidate_link_count'] == 0
    assert body['items'][0]['open_blocking_item_count'] == 5
    assert client.get(f'/api/opportunities/{opportunity.id}').json()['open_blocking_item_count'] == 5


@requires_postgres
def test_section_case_grouping_and_limit_execute_on_postgresql(empty_extensions):
    from app.lifecycle.services.opportunity_queries import list_opportunities
    with migrated_engine() as engine, Session(engine) as session:
        held = add_opportunity(session, status='보류')
        blocked = add_opportunity(session, status='보류')
        link = add_link(session, blocked)
        provider = BlockingProjection({link.notice_id: 4})
        empty_extensions.register_judgment_projection(provider, owner='test')
        session.commit()
        response = list_opportunities(session, tracking_status='보류', section='조치 필요', limit=1)
        assert response.total == 1
        assert response.items[0].id == blocked.id
        assert response.items[0].open_blocking_item_count == 4
        assert response.section_counts == {'조치 필요': 1, '추적 중': 0, '보류': 1, '추적 종료': 0, '미결정': 0}
        assert held.id != blocked.id


def _assert_link_loading_query_count_is_constant(session, registry, engine):
    """하나의 페이지 안에서도 연결 공고 500개 경계가 조회를 늘리면 안 된다."""
    from app.lifecycle.services.opportunity_queries import list_opportunities

    opportunity = add_opportunity(session, status='계속 추적')
    opportunity_id = opportunity.id
    counts = {}
    registry.register_judgment_projection(BlockingProjection(counts), owner='test')
    query_counts = []
    for link_count in (1, 501):
        opportunity = session.get(Opportunity, opportunity_id)
        while len(counts) < link_count:
            link = add_link(session, opportunity)
            counts[link.notice_id] = 1
        session.commit()
        session.expunge_all()
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, 'before_cursor_execute', capture)
        try:
            response = list_opportunities(session, section='조치 필요', limit=1)
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert response.total == 1 and len(response.items) == 1
        assert response.items[0].id == opportunity_id
        assert len(response.items[0].links) == link_count
        assert response.items[0].open_blocking_item_count == link_count
        assert all(link.title == '합성 사업' for link in response.items[0].links)
        query_counts.append(len(statements))
    assert query_counts[0] == query_counts[1], query_counts


def test_page_link_loading_is_constant_across_500_notice_boundary(workspace):
    _, session, registry, engine = workspace
    _assert_link_loading_query_count_is_constant(session, registry, engine)


@requires_postgres
def test_page_link_loading_is_constant_across_500_notice_boundary_on_postgresql(empty_extensions):
    with migrated_engine() as engine, Session(engine) as session:
        _assert_link_loading_query_count_is_constant(session, empty_extensions, engine)
