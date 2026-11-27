"""OpenAI Responses API body, usage and price for `gpt-6-luna`/high (ADR-0081).

This is the body the 2026-11-27 evaluation sent (`scripts/engine-eval.py --transport responses`,
19/19 cases): the system text as a developer message, the document as a user part ending with an
explicit prompt-cache breakpoint for the passes that share it, and the instruction as a second
user part. `store` is off. Nothing here opens a connection.
"""

from __future__ import annotations

import hashlib
import json

MODEL = "gpt-6-luna"
EFFORT = "high"
TRANSPORT = "openai_responses"
RESPONSES_URL = "https://api.openai.com/v1/responses"
WIRE_VERSION = "bidops.engine-live-wire.v1"
# Passes that send the same system + RFP document. `units` sends a different document.
CACHED_DOCUMENT_PURPOSES = frozenset({"extract", "match", "synth"})
PURPOSES = ("extract", "units", "match", "synth")

# OpenAI API Standard tier, USD per 1M tokens (checked 2026-11-26; models/gpt-6-luna and pricing
# pages). A request whose input exceeds LONG_CONTEXT_INPUT is billed at the multipliers below.
PRICE_SOURCE = "openai-api-standard-2026-11-26"
USD_PER_MTOK = {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50}
LONG_CONTEXT_INPUT = 272_000
LONG_CONTEXT_MULTIPLIER = {"input": 2.0, "output": 1.5}


def request_body(parts: tuple[str, str, str], *, purpose: str) -> dict:
    """The Responses API request body for one engine call."""
    if purpose not in PURPOSES:
        raise ValueError("unsupported purpose")
    system, document, instruction = parts
    doc_part = {"type": "input_text", "text": document}
    if purpose in CACHED_DOCUMENT_PURPOSES:
        doc_part["prompt_cache_breakpoint"] = {"mode": "explicit"}
    return {
        "model": MODEL,
        "reasoning": {"effort": EFFORT},
        "store": False,
        "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [doc_part, {"type": "input_text", "text": instruction}]},
        ],
    }


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def body_sha256(body: dict) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


def document_text(body: dict) -> str:
    """The document part of a request built by `request_body` (shape already checked)."""
    return body["input"][1]["content"][0]["text"]


def usage(response: dict) -> dict | None:
    """Usage counts of a response body; `None` when the response carries no usage."""
    raw = response.get("usage")
    if not isinstance(raw, dict):
        return None
    details = raw.get("input_tokens_details") or {}
    out_details = raw.get("output_tokens_details") or {}

    def count(value):
        return value if type(value) is int and value >= 0 else 0

    return {
        "input_tokens": count(raw.get("input_tokens")),
        "cached_input_tokens": count(details.get("cached_tokens")),
        "cache_write_input_tokens": count(details.get("cache_write_tokens")),
        "output_tokens": count(raw.get("output_tokens")),
        "reasoning_output_tokens": count(out_details.get("reasoning_tokens")),
    }


def text(response: dict) -> str:
    """Concatenated `output_text` parts of the assistant message items."""
    return "".join(
        part.get("text", "")
        for item in response.get("output") or [] if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content") or [] if isinstance(part, dict) and part.get("type") == "output_text"
    )


def api_equivalent(counts: dict) -> dict:
    """Token split and USD of one request. Cached and cache-write tokens are parts of input."""
    cached = min(counts["cached_input_tokens"], counts["input_tokens"])
    written = min(counts["cache_write_input_tokens"], counts["input_tokens"] - cached)
    fresh = counts["input_tokens"] - cached - written
    long_context = counts["input_tokens"] > LONG_CONTEXT_INPUT
    m_in = LONG_CONTEXT_MULTIPLIER["input"] if long_context else 1.0
    m_out = LONG_CONTEXT_MULTIPLIER["output"] if long_context else 1.0
    p = USD_PER_MTOK
    usd = (
        fresh * p["input"] * m_in + cached * p["cached_input"] * m_in + written * p["cache_write"] * m_in
        + counts["output_tokens"] * p["output"] * m_out
    ) / 1_000_000
    return {"fresh_input_tokens": fresh, "cache_read_input_tokens": cached, "cache_write_input_tokens": written,
            "output_tokens": counts["output_tokens"], "long_context": long_context, "usd": usd}
