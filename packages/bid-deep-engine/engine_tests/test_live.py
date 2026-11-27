"""Live mode over frames (ADR-0081): request body, frame protocol and the preview plan.

The fake supervisor answers each frame with a Responses API body shaped like the bodies recorded
on 2026-11-27 (`status`, `model`, `output[]` with reasoning items and one message, `usage` with
`input_tokens_details.cached_tokens/cache_write_tokens`). Its answer text is the deterministic
mock's value for the same stage, so the real pipeline, gates and readiness run unchanged.
"""

import io
import json

import pytest

from bid_deep_engine import runner
from bid_deep_engine.analysis.schemas import MatchOut, RfpFacts, SynthOut
from bid_deep_engine.analysis.workunits import WorkUnitAssignmentsOut
from bid_deep_engine.live import ipc, responses
from engine_tests.test_runner import make_bundle_payload

OUTPUT_MODELS = {"extract": RfpFacts, "units": WorkUnitAssignmentsOut, "match": MatchOut, "synth": SynthOut}


def live_payload():
    payload = make_bundle_payload()
    payload["schema_version"] = "bidops.engine-input.v3"
    payload["mode"] = "live"
    payload["company_bundle"]["slug"] = "synthetic"
    for key in ("company_id", "company_name", "profile_version_id", "profile_sha256",
                "profile_payload", "graph_version_id", "graph_sha256", "graph_nodes"):
        payload.pop(key, None)
    return payload


def recorded_shape(text, *, status="completed", cached=0, written=0):
    return {
        "id": "resp_test", "object": "response", "status": status, "model": "gpt-6-luna",
        "store": False, "error": None, "incomplete_details": None,
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {
            "input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
            "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": written},
            "output_tokens_details": {"reasoning_tokens": 50},
        },
    }


class FakeSupervisor:
    """Reader/writer pair standing in for the BidOps supervisor."""

    def __init__(self, payload, *, reply=None):
        self.frames = []
        self._pending = []
        _, rfp = runner.document_from_blocks(payload)
        self.mock = runner.MockTransport(rfp)
        self.reply = reply or self.answer

    def answer(self, frame):
        value = self.mock.parse(OUTPUT_MODELS[frame["purpose"]], purpose=frame["purpose"]).parsed
        return {"frame": "response", "seq": frame["seq"], "duration_ms": 7,
                "body": recorded_shape(value.model_dump_json())}

    # writer
    def write(self, text):
        for line in text.splitlines():
            frame = json.loads(line)
            self.frames.append(frame)
            reply = self.reply(frame)
            if reply is not None:
                self._pending.append(json.dumps(reply, ensure_ascii=False) + "\n")

    def flush(self):
        pass

    # reader
    def readline(self, limit=-1):
        return self._pending.pop(0) if self._pending else ""


def test_request_body_is_the_evaluated_shape():
    body = responses.request_body(("SYS", "\n\n# 문서\n\nDOC", "\n\n# 지시\n\nDO"), purpose="match")
    assert body["model"] == "gpt-6-luna" and body["reasoning"] == {"effort": "high"}
    assert body["store"] is False
    assert body["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    developer, user = body["input"]
    assert developer == {"role": "developer", "content": [{"type": "input_text", "text": "SYS"}]}
    assert user["content"][0] == {"type": "input_text", "text": "\n\n# 문서\n\nDOC",
                                  "prompt_cache_breakpoint": {"mode": "explicit"}}
    assert user["content"][1] == {"type": "input_text", "text": "\n\n# 지시\n\nDO"}
    units = responses.request_body(("S", "D", "I"), purpose="units")
    assert "prompt_cache_breakpoint" not in units["input"][1]["content"][0]
    with pytest.raises(ValueError):
        responses.request_body(("S", "D", "I"), purpose="chat")


def test_usage_and_price_follow_the_recorded_usage_fields():
    counts = responses.usage(recorded_shape("{}", cached=600, written=300))
    assert counts == {"input_tokens": 1000, "cached_input_tokens": 600, "cache_write_input_tokens": 300,
                      "output_tokens": 200, "reasoning_output_tokens": 50}
    priced = responses.api_equivalent(counts)
    assert (priced["fresh_input_tokens"], priced["cache_read_input_tokens"], priced["cache_write_input_tokens"]) == (100, 600, 300)
    assert priced["usd"] == pytest.approx((100 * 0.10 + 600 * 0.01 + 300 * 0.125 + 200 * 0.50) / 1e6)
    big = responses.api_equivalent({**counts, "input_tokens": 300_000, "cached_input_tokens": 0, "cache_write_input_tokens": 0})
    assert big["long_context"] is True
    assert big["usd"] == pytest.approx((300_000 * 0.10 * 2 + 200 * 0.50 * 1.5) / 1e6)
    assert responses.usage({"status": "completed"}) is None


def test_live_run_sends_every_call_as_a_frame_and_marks_the_result_unmeasured():
    payload = live_payload()
    fake = FakeSupervisor(payload)
    out = runner.execute_live(payload, fake, fake)
    purposes = [frame["purpose"] for frame in fake.frames]
    assert purposes[0] == "extract" and purposes[-2:] == ["match", "synth"]
    assert [frame["seq"] for frame in fake.frames] == list(range(1, len(purposes) + 1))
    assert out["calls"] == len(purposes)
    assert out["quality_status"] == "unmeasured_reference" and out["status"] == "completed"
    assert "mock_reference_not_quality_evidence" not in out["warnings"]
    # extract, match and synth share one byte-identical document part (the cache breakpoint).
    shared = {responses.document_text(f["body"]) for f in fake.frames if f["purpose"] != "units"}
    assert len(shared) == 1
    calls = out["artifacts"]["usage.json"]["calls"] if "usage.json" in out["artifacts"] else None
    if calls:
        assert all(call["model"] == "gpt-6-luna" for call in calls)


def test_preview_plan_binds_the_exact_first_request():
    payload = live_payload()
    plan = runner.preview(payload)["live"]
    fake = FakeSupervisor(payload)
    runner.execute_live(payload, fake, fake)
    assert plan["first_request_sha256"] == responses.body_sha256(fake.frames[0]["body"])
    assert plan["planned_calls"] >= len(fake.frames) - 1  # a units repair may add one
    assert plan["transport"] == "openai_responses" and plan["model"] == "gpt-6-luna"
    assert plan["endpoint"] == "https://api.openai.com/v1/responses"


def test_abort_fails_the_run_and_no_later_frame_is_sent():
    payload = live_payload()
    fake = FakeSupervisor(payload, reply=lambda frame: {"frame": "abort", "seq": frame["seq"], "code": "budget_exhausted"})
    out = runner.execute_live(payload, fake, fake)
    assert len(fake.frames) == 1
    assert out["status"] == "failed" and out["quality_status"] == "unmeasured_reference"
    assert out["error_code"] == "engine_pipeline_failed"


@pytest.mark.parametrize("reply", [
    lambda frame: None,  # supervisor closed the pipe
    lambda frame: {"frame": "response", "seq": frame["seq"] + 1, "body": recorded_shape("{}")},
    lambda frame: {"frame": "something", "seq": frame["seq"]},
])
def test_broken_replies_abort_without_resending(reply):
    payload = live_payload()
    fake = FakeSupervisor(payload, reply=reply)
    out = runner.execute_live(payload, fake, fake)
    assert len(fake.frames) == 1 and out["status"] == "failed"


def test_incomplete_response_fails_the_stage():
    payload = live_payload()
    fake = FakeSupervisor(payload, reply=lambda frame: {"frame": "response", "seq": frame["seq"],
                                                       "body": recorded_shape("{}", status="incomplete")})
    out = runner.execute_live(payload, fake, fake)
    assert out["status"] == "failed"


def test_live_mode_is_refused_by_the_mock_entry_and_mock_by_the_live_entry():
    payload = live_payload()
    with pytest.raises(runner.EngineError):
        runner.execute(payload)
    mock = {**payload, "mode": "mock_reference"}
    fake = FakeSupervisor(payload)
    with pytest.raises(runner.EngineError):
        runner.execute_live(mock, fake, fake)
    v2 = {**payload, "schema_version": "bidops.engine-input.v2"}
    with pytest.raises(runner.EngineError):
        runner.execute_live(v2, fake, fake)


def test_live_main_over_real_pipes_keeps_frames_apart_from_other_output():
    """The real `--live-ipc` process: payload line in, frames out, nothing else on the frame pipe."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    payload = live_payload()
    fake = FakeSupervisor(payload)
    src = Path(runner.__file__).resolve().parents[1]
    proc = subprocess.Popen(
        [_sys.executable, "-m", "bid_deep_engine.runner", "--live-ipc"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"},
    )
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    result = None
    for line in proc.stdout:
        frame = json.loads(line)
        if frame["frame"] == "result":
            result = frame["output"]
            break
        assert frame["frame"] == "call"
        fake.frames.append(frame)
        proc.stdin.write(json.dumps(fake.answer(frame), ensure_ascii=False) + "\n")
        proc.stdin.flush()
    proc.stdin.close()
    assert proc.wait(timeout=60) == 0
    assert result is not None and result["status"] == "completed"
    assert result["calls"] == len(fake.frames)
    assert proc.stdout.read() == ""
