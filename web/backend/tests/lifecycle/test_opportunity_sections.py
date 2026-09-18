"""사업 추적 구역·조치 사유·보류 기한·검색의 SQL 분류, 감사 이력과 사람 저장 계약."""
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.core.models import AuditEvent
from app.lifecycle.models import Notice, Opportunity, OpportunityLink, OrderPlan
from app.lifecycle.routers import opportunities as opportunities_router
from app.lifecycle.services.opportunity_queries import (
    count_hold_review,
    count_opportunity_section,
    get_opportunity,
    list_opportunities,
)
from tests.postgres import migrated_engine, requires_postgres

NOW = datetime(2026, 9, 7, tzinfo=UTC)
# 목록 요청의 고정 기준 시각. NOW에 보류한 사업은 아직 기한 전이다.
CLOCK = NOW + timedelta(days=1)
KST = timezone(timedelta(hours=9))
router = opportunities_router.router
NO_REASONS = {'new_link': 0, 'candidate_pending': 0, 'merge_confirmation': 0, 'blocking_item': 0, 'hold_overdue': 0}


@pytest.fixture
def workspace(empty_extensions, monkeypatch):
    monkeypatch.setattr(opportunities_router, '_request_now', lambda: CLOCK)
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


def add_link(session, opportunity, *, status='확정', strategy=None, notice=None):
    if notice is None:
        notice = Notice(notice_key=f'pre:fixture-{uuid4()}', source_type='pre_spec', title='합성 사업')
        session.add(notice)
        session.flush()
    official = status == '확정'
    link = OpportunityLink(opportunity_id=opportunity.id, notice_id=notice.id, stage='notice',
                           link_type='official' if official else 'candidate', status=status,
                           search_strategy=strategy,
                           evidence_external_no=notice.notice_key if official else None)
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
    add_link(session, pending, status='후보 확인 대기', strategy='full')
    merge_asked = add_opportunity(session, status='계속 추적')
    add_link(session, merge_asked, status='후보 확인 대기', strategy='merge_confirmation')
    blocked = add_opportunity(session, status='계속 추적')
    blocking_link = add_link(session, blocked)
    # 종료는 새 연결·후보만 올린다. 차단 항목만 있으면 추적 종료에 남는다.
    closed_blocked = add_opportunity(session, status='종료')
    closed_blocking_link = add_link(session, closed_blocked)
    # 미선택은 사유가 있어도 조치 필요가 아니다. 사유는 모든 행에 계산한다.
    undecided_pending = add_opportunity(session)
    add_link(session, undecided_pending, status='후보 확인 대기', strategy='normalized')
    registry.register_judgment_projection(
        BlockingProjection({blocking_link.notice_id: 2, closed_blocking_link.notice_id: 1}), owner='test'
    )
    searched = add_opportunity(session, status='종료')
    session.add(OpportunityLink(opportunity_id=searched.id, stage='notice', link_type='candidate',
                                status='검색 미확인', attempted_strategies_json=['full']))
    merged = add_opportunity(session, stage='bid_notice')
    merged.merged_into_opportunity_id = tracked.id
    merged.merged_at = NOW
    merged.merge_reason = '합성 병합'
    session.commit()

    body = client.get('/api/opportunities').json()
    expected = {undecided.id: None, plan.id: None, bid.id: '신규 입찰공고', tracked.id: '추적 중',
                held.id: '보류', closed.id: '추적 종료', signaled.id: '조치 필요',
                pending.id: '조치 필요', merge_asked.id: '조치 필요', blocked.id: '조치 필요',
                closed_blocked.id: '추적 종료', undecided_pending.id: None, searched.id: '추적 종료'}
    assert {row['id']: row['section'] for row in body['items']} == expected
    reasons = {signaled.id: ['new_link'], pending.id: ['candidate_pending'],
               merge_asked.id: ['merge_confirmation'], blocked.id: ['blocking_item'],
               closed_blocked.id: ['blocking_item'], undecided_pending.id: ['candidate_pending']}
    assert {row['id']: row['action_reasons'] for row in body['items']} == {
        pk: reasons.get(pk, []) for pk in expected
    }
    held_ids = {held.id, pending.id}
    assert all(row['hold_review_due_at'] is None for row in body['items'] if row['id'] not in held_ids)
    assert {datetime.fromisoformat(row['hold_review_due_at']) for row in body['items']
            if row['id'] in held_ids} == {NOW + timedelta(days=14)}
    assert body['section_counts'] == {'조치 필요': 4, '추적 중': 1, '보류': 1, '추적 종료': 3,
                                      '신규 입찰공고': 1, '미결정': 3}
    assert body['action_reason_counts'] == {**NO_REASONS, 'new_link': 1, 'candidate_pending': 2,
                                            'merge_confirmation': 1, 'blocking_item': 2}
    assert sum(body['section_counts'].values()) == body['total'] == 13
    rows = {row['id']: row for row in body['items']}
    assert rows[pending.id]['pending_candidate_link_count'] == 1
    assert rows[merge_asked.id]['pending_candidate_link_count'] == 1
    assert rows[blocked.id]['open_blocking_item_count'] == 2
    assert rows[searched.id]['pending_candidate_link_count'] == 0
    for pk, section in expected.items():
        detail = client.get(f'/api/opportunities/{pk}').json()
        assert detail['section'] == section
        assert detail['action_reasons'] == rows[pk]['action_reasons']
        assert detail['hold_review_due_at'] == rows[pk]['hold_review_due_at']
        assert detail['open_blocking_item_count'] == rows[pk]['open_blocking_item_count']
        assert detail['pending_candidate_link_count'] == rows[pk]['pending_candidate_link_count']

    action = client.get('/api/opportunities', params={'section': '조치 필요', 'limit': 1, 'offset': 1}).json()
    assert action['total'] == 4 and len(action['items']) == 1
    assert action['section_counts'] == body['section_counts']
    # 사유 집계는 활성 reason 필터만 빼고 센다. 구역 필터는 적용된다.
    assert action['action_reason_counts'] == {**NO_REASONS, 'new_link': 1, 'candidate_pending': 1,
                                              'merge_confirmation': 1, 'blocking_item': 1}
    combined = client.get('/api/opportunities', params={'section': '조치 필요', 'tracking_status': '보류'}).json()
    assert [row['id'] for row in combined['items']] == [pending.id]
    assert combined['section_counts'] == {'조치 필요': 1, '추적 중': 0, '보류': 1, '추적 종료': 0,
                                          '신규 입찰공고': 0, '미결정': 0}
    stage = client.get('/api/opportunities', params={'section': '조치 필요', 'first_registered_stage': 'order_plan'}).json()
    assert stage['total'] == 0 and stage['section_counts']['미결정'] == 1
    newcomers = client.get('/api/opportunities', params={'section': '신규 입찰공고'}).json()
    assert [row['id'] for row in newcomers['items']] == [bid.id] and newcomers['total'] == 1

    by_reason = client.get('/api/opportunities', params={'reason': 'candidate_pending'}).json()
    assert {row['id'] for row in by_reason['items']} == {pending.id, undecided_pending.id}
    assert by_reason['total'] == 2
    assert by_reason['section_counts'] == {'조치 필요': 1, '추적 중': 0, '보류': 0, '추적 종료': 0,
                                           '신규 입찰공고': 0, '미결정': 1}
    assert by_reason['action_reason_counts'] == body['action_reason_counts']
    closed_blocking = client.get('/api/opportunities', params={'reason': 'blocking_item', 'section': '추적 종료'}).json()
    assert [row['id'] for row in closed_blocking['items']] == [closed_blocked.id]
    assert closed_blocking['action_reason_counts'] == {**NO_REASONS, 'blocking_item': 1}

    assert count_opportunity_section(session, '조치 필요', now=CLOCK) == 4
    assert count_opportunity_section(session, '신규 입찰공고', now=CLOCK) == 1
    for params in ({'section': '미결정'}, {'reason': 'stage_overdue'}, {'hold_review': 'soon'},
                   {'sort': 'due'}):
        assert client.get('/api/opportunities', params=params).status_code == 422


def test_stale_pending_candidate_already_owned_by_its_owner_is_not_actionable(workspace):
    client, session, _, _ = workspace
    tracked = add_opportunity(session, status='계속 추적')
    official = add_link(session, tracked)
    # 뒤늦은 공식 연결·자동 병합이 이미 같은 대상을 소유하게 만든 대기 후보다.
    add_link(session, tracked, status='후보 확인 대기', strategy='full', notice=official.notice)
    held = add_opportunity(session, status='보류')
    add_link(session, held, status='후보 확인 대기', strategy='full', notice=official.notice)
    session.commit()

    body = client.get('/api/opportunities').json()
    rows = {row['id']: row for row in body['items']}
    assert rows[tracked.id]['section'] == '추적 중'
    assert rows[tracked.id]['action_reasons'] == [] and rows[tracked.id]['pending_candidate_link_count'] == 0
    assert rows[held.id]['section'] == '조치 필요'
    assert rows[held.id]['action_reasons'] == ['candidate_pending']
    assert rows[held.id]['pending_candidate_link_count'] == 1
    assert client.get(f'/api/opportunities/{tracked.id}').json()['section'] == '추적 중'


def _held(session, selected_at, *, stage='pre_spec'):
    item = add_opportunity(session, stage=stage, status='보류')
    item.tracking_selected_at = selected_at
    session.flush()
    return item


def _assert_hold_review_boundaries(session, now):
    """보류 기한 경계: 기한 = now는 지남, now + 1µs는 임박, now + 3일은 임박, 그 뒤는 해당 없음."""

    period = timedelta(days=14)
    micro = timedelta(microseconds=1)
    exactly_due = _held(session, (now - period).astimezone(KST))
    due_after_one_micro = _held(session, now - period + micro)
    due_soon_edge = _held(session, now - period + timedelta(days=3))
    later = _held(session, now - period + timedelta(days=3) + micro)
    tracked = add_opportunity(session, status='계속 추적')
    tracked.tracking_selected_at = now - timedelta(days=90)
    undecided = add_opportunity(session)
    session.flush()
    exactly_due, due_after_one_micro, due_soon_edge, later, tracked, undecided = (
        item.id for item in (exactly_due, due_after_one_micro, due_soon_edge, later, tracked, undecided)
    )
    session.commit()
    session.expunge_all()
    ids = lambda response: [item.id for item in response.items]

    overdue = list_opportunities(session, hold_review='overdue', now=now)
    assert ids(overdue) == [exactly_due]
    assert overdue.items[0].hold_review_due_at == now
    assert overdue.items[0].action_reasons == ['hold_overdue'] and overdue.items[0].section == '조치 필요'
    assert overdue.action_reason_counts['hold_overdue'] == 1
    assert overdue.section_counts['조치 필요'] == overdue.total == 1
    due_soon = list_opportunities(session, hold_review='due_soon', now=now)
    assert set(ids(due_soon)) == {due_after_one_micro, due_soon_edge}
    assert {item.section for item in due_soon.items} == {'보류'}
    assert due_soon.action_reason_counts['hold_overdue'] == 0
    attention = list_opportunities(session, hold_review='attention', now=now)
    assert set(ids(attention)) == {exactly_due, due_after_one_micro, due_soon_edge}
    by_reason = list_opportunities(session, reason='hold_overdue', section='조치 필요', now=now)
    assert ids(by_reason) == [exactly_due]

    ordered = list_opportunities(session, sort='hold_review_due_at', now=now)
    assert ids(ordered)[:4] == [exactly_due, due_after_one_micro, due_soon_edge, later]
    assert set(ids(ordered)[4:]) == {tracked, undecided}
    assert [item.hold_review_due_at for item in ordered.items[:4]] == [
        now, now + micro, now + timedelta(days=3), now + timedelta(days=3) + micro
    ]
    assert all(item.hold_review_due_at is None for item in ordered.items[4:])

    # 같은 순간을 +09:00으로 넘겨도 결과가 같다. 1µs 앞이면 기한 전이다.
    assert ids(list_opportunities(session, hold_review='overdue', now=now.astimezone(KST))) == [exactly_due]
    assert list_opportunities(session, hold_review='overdue', now=now - micro).total == 0
    assert count_hold_review(session, 'overdue', now=now) == 1
    assert count_hold_review(session, 'due_soon', now=now) == 2
    assert count_hold_review(session, 'attention', now=now.astimezone(KST)) == 3
    assert count_opportunity_section(session, '조치 필요', now=now) == 1
    assert count_opportunity_section(session, '조치 필요', now=now - micro) == 0
    detail = get_opportunity(session, exactly_due, now=now)
    assert detail.action_reasons == ['hold_overdue'] and detail.hold_review_due_at == now
    with pytest.raises(ValueError):
        list_opportunities(session, now=now.replace(tzinfo=None))


def test_hold_review_due_boundaries_are_exact_to_the_microsecond(workspace):
    client, session, _, _ = workspace
    now = datetime(2026, 9, 20, 3, 0, 0, 123456, tzinfo=UTC)
    _assert_hold_review_boundaries(session, now)


def test_hold_review_query_params_use_the_request_clock(workspace, monkeypatch):
    client, session, _, _ = workspace
    now = datetime(2026, 9, 20, 3, 0, 0, 654321, tzinfo=UTC)
    monkeypatch.setattr(opportunities_router, '_request_now', lambda: now)
    due = _held(session, now - timedelta(days=14))
    soon = _held(session, now - timedelta(days=13))
    session.commit()
    body = client.get('/api/opportunities', params={'hold_review': 'attention', 'sort': 'hold_review_due_at', 'limit': 5}).json()
    assert [row['id'] for row in body['items']] == [due.id, soon.id]
    assert datetime.fromisoformat(body['items'][0]['hold_review_due_at']) == now
    assert body['items'][0]['action_reasons'] == ['hold_overdue']
    assert client.get('/api/opportunities', params={'hold_review': 'overdue'}).json()['total'] == 1
    assert client.get('/api/opportunities', params={'reason': 'hold_overdue', 'section': '조치 필요'}).json()['total'] == 1


def _owned_plan(session, opportunity, *, title, agency):
    plan = OrderPlan(order_plan_unty_no=f'R26DD{uuid4().int % 10**8:08d}', title=title, agency_name=agency)
    session.add(plan)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity.id, order_plan_id=plan.id, stage='order_plan',
                                link_type='official', status='확정', evidence_external_no=plan.order_plan_unty_no))
    session.flush()
    return plan


def _assert_search_matches_owned_records(session, now):
    plan_owner = add_opportunity(session, stage='order_plan', status='계속 추적')
    _owned_plan(session, plan_owner, title='Smart  City 통합플랫폼 구축', agency='서울특별시 강남구')
    notice_owner = add_opportunity(session)
    owned_notice = Notice(notice_key=f'pre:search-{uuid4()}', source_type='pre_spec', title='다른 사업',
                          agency='부산광역시', demand_agency='해양 수산부')
    session.add(owned_notice)
    session.flush()
    add_link(session, notice_owner, notice=owned_notice)
    # 대기 후보의 대상 제목은 검색하지 않는다.
    candidate_owner = add_opportunity(session, status='보류')
    stranger = Notice(notice_key=f'pre:search-{uuid4()}', source_type='pre_spec', title='SMART CITY 통합플랫폼')
    session.add(stranger)
    session.flush()
    add_link(session, candidate_owner, status='후보 확인 대기', strategy='full', notice=stranger)
    session.commit()
    ids = lambda **params: {item.id for item in list_opportunities(session, now=now, **params).items}

    assert ids(q='smart city통합') == {plan_owner.id}
    assert ids(q=' 해양수산부 ') == {notice_owner.id}
    assert ids(q='강남 구') == {plan_owner.id}
    assert ids(q='%%') == set()
    assert ids(q='플랫폼', section='추적 중') == {plan_owner.id}
    counted = list_opportunities(session, q='플랫폼', now=now)
    assert counted.total == sum(counted.section_counts.values()) == 1


def test_q_matches_owned_records_ignoring_case_and_whitespace(workspace):
    client, session, _, _ = workspace
    _assert_search_matches_owned_records(session, CLOCK)
    assert client.get('/api/opportunities', params={'q': '통합플랫폼'}).json()['total'] == 1
    blank = client.get('/api/opportunities', params={'q': ' a '})
    assert blank.status_code == 422 and blank.json()['error']['code'] == 'invalid_request'
    assert client.get('/api/opportunities', params={'q': 'a'}).status_code == 422
    assert client.get('/api/opportunities', params={'q': 'x' * 101}).status_code == 422


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
    opportunity = add_opportunity(session, status='계속 추적')
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
    with migrated_engine() as engine, Session(engine) as session:
        held = add_opportunity(session, status='보류')
        blocked = add_opportunity(session, status='보류')
        link = add_link(session, blocked)
        stale_owner = add_opportunity(session, status='계속 추적')
        stale_target = add_link(session, stale_owner)
        add_link(session, stale_owner, status='후보 확인 대기', strategy='full', notice=stale_target.notice)
        provider = BlockingProjection({link.notice_id: 4})
        empty_extensions.register_judgment_projection(provider, owner='test')
        session.commit()
        response = list_opportunities(session, tracking_status='보류', section='조치 필요', limit=1, now=CLOCK)
        assert response.total == 1
        assert response.items[0].id == blocked.id
        assert response.items[0].open_blocking_item_count == 4
        assert response.items[0].action_reasons == ['blocking_item']
        assert response.section_counts == {'조치 필요': 1, '추적 중': 0, '보류': 1, '추적 종료': 0,
                                           '신규 입찰공고': 0, '미결정': 0}
        assert response.action_reason_counts == {**NO_REASONS, 'blocking_item': 1}
        assert held.id != blocked.id
        assert get_opportunity(session, stale_owner.id, now=CLOCK).section == '추적 중'


@requires_postgres
def test_hold_review_boundaries_and_search_execute_on_postgresql(empty_extensions):
    now = datetime(2026, 9, 20, 3, 0, 0, 123456, tzinfo=UTC)
    with migrated_engine() as engine, Session(engine) as session:
        _assert_hold_review_boundaries(session, now)
    with migrated_engine() as engine, Session(engine) as session:
        _assert_search_matches_owned_records(session, now)


def _assert_link_loading_query_count_is_constant(session, registry, engine):
    """하나의 페이지 안에서도 연결 공고 500개 경계가 조회를 늘리면 안 된다."""

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
            response = list_opportunities(session, section='조치 필요', limit=1, now=CLOCK)
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
