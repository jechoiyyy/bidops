"""Shared literal search contract, including SQLite SQL parity."""

import pytest
from sqlalchemy import create_engine, literal, select

from app.core.search import SEARCH_WHITESPACE, search_key, search_match, search_sql_match, validation_value
from tests.postgres import migrated_engine, requires_postgres


@pytest.mark.parametrize(("query", "target", "expected"), [
    ("사이버 수사", "사이버수사포털시스템 고도화", True),
    ("사이버 고도화", "사이버수사포털시스템 고도화", False),
    ("고도화 사이버", "사이버수사포털시스템 고도화", False),
    ("AB\u00a0\u200b C\ufeff", "aB\u200b c", True),
    ("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", True),
    ("ä", "Ä", False),
    ("i", "İ", False),
    ("A%_\\", "a%_\\", True),
    ("A%_\\", "aXYZ", False),
    ("사이버수사", "사이버", False),
])
def test_search_key_and_sql_literal_match(query, target, expected):
    assert search_match(query, target) is expected
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        assert connection.scalar(select(search_sql_match(literal(target), query))) is expected


def test_whitespace_set_and_validation_length():
    assert len(SEARCH_WHITESPACE) == 26
    assert search_key("A" + "".join(SEARCH_WHITESPACE) + "B") == "ab"
    assert search_key("A\u200bB") == "a\u200bb"
    assert search_match("사이버수사", "사이버", "수사") is False
    assert search_match("발주기관 미확인", None) is False
    assert validation_value("  A  B  ") == "A B"
    assert validation_value("\ufeff\u3000") == ""
    assert validation_value("  A  ") == "A"
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        for whitespace in SEARCH_WHITESPACE:
            assert connection.scalar(select(search_sql_match(literal("A" + whitespace + "B"), "ab"))) is True


@requires_postgres
def test_postgresql_search_sql_matches_python_key():
    cases = [
        ("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", True),
        ("ab", "A" + "".join(SEARCH_WHITESPACE) + "B", True),
        ("a\u200bb", "A\u200bB", True),
        ("ä", "Ä", False),
        ("i", "İ", False),
        ("A%_\\", "a%_\\", True),
        ("A%_\\", "aXYZ", False),
    ]
    with migrated_engine() as engine, engine.connect() as connection:
        for query, target, expected in cases:
            assert search_match(query, target) is expected
            assert connection.scalar(select(search_sql_match(literal(target), query))) is expected
