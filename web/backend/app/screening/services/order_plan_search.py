"""Python casefold 검색 의미를 보존하는 DB별 SQL 식.

PostgreSQL 17에는 Unicode full casefold 함수가 없고 SQLite lower는 ASCII만
처리한다. DB의 locale과 무관하게 이전 Python 검색과 같은 문자표를 사용한다.
"""
from __future__ import annotations

from functools import lru_cache
import sys
from typing import Any

from sqlalchemy import String, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ...core.db import isolated_test_boundary_active


@lru_cache(maxsize=1)
def _casefold_tables() -> tuple[str, str, tuple[tuple[str, str], ...]]:
    single_source: list[str] = []
    single_target: list[str] = []
    expansions: list[tuple[str, str]] = []
    for codepoint in range(sys.maxunicode + 1):
        character = chr(codepoint)
        folded = character.casefold()
        if character == folded:
            continue
        if len(folded) == 1:
            single_source.append(character)
            single_target.append(folded)
        else:
            expansions.append((character, folded))
    return "".join(single_source), "".join(single_target), tuple(expansions)


class _PostgreSQLCasefold(FunctionElement):
    """SQLAlchemy 방문 깊이가 문자표 크기에 비례하지 않도록 인자를 평탄하게 둔다."""

    type = String()
    inherit_cache = True


@compiles(_PostgreSQLCasefold, "postgresql")
def _compile_postgresql_casefold(element, compiler, **kwargs):
    arguments = list(element.clauses)
    rendered = [compiler.process(argument, **kwargs) for argument in arguments]
    expression = f"translate({rendered[0]}, {rendered[1]}, {rendered[2]})"
    for index in range(3, len(rendered), 2):
        expression = f"replace({expression}, {rendered[index]}, {rendered[index + 1]})"
    return expression


def casefold_column(session: Session, column: Any) -> ColumnElement[str]:
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        if not isolated_test_boundary_active():
            raise RuntimeError("SQLite 검색은 격리 테스트에서만 지원합니다")
        # 연결 수명에만 한정되며 스키마·전역 engine·다른 연결은 바꾸지 않는다.
        connection = session.connection().connection.driver_connection
        connection.create_function(
            "bidops_order_plan_casefold", 1,
            lambda value: value.casefold() if value is not None else None,
            deterministic=True,
        )
        return func.bidops_order_plan_casefold(column)
    if dialect != "postgresql":
        raise RuntimeError("지원하지 않는 검색 DB입니다")
    source, target, expansions = _casefold_tables()
    # full casefold의 결과는 다시 casefold해도 같으므로 뒤의 치환이 앞의
    # 결과를 재변환하지 않는다. 한 글자 치환과 확장을 나눠도 의미가 같다.
    expansion_arguments = [value for pair in expansions for value in pair]
    return _PostgreSQLCasefold(column, source, target, *expansion_arguments)
