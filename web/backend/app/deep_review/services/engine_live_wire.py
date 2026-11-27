"""Wire contract of the live engine path (ADR-0081), checked on the supervisor side.

The engine subprocess builds each request with `bid_deep_engine.live.responses.request_body`; the
web process never imports the engine package, so this module restates the same constants and
rebuilds every body from its own three parts. A frame whose body is not byte-for-byte that
rebuild (another model, effort, store flag, cache option or an extra key) is refused before
anything is sent. `tests/deep_review/test_engine_live_wire.py` loads the engine module by path and
checks that both builders produce the same bodies.
"""

from __future__ import annotations

import hashlib
import json

MODEL = "gpt-6-luna"
EFFORT = "high"
TRANSPORT = "openai_responses"
RESPONSES_URL = "https://api.openai.com/v1/responses"
WIRE_VERSION = "bidops.engine-live-wire.v1"
CACHED_DOCUMENT_PURPOSES = frozenset({"extract", "match", "synth"})
PURPOSES = ("extract", "units", "match", "synth")
MAX_UNITS_CALLS = 2
PRICE_SOURCE = "openai-api-standard-2026-11-26"
USD_PER_MTOK = {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50}
LONG_CONTEXT_INPUT = 272_000
LONG_CONTEXT_MULTIPLIER = {"input": 2.0, "output": 1.5}
MAX_FRAME_BYTES = 16 * 1024 * 1024


class WireRefusal(Exception):
    """A frame the supervisor will not send. `code` is a short identifier."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def request_body(parts: tuple[str, str, str], *, purpose: str) -> dict:
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


def estimated_tokens(body: dict) -> int:
    """Rough input size (characters / 2), the same rule the engine's `count_tokens` uses."""
    return len(canonical(body).decode("utf-8")) // 2


def _parts(body) -> tuple[str, str, str]:
    try:
        developer, user = body["input"]
        (system,) = developer["content"]
        document, instruction = user["content"]
        texts = (system["text"], document["text"], instruction["text"])
    except (KeyError, TypeError, ValueError):
        raise WireRefusal("frame_body_invalid") from None
    if not all(isinstance(text, str) for text in texts):
        raise WireRefusal("frame_body_invalid")
    return texts


class CallSequence:
    """Checks one run's frames in order: extract → units (≤2) → match → synth, nothing after.

    extract, match and synth must carry one byte-identical document part (the cached prefix).
    """

    def __init__(self, *, first_request_sha256: str):
        self.first_request_sha256 = first_request_sha256
        self.seq = 0
        self.purposes: list[str] = []
        self.document: str | None = None

    def check(self, frame) -> tuple[int, str, dict, bytes]:
        if not isinstance(frame, dict) or set(frame) != {"frame", "seq", "purpose", "body"} \
                or frame["frame"] != "call":
            raise WireRefusal("frame_invalid")
        seq, purpose, body = frame["seq"], frame["purpose"], frame["body"]
        if type(seq) is not int or seq != self.seq + 1:
            raise WireRefusal("frame_order_invalid")
        if purpose not in PURPOSES or not isinstance(body, dict):
            raise WireRefusal("frame_invalid")
        previous = self.purposes[-1] if self.purposes else None
        allowed = {
            None: {"extract"},
            "extract": {"units", "match"},
            "units": {"units", "match"},
            "match": {"synth"},
            "synth": set(),
        }[previous]
        if purpose not in allowed or (purpose == "units" and self.purposes.count("units") >= MAX_UNITS_CALLS):
            raise WireRefusal("frame_order_invalid")
        parts = _parts(body)
        if request_body(parts, purpose=purpose) != body:
            raise WireRefusal("frame_body_invalid")
        if purpose in CACHED_DOCUMENT_PURPOSES:
            if self.document is None:
                self.document = parts[1]
            elif parts[1] != self.document:
                raise WireRefusal("frame_document_changed")
        raw = canonical(body)
        if seq == 1 and hashlib.sha256(raw).hexdigest() != self.first_request_sha256:
            raise WireRefusal("input_changed")
        self.seq = seq
        self.purposes.append(purpose)
        return seq, purpose, body, raw


def usage(response: dict) -> dict | None:
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


def usd(counts: dict) -> float:
    cached = min(counts["cached_input_tokens"], counts["input_tokens"])
    written = min(counts["cache_write_input_tokens"], counts["input_tokens"] - cached)
    fresh = counts["input_tokens"] - cached - written
    long_context = counts["input_tokens"] > LONG_CONTEXT_INPUT
    m_in = LONG_CONTEXT_MULTIPLIER["input"] if long_context else 1.0
    m_out = LONG_CONTEXT_MULTIPLIER["output"] if long_context else 1.0
    p = USD_PER_MTOK
    return (
        fresh * p["input"] * m_in + cached * p["cached_input"] * m_in + written * p["cache_write"] * m_in
        + counts["output_tokens"] * p["output"] * m_out
    ) / 1_000_000
