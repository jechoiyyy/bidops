from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
import json
import logging
from types import SimpleNamespace
from typing import Iterator

from app.logging_setup import _THIRD_PARTY_FLOOR, configure


@contextmanager
def _configured_logging(*, log_traceback: bool = False) -> Iterator[tuple[logging.Logger, StringIO]]:
    root = logging.getLogger()
    previous_handlers = root.handlers
    previous_level = root.level
    previous_floors = {name: logging.getLogger(name).level for name in _THIRD_PARTY_FLOOR}
    root.handlers = []
    stream = StringIO()
    settings = SimpleNamespace(log_level="DEBUG", log_traceback=log_traceback)
    try:
        configure(settings)
        handler = root.handlers[0]
        handler.stream = stream
        yield logging.getLogger("bidops.test"), stream
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = previous_handlers
        root.setLevel(previous_level)
        for name, level in previous_floors.items():
            logging.getLogger(name).setLevel(level)


def test_unsafe_structured_keys_are_removed() -> None:
    with _configured_logging() as (logger, stream):
        logger.warning(
            "reviewed",
            extra={
                "bidops": {
                    "event": "reviewed",
                    "prompt": "private prompt",
                    "password": "private password",
                    "reviewer_name": "private reviewer",
                }
            },
        )

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "reviewed"
    assert "prompt" not in payload
    assert "password" not in payload
    assert "reviewer_name" not in payload


def test_secret_like_message_is_masked() -> None:
    with _configured_logging() as (logger, stream):
        logger.warning("api_key=abc123")

    payload = json.loads(stream.getvalue())
    assert payload["message"] == "api_key=[비밀 값]"


def test_configure_is_reentrant_without_duplicate_handlers() -> None:
    with _configured_logging() as (_, _):
        root = logging.getLogger()
        settings = SimpleNamespace(log_level="DEBUG", log_traceback=False)
        configure(settings)
        configure(settings)
        assert len(root.handlers) == 1


def test_traceback_is_controlled_by_log_traceback() -> None:
    with _configured_logging(log_traceback=False) as (logger, stream):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.error("failed", exc_info=True)
        without_traceback = json.loads(stream.getvalue())

    with _configured_logging(log_traceback=True) as (logger, stream):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.error("failed", exc_info=True)
        with_traceback = json.loads(stream.getvalue())

    assert "traceback" not in without_traceback
    assert "traceback" in with_traceback


def test_sql_statement_and_bound_parameters_are_dropped_from_a_traceback() -> None:
    """A DBAPI error carries the statement and its values in its own text.

    ``exc_info=True`` around a database call is the normal pattern in the
    workers and the screening queue, so the notice text bound into a failing
    INSERT must not ride out with the traceback.
    """

    with _configured_logging(log_traceback=True) as (logger, stream):
        try:
            raise RuntimeError(
                "(psycopg.errors.CheckViolation) new row violates check\n"
                "[SQL: INSERT INTO bidops.notice (title) VALUES (%(title)s)]\n"
                "[parameters: {'title': '2026년 정보시스템 구축 사업 공고'}]"
            )
        except RuntimeError:
            logger.error("insert failed", exc_info=True)

    payload = json.loads(stream.getvalue())
    assert "정보시스템 구축 사업" not in payload["traceback"]
    assert "INSERT INTO" not in payload["traceback"]
    assert "[SQL 및 파라미터 생략]" in payload["traceback"]
    assert "CheckViolation" in payload["traceback"]


def test_third_party_loggers_stay_at_warning_when_the_app_is_verbose() -> None:
    """A DEBUG application level must not turn on SQL, HTTP, or SDK body logging.

    ``sqlalchemy`` emits bind parameters, ``openai`` emits request bodies, and
    the HTTP clients emit full URLs including query strings.  The masking
    filter cannot redact notice text or a prompt, so these stay pinned.
    """

    with _configured_logging() as (_, stream):
        assert logging.getLogger().level == logging.DEBUG
        for name in _THIRD_PARTY_FLOOR:
            assert logging.getLogger(name).level == logging.WARNING, name

        logging.getLogger("sqlalchemy.engine.Engine").debug(
            "SELECT title FROM notice -- 공고 원문"
        )
        logging.getLogger("openai._base_client").debug("request body with a prompt")

    assert stream.getvalue() == ""


def test_output_is_one_json_line() -> None:
    with _configured_logging() as (logger, stream):
        logger.warning("one line", extra={"bidops": {"count": 1}})

    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["message"] == "one line"
