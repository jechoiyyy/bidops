"""Shared worker boundary with synthetic source and runner; never calls Luna."""
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.app.test_deep_reviews import engine
from tests.app.test_luna_deep_review import setup
from tests.postgres import migrated_engine
from app.deep_review.models import AssumptionInputVersion, AssumptionRun, AssumptionStage
from app.deep_review.services.assumption_analysis import AssumptionAnalysisService
from app.deep_review.services.assumption_report import SECTIONS
from app.deep_review.services.deep_reviews import DeepReviewServiceError
from app.core.model_client import InvocationResult, ModelInvocationError


class Runner:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def invoke_prompt(self, prompt, *, contract):
        data = json.loads(prompt); self.calls.append(data)
        assert contract == 'assumption-stage-v1'
        assert data['scenario']['settings']['model'] == 'gpt-5.6-luna'
        if data['stage'] == self.fail:
            raise ModelInvocationError('output_truncated', (), b'{"partial":')
        keys = list(SECTIONS) if data['stage'] == 'decision' else ['scope']
        output = {'sections': [{'key': key, 'paragraphs': [{'kind': 'interpretation',
            'body': '검토 조건이 수행 비용에 영향을 주므로 문서의 계약 조건을 확인해야 합니다.',
            'refs': [{'source_id': 'missing-reference', 'quote': '원문에 없는 인용'},
                     {'source_id': 'document-1', 'quote': next(s[2] for s in data['sources'] if s[0] == 'document-1')}]}]} for key in keys]}
        raw = json.dumps(output).encode()
        return InvocationResult(output, raw, hashlib.sha256(prompt.encode()).hexdigest(), hashlib.sha256(raw).hexdigest(),
                                None, None, 1, (), 'codex-exec', 'gpt-5.6-luna')


def context(engine, monkeypatch, fail=None):
    notice, bundle, base = setup(engine, monkeypatch)
    service = AssumptionAnalysisService(base=base, client=Runner(fail))
    # Fixture notice uses its seeded PK; production remains explicitly 1489-only.
    from app.deep_review.services.assumption_inputs import scenario
    from app.deep_review.services.assumption_analysis import execution_contract
    from app.deep_review.services.input_versions import resolve_active_versions
    from app.deep_review.services.luna_inputs import snapshot
    from app.lifecycle import lock_notice
    def synthetic(session, notice_id, bundle_id):
        profile, policy = resolve_active_versions(session, allow_unmeasured_reference=True)
        data = snapshot(base, session, lock_notice(session, notice_id), bundle_id, profile, policy, False)
        data.pop('policy'); data['schema'] = 'bidops.assumption-input.v1'; data['scenario'] = scenario()
        data['prompt_contract'] = execution_contract()
        return data, profile.id
    monkeypatch.setattr(service, '_snapshot', synthetic)
    return notice, bundle, service


def exercise(engine, monkeypatch, fail=None):
    notice, bundle, service = context(engine, monkeypatch, fail)
    with Session(engine) as session:
        preview = service.preview(session, notice, bundle)
        request = uuid4(); pid = UUID(preview['preview_id'])
        created = service.create(session, notice, pid, 'tester', request)
        assert service.create(session, notice, pid, 'tester', request) == created
        with pytest.raises(DeepReviewServiceError, match='이미 승인'):
            service.create(session, notice, pid, 'tester', uuid4())
        assert service.run_once(session, 'test-worker') is True
        result = service.view(session, UUID(created['id']))
        assert result['call_count'] == (2 if fail else 3)
        assert result['status'] == ('failed' if fail else 'completed'), result
        if fail:
            assert result['report'] is None
            assert result['stages'][0]['result']['sections']
            assert result['error_code'] == 'output_truncated'
        else:
            assert len(result['report']['sections']) == 8
            ref = result['report']['sections'][0]['paragraphs'][0]['refs'][0]
            assert ref['status'] == 'unlinked'
        assert all(r.raw_content_object_id for r in session.scalars(select(AssumptionStage)).all())
        assert service.run_once(session, 'test-worker') is False
        return result


@pytest.mark.parametrize('fail', [None, 'company'])
def test_approval_three_calls_and_partial_results(engine, monkeypatch, fail):
    exercise(engine, monkeypatch, fail)


@pytest.mark.requires_postgres
def test_postgres_results(monkeypatch):
    with migrated_engine() as engine:
        exercise(engine, monkeypatch)


def test_preview_changes_and_active_run_are_rejected(engine, monkeypatch):
    notice, bundle, service = context(engine, monkeypatch)
    with Session(engine) as session:
        pre = service.preview(session, notice, bundle)
        original = service._snapshot
        def changed(*args):
            data, profile = original(*args)
            data['scenario']['version'] = 'changed'
            return data, profile
        monkeypatch.setattr(service, '_snapshot', changed)
        with pytest.raises(DeepReviewServiceError) as error:
            service.create(session, notice, UUID(pre['preview_id']), 'tester', uuid4())
        assert error.value.code == 'preview_changed'
        assert session.scalar(select(AssumptionRun)) is None
        monkeypatch.setattr(service, '_snapshot', original)
        created = service.create(session, notice, UUID(pre['preview_id']), 'tester', uuid4())
        other = service.preview(session, notice, bundle)
        with pytest.raises(DeepReviewServiceError) as error:
            service.create(session, notice, UUID(other['preview_id']), 'tester', uuid4())
        assert error.value.code == 'active_run_exists'


def test_late_result_is_not_published_and_never_retried(engine, monkeypatch):
    from datetime import timedelta
    notice, bundle, service = context(engine, monkeypatch)
    invoke = service.client.invoke_prompt
    def late(*args, **kwargs):
        result = invoke(*args, **kwargs)
        now = service.base.clock()
        service.base.clock = lambda: now + timedelta(hours=3)
        return result
    service.client.invoke_prompt = late
    with Session(engine) as session:
        pre = service.preview(session, notice, bundle)
        created = service.create(session, notice, UUID(pre['preview_id']), 'tester', uuid4())
        service.run_once(session, 'worker-one')
        assert service.view(session, UUID(created['id']))['status'] == 'failed'
        assert service.run_once(session, 'worker-two') is False
        assert len(service.client.calls) == 1
        assert session.scalar(select(AssumptionStage)) is None


def rest_exercise(engine, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.db import get_db
    from app.deep_review.routers import assumption_analysis as router
    from pathlib import Path
    import os
    notice, bundle, service = context(engine, monkeypatch)
    monkeypatch.setattr(router, 'service', service)
    app = FastAPI(); app.include_router(router.router)
    def db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = db
    http = TestClient(app)
    pre = http.post(f'/api/notices/{notice}/assumption-analysis-previews', json={'bundle_id': str(bundle)})
    assert pre.status_code == 200, pre.text
    payload = {'preview_id': pre.json()['preview_id'], 'request_id': str(uuid4())}
    assert http.post(f'/api/notices/{notice}/assumption-analyses', json=payload).status_code == 400
    response = http.post(f'/api/notices/{notice}/assumption-analyses', json=payload, headers={'X-BidOps-Actor-Name':'tester'})
    assert response.status_code == 202, response.text
    with Session(engine) as session:
        assert service.run_once(session, 'rest-worker')
    detail = http.get('/api/assumption-analyses/' + response.json()['id'])
    assert detail.status_code == 200, detail.text
    assert detail.json()['status'] == 'completed'
    assert http.get(f'/api/notices/{notice}/assumption-analyses').json()['items'][0]['id'] == response.json()['id']
    if os.environ.get('BIDOPS_ASSUMPTION_FIXTURE'):
        Path(os.environ['BIDOPS_ASSUMPTION_FIXTURE']).write_text(json.dumps({'preview':pre.json(), 'analysis':detail.json()}, ensure_ascii=False, indent=2))


def test_rest(engine, monkeypatch):
    rest_exercise(engine, monkeypatch)


@pytest.mark.requires_postgres
def test_postgres_rest_and_append_only(monkeypatch):
    from sqlalchemy import text
    with migrated_engine() as engine:
        rest_exercise(engine, monkeypatch)
        for table in ('assumption_input_version', 'assumption_run', 'assumption_stage'):
            with pytest.raises(Exception):
                with engine.begin() as connection:
                    connection.execute(text(f'UPDATE {table} SET id = id'))
            with pytest.raises(Exception):
                with engine.begin() as connection:
                    connection.execute(text(f'DELETE FROM {table}'))


@pytest.mark.requires_postgres
def test_concurrent_submission_is_idempotent(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    with migrated_engine() as engine:
        notice, bundle, service = context(engine, monkeypatch)
        with Session(engine) as session:
            pre = service.preview(session, notice, bundle)
        request = uuid4()
        def submit():
            with Session(engine) as session:
                return service.create(session, notice, UUID(pre['preview_id']), 'tester', request)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one, two = list(pool.map(lambda _: submit(), range(2)))
        assert one == two
        with Session(engine) as session:
            assert len(session.scalars(select(AssumptionRun)).all()) == 1


def test_changed_execution_code_invalidates_queued_consent(engine, monkeypatch):
    from app.deep_review.services import assumption_analysis as module
    notice, bundle, service = context(engine, monkeypatch)
    with Session(engine) as session:
        pre = service.preview(session, notice, bundle)
        created = service.create(session, notice, UUID(pre['preview_id']), 'tester', uuid4())
        monkeypatch.setattr(module, 'execution_contract', lambda: {'version': 'changed-after-consent'})
        assert service.run_once(session, 'worker')
        result = service.view(session, UUID(created['id']))
        assert result['status'] == 'failed'
        assert result['error_code'] == 'execution_config_changed'
        assert result['call_count'] == 0 and service.client.calls == []


@pytest.mark.requires_postgres
def test_upgrade_from_0032_preserves_existing_audit():
    from sqlalchemy import create_engine, text
    from tests.postgres import temporary_database, run_alembic
    with temporary_database(upgrade_to='0032_luna_deep_review') as url:
        db = create_engine(url)
        marker = uuid4()
        with db.begin() as connection:
            connection.execute(text("INSERT INTO bidops.audit_event (id,actor_kind,action,aggregate_type,aggregate_id,safe_metadata,created_at) VALUES (:id,'system','test.existing','test','existing','{}',now())"), {'id':marker})
        result = run_alembic(url, 'upgrade', 'head')
        assert result.returncode == 0, result.stderr
        with db.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM bidops.audit_event WHERE id=:id'), {'id':marker}) == 1
            assert connection.scalar(text('SELECT version_num FROM bidops.alembic_version')) == '0033_assumption_analysis'
        db.dispose()
