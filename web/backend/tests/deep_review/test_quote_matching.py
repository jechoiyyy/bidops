"""Formatting equivalence must not hide changed business conditions."""
import pytest
from app.deep_review.services.quote_matching import page_texts, source_quote
from app.deep_review.services.deep_review_validation import _fact_numeric_status


@pytest.mark.parametrize('quote,source', [
    ('유지관리 ▸ 84백만원', '유지관리▸ 84백만원'),
    ('제안사는 비용을 부담한다.', '제안사는\n비용을  부담한다.'),
    ("'27년 사업", '’27년 사업'),
    ('기간 27일', '기간 ２７일'),
])
def test_formatting_resolves_to_unchanged_source(quote, source):
    assert source_quote(quote, [source, source]) == source


@pytest.mark.parametrize('quote,source', [
    ('제안사가 부담한다', '제안사가 부담하지 않는다'),
    ('금액 85백만원', '금액 84백만원'),
    ('기간 10개월', '기간 1 0개월'),
    ('기간 10개월', '기간 １ ０개월'),
    ('최대 5명', '최소 5명'),
    ('84만원', '84백만원'),
])
def test_meaning_change_is_not_resolved(quote, source):
    assert source_quote(quote, [source]) is None


def test_quote_cannot_join_separate_source_blocks():
    assert source_quote('개발하고 납품한다', ['개발하고', '납품한다']) is None


def test_page_locator_allows_contiguous_blocks_but_not_omission():
    from app.deep_review.services.deep_review_validation import _resolve_document_locator
    from app.deep_review.services.evidence import _resolve_locator_against_page, EvidenceServiceError
    blocks = [{'block_key': str(i), 'page': 1, 'text': text} for i, text in enumerate(['개발한다.', '외부 반출은 금지한다.', '검수 후 납품한다.'])]
    full = '개발한다. 외부 반출은 금지한다. 검수 후 납품한다.'
    canonical = source_quote(full, page_texts(blocks))
    assert canonical == '개발한다.\n외부 반출은 금지한다.\n검수 후 납품한다.'
    structure = {'pages': [{'number': 1}], 'page': 1, 'blocks': blocks}
    evidence = {'evidence_id': 'fixture', 'locator_type': 'page', 'locator': {'page': 1}, 'quote': canonical}
    issues = []; _resolve_document_locator(evidence, structure, path='$', issues=issues, allow_page_span=True)
    assert issues == []
    _resolve_locator_against_page('page', {'page': 1}, canonical, structure)
    assert source_quote('개발한다. 검수 후 납품한다.', page_texts(blocks)) is None
    for changed in ({**evidence, 'quote': '개발한다.\n검수 후 납품한다.'}, {**evidence, 'locator': {'page': 2}}):
        issues = []; _resolve_document_locator(changed, structure, path='$', issues=issues, allow_page_span=True)
        assert issues
    with pytest.raises(EvidenceServiceError):
        _resolve_locator_against_page('page', {'page': 1}, '개발한다.\n검수 후 납품한다.', structure)


@pytest.mark.parametrize('body,quote,expected', [
    ('사업비는 84,000,000원이다.', '84백만원', (True, False)),
    ('사업비는 0.84억원이다.', '84백만원', (True, False)),
    ('사업비는 84만원이다.', '84백만원', (False, False)),
    ('사업비는 85,000,000원이다.', '84백만원', (False, False)),
    ('2027년 1월 착수한다.', '사업 착수(’27. 1월)', (True, True)),
    ('2028년 1월 착수한다.', '사업 착수(’27. 1월)', (False, False)),
    ('사업비는 2027원이다.', '’27년 사업', (False, False)),
])
def test_numeric_equivalence_and_year_warning(body, quote, expected):
    assert _fact_numeric_status(body, [quote]) == expected
