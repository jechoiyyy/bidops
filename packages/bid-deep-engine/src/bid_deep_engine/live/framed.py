"""Prompt parts and JSON answer checks shared by every text-in/text-out engine transport.

`parts` returns (system, document, instruction). They concatenate to the single prompt the
codex-exec transport sends, so the Responses API and codex paths see the same text and differ
only in message boundaries.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..analysis.llm import CallRecord, LlmOutputError, OutputFailure, ParseResult
from ..analysis.pricing import TokenUsage
from . import responses

OUTPUT_HEADER = (
    "아래 JSON Schema를 따르는 JSON 객체 하나만 출력한다. 설명, 머리말, 코드 펜스를 붙이지 않는다."
)


def parts(output_model, *, system: str, document: str, instruction: str) -> tuple[str, str, str]:
    schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False)
    return (
        system,
        f"\n\n# 문서\n\n{document}",
        f"\n\n# 지시\n\n{instruction}\n\n# 출력 형식\n\n{OUTPUT_HEADER}\n\n{schema}\n",
    )


def json_object_text(text: str) -> str | None:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else None


def call_record(purpose: str, counts: dict | None, duration_ms: int, served_model: str) -> CallRecord:
    priced = None if counts is None else responses.api_equivalent(counts)
    return CallRecord(
        at=datetime.now(UTC).isoformat(timespec="seconds"), purpose=purpose, model=responses.MODEL,
        served_model=served_model, price_model=None if priced is None else responses.MODEL,
        cost_basis="exact", stop_reason="end_turn",
        input_tokens=0 if priced is None else priced["fresh_input_tokens"],
        output_tokens=0 if priced is None else priced["output_tokens"],
        cache_read_input_tokens=0 if priced is None else priced["cache_read_input_tokens"],
        cache_creation_5m=0 if priced is None else priced["cache_write_input_tokens"],
        cache_creation_1h=0, input_tokens_counted=0, estimate_usd=None,
        cost_usd=0.0 if priced is None else priced["usd"], duration_ms=duration_ms,
    )


def token_usage(counts: dict | None) -> TokenUsage:
    if counts is None:
        return TokenUsage()
    priced = responses.api_equivalent(counts)
    return TokenUsage(
        input_tokens=priced["fresh_input_tokens"], output_tokens=priced["output_tokens"],
        cache_read_input_tokens=priced["cache_read_input_tokens"],
        cache_creation_5m=priced["cache_write_input_tokens"],
    )


def parse_answer(output_model, text: str, *, slug: str, purpose: str, record: CallRecord,
                 usage: TokenUsage, served_model: str) -> ParseResult:
    """Validate the model's text against `output_model` exactly as the evaluation tool does."""
    body = json_object_text(text)
    if body is None:
        raise LlmOutputError(
            slug, purpose, record=record,
            failure=OutputFailure(response_text=text or None, json_text=None, validation_errors=[],
                                  error_count=0, kind="no_json" if text else "no_text"),
        )
    try:
        value = output_model.model_validate_json(body)
    except Exception as exc:
        errors = getattr(exc, "errors", lambda: [])()
        raise LlmOutputError(
            slug, purpose, record=record,
            failure=OutputFailure(
                response_text=text, json_text=body,
                validation_errors=[
                    {"loc": ".".join(str(p) for p in e.get("loc", ())), "msg": str(e.get("msg", "")),
                     "type": str(e.get("type", ""))}
                    for e in errors[:20]
                ],
                error_count=len(errors), kind="validation",
            ),
        ) from None
    return ParseResult(value, usage, served_model, "end_turn", record)
