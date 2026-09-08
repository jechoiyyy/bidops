"""Page binding, legacy isolation, immutable import and safe API/PDF regression."""
from copy import deepcopy
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.db import Base, get_db
from app.core.object_store import FilesystemObjectStore, ObjectStoreError
from app.deep_review.models import ContentObject, DocumentVersion, PreSpecPageOverview, PreSpecOverviewReview
from app.lifecycle.models import Notice
from app.deep_review.services.page_overview import canonical, digest, import_page_overview, list_page_overviews, get_page_pdf, PageOverviewError
from app.deep_review.services.page_overview_validation import validate_page_overview
from app.deep_review.routers import deep_reviews


class Scanner:
    version = 'test-v1'
    def scan(self, data):
        return True


def payload():
    fact = {'text': 'RCMS 사업은 6개월 수행한다. (PDF 3페이지)', 'evidence_pages': [3]}
    return {'schema_version': 'bidops.prespec-overview-page-review.v3', 'business_overview': [fact], 'main_tasks': [deepcopy(fact)],
            'budget_and_period': [], 'important_conditions': [], 'reviewer_analysis': ['회사 역량 확인 필요'], 'unknowns': [], 'input_limitations': ['PDF 일부 검토']}


def seed(session):
    notice = Notice(notice_key=f'pre:{uuid4()}', source_type='pre_spec', title='Test')
    session.add(notice)
    source = ContentObject(sha256='a'*64, size_bytes=10, detected_mime='application/pdf', retention_class='document-source')
    session.add(source); session.flush()
    document = DocumentVersion(notice_id=notice.id, content_object_id=source.id, version=1, source_kind='manual',
                               original_filename='test.pdf', role='제안요청서', is_current=True, safety_status='safe', needs_human_review=False)
    session.add(document); session.flush()
    pdf = b'%PDF-1.4 test'
    record = {'notice_id': notice.id, 'document_version_id': str(document.id), 'source_sha256': source.sha256,
              'pdf_sha256': digest(pdf), 'pdf_pages': 3, 'selected_pages': [3],
              'model_input': {'blocks': [{'pdf_page': 3, 'text': 'RCMS 사업은 6개월 수행한다.'}]}}
    manifest = {'schema_version': 'bidops.prespec-overview-page-run.v1', 'run_id': str(uuid4()), 'quality_status': 'unmeasured_reference',
                'model': 'test-model', 'model_digest': 'b'*64, 'policy_digest': 'c'*64, 'prompt_version': 'test-v4',
                'inputs': [{'notice_id': notice.id, 'source_sha256': source.sha256, 'pdf_sha256': digest(pdf), 'prompt_sha256': 'd'*64}]}
    outcome = {'notice_id': notice.id, 'prompt_sha256': 'd'*64, 'status': 'validation_failed',
               'validation_errors': ['fact_number_not_on_cited_pages', 'latin_term_not_on_cited_pages']}
    return dict(record=record, manifest=manifest, outcome=outcome, output=payload(), pdf=pdf, pdf_pages=['cover', 'toc', 'RCMS 사업은 6개월 수행한다.'])


@pytest.fixture
def context(tmp_path):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        data = seed(session)
        yield session, data, FilesystemObjectStore(tmp_path)
    engine.dispose()


def test_citation_metadata_does_not_weaken_fact_checks():
    original = payload(); before = deepcopy(original)
    assert validate_page_overview(original, {3: 'RCMS 사업은 6개월 수행한다.'}) == []
    assert original == before
    original['main_tasks'][0]['text'] = 'RCMS 99개월 수행 (PDF 3페이지)'
    assert 'fact_number_not_on_cited_pages' in validate_page_overview(original, {3: 'RCMS 6개월'})
    original['main_tasks'][0]['text'] = 'RCMS 6개월 수행 (PDF 4페이지)'
    assert 'pdf_inline_locator_mismatch' in validate_page_overview(original, {3: 'RCMS 6개월'})
    original['main_tasks'][0]['evidence_pages'] = [True]
    assert validate_page_overview(original, {3: 'RCMS 6개월'}) == ['schema_invalid']


def test_import_preserves_failure_and_does_not_create_recommendation(context):
    session, data, store = context
    original = deepcopy(data['output'])
    row, created = import_page_overview(session, **data, store=store, scanner=Scanner(), actor='tester')
    session.commit()
    assert created and row.validation_status == 'failed' and row.evidence_check_status == 'passed'
    assert row.payload_jsonb == original and row.payload_sha256 == digest(canonical(original))
    assert session.scalar(select(func.count()).select_from(PreSpecOverviewReview)) == 0
    same, created = import_page_overview(session, **data, store=store, scanner=Scanner(), actor='tester')
    assert same.id == row.id and not created
    data['output']['unknowns'] = ['different']
    with pytest.raises(PageOverviewError, match='idempotency_conflict'):
        import_page_overview(session, **data, store=store, scanner=Scanner(), actor='tester')
    view = list_page_overviews(session, row.notice_id).model_dump(mode='json')
    assert 'object_key' not in str(view) and 'recommendation' not in str(view)
    assert get_page_pdf(session, row.notice_id, row.id, store) == data['pdf']
    row.model_name = 'changed'
    with pytest.raises(ValueError, match='append-only'):
        session.flush()


@pytest.mark.parametrize('change,code', [
    (lambda d: d['record'].update(source_sha256='e'*64), 'source_hash_mismatch'),
    (lambda d: d.update(pdf=b'%PDF-other'), 'pdf_hash_mismatch'),
    (lambda d: d.update(pdf_pages=['cover','toc','different']), 'pdf_text_mismatch'),
    (lambda d: d['record'].update(selected_pages=[1]), 'input_pages_invalid'),
    (lambda d: d['manifest'].update(quality_status='measured'), 'quality_invalid'),
])
def test_rejects_wrong_lineage(context, change, code):
    session, data, store = context; change(data)
    with pytest.raises(PageOverviewError, match=code):
        import_page_overview(session, **data, store=store, scanner=Scanner(), actor='tester')
    assert session.scalar(select(func.count()).select_from(PreSpecPageOverview)) == 0


def test_pdf_scan_scope_and_pinned_version(context, monkeypatch):
    session, data, store = context
    scanner = Scanner(); monkeypatch.setattr(scanner, 'scan', lambda _: False)
    with pytest.raises(PageOverviewError, match='unsafe_pdf'):
        import_page_overview(session, **data, store=store, scanner=scanner, actor='tester')
    row, _ = import_page_overview(session, **data, store=store, scanner=Scanner(), actor='tester')
    session.commit()
    other = Notice(notice_key='pre:other', source_type='pre_spec'); session.add(other); session.commit()
    with pytest.raises(PageOverviewError, match='not_found'):
        get_page_pdf(session, other.id, row.id, store)
    app = FastAPI(); app.include_router(deep_reviews.pre_spec_overview_router)
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(deep_reviews, 'object_store', lambda **_: store)
    client = TestClient(app)
    response = client.get(f'/api/pre-specs/{row.notice_id}/overview-pages')
    assert response.status_code == 200 and response.json()['reviews'][0]['validation_status'] == 'failed'
    response = client.get(f'/api/pre-specs/{row.notice_id}/overview-pages/{row.id}/pdf')
    assert response.status_code == 200 and response.content == data['pdf']
    assert response.headers['content-type'] == 'application/pdf'
    def unavailable(*args, **kwargs):
        assert kwargs['version_id'] is not None
        raise ObjectStoreError('secret/path/token')
    monkeypatch.setattr(store, 'get', unavailable)
    response = client.get(f'/api/pre-specs/{row.notice_id}/overview-pages/{row.id}/pdf')
    assert response.status_code == 503 and 'secret' not in response.text


def test_multi_page_citations_and_no_content_or_false_budget():
    output = payload()
    output['main_tasks'] = [{'text': 'RCMS 6개월 (PDF 3페이지 · PDF 4페이지)', 'evidence_pages': [3, 4]}]
    pages = {3: 'RCMS 6개월', 4: '과업 범위'}
    assert validate_page_overview(output, pages) == []
    output['main_tasks'][0]['text'] = '(PDF 3페이지 · PDF 4페이지)'
    assert 'fact_empty' in validate_page_overview(output, pages)
    output['main_tasks'][0]['text'] = '계약금액 153000원'
    pages[4] = '사업금액 153000원'
    assert 'budget_mislabelled_as_contract_amount' in validate_page_overview(output, pages)


def test_cli_rejects_symlinks_and_limits_read_size(tmp_path):
    from app.deep_review.cli.import_page_overview import read_file
    (tmp_path/'file').write_bytes(b'12345')
    (tmp_path/'link').symlink_to(tmp_path/'file')
    with pytest.raises(OSError):
        read_file(tmp_path, 'link')
    with pytest.raises(PageOverviewError, match='input_size_limit'):
        read_file(tmp_path, 'file', 3)
    with pytest.raises(PageOverviewError, match='invalid_path'):
        read_file(tmp_path, '../file')
