"""Narrative policy → bounded model fixture → DB → REST, on both DB dialects."""
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.app.test_deep_reviews import engine, _seed_review_context, _fixture_structure, _FixtureStore
from tests.postgres import migrated_engine
from app.core.config import get_settings
from app.core.db import get_db
from app.core.model_client import InvocationResult, build_prompt
from app.deep_review.models import ContentObject, ContentScan, DocumentBundleItem, DocumentStructure, DocumentBlock, DeepReview, ReportRevision, DeepReviewStage
from app.deep_review.services.deep_reviews import DeepReviewService, _policy_payload
from app.deep_review.services.input_versions import CANONICAL_POLICY_FILE, import_policy_version, _policy_hash_matches
from app.deep_review.services.narrative_inputs import select_profile, pack_verified, validate_slice_output, build_slices
from app.deep_review.services.reports import ReportService, ReportServiceError
from app.deep_review.services.deep_review_validation import validate_deep_review_report, DeepReviewValidationError
from app.deep_review.routers.reports import router
from app.deep_review.schemas.reports import ReportRevisionRequest

SOURCE = "제안사는 기관 내부망에서 검색 서비스를 구축하고 시험 결과와 운영 매뉴얼을 제출해야 한다. 실제 운영 자료의 외부 반출은 허용되지 않는다. 검수 방법은 착수 시 협의한다. 평가에는 수행 방법과 운영 지원 방안이 포함된다."


def structure_loader(session, structure):
    value = _fixture_structure(session, structure)
    value['blocks'] = [{"block_key": "source-1", "parent_block_key": None, "type": "paragraph", "page": 1, "bbox": None, "text": SOURCE, "confidence": None, "attributes": {}}]
    return value


class NarrativeClient:
    def __init__(self):
        self.calls = []
        self.outputs = []

    def invoke(self, stage, input_slice, policy, **kwargs):
        assert len(build_prompt(stage, input_slice, policy, profile=kwargs.get('profile'))) <= 24000
        self.calls.append(deepcopy(input_slice))
        prior = input_slice.get('verified_claims', [])
        prior_ids = [row['claim_id'] for row in prior]
        refs = [row['evidence_id'] for row in input_slice.get('prior_evidence', [])]
        units = input_slice.get('requirements', [])
        unit_ids = [row['requirement_id'] for row in units]
        claims, evidence = [], []
        def claim(section, role, body, *, kind='opinion', key=False, title='내부망에서의 검수 준비'):
            row = {'claim_id': str(uuid4()), 'category': title, 'claim_type': kind, 'body': body,
                   'status': 'unknown' if kind == 'unknown' else 'supported', 'formula': None,
                   'premise_claim_ids': prior_ids if kind == 'inference' else [], 'reason': None if kind == 'fact' else '내부망 환경과 검수 협의 범위에 따라 준비 내용이 달라집니다.',
                   'evidence_ids': refs, 'report_section': section, 'narrative_role': role,
                   'topic_key': 'internal-acceptance', 'source_unit_ids': unit_ids, 'requirement_ids': [],
                   'related_claim_ids': prior_ids, 'is_key_point': key}
            claims.append(row)
        if stage == 'requirements_and_evaluation':
            unit = units[0]; eid = str(uuid4()); refs = [eid]
            evidence = [{'evidence_id': eid, 'source_kind': 'document', 'document_version_id': unit['document_version_id'], 'structure_id': unit['structure_id'], 'profile_version_id': None, 'profile_evidence_id': None, 'locator_type': 'paragraph', 'locator': {'page': 1, 'block_key': 'source-1', 'paragraph_key': None, 'text_start': 0, 'text_end': len(SOURCE)}, 'quote': SOURCE, 'confidence': None, 'source_sha256': unit['source_sha256']}]
            claim('scope', 'source', SOURCE, kind='fact', title='과업과 운영 자료의 사용 범위')
            claim('evaluation', 'source', '평가에는 수행 방법과 운영 지원 방안이 포함된다.', kind='fact', title='평가에서 설명해야 하는 내용')
        elif stage == 'delivery_risk_economics':
            claim('company_fit', 'company_basis', '이 입력에는 내부망 검수에 활용할 회사 실적 자료가 없다. 역량 미달로 판단할 수 없으며 승인된 실적 근거를 추가 확인해야 한다.', kind='unknown', title='회사 실적 대조의 한계')
            claim('delivery', 'impact', '운영 자료를 외부로 반출할 수 없으므로 외부 개발 환경에서 검수를 마무리한다고 가정하기 어렵다. 내부망 접근 일정과 반입 가능한 시험 자료를 확보해야 일정의 전제를 세울 수 있다.', kind='inference', key=True)
            claim('delivery', 'impact', '검수 방법은 착수 시 협의하므로 검수 대상과 통과 기준이 아직 확정되었다고 볼 수 없다. 기준이 늦게 정해지면 시험 계획과 재작업 범위가 달라질 수 있다.', kind='inference', title='검수 협의와 재작업의 관계')
            claim('contract_economics', 'impact', '추가 시험과 현장 지원이 얼마나 필요한지 확인되지 않아 현재 자료만으로 이익률을 계산할 수 없다. 현장 투입과 지원 기간을 비용 가정에 명시해야 한다.', kind='inference', title='비용 판단에 필요한 가정')
            claim('actions', 'action', '기술 담당자는 내부망 접근 절차와 시험용 자료 제공 가능 여부를 확인하고, 사업 담당자는 검수 기준의 확정 시점을 확인한다. 확인 전에는 수행 일정을 확정하지 않는다.')
            claim('decision_conditions', 'decision_condition', '내부망 시험 환경과 검수 기준을 제안 준비 전에 확인할 수 있다면 수행 계획을 구체화한다. 확인이 늦어지면 일정과 비용 가정을 다시 검토한다.')
        else:
            if input_slice['synthesis_phase'] == 'global':
                claim('assessment', 'recommendation', '조건부 추진 검토', key=True, title='system_recommendation')
            else:
                claim('assessment', 'synthesis', '요구 과업은 확인되지만 내부망 시험 환경과 검수 기준을 아직 확정할 수 없다. 회사 실적과 자료 제공 조건을 확인한 뒤 일정 및 비용 가정을 갱신하는 순서가 필요하다.', key=True, title='먼저 확인할 판단 조건')
        result = {'schema': 'bidops.deep-review-stage.v2', 'deep_review_id': input_slice['deep_review_id'], 'attempt_id': input_slice['attempt_id'], 'stage': stage, 'claims': claims, 'evidence': evidence, 'unknowns': ['회사 실적과 현장 지원 비용은 추가 확인이 필요합니다.'], 'warnings': [], 'coverage': [{'source_unit_id': uid, 'status': 'reviewed', 'claim_ids': [row['claim_id'] for row in claims], 'reason': None} for uid in unit_ids], 'considered_claim_ids': prior_ids if stage == 'synthesis_and_validation' else []}
        self.outputs.append(deepcopy(result))
        return InvocationResult(result, json.dumps(result).encode(), 'a'*64, 'b'*64, 1, 1, 1, ({'retry_index': 0, 'status': 'succeeded'},))


def exercise(engine, monkeypatch, *, export=False, page_span=False, source_verification_enabled=True):
    notice, bundle, _, _ = _seed_review_context(engine, monkeypatch, measured=False)
    with Session(engine) as session:
        policy = import_policy_version(session, CANONICAL_POLICY_FILE.with_name('analysis-policy-narrative-v2.json'), label='analysis-policy-narrative-v2')
        assert _policy_hash_matches(policy)
        assert _policy_payload(policy)['prompt_output_contract']['schema'] == 'bidops.deep-review-stage.v2'
        structure = session.scalar(select(DocumentStructure))
        content = session.get(ContentObject, structure.payload_content_object_id)
        payload_content = ContentObject(sha256=structure.payload_sha256, size_bytes=1, detected_mime='application/json', retention_class='fixture')
        session.add(payload_content); session.flush()
        structure.payload_content_object_id = payload_content.id
        item = session.scalar(select(DocumentBundleItem)); item.detected_mime = content.detected_mime
        session.add(ContentScan(content_object_id=content.id, scanner='fixture', scanner_version='1', status='clean', safe_result={}))
        for index, text in enumerate(SOURCE.split(' ', 1) if page_span else [SOURCE]):
            session.add(DocumentBlock(structure_id=structure.id, block_key=f'source-{index+1}', page=1, block_type='paragraph', content=text, attributes={}))
        session.commit()
        monkeypatch.setenv('BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID', str(policy.id))
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "true")
    get_settings.cache_clear()
    client = NarrativeClient()
    service = DeepReviewService(client=client, structure_loader=structure_loader, raw_response_store=_FixtureStore())
    from app.deep_review.routers import deep_reviews as review_router
    monkeypatch.setattr(review_router, 'service', service)
    app = FastAPI(); app.include_router(router); app.include_router(review_router.router)
    def db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = db
    http = TestClient(app)
    response = http.post(f'/api/notices/{notice}/deep-reviews', json={'request_id': str(uuid4()), 'bundle_id': str(bundle), 'source_verification_enabled': source_verification_enabled}, headers={'X-BidOps-Actor-Name': 'reviewer'})
    assert response.status_code == 202, response.text
    created = response.json()
    assert created['current_attempt']['source_verification_enabled'] is source_verification_enabled
    with Session(engine) as session:
        job = service.claim_next_job(session, 'narrative-test')
        service.run_claim(session, job)
        review = service.view(session, UUID(created['id']))
        assert review['status'] == 'completed'
        result = ReportService().get_report(session, UUID(created['id']))
        report = result['report']
        assert len(report['sections']) == 8
        assert report['schema'] == 'bidops.deep-review-report.v2'
        assert report['quality_status'] == 'unmeasured_reference'
        assert [row['body'] for row in report['claims']] == [row['body'] for output in client.outputs for row in output['claims']]
        assert len([row for row in report['sections'] if row['section_key']=='delivery'][0]['blocks']) == 2
        assert report['validation_summary']['warnings'] == sum(row['status']=='warning' for row in result['validation']['checks'])
        assert client.calls[-1]['synthesis_phase'] == 'global'
        assert not any(row['narrative_role']=='recommendation' for output in client.outputs[:-1] for row in output['claims'])
        count = len(client.calls)
        assert count >= 4
        broken = deepcopy(report); broken['sections'][3]['blocks'].pop()
        with pytest.raises(DeepReviewValidationError):
            validate_deep_review_report(broken)
    from app.deep_review.routers import reports as reports_router
    from app.deep_review.schemas.document_bundles import DocumentStructure as StructureSchema
    # Object storage boundary is synthetic; REST scope, hash, scan and quote checks are real.
    monkeypatch.setattr(reports_router.evidence_service.document_service, 'get_structure', lambda session, sid: StructureSchema.model_validate(structure_loader(session, session.get(DocumentStructure, sid))))
    http = TestClient(app)
    response = http.get(f"/api/deep-reviews/{created['id']}/report")
    assert response.status_code == 200, response.text
    assert response.json()['report']['claims'] == report['claims']
    eid = report['claims'][0]['evidence_ids'][0]
    source = http.get(f'/api/evidence/{eid}')
    assert source.status_code == 200, source.text
    assert source.json()['source_verification_enabled'] is source_verification_enabled
    if export and os.environ.get('BIDOPS_NARRATIVE_FIXTURE'):
        Path(os.environ['BIDOPS_NARRATIVE_FIXTURE']).write_text(json.dumps({'report': response.json(), 'review': review, 'evidence': source.json()}, ensure_ascii=False, indent=2))
    revised = deepcopy(response.json()['report'])
    revised['sections'][3]['blocks'][1]['body'] += ' 담당자가 계약 조건을 추가 확인했다.'
    changed_id = revised['sections'][3]['blocks'][1]['claim_ids'][0]
    next(row for row in revised['claims'] if row['claim_id']==changed_id)['body'] = revised['sections'][3]['blocks'][1]['body']
    request = ReportRevisionRequest.model_validate({'request_id': str(uuid4()), 'base_revision_id': result['current_revision_id'], 'report': revised, 'reason': '검수 조건 확인', 'factual_change_evidence_ids': [eid]})
    response = http.post(f"/api/deep-reviews/{created['id']}/report-revisions", json=request.model_dump(mode='json'), headers={'X-BidOps-Actor-Name': 'reviewer'})
    assert response.status_code == 201, response.text
    newer = response.json()
    with Session(engine) as session:
        assert len(newer['history']) == 2
        row = session.get(DeepReview, UUID(created['id'])); row.status = 'failed'; session.commit()
        assert ReportService().get_report(session, row.id)['current_revision_id'] == newer['current_revision_id']
        assert len(session.scalars(select(ReportRevision)).all()) == 2
    return result


def test_narrative_worker_storage_rest_and_revisions(engine, monkeypatch):
    exercise(engine, monkeypatch, export=True)


def test_year_notation_is_visible_without_blocking_report(engine, monkeypatch):
    import sys
    from dataclasses import replace
    monkeypatch.setattr(sys.modules[__name__], 'SOURCE', SOURCE + ' 사업은 ’27년에 시작한다.')
    original = NarrativeClient.invoke
    def year_claim(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if args[0] == 'requirements_and_evaluation':
            result.structured_output['claims'][0]['body'] = '이 사업은 2027년에 시작하며 원문에 정해진 과업을 수행한다.'
            self.outputs[-1] = deepcopy(result.structured_output)
            result = replace(result, raw_response=json.dumps(result.structured_output).encode())
        return result
    monkeypatch.setattr(NarrativeClient, 'invoke', year_claim)
    result = exercise(engine, monkeypatch)
    assert result['validation']['status'] == 'passed'
    assert any(row['check_type'] == 'year_notation' and row['status'] == 'warning' for row in result['validation']['checks'])
    assert any('축약된 연도' in text for text in result['report']['analysis_limitations'])


def test_contiguous_page_quote_worker_storage_and_evidence_api(engine, monkeypatch):
    import sys
    from dataclasses import replace
    old_loader = structure_loader
    def split_loader(session, structure):
        value = old_loader(session, structure)
        parts = SOURCE.split(' ', 1)
        value['blocks'] = [{**value['blocks'][0], 'block_key': f'source-{i+1}', 'text': part} for i, part in enumerate(parts)]
        return value
    monkeypatch.setattr(sys.modules[__name__], 'structure_loader', split_loader)
    monkeypatch.setattr('app.deep_review.services.input_versions._structure_payload', lambda session, item, structure: split_loader(session, structure))
    original = NarrativeClient.invoke
    def page_quote(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if args[0] == 'requirements_and_evaluation':
            ref = result.structured_output['evidence'][0]
            ref['locator_type'] = 'page'; ref['locator'] = {'page': 1}
            result = replace(result, raw_response=json.dumps(result.structured_output).encode())
        return result
    monkeypatch.setattr(NarrativeClient, 'invoke', page_quote)
    exercise(engine, monkeypatch, page_span=True)


@pytest.mark.parametrize('enabled,foreign_hash', [(True, False), (False, False), (False, True)])
def test_source_verification_selection_preserves_scope(engine, monkeypatch, enabled, foreign_hash):
    from dataclasses import replace
    from app.deep_review.services.deep_reviews import DeepReviewServiceError
    original = NarrativeClient.invoke
    def mismatch(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if args[0] == 'requirements_and_evaluation':
            ref = result.structured_output['evidence'][0]
            ref.update(locator_type='page', locator={'page': 1}, quote='모델이 잘못 인용한 금액 999원')
            if foreign_hash:
                ref['source_sha256'] = 'f' * 64
            result.structured_output['claims'][0]['body'] = '사업비는 원문에 없는 금액인 123원이다.'
            self.outputs[-1] = deepcopy(result.structured_output)
            result = replace(result, raw_response=json.dumps(result.structured_output).encode())
        return result
    monkeypatch.setattr(NarrativeClient, 'invoke', mismatch)
    if enabled or foreign_hash:
        with pytest.raises(DeepReviewServiceError):
            exercise(engine, monkeypatch, source_verification_enabled=enabled)
        with Session(engine) as session:
            assert session.scalar(select(ReportRevision)) is None
        return
    result = exercise(engine, monkeypatch, source_verification_enabled=False)
    assert any(c['check_type'] == 'source_verification_skipped' for c in result['validation']['checks'])
    assert any('대조를 끈 실행' in text for text in result['report']['analysis_limitations'])
    # A later enabled run cannot rewrite the old report's selection or evidence.
    from app.deep_review.routers import deep_reviews as review_router
    from app.deep_review.services.verification import enabled_for_attempt, enabled_for_evidence
    from app.deep_review.services.deep_reviews import DeepReviewServiceError
    rid = UUID(result['deep_review_id']); request_id = uuid4()
    with Session(engine) as session:
        previous = ReportService().get_report(session, rid)
        new = review_router.service.create_attempt(session, rid, 'reviewer', request_id, source_verification_enabled=True)
        assert new['source_verification_enabled'] is True
        assert enabled_for_attempt(session, UUID(new['id'])) is True
        assert not enabled_for_evidence(session, UUID(result['report']['claims'][0]['evidence_ids'][0]))
        assert ReportService().get_report(session, rid) == previous
        with pytest.raises(DeepReviewServiceError) as error:
            review_router.service.create_attempt(session, rid, 'reviewer', request_id, source_verification_enabled=False)
        assert error.value.code == 'idempotency_conflict'


def test_retry_http_selects_off_without_changing_previous_report(engine, monkeypatch):
    result = exercise(engine, monkeypatch)
    from app.deep_review.routers import deep_reviews as review_router
    app = FastAPI(); app.include_router(review_router.router)
    def db():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = db
    http = TestClient(app); request_id = str(uuid4()); rid = result['deep_review_id']
    payload = {'request_id': request_id, 'source_verification_enabled': False}
    response = http.post(f'/api/deep-reviews/{rid}/attempts', json=payload, headers={'X-BidOps-Actor-Name': 'reviewer'})
    assert response.status_code == 202, response.text
    assert response.json()['source_verification_enabled'] is False
    assert http.get(f'/api/deep-reviews/{rid}').json()['current_attempt']['source_verification_enabled'] is False
    with Session(engine) as session:
        old = ReportService().get_report(session, UUID(rid))
        assert all(check['check_type'] != 'source_verification_skipped' for check in old['validation']['checks'])
    payload['source_verification_enabled'] = True
    assert http.post(f'/api/deep-reviews/{rid}/attempts', json=payload, headers={'X-BidOps-Actor-Name': 'reviewer'}).status_code == 409


def test_large_unit_analysis_is_split_without_losing_prior_claims():
    from app.deep_review.services.narrative_inputs import bind_local_ids
    units = [{'requirement_id': 'u', 'text': SOURCE}]
    claims = [{'claim_id': str(uuid4()), 'body': '검토 내용' * 35, 'source_unit_ids': ['u'], 'evidence_ids': []} for _ in range(5)]
    policy = {'chunking': {'profile_characters': 100, 'prior_characters': 600}}
    parts = build_slices('delivery_risk_economics', units, {}, [{'claims': claims, 'evidence': []}], policy)
    assert len(parts) > 1
    assert [c['claim_id'] for p in parts for c in p['verified_claims']] == [c['claim_id'] for c in claims]
    assert [p['slice_index'] for p in parts] == list(range(len(parts)))
    raw_id = str(uuid4())
    output = {'attempt_id': str(uuid4()), 'stage': 'delivery_risk_economics', 'claims': [{'claim_id': raw_id, 'body': '본문 보존', 'related_claim_ids': [], 'premise_claim_ids': [], 'evidence_ids': []}], 'evidence': [], 'coverage': [{'claim_ids': [raw_id]}]}
    bound = [bind_local_ids(output, part) for part in parts]
    assert len({p['claims'][0]['claim_id'] for p in bound}) == len(parts)
    assert all(p['claims'][0]['body'] == '본문 보존' and p['coverage'][0]['claim_ids'] == [p['claims'][0]['claim_id']] for p in bound)


def test_rejected_narrative_scope_keeps_safe_code_and_private_raw_response(engine, monkeypatch):
    from dataclasses import replace
    from app.deep_review.services.deep_reviews import DeepReviewServiceError
    original = NarrativeClient.invoke
    def incomplete(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        payload = deepcopy(result.structured_output)
        payload['coverage'] = []
        return replace(result, structured_output=payload, raw_response=json.dumps(payload).encode())
    monkeypatch.setattr(NarrativeClient, 'invoke', incomplete)
    with pytest.raises(DeepReviewServiceError):
        exercise(engine, monkeypatch)
    with Session(engine) as session:
        failed = session.scalar(select(DeepReviewStage).where(DeepReviewStage.status == 'failed'))
        assert failed.raw_response_content_object_id is not None
        assert 'narrative:source_coverage_mismatch' in [row.get('error_code') for row in failed.invocation_metadata]
        assert all('body' not in row and 'quote' not in row for row in failed.invocation_metadata)
        assert session.scalar(select(ReportRevision)) is None


@pytest.mark.requires_postgres
@pytest.mark.parametrize("year_notation", [False, True])
def test_narrative_postgres(monkeypatch, year_notation):
    with migrated_engine() as bind:
        if year_notation:
            test_year_notation_is_visible_without_blocking_report(bind, monkeypatch)
        else:
            exercise(bind, monkeypatch)


@pytest.mark.requires_postgres
def test_narrative_page_span_postgres(monkeypatch):
    with migrated_engine() as bind:
        test_contiguous_page_quote_worker_storage_and_evidence_api(bind, monkeypatch)


@pytest.mark.requires_postgres
def test_source_verification_postgres(monkeypatch):
    with migrated_engine() as bind:
        test_source_verification_selection_preserves_scope(bind, monkeypatch, False, False)


@pytest.mark.requires_postgres
def test_narrative_rejection_postgres(monkeypatch):
    with migrated_engine() as bind:
        test_rejected_narrative_scope_keeps_safe_code_and_private_raw_response(bind, monkeypatch)


@pytest.mark.requires_postgres
@pytest.mark.parametrize("tampered", [False, True])
def test_profile_source_repair_postgres(monkeypatch, tampered):
    from tests.app.test_deep_reviews import test_explicit_profile_source_repair_preserves_snapshot_and_old_location
    with migrated_engine() as bind:
        test_explicit_profile_source_repair_preserves_snapshot_and_old_location(bind, monkeypatch, tampered)


def test_shared_evidence_repeated_per_pack_and_profile_relevance():
    evidence = [{'evidence_id': 'shared', 'quote': '내부망 검수 근거'*15}]
    rows = [{'claim_id': str(index), 'evidence_ids': ['shared'], 'body': '내용'*100} for index in range(5)]
    packs = pack_verified(rows, evidence, budget=700)
    assert len(packs)>1
    assert all(row['prior_evidence'] == evidence for row in packs)
    profile = {'facts': [{'fact_key':'unrelated','value':'회계 처리'}, {'fact_key':'relevant','value':'내부망 검수 시험'}], 'evidence': [{'fact_key':'relevant','profile_evidence_id':'e','quote':'내부망 검수 시험'}]}
    chosen = select_profile([{'text':'내부망 검수'}], profile, 1000)
    assert chosen['profile_selection']['selected_fact_keys'] == ['relevant']
    assert chosen['profile_selection']['unselected_fact_count'] == 1
    assert chosen['profile_selection']['absence_is_noncompliance'] is False
    with pytest.raises(ValueError, match='source_units_empty'):
        build_slices('delivery_risk_economics', [{'text':''}], profile, [], {})

@pytest.mark.parametrize('change,error', [
    ('missing_unit', 'source_coverage_mismatch'), ('missing_requirement', 'requirement_coverage_mismatch'),
    ('foreign_quote', 'document_evidence_out_of_slice'), ('foreign_profile', 'profile_evidence_out_of_slice'),
    ('coverage_without_content', 'coverage_without_analysis'),
])
def test_slice_validation_rejects_silent_omission_and_unsupplied_evidence(change, error):
    unit = {'requirement_id':'unit-1', 'document_requirement_ids':['SFR-001'], 'document_version_id':'doc', 'structure_id':'structure', 'text':SOURCE}
    payload = {'claims':[{'claim_id':'c', 'source_unit_ids':['unit-1'], 'requirement_ids':['SFR-001'], 'related_claim_ids':[], 'premise_claim_ids':[], 'evidence_ids':['e'], 'claim_type':'fact', 'body':SOURCE}], 'coverage':[{'source_unit_id':'unit-1','status':'reviewed','claim_ids':['c'],'reason':None}], 'considered_claim_ids':[], 'evidence':[{'evidence_id':'e','source_kind':'document','document_version_id':'doc','structure_id':'structure','quote':SOURCE}]}
    if change == 'missing_unit': payload['coverage'] = []
    if change == 'missing_requirement': payload['claims'][0]['requirement_ids'] = []
    if change == 'foreign_quote': payload['evidence'][0]['quote'] = '입력에 없는 회사 자격'
    if change == 'foreign_profile': payload['evidence'][0].update(source_kind='profile',profile_evidence_id='not-supplied')
    if change == 'coverage_without_content': payload['claims'][0]['body'] = 'SFR-001'
    with pytest.raises(ValueError, match=error):
        validate_slice_output(payload, {'requirements':[unit]}, 'requirements_and_evaluation')


@pytest.mark.parametrize('considered,related,error', [
    ([], ['prior'], None),
    (['prior'], ['prior'], None),
    (['not-supplied'], ['prior'], 'considered_claim_out_of_slice'),
    (['prior'], ['profile-source'], 'claim_relation_out_of_slice'),
])
def test_delivery_accepts_optional_prior_coverage_but_preserves_reference_types(considered, related, error):
    incoming = {
        'requirements':[{'requirement_id':'unit', 'document_requirement_ids':[]}],
        'verified_claims':[{'claim_id':'prior'}],
        'profile_evidence':[{'profile_evidence_id':'profile-source'}],
    }
    output = {
        'claims':[{'claim_id':'next', 'source_unit_ids':['unit'], 'requirement_ids':[],
                   'related_claim_ids':related, 'premise_claim_ids':[], 'evidence_ids':[],
                   'claim_type':'inference', 'body':'현장 지원 범위에 따라 투입 계획을 확인해야 합니다.'}],
        'coverage':[{'source_unit_id':'unit', 'status':'reviewed', 'claim_ids':['next'], 'reason':None}],
        'considered_claim_ids':considered, 'evidence':[],
    }
    if error:
        with pytest.raises(ValueError, match=error):
            validate_slice_output(output, incoming, 'delivery_risk_economics', source_verification_enabled=False)
    else:
        validate_slice_output(output, incoming, 'delivery_risk_economics', source_verification_enabled=False)
        assert output['considered_claim_ids'] == considered


def test_narrative_binding_cache_includes_contract(monkeypatch):
    from app.deep_review.services import deep_reviews as module
    class Bound:
        def close(self): pass
    calls=[]
    def bind(*args, **kwargs):
        calls.append(kwargs['output_contract'].name)
        return Bound()
    monkeypatch.setattr(module.ModelClient, 'for_purpose', bind)
    monkeypatch.setenv('BIDOPS_ANALYSIS_PROVIDER', 'vllm'); get_settings.cache_clear()
    service = DeepReviewService(raw_response_store=_FixtureStore())
    service._bind_client('qwen3.8-27B')
    service._bind_client('qwen3.8-27B', narrative=True)
    service._bind_client('qwen3.8-27B', narrative=True)
    assert calls == ['bidops_deep_review_stage_v1', 'bidops_deep_review_stage_v2']


def test_calculation_can_replay_evidence_supplied_from_a_prior_stage():
    from tests.deep_review.test_deep_review_contracts import evidence, stage, U3, U5
    from app.deep_review.services.deep_review_validation import validate_deep_review_stage
    row = {'claim_id': U3, 'category':'비용 계산', 'claim_type':'calculation', 'body':'2.5', 'status':'supported', 'formula':'100 * 2.5 / 100 = 2.5', 'premise_claim_ids':[], 'reason':None, 'evidence_ids':[U5], 'report_section':'contract_economics', 'narrative_role':'synthesis', 'topic_key':'cost', 'source_unit_ids':[], 'requirement_ids':[], 'related_claim_ids':[], 'is_key_point':False}
    payload = {**stage(claim=row), 'schema':'bidops.deep-review-stage.v2', 'coverage':[], 'considered_claim_ids':[]}
    with pytest.raises(DeepReviewValidationError):
        validate_deep_review_stage(payload, known_evidence_ids={U5})
    assert validate_deep_review_stage(payload, known_evidence_ids={U5}, known_evidence=[evidence()]) == payload


def test_synthesis_rejects_invented_source_identifiers():
    incoming = {'verified_claims':[{'claim_id':'prior','source_unit_ids':['unit'], 'requirement_ids':['SFR-001']}], 'synthesis_phase':'partial'}
    output = {'claims':[{'claim_id':'next','source_unit_ids':['invented'], 'requirement_ids':[], 'related_claim_ids':['prior'], 'premise_claim_ids':[], 'evidence_ids':[], 'narrative_role':'synthesis'}], 'considered_claim_ids':['prior'], 'coverage':[], 'evidence':[]}
    with pytest.raises(ValueError, match='synthesis_source_out_of_slice'):
        validate_slice_output(output, incoming, 'synthesis_and_validation')


def test_fact_number_missing_from_cited_quote_is_rejected():
    from tests.deep_review.test_deep_review_contracts import evidence, stage, bundle, structures, U3, U5
    from app.deep_review.services.deep_review_validation import validate_deep_review_stage
    row = {'claim_id':U3, 'category':'수량', 'claim_type':'fact', 'body':'총 999개를 요구한다.', 'status':'supported', 'formula':None, 'premise_claim_ids':[], 'reason':None, 'evidence_ids':[U5], 'report_section':'scope', 'narrative_role':'source', 'topic_key':'quantity', 'source_unit_ids':[], 'requirement_ids':[], 'related_claim_ids':[], 'is_key_point':False}
    payload = {**stage(claim=row, evidence=evidence()), 'schema':'bidops.deep-review-stage.v2', 'coverage':[], 'considered_claim_ids':[]}
    with pytest.raises(DeepReviewValidationError, match='fact_number_not_in_evidence'):
        validate_deep_review_stage(payload, bundle=bundle(), structures=structures())
    payload['claims'][0]['body'] = '원문 수치 100'
    assert validate_deep_review_stage(payload, bundle=bundle(), structures=structures()) == payload


@pytest.mark.parametrize('change,error', [
    ('related', None), ('premise', 'claim_relation_out_of_slice'),
    ('evidence', 'evidence_out_of_slice'), ('quote', 'document_evidence_out_of_slice'),
    ('coverage', 'source_coverage_mismatch'), ('synthesis', 'synthesis_claim_omission'),
])
def test_optional_relation_projection_preserves_required_guards(change, error):
    from app.deep_review.services.narrative_inputs import project_related_claims
    unit = {'requirement_id':'unit', 'document_requirement_ids':[], 'document_version_id':'doc', 'structure_id':'structure', 'text':SOURCE}
    incoming = {'requirements':[unit]}
    output = {'claims':[{'claim_id':'c', 'source_unit_ids':['unit'], 'requirement_ids':[], 'related_claim_ids':['e'], 'premise_claim_ids':[], 'evidence_ids':['e'], 'claim_type':'fact', 'body':SOURCE}], 'coverage':[{'source_unit_id':'unit','status':'reviewed','claim_ids':['c'],'reason':None}], 'considered_claim_ids':[], 'evidence':[{'evidence_id':'e','source_kind':'document','document_version_id':'doc','structure_id':'structure','quote':SOURCE}]}
    stage = 'requirements_and_evaluation'
    if change == 'premise': output['claims'][0]['premise_claim_ids'] = ['e']
    if change == 'evidence': output['claims'][0]['evidence_ids'] = ['missing']
    if change == 'quote': output['evidence'][0]['quote'] = '원문에 없는 내용'
    if change == 'coverage': output['coverage'] = []
    if change == 'synthesis':
        stage = 'synthesis_and_validation'
        incoming['verified_claims'] = [{'claim_id':'prior', 'source_unit_ids':['unit'], 'requirement_ids':[]}]
        output['considered_claim_ids'] = ['prior']; output['coverage'] = []
    before = deepcopy(output)
    projected, warnings = project_related_claims(output, incoming, {'validation':{'related_claim_policy':'omit_invalid_with_warning_v1'}})
    assert output == before
    assert warnings == [{'code':'related_claim_out_of_scope_omitted', 'claim_id':'c', 'removed_related_claim_ids':['e']}]
    if error:
        with pytest.raises(ValueError, match=error): validate_slice_output(projected, incoming, stage)
    else:
        validate_slice_output(projected, incoming, stage)
        assert projected['claims'][0]['evidence_ids'] == ['e']
