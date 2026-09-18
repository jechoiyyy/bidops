"""이름 대조 사다리 이식 검사 (spec §4.1).

`experiments/lifecycle-linkage-survey/tests/test_name_normalize.py`의 정규화·사다리
사례를 그대로 옮겼다. 실험 스크립트와 동작이 같아야 한다.
"""

from __future__ import annotations

from app.lifecycle.services import name_matching as normalize


def test_character_classification_keeps_unknown_out_of_both_measured_sets() -> None:
    assert set(normalize.CONFIRMED_BREAKING_CHARS) == {"·", "&", "‘", "’", "•"}
    for harmless in "~/_『』・‧․":
        assert harmless in normalize.CONFIRMED_HARMLESS_CHARS
    assert normalize.UNKNOWN_CHARS == "∙"
    assert "∙" not in normalize.CONFIRMED_BREAKING_CHARS
    assert "∙" not in normalize.CONFIRMED_HARMLESS_CHARS


def test_middle_dot_codepoints_are_equivalent() -> None:
    values = [normalize.normalize(f"가{dot}나") for dot in normalize.DOT_CHARS]

    assert len(set(values)) == 1


def test_leading_tags_are_removed_without_removing_body_text() -> None:
    assert normalize.normalize("[재공고] (긴급) 2026년 재공고 사업") == "2026년 재공고 사업"
    assert normalize.normalize("[재공고]") == ""


def test_longest_fragment_is_a_literal_substring() -> None:
    name = "기관  \t사업(세부) 용역"

    fragment = normalize.longest_fragment(name)

    assert fragment is not None
    assert fragment in name
    assert fragment == "기관  \t사업"


def test_breaking_split_splits_all_confirmed_breakers_and_keeps_harmless_context() -> None:
    for breaking in normalize.CONFIRMED_BREAKING_CHARS:
        name = f"기관  사업(세부)~사업/『내용』{breaking}용역"

        fragment = normalize.breaking_split(name)

        assert fragment == "기관  사업(세부)~사업/『내용』"
        assert fragment in name
        assert "  " in fragment
        assert "(세부)" in fragment
        assert "~" in fragment
        assert "/" in fragment
        assert "『내용』" in fragment
        assert breaking not in fragment


def test_breaking_split_is_absent_without_a_confirmed_breaker() -> None:
    name = "기관 사업(세부) ~사업/『내용』・‧․∙ 용역"

    assert normalize.breaking_split(name) is None
    assert "breaking_split" not in [
        strategy for strategy, _query in normalize.search_variants(name)
    ]


def test_short_queries_are_omitted_and_duplicate_queries_are_removed() -> None:
    assert normalize.search_variants("가나다") == []

    variants = normalize.search_variants("abcdef")
    queries = [query for _strategy, query in variants]

    assert queries == ["abcdef"]
    assert len(queries) == len(set(queries))
    assert all(len(query) >= normalize.MIN_FRAGMENT_CHARS for query in queries)


def test_ladder_is_ordered_and_fragment_is_literal() -> None:
    name = "[재공고] 긴본문구간·아주긴연속부분 사업(세부) 용역"

    variants = normalize.search_variants(name)

    assert [strategy for strategy, _query in variants] == [
        "full",
        "breaking_split",
        "normalized",
        "longest_fragment",
        "prefix12",
    ]
    assert list(normalize.SEARCH_STRATEGIES) == [
        strategy for strategy, _query in variants
    ]
    breaking_fragment = dict(variants)["breaking_split"]
    assert breaking_fragment in name
    fragment = dict(variants)["longest_fragment"]
    assert fragment in name


def test_prefix12_uses_collapsed_source_not_normalized_source() -> None:
    name = "가나다라마바사·아자차카타파"
    variants = dict(normalize.search_variants(name))

    assert variants["prefix12"] == normalize.collapse(name)[: normalize.PREFIX_CHARS].strip()
    assert variants["prefix12"] != normalize.normalize(name)[: normalize.PREFIX_CHARS].strip()
