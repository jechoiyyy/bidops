"""구조화 로깅 설정. 마스킹은 필터에서 강제한다."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
import sys
from typing import Any

from .config import Settings, get_settings
from .redaction import mask_secrets


SAFE_KEYS = frozenset(
    {
        "event",
        "execution_id",
        "run_id",
        "notice_id",
        "notice_pk",
        "deep_review_id",
        "attempt_id",
        "stage",
        "job_id",
        "fence",
        "worker_id",
        "status",
        "error_code",
        "failure_type",
        "retry_count",
        "duration_ms",
        "size_bytes",
        "sha256",
        "digest",
        "policy_version",
        "profile_version",
        "generation_config_digest",
        "queue_no",
        "exit_code",
        "http_status",
        "count",
    }
)
_RESERVED_KEYS = frozenset({"ts", "level", "logger", "message"})
_HANDLER_MARKER = "_bidops_logging_handler"

# Third-party loggers that emit request bodies, SQL bind parameters, or full
# URLs at DEBUG/INFO.  The masking filter only redacts key-like assignments, so
# a developer raising BIDOPS_LOG_LEVEL to DEBUG would otherwise dump prompts,
# notice text, and query strings that docs/security.md keeps out of logs.
# These stay pinned at WARNING no matter what the application level is.
_THIRD_PARTY_FLOOR = (
    "sqlalchemy",
    "alembic",
    "openai",
    "httpx",
    "httpcore",
    "urllib3",
    "botocore",
    "boto3",
    "minio",
    "apscheduler",
    "asyncio",
    "multipart",
)


# SQLAlchemy renders the failing statement and its bound values into the
# exception text, so a DBAPI traceback can carry notice text or model output
# that mask_secrets has no pattern for.  Everything from the statement marker
# onward is dropped; the exception type and Python frames are what diagnose a
# query failure anyway.
_SQL_PAYLOAD = re.compile(r"\[SQL:.*", re.DOTALL)


def _redact_traceback(text: str) -> str:
    return mask_secrets(_SQL_PAYLOAD.sub("[SQL 및 파라미터 생략]", text))


class SecretMaskingFilter(logging.Filter):
    """Keep structured fields safe and redact the free-form log message."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(str(record.msg))
        bidops = getattr(record, "bidops", {})
        if not isinstance(bidops, dict):
            bidops = {}
        record.bidops = {
            key: mask_secrets(value)[:200] if isinstance(value, str) else value
            for key, value in bidops.items()
            if key in SAFE_KEYS
        }
        return True


class JsonFormatter(logging.Formatter):
    """Render a log record as one flat, JSON-encoded line."""

    def __init__(self, log_traceback: bool = False) -> None:
        super().__init__()
        self.log_traceback = log_traceback

    def format(self, record: logging.LogRecord) -> str:
        bidops = getattr(record, "bidops", {})
        if not isinstance(bidops, dict):
            bidops = {}
        safe_bidops = {
            key: value for key, value in bidops.items() if key not in _RESERVED_KEYS
        }
        payload: dict[str, Any] = {
            **safe_bidops,
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and self.log_traceback:
            payload["traceback"] = _redact_traceback(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure(settings: Settings | None = None) -> None:
    """Configure the process-wide structured logging handler."""

    settings = settings or get_settings()
    level = getattr(logging, settings.log_level)
    root = logging.getLogger()
    root.setLevel(level)

    handler = next(
        (
            candidate
            for candidate in root.handlers
            if getattr(candidate, _HANDLER_MARKER, False)
        ),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        setattr(handler, _HANDLER_MARKER, True)
        root.addHandler(handler)

    for candidate in list(root.handlers):
        if candidate is not handler and getattr(candidate, _HANDLER_MARKER, False):
            root.removeHandler(candidate)
            candidate.close()

    handler.setLevel(level)
    handler.filters.clear()
    handler.addFilter(SecretMaskingFilter())
    handler.setFormatter(JsonFormatter(log_traceback=settings.log_traceback))

    for name in _THIRD_PARTY_FLOOR:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

    logging.getLogger("uvicorn.access").propagate = False
