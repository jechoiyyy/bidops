"""Frame transport for `runner --live-ipc` and the preview's first-request plan.

The runner never opens a network connection and never holds a key. For each engine call it writes
one JSON line `{"frame": "call", "seq", "purpose", "body"}` to the frame writer and blocks on one
JSON line from the frame reader:

- `{"frame": "response", "seq", "body", "duration_ms"}` — the raw Responses API body the
  supervisor received for that request;
- `{"frame": "abort", "seq", "code"}` — the supervisor refused or lost the call. Every later call
  in the run fails without another frame.

Any other line, a wrong `seq`, or end of input aborts the run the same way.
"""

from __future__ import annotations

import json

from ..analysis.llm import LlmCallError
from . import framed, responses

MAX_FRAME_BYTES = 16 * 1024 * 1024


class FrameTransport:
    """`LlmClient` that sends each call to the supervisor as a frame."""

    phase = "analyze"
    fallbacks = False
    transport_name = responses.TRANSPORT
    model_name = responses.MODEL

    def __init__(self, reader, writer, *, run_id: str):
        self._reader = reader
        self._writer = writer
        self.run_id = run_id
        self.seq = 0
        self.aborted: str | None = None

    def count_tokens(self, **kwargs) -> int:
        return sum(len(str(v)) for v in kwargs.values()) // 2

    def _abort(self, code: str):
        self.aborted = self.aborted or code
        raise LlmCallError(f"live_call_aborted:{self.aborted}")

    def parse(self, output_model, *, purpose, system, document, instruction, slug, **kwargs):
        if self.aborted:
            self._abort(self.aborted)
        body = responses.request_body(
            framed.parts(output_model, system=system, document=document, instruction=instruction),
            purpose=purpose,
        )
        self.seq += 1
        self._writer.write(json.dumps(
            {"frame": "call", "seq": self.seq, "purpose": purpose, "body": body}, ensure_ascii=False,
        ) + "\n")
        self._writer.flush()
        line = self._reader.readline(MAX_FRAME_BYTES + 1)
        if not line or len(line) > MAX_FRAME_BYTES:
            self._abort("supervisor_closed")
        try:
            reply = json.loads(line)
        except ValueError:
            self._abort("frame_invalid")
        if not isinstance(reply, dict) or reply.get("seq") != self.seq:
            self._abort("frame_invalid")
        if reply.get("frame") == "abort":
            code = reply.get("code")
            self._abort(code if isinstance(code, str) and code.isidentifier() else "aborted")
        if reply.get("frame") != "response" or not isinstance(reply.get("body"), dict):
            self._abort("frame_invalid")
        answer = reply["body"]
        if answer.get("status") != "completed":
            # The supervisor already recorded the call; the stage fails like a transport error.
            raise LlmCallError("live_response_not_completed")
        counts = responses.usage(answer)
        served = answer.get("model") if isinstance(answer.get("model"), str) else responses.MODEL
        duration = reply.get("duration_ms") if type(reply.get("duration_ms")) is int else 0
        record = framed.call_record(purpose, counts, duration, served)
        return framed.parse_answer(
            output_model, responses.text(answer), slug=slug, purpose=purpose, record=record,
            usage=framed.token_usage(counts), served_model=served,
        )


class FirstRequestPlan:
    """Builds the first request exactly as the live run will, records its body and stops."""

    phase = "analyze"
    fallbacks = False
    transport_name = responses.TRANSPORT
    model_name = responses.MODEL
    run_id = "preview"

    def __init__(self):
        self.first: dict | None = None
        self.first_purpose: str | None = None

    def count_tokens(self, **kwargs) -> int:
        return sum(len(str(v)) for v in kwargs.values()) // 2

    def parse(self, output_model, *, purpose, system, document, instruction, slug, **kwargs):
        if self.first is None:
            self.first_purpose = purpose
            self.first = responses.request_body(
                framed.parts(output_model, system=system, document=document, instruction=instruction),
                purpose=purpose,
            )
        raise LlmCallError("plan_only")
