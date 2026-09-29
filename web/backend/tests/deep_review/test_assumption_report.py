from copy import deepcopy
import json
import pytest
from app.deep_review.services.assumption_report import project_output, prompts, source_units, AssumptionOutputError, SECTIONS
from app.deep_review.services.assumption_inputs import scenario


def sample():
    return {'bundle': {'documents': [{'structure_id_at_confirmation':'s', 'document_version_id':'d'}]},
            'structures': {'s': {'blocks': [{'text':'동일 원문 조건 90분', 'page':1, 'block_key':'a'}, {'text':'동일 원문 조건 90분', 'page':2, 'block_key':'b'}]}},
            'profile': {'evidence': [], 'facts': []}, 'scenario':scenario()}


def test_duplicate_text_preserves_all_locations_and_default_is_three_calls():
    data=sample()
    sources=source_units(data)
    doc=[s for s in sources if s['kind']=='document_fact']
    assert len(doc)==1 and [p['page'] for p in doc[0]['locations']]==[1,2]
    assert all(len(prompts(stage,data,[]))==1 for stage in ('business','company','decision'))


def test_split_preserves_every_source_and_never_silently_clips(monkeypatch):
    from app.deep_review.services import assumption_report as module
    data=sample()
    data['structures']['s']['blocks']=[{'text': str(i)+'문맥'*500,'page':i,'block_key':str(i)} for i in range(10)]
    monkeypatch.setattr(module,'MAX_PROMPT_CHARS',9000)
    parts=prompts('business',data,[])
    assert len(parts)>1
    assert [(s[0],s[2]) for p in parts for s in json.loads(p)['sources']]==[(s['id'],s['text']) for s in source_units(data) if s['kind']=='document_fact']
    data['structures']['s']['blocks'][0]['text']='너무 큰 문맥'*10000
    with pytest.raises(AssumptionOutputError,match='source_context_too_large'):
        prompts('business',data,[])


def test_invalid_links_warn_and_readable_body_is_preserved():
    paragraph={'kind':'company_fact','body':'유효한 근거가 없어 확인이 필요한 비용 99999원입니다.',
               'refs':[{'source_id':'missing','quote':'임의 문구'}, {'source_id':'a','quote':'다른 인용'}]}
    raw={'sections':[{'key':'company_fit','paragraphs':[paragraph]}]}
    original=deepcopy(raw)
    result=project_output(raw,[{'id':'a','kind':'assumption','text':'가정 값 300만원'}],final=True)
    p=result['sections'][0]['paragraphs'][0]
    assert p['body']==paragraph['body'] and raw==original
    assert set(p['warnings'])=={'unlinked','quote_mismatch','source_kind_mismatch','numbers_unverified'}
    assert result['complete'] is False


def test_titles_only_do_not_complete_and_unreadable_structure_fails():
    value={'sections':[{'key':key,'paragraphs':[{'kind':'unknown','body':'미확인','refs':[]}]} for key in SECTIONS]}
    assert not project_output(value,[],final=True)['complete']
    with pytest.raises(AssumptionOutputError,match='schema_invalid'):
        project_output({'sections':[]},[])
