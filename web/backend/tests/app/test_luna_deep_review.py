"""Current Luna approval → synthesis worker → report tests; no external model."""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.app.test_deep_reviews import engine, _seed_review_context, _FixtureStore
from tests.app.test_narrative_review import NarrativeClient, structure_loader, SOURCE
from tests.postgres import migrated_engine
from app.core.config import get_settings
from app.deep_review.models import *
from app.lifecycle.models import Notice
from app.deep_review.services.deep_reviews import DeepReviewService, DeepReviewServiceError
from app.deep_review.services.input_versions import CANONICAL_POLICY_FILE, import_policy_version
from app.deep_review.services.luna_inputs import preview
from app.deep_review.services.reports import ReportService


def setup(engine, monkeypatch, *, policy_name='analysis-policy-luna-v1.json'):
    notice, bundle, _, _ = _seed_review_context(engine, monkeypatch, measured=False)
    with Session(engine) as session:
        session.get(Notice, notice).source_type = 'pre_spec'
        policy = import_policy_version(session, CANONICAL_POLICY_FILE.with_name(policy_name))
        structure = session.scalar(select(DocumentStructure))
        content = session.get(ContentObject, structure.payload_content_object_id)
        payload = ContentObject(sha256=structure.payload_sha256, size_bytes=1, detected_mime='application/json', retention_class='fixture')
        session.add(payload); session.flush()
        structure.payload_content_object_id = payload.id
        session.scalar(select(DocumentBundleItem)).detected_mime = content.detected_mime
        session.add(ContentScan(content_object_id=content.id, scanner='fixture', scanner_version='1', status='clean', safe_result={}))
        session.add(DocumentBlock(structure_id=structure.id, block_key='source-1', page=1, block_type='paragraph', content=SOURCE, attributes={}))
        job = WorkJob(job_type='prespec_overview', aggregate_type='prespec_overview_run', aggregate_id=uuid4(), status='completed')
        session.add(job); session.flush()
        session.add(PrespecOverviewRun(notice_id=notice, document_version_id=structure.document_version_id, work_job_id=job.id,
                    status='completed', range_source='auto', range_reason_codes=[], policy_digest='0'*64, model_name='fixture',
                    warnings_json=[], reason_codes=[], call_count=0, raw_response_refs=[], result_json={'schema_version':'test'}, completed_at=datetime.now(UTC)))
        session.commit()
        monkeypatch.setenv('BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID', str(policy.id))
    monkeypatch.setenv('BIDOPS_REFERENCE_WORKFLOW_MODE', 'true')
    monkeypatch.setenv('BIDOPS_LUNA_DEEP_REVIEW_ENABLED', 'true')
    get_settings.cache_clear()
    return notice, bundle, DeepReviewService(client=NarrativeClient(), structure_loader=structure_loader, raw_response_store=_FixtureStore())


def exercise(engine, monkeypatch):
    notice, bundle, service = setup(engine, monkeypatch)
    with Session(engine) as session:
        with pytest.raises(DeepReviewServiceError, match='전송 미리보기') as error:
            service.create_review(session, notice, bundle, 'tester', uuid4())
        assert error.value.code == 'preview_required'
        pre = preview(service, session, notice, bundle, True)
        pid = UUID(pre['preview_id'])
        with pytest.raises(DeepReviewServiceError) as error:
            service.create_review(session, notice, bundle, 'tester', uuid4(), preview_id=pid, source_verification_enabled=False)
        assert error.value.code == 'preview_changed'
        request_id = uuid4()
        created = service.create_review(session, notice, bundle, 'tester', request_id, preview_id=pid)
        assert service.create_review(session, notice, bundle, 'tester', request_id, preview_id=pid) == created
        assert created['current_attempt']['provider'] == 'codex-exec'
        assert session.scalar(select(DeepReviewApproval)).claimed_name == 'tester'
        with pytest.raises(DeepReviewServiceError):
            service.create_attempt(session, UUID(created['id']), 'tester', uuid4(), preview_id=pid)
        claim = service.claim_next_job(session, 'luna-test')
        service.run_claim(session, claim)
        view = service.view(session, claim.deep_review_id)
        assert view['status'] == 'completed'
        report = ReportService().get_report(session, claim.deep_review_id)
        assert report['report']['quality_status'] == 'unmeasured_reference'
        assert len(service.client.calls) >= 4
        assert service.client.calls[-1]['synthesis_phase'] == 'global'
        from app.deep_review.services.evidence import EvidenceService
        from app.deep_review.schemas.document_bundles import DocumentStructure as StructureSchema
        evidence_service = EvidenceService()
        monkeypatch.setattr(evidence_service.document_service, 'get_structure', lambda session, sid: StructureSchema.model_validate(structure_loader(session, session.get(DocumentStructure, sid))))
        evidence = evidence_service.get(session, UUID(report['report']['claims'][0]['evidence_ids'][0]))
        assert evidence['quote'] == SOURCE
        if os.environ.get('BIDOPS_LUNA_FIXTURE'):
            Path(os.environ['BIDOPS_LUNA_FIXTURE']).write_text(json.dumps({'review': view, 'report': report, 'preview': pre, 'evidence': evidence}, ensure_ascii=False, default=str))
        second = preview(service, session, notice, bundle, False, claim.deep_review_id)
        attempt = service.create_attempt(session, claim.deep_review_id, 'tester', uuid4(), preview_id=UUID(second['preview_id']), source_verification_enabled=False)
        assert attempt['sequence'] == 2
        assert ReportService().get_report(session, claim.deep_review_id)['current_revision_id'] == report['current_revision_id']
        claim = service.claim_next_job(session, 'luna-test')
        service.clock = lambda: datetime.now(UTC) + timedelta(hours=3)
        assert service.claim_next_job(session, 'second-worker') is None
        assert service.view(session, claim.deep_review_id)['status'] == 'failed'
        assert len(service.client.calls) == 4


def test_luna_approval_worker_report(engine, monkeypatch):
    exercise(engine, monkeypatch)


@pytest.mark.requires_postgres
def test_luna_approval_worker_report_postgres(monkeypatch):
    with migrated_engine() as engine:
        exercise(engine, monkeypatch)
        with engine.begin() as connection:
            with pytest.raises(Exception):
                connection.execute(text('UPDATE deep_review_preview SET input_sha256 = input_sha256'))


def test_disabled_auto_start_has_no_side_effects(engine):
    from app.deep_review.services.auto_preparation import maybe_auto_start_deep_review
    with Session(engine) as session:
        result = maybe_auto_start_deep_review(session, 123)
        assert result.reason == 'manual_request_required'
        assert session.scalar(select(WorkJob)) is None


def test_rest_preview_approval_and_agent_contract(engine, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.db import get_db
    from app.deep_review.routers import deep_reviews as router
    notice, bundle, service = setup(engine, monkeypatch)
    monkeypatch.setattr(router, 'service', service)
    app = FastAPI(); app.include_router(router.router)
    def db():
        with Session(engine) as session: yield session
    app.dependency_overrides[get_db] = db
    http = TestClient(app)
    payload = {'bundle_id': str(bundle), 'source_verification_enabled': True}
    response = http.post(f'/api/notices/{notice}/deep-review-previews', json=payload)
    assert response.status_code == 200, response.text
    approved = response.json()
    request = {**payload, 'request_id': str(uuid4()), 'preview_id': approved['preview_id']}
    headers = {'X-BidOps-Actor-Name': 'tester'}
    response = http.post(f'/api/notices/{notice}/deep-reviews', json=request, headers=headers)
    assert response.status_code == 202, response.text
    assert response.json()['current_attempt']['reasoning_effort'] == 'xhigh'
    replay = http.post(f'/api/notices/{notice}/deep-reviews', json=request, headers=headers)
    assert replay.json() == response.json()
    assert http.post(f'/api/notices/{notice+1}/deep-review-previews', json=payload).status_code == 404
    assert http.post(f'/api/notices/{notice}/deep-reviews', json={**request,'preview_id':str(uuid4())},headers=headers).status_code == 409


@pytest.mark.parametrize('kind', ['schema', 'evidence', 'timeout', 'auth', 'late'])
def test_failed_output_never_publishes(engine, monkeypatch, kind):
    from dataclasses import replace
    from app.core.model_client import ModelInvocationError
    from app.deep_review.services.deep_reviews import StaleFenceError
    notice, bundle, service = setup(engine, monkeypatch)
    original = service.client.invoke
    originals = []
    def invoke(*args, **kwargs):
        if kind in {'timeout','auth'}:
            raise ModelInvocationError('model_timeout' if kind=='timeout' else 'authentication_failed', ())
        result = original(*args, **kwargs)
        if kind == 'late':
            service.clock = lambda: datetime.now(UTC)+timedelta(hours=3)
        elif kind == 'schema':
            result = replace(result, structured_output={'schema':'invalid'})
        else:
            result.structured_output['evidence'][0]['source_sha256'] = 'f'*64
        return result
    service.client.invoke = invoke
    with Session(engine) as session:
        pre = preview(service, session, notice, bundle, True)
        created = service.create_review(session, notice, bundle, 'tester', uuid4(), preview_id=UUID(pre['preview_id']))
        claim = service.claim_next_job(session,'luna-test')
        with pytest.raises(DeepReviewServiceError): service.run_claim(session,claim)
        assert session.scalar(select(ReportRevision)) is None
        if kind == 'late':
            assert service.claim_next_job(session,'recovery') is None
        assert service.view(session,UUID(created['id']))['status'] == 'failed'


@pytest.mark.requires_postgres
def test_upgrade_from_previous_head_and_permissions():
    from tests.postgres import temporary_database, run_alembic
    from sqlalchemy import create_engine, inspect
    with temporary_database(upgrade_to='0031_prespec_preliminary_assessment') as url:
        result = run_alembic(url, 'upgrade', 'head')
        assert result.returncode == 0, result.stderr
        engine = create_engine(url)
        with engine.connect() as connection:
            assert 'deep_review_preview' in inspect(connection).get_table_names(schema='bidops')
            assert len(inspect(connection).get_foreign_keys('deep_review_preview', schema='bidops')) == 4
        engine.dispose()


def test_operator_close_is_queued_only_and_audited(engine, monkeypatch):
    from app.deep_review.cli.close_deep_review import close_queued
    from app.core.models import AuditEvent
    notice,bundle,service = setup(engine,monkeypatch)
    with Session(engine) as session:
        pre=preview(service,session,notice,bundle,True)
        created=service.create_review(session,notice,bundle,'tester',uuid4(),preview_id=UUID(pre['preview_id']))
        rid=UUID(created['id'])
        assert close_queued(session,rid,'operator')['status']=='failed'
        assert session.scalar(select(AuditEvent).where(AuditEvent.action=='deep_review.operator_close')).claimed_name=='operator'
        with pytest.raises(DeepReviewServiceError): close_queued(session,rid,'operator')


@pytest.mark.requires_postgres
def test_concurrent_same_notice_requests_are_serialized(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with migrated_engine() as engine:
        notice,bundle,service=setup(engine,monkeypatch)
        with Session(engine) as session:
            a=preview(service,session,notice,bundle,True)
            b=preview(service,session,notice,bundle,True)
        barrier=Barrier(2)
        def submit(pid):
            with Session(engine) as session:
                barrier.wait()
                try:
                    return service.create_review(session,notice,bundle,'tester',uuid4(),preview_id=UUID(pid))['status']
                except DeepReviewServiceError as error:
                    return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(submit,[a['preview_id'],b['preview_id']]))
        assert sorted(outcomes)==['active_attempt_exists','queued']
        with Session(engine) as session:
            assert len(session.scalars(select(DeepReviewApproval)).all())==1


def test_frozen_input_is_used_and_live_structure_is_not_reread(engine,monkeypatch):
    notice,bundle,service=setup(engine,monkeypatch)
    with Session(engine) as session:
        pre=preview(service,session,notice,bundle,True)
        service.create_review(session,notice,bundle,'tester',uuid4(),preview_id=UUID(pre['preview_id']))
        def forbidden(*_args): raise AssertionError('live structures must not be reloaded')
        service.structure_loader=forbidden
        claim=service.claim_next_job(session,'luna-test')
        service.run_claim(session,claim)
        assert service.view(session,claim.deep_review_id)['status']=='completed'


def test_projection_reports_latest_status_in_one_batch(engine,monkeypatch):
    from app.deep_review.services.auto_preparation import auto_preparation_fields
    notice,bundle,service=setup(engine,monkeypatch)
    with Session(engine) as session:
        pre=preview(service,session,notice,bundle,True)
        created=service.create_review(session,notice,bundle,'tester',uuid4(),preview_id=UUID(pre['preview_id']))
        fields=auto_preparation_fields(session,[notice])
        assert str(fields[notice]['latest_deep_review_id'])==created['id']
        assert fields[notice]['latest_deep_review_status']=='queued'


def test_worker_rejects_mock_configuration_after_approval(engine, monkeypatch):
    notice, bundle, service = setup(engine, monkeypatch)
    with Session(engine) as session:
        pre = preview(service, session, notice, bundle, True)
        service.create_review(session, notice, bundle, 'tester', uuid4(), preview_id=UUID(pre['preview_id']))
        claim = service.claim_next_job(session, 'luna-test')
        service.settings = service.settings.model_copy(update={'analysis_provider': 'mock'})
        with pytest.raises(DeepReviewServiceError, match='Luna 실행 비활성'):
            service.run_claim(session, claim)
        assert service.view(session, claim.deep_review_id)['status'] == 'failed'
        assert not service.client.calls


def test_worker_through_luna_http_adapter(engine, monkeypatch):
    import hashlib
    import time
    import httpx
    from app.deep_review.services.luna_client import LunaClient
    notice, bundle, service = setup(engine, monkeypatch)
    fake = NarrativeClient()
    result = {}
    def transport(request):
        if request.method == 'POST':
            prompt = json.loads(request.content)['prompt']
            payload = json.loads(prompt)
            output = fake.invoke(payload['stage'], payload['input_slice'], {'stages': []})
            result.update(status='completed', raw_response=output.raw_response.decode(), cli_version='0.155.1',
                          input_sha256=hashlib.sha256(prompt.encode()).hexdigest(), latency_ms=1)
            return httpx.Response(202, json={'call_id': str(uuid4())})
        return httpx.Response(200, json=result if request.method == 'GET' else {})
    service = DeepReviewService(client=LunaClient('http://codex-runner:8091', lambda: None, time.monotonic()+30,
                                transport=httpx.MockTransport(transport)), structure_loader=structure_loader, raw_response_store=_FixtureStore())
    with Session(engine) as session:
        pre = preview(service, session, notice, bundle, True)
        service.create_review(session, notice, bundle, 'tester', uuid4(), preview_id=UUID(pre['preview_id']))
        claim = service.claim_next_job(session, 'luna-http-test')
        service.run_claim(session, claim)
        assert service.view(session, claim.deep_review_id)['status'] == 'completed'
        assert len(fake.calls) == 4


def exercise_optional_relation(engine, monkeypatch, *, strict=False):
    from copy import deepcopy
    from dataclasses import replace
    from app.deep_review.services.input_versions import _policy_hash_matches
    notice, bundle, service = setup(engine, monkeypatch, policy_name=f"analysis-policy-luna-{'v1' if strict else 'v2'}.json")
    original = service.client.invoke
    originals = []
    def invoke(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == 'requirements_and_evaluation':
            output = deepcopy(result.structured_output)
            output['claims'][0]['related_claim_ids'] = [output['evidence'][0]['evidence_id']]
            originals.append(output)
            return replace(result, structured_output=output, raw_response=json.dumps(output).encode())
        return result
    service.client.invoke = invoke
    with Session(engine) as session:
        assert all(_policy_hash_matches(p) for p in session.scalars(select(AnalysisPolicyVersion)).all())
        pre = preview(service, session, notice, bundle, True)
        created = service.create_review(session, notice, bundle, 'tester', uuid4(), preview_id=UUID(pre['preview_id']))
        job = service.claim_next_job(session, 'relation-test')
        if strict:
            with pytest.raises(DeepReviewServiceError, match='범위 검증'):
                service.run_claim(session, job)
            assert service.view(session, job.deep_review_id)['status'] == 'failed'
            return
        service.run_claim(session, job)
        report = ReportService().get_report(session, job.deep_review_id)
        assert service.view(session, job.deep_review_id)['status'] == 'completed'
        first = report['report']['claims'][0]
        assert first['related_claim_ids'] == []
        assert len(first['evidence_ids']) == 1
        checks = [c for c in report['validation']['checks'] if c['check_type'] == 'related_claim_out_of_scope_omitted']
        assert len(checks) == 1 and checks[0]['related_claim_ids'] == [first['claim_id']]
        assert checks[0]['status'] == 'warning'
        assert checks[0]['message'] in report['report']['analysis_limitations']
        assert report['report']['quality_status'] == 'unmeasured_reference'
        stage = session.scalar(select(DeepReviewStage).where(DeepReviewStage.attempt_id == job.attempt_id, DeepReviewStage.sequence == 1))
        assert stage.raw_response_content_object_id is not None
        diagnostic = stage.invocation_metadata[0]['related_claim_diagnostics'][0]
        assert diagnostic['claim_id'] == first['claim_id']
        assert len(diagnostic['removed_related_claim_ids']) == 1
        from app.deep_review.schemas.reports import ReportRevisionRequest
        revised = ReportService().create_revision(session, job.deep_review_id, 'tester', ReportRevisionRequest.model_validate({
            'request_id': str(uuid4()), 'base_revision_id': report['current_revision_id'],
            'report': report['report'], 'reason': '경고 보존 확인', 'factual_change_evidence_ids': [],
        }))
        assert [c for c in revised['validation']['checks'] if c['check_type'] == 'related_claim_out_of_scope_omitted'] == checks
        # Original response retains the offending evidence ID; projection alone changes.
        assert originals[0]['claims'][0]['related_claim_ids'] == [originals[0]['evidence'][0]['evidence_id']]
        assert diagnostic['removed_related_claim_ids'] == originals[0]['claims'][0]['related_claim_ids']
        if os.environ.get('BIDOPS_RELATION_FIXTURE'):
            Path(os.environ['BIDOPS_RELATION_FIXTURE']).write_text(json.dumps({'review': service.view(session, job.deep_review_id), 'report': report}, ensure_ascii=False))


@pytest.mark.parametrize('strict', [False, True])
def test_optional_relation_policy_worker_report(engine, monkeypatch, strict):
    exercise_optional_relation(engine, monkeypatch, strict=strict)


@pytest.mark.requires_postgres
def test_optional_relation_policy_worker_report_postgres(monkeypatch):
    with migrated_engine() as engine:
        exercise_optional_relation(engine, monkeypatch)


def exercise_validation_off(engine, monkeypatch, *, corruption=None):
    from copy import deepcopy
    from dataclasses import replace
    from app.deep_review.services.verification import enabled_for_attempt
    notice, bundle, service = setup(engine, monkeypatch, policy_name='analysis-policy-luna-v3.json')
    original = service.client.invoke
    def invoke(*args, **kwargs):
        result = original(*args, **kwargs)
        value = deepcopy(result.structured_output)
        if args[0] == 'requirements_and_evaluation':
            value['considered_claim_ids'] = [row['claim_id'] for row in value['claims']]
            value['coverage'] = []
            value['claims'][0]['body'] = '사업비는 123456789원이며 이 문장은 검증하지 않은 모델의 출력이다.'
            value['evidence'][0]['quote'] = '원문에 없는 모델 인용'
            if corruption == 'hash': value['evidence'][0]['source_sha256'] = 'f'*64
            if corruption == 'dangling': value['claims'][0]['evidence_ids'] = [str(uuid4())]
        return replace(result, structured_output=value, raw_response=json.dumps(value).encode())
    service.client.invoke = invoke
    with Session(engine) as session:
        pre = preview(service, session, notice, bundle, True)
        assert pre['input']['policy']['validation']['result_checks'] == 'disabled_reference_v1'
        service.create_review(session, notice, bundle, 'tester', uuid4(), preview_id=UUID(pre['preview_id']))
        job = service.claim_next_job(session, 'validation-off-test')
        assert enabled_for_attempt(session, job.attempt_id) is False
        if corruption:
            with pytest.raises(DeepReviewServiceError): service.run_claim(session, job)
            assert service.view(session, job.deep_review_id)['status'] == 'failed'
            return
        service.run_claim(session, job)
        result = ReportService().get_report(session, job.deep_review_id)
        assert service.view(session, job.deep_review_id)['status'] == 'completed'
        assert result['report']['claims'][0]['body'].startswith('사업비는 123456789원')
        checks = result['validation']['checks']
        assert any(c['check_type'] == 'result_validation_skipped' and c['status'] == 'warning' for c in checks)
        assert any('검증을 끈 참조 실행' in value for value in result['report']['analysis_limitations'])
        assert result['report']['quality_status'] == 'unmeasured_reference'
        if os.environ.get('BIDOPS_VALIDATION_OFF_FIXTURE'):
            Path(os.environ['BIDOPS_VALIDATION_OFF_FIXTURE']).write_text(json.dumps({'review':service.view(session, job.deep_review_id),'report':result,'preview':pre},ensure_ascii=False))


@pytest.mark.parametrize('corruption', [None, 'hash', 'dangling'])
def test_validation_off_keeps_storage_scope(engine, monkeypatch, corruption):
    exercise_validation_off(engine, monkeypatch, corruption=corruption)


@pytest.mark.requires_postgres
def test_validation_off_postgres(monkeypatch):
    with migrated_engine() as engine:
        exercise_validation_off(engine, monkeypatch)
