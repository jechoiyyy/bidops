"""Shared fakes for the lifecycle linkage survey tests.

Nothing here touches the network: the fetcher is driven by canned payloads so
every contract can be exercised offline.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import survey  # noqa: E402


def page_payload(
    items: Sequence[dict[str, Any]],
    total: int | None = None,
    page_no: int = 1,
    rows: int = 500,
) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {
                "totalCount": len(items) if total is None else total,
                "pageNo": page_no,
                "numOfRows": rows,
                "items": list(items),
            },
        }
    }


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


class FakeOpener:
    """Serves canned payloads and records the URLs it was asked to open."""

    def __init__(self, payloads: Sequence[dict[str, Any]]):
        self.payloads = list(payloads)
        self.urls: list[str] = []

    def open(self, request: Any, timeout: Any = None) -> FakeResponse:
        self.urls.append(request.full_url)
        payload = self.payloads.pop(0)
        return FakeResponse(json.dumps(payload).encode("utf-8"))


def make_fetcher(payloads: Sequence[dict[str, Any]]) -> "survey.SurveyFetcher":
    return survey.SurveyFetcher(
        "test-service-key", opener=FakeOpener(payloads), sleeper=lambda _seconds: None
    )
