"""Literal list search shared by lifecycle and screening endpoints."""

from __future__ import annotations

import sqlite3
from typing import Any

from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import String


# Unicode White_Space (PropList 16.0) plus BOM. Keep zero-width space.
SEARCH_WHITESPACE = tuple(map(chr, (
    *range(0x09, 0x0E), 0x20, 0x85, 0xA0, 0x1680,
    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF,
)))
_SPACE_SET = frozenset(SEARCH_WHITESPACE)
_ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"


class _SearchSQLKey(FunctionElement[str]):
    """Render the search key as one SQL function call on either database."""

    type = String()
    inherit_cache = True


@compiles(_SearchSQLKey, "sqlite")
def _sqlite_search_key(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(func.bidops_search_key(*element.clauses), **kw)


@compiles(_SearchSQLKey, "postgresql")
def _postgresql_search_key(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(
        func.translate(
            *element.clauses, _ASCII_UPPER + "".join(SEARCH_WHITESPACE), _ASCII_LOWER
        ),
        **kw,
    )


def search_key(value: str | None) -> str:
    """Remove specified whitespace and fold only ASCII uppercase letters."""

    if not value:
        return ""
    return "".join(chr(ord(char) + 32) if "A" <= char <= "Z" else char
                   for char in value if char not in _SPACE_SET)


@event.listens_for(Engine, "connect")
def _register_sqlite_search_key(dbapi_connection: Any, _connection_record: Any) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function("bidops_search_key", 1, search_key, deterministic=True)


def validation_value(value: str) -> str:
    """Collapse specified whitespace for codepoint length validation only."""

    result: list[str] = []
    for char in value:
        if char in _SPACE_SET:
            if result and result[-1] != " ":
                result.append(" ")
        else:
            result.append(char)
    return "".join(result).strip(" ")


def search_match(query: str, *fields: str | None) -> bool:
    needle = search_key(query)
    return bool(needle) and any(needle in search_key(field) for field in fields if field is not None)


def search_sql_key(expression: Any) -> Any:
    return _SearchSQLKey(expression)


def search_sql_match(expression: Any, query: str) -> Any:
    """Bind a literal LIKE pattern with the same key as :func:`search_key`."""

    needle = search_key(query)
    pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return search_sql_key(expression).like(pattern, escape="\\")
