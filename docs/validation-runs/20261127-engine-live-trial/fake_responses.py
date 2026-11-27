"""Fake OpenAI Responses endpoint for the isolated live-engine trial (no network beyond the trial net).

POST /v1/responses answers with the body shape of the 83 live responses recorded on 2026-11-27; the
answer text is the engine mock's value for the stage named by the request's output schema. Every
request is appended to /trial/requests.jsonl (sha256, purpose, auth header present) for counting.
"""

import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

sys.path.insert(0, "/app/packages/bid-deep-engine/src")
from bid_deep_engine import runner  # noqa: E402
from bid_deep_engine.analysis.schemas import MatchOut, RfpFacts, SynthOut  # noqa: E402
from bid_deep_engine.analysis.workunits import WorkUnitAssignmentsOut  # noqa: E402

MODELS = {"RfpFacts": ("extract", RfpFacts), "MatchOut": ("match", MatchOut), "SynthOut": ("synth", SynthOut),
          "WorkUnitAssignmentsOut": ("units", WorkUnitAssignmentsOut)}
LOG = "/trial/requests.jsonl"


_MOCK = {}


def _mock():
    """The engine mock built from the frozen input the trial driver wrote (same document as the run)."""
    if "transport" not in _MOCK:
        payload = json.load(open("/trial/frozen.json", encoding="utf-8"))
        _, rfp = runner.document_from_blocks(payload)
        _MOCK["transport"] = runner.MockTransport(rfp)
    return _MOCK["transport"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.loads(raw)
        instruction = body["input"][1]["content"][1]["text"]
        title = json.loads(instruction.rstrip().rsplit("\n\n", 1)[-1])["title"]
        purpose, model = MODELS[title]
        document = body["input"][1]["content"][0]["text"]
        value = _mock().parse(model, purpose=purpose).parsed
        cached = 800 if purpose in ("match", "synth") else 0
        answer = {
            "id": f"resp_{uuid4().hex[:8]}", "object": "response", "status": "completed", "model": "gpt-6-luna",
            "store": False, "error": None, "incomplete_details": None,
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": value.model_dump_json()}]}],
            "usage": {"input_tokens": len(raw) // 2, "output_tokens": 200, "total_tokens": len(raw) // 2 + 200,
                      "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": 0 if cached else 900},
                      "output_tokens_details": {"reasoning_tokens": 50}},
        }
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(json.dumps({"sha256": hashlib.sha256(raw).hexdigest(), "purpose": purpose,
                                  "authorized": self.headers.get("Authorization", "").startswith("Bearer "),
                                  "store": body.get("store"), "doc_chars": len(document)}) + "\n")
        data = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
