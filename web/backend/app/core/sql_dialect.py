"""One CHECK-constraint source string compiled for both SQL dialects.

PostgreSQL 17 is the canonical store, but the declarative model is also used
by isolated SQLite tests (see :mod:`app.core.db`).  A handful of predicates have no
spelling both dialects accept:

* character classes: SQLite ``GLOB`` versus PostgreSQL POSIX ``~``
* JSON shape: SQLite JSON1 ``json_valid``/``json_type`` versus ``json_typeof``
* backslash search: ``LIKE`` treats ``\\`` as an escape in PostgreSQL but as a
  literal in SQLite, so the same pattern means two different things
* ``char(92)`` is spelled ``chr(92)`` in PostgreSQL

Constraints are therefore written once in the SQLite flavour and wrapped in
:func:`dual`, which derives the PostgreSQL spelling.  The translation refuses
to emit SQL it does not understand, so a new dialect-specific construct fails
at import time instead of silently degrading enforcement on one dialect.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement
from sqlalchemy.types import Boolean


class UntranslatableSQL(ValueError):
    """A CHECK fragment uses a SQLite construct with no known PostgreSQL form."""


_OPERAND = r"(?:\w+\([^()]*\)|[\w.]+)"

# ``X NOT GLOB '*[^0-9a-f]*'`` -> every character is lowercase hex.
_NOT_GLOB_HEX = re.compile(rf"(?P<expr>{_OPERAND})\s+NOT GLOB '\*\[\^0-9a-f\]\*'")
# ``X GLOB '[0-2][0-9]:[0-5][0-9]'`` -> HH:MM clock literal. GLOB is anchored.
_GLOB_CLOCK = re.compile(rf"(?P<expr>{_OPERAND})\s+GLOB '\[0-2\]\[0-9\]:\[0-5\]\[0-9\]'")
_JSON_SHAPE = re.compile(
    r"json_valid\((?P<a>[\w.]+)\)\s+AND\s+json_type\((?P=a)\)\s*=\s*'(?P<kind>object|array)'"
)
# Both spellings of "contains a backslash". PostgreSQL LIKE reads a backslash
# in the pattern as an escape character, so the same pattern would silently
# mean "ends with a literal percent"; a regular expression is used instead.
_LIKE_BACKSLASH = re.compile(
    rf"(?P<expr>{_OPERAND})\s+NOT LIKE\s+(?:'%\\%'|'%'\s*\|\|\s*char\(92\)\s*\|\|\s*'%')"
)

# Emitted PostgreSQL that legitimately contains a backslash is masked while the
# residual check runs, so the check cannot flag this module's own output.
_BACKSLASH_REGEX_LITERAL = "!~ '\\\\'"
_MASK = "\x00no-backslash\x00"

_RESIDUAL = re.compile(r"\bGLOB\b|\bjson_valid\b|\bjson_type\b|\bchar\(92\)|\\")


def to_postgresql(sql: str) -> str:
    """Translate one SQLite-flavoured CHECK fragment to PostgreSQL."""

    out = _LIKE_BACKSLASH.sub(
        lambda m: f"{m.group('expr')} {_BACKSLASH_REGEX_LITERAL}", sql
    )
    out = _NOT_GLOB_HEX.sub(lambda m: f"{m.group('expr')} ~ '^[0-9a-f]*$'", out)
    out = _GLOB_CLOCK.sub(lambda m: f"{m.group('expr')} ~ '^[0-2][0-9]:[0-5][0-9]$'", out)
    # The column type already guarantees syntactic validity in PostgreSQL, so
    # only the top-level shape has to be asserted.
    out = _JSON_SHAPE.sub(lambda m: f"json_typeof({m.group('a')}) = '{m.group('kind')}'", out)
    if _RESIDUAL.search(out.replace(_BACKSLASH_REGEX_LITERAL, _MASK)):
        raise UntranslatableSQL(sql)
    return out


class DualSQL(ColumnElement[bool]):
    """A CHECK fragment rendered differently per dialect."""

    type = Boolean()
    inherit_cache = True

    def __init__(self, sqlite_sql: str, postgresql_sql: str) -> None:
        self.sqlite_sql = sqlite_sql
        self.postgresql_sql = postgresql_sql


def _emit(compiler, sql: str) -> str:
    """Emit literal SQL with the dialect's own text post-processing.

    ``post_process_text`` is what SQLAlchemy applies to a plain ``text()``
    CHECK body; without it a ``LIKE '/%'`` pattern reaches psycopg as a
    placeholder and the DDL is rejected.
    """

    post_process = getattr(compiler, "post_process_text", None)
    return post_process(sql) if post_process is not None else sql


@compiles(DualSQL)
def _dual_default(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return _emit(compiler, element.sqlite_sql)


@compiles(DualSQL, "postgresql")
def _dual_postgresql(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return _emit(compiler, element.postgresql_sql)


def dual(sql: str) -> DualSQL:
    """Wrap a SQLite-flavoured CHECK fragment so PostgreSQL enforces the same rule."""

    return DualSQL(sql, to_postgresql(sql))
