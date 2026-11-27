#!/usr/bin/env python3
"""Responses API transport in scripts/engine-eval.py (evaluation only).

The fake API below returns the body shape documented in the OpenAI prompt caching guide and the
Responses create reference (read 2026-11-26): ``status``, ``output`` message items with
``output_text`` parts, and ``usage`` with ``input_tokens_details.cached_tokens`` /
``cache_write_tokens`` and ``output_tokens_details.reasoning_tokens``. The success shape was
compared with the 83 live responses of 2026-11-27 (``prespec1123-25-engine-20261127``, all
``completed``); no live error body was recorded, so the error case follows the documented shape
only. No network, no model, no database.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("ENGINE_EVAL_SCRIPT", ROOT / "scripts/engine-eval.py"))


def _load_module():
    spec = importlib.util.spec_from_file_location("engine_eval_responses_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = _load_module()


def _body(text='{"value": 1}', *, status="completed", cached=40000, written=0):
    return {
        "id": "resp_test", "object": "response", "status": status, "model": "gpt-6-luna",
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {
            "input_tokens": 60000,
            "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": written},
            "output_tokens": 9000, "output_tokens_details": {"reasoning_tokens": 6000}, "total_tokens": 69000,
        },
    }


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class RequestShapeTest(unittest.TestCase):
    PARTS = ("SYSTEM", "\n\n# 문서\n\nDOC", "\n\n# 지시\n\nDO IT")

    def test_breakpoint_after_document_for_shared_passes(self):
        body = ev.responses_request(self.PARTS, purpose="match")
        self.assertEqual(body["model"], "gpt-6-luna")
        self.assertEqual(body["reasoning"], {"effort": "high"})
        self.assertFalse(body["store"])
        self.assertEqual(body["prompt_cache_options"], {"mode": "explicit", "ttl": "30m"})
        developer, user = body["input"]
        self.assertEqual(developer["role"], "developer")
        self.assertNotIn("prompt_cache_breakpoint", developer["content"][0])
        doc, instruction = user["content"]
        self.assertEqual(doc["prompt_cache_breakpoint"], {"mode": "explicit"})
        self.assertNotIn("prompt_cache_breakpoint", instruction)
        # Same text as the codex prompt, only split.
        sent = developer["content"][0]["text"] + doc["text"] + instruction["text"]
        self.assertEqual(sent, "".join(self.PARTS))

    def test_units_writes_no_cache(self):
        body = ev.responses_request(self.PARTS, purpose="units")
        self.assertNotIn("prompt_cache_breakpoint", body["input"][1]["content"][0])

    def test_usage_and_text(self):
        usage = ev.responses_usage(_body(written=2000))
        self.assertEqual(usage, {"input_tokens": 60000, "cached_input_tokens": 40000, "cache_write_input_tokens": 2000,
                                 "output_tokens": 9000, "reasoning_output_tokens": 6000, "turns": 1})
        self.assertEqual(ev.responses_text(_body()), '{"value": 1}')
        self.assertIsNone(ev.responses_usage({"status": "completed"}))
        priced = ev.luna_api_equivalent(usage)
        expected = (18000 * 0.10 + 40000 * 0.01 + 2000 * 0.125 + 9000 * 0.50) / 1_000_000
        self.assertAlmostEqual(priced["usd"], expected, places=12)


class ResponsesTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ev._load_engine(ev.DEFAULT_ENGINE_SRC)

    def _transport(self, tmp: Path, urlopen):
        _runner, llm, _pipeline, token_usage = self.engine
        run_dir = tmp / "eval" / "runs" / "t" / "C1" / "r1"
        run_dir.mkdir(parents=True)
        budget = ev._CallBudget(tmp / "eval", {"max_calls": 5})
        return ev.ResponsesLunaTransport(llm, token_usage, run_dir, budget=budget, api_key="sk-test", urlopen=urlopen), run_dir

    def test_parse_records_cache_read_and_keeps_key_out_of_files(self):
        from pydantic import BaseModel

        class Out(BaseModel):
            value: int

        seen = {}

        def urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data)
            return _FakeResponse(json.dumps(_body()).encode())

        with tempfile.TemporaryDirectory() as raw:
            transport, run_dir = self._transport(Path(raw), urlopen)
            result = transport.parse(Out, purpose="synth", system="S", document="D", instruction="I", slug="C1")
            self.assertEqual(result.parsed.value, 1)
            self.assertEqual(seen["url"], ev.RESPONSES_URL)
            self.assertEqual(seen["auth"], "Bearer sk-test")
            self.assertIn("prompt_cache_breakpoint", seen["body"]["input"][1]["content"][0])
            self.assertEqual(result.usage.cache_read_input_tokens, 40000)
            self.assertEqual(result.usage.input_tokens, 20000)
            self.assertEqual(result.record.price_model, "gpt-6-luna")
            ledger = json.loads((run_dir / "calls" / "01-synth.call.json").read_text())
            self.assertEqual(ledger["usage"]["cached_input_tokens"], 40000)
            saved = run_dir / "calls" / "01.response.json"
            self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
            for path in (run_dir / "calls").iterdir():
                self.assertNotIn(b"sk-test", path.read_bytes())
            # The prompt file still holds the joined text, identical to what codex would get.
            prompt = (run_dir / "calls" / "01-synth.prompt.txt").read_text()
            self.assertTrue(prompt.startswith("S\n\n# 문서\n\nD\n\n# 지시\n\nI"))

    def test_http_error_and_incomplete_fail_the_call(self):
        from pydantic import BaseModel

        class Out(BaseModel):
            value: int

        def http_error(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 429, "rate", {}, io.BytesIO(b'{"error":{"type":"rate_limit"}}'))

        def incomplete(request, timeout):
            return _FakeResponse(json.dumps(_body(status="incomplete")).encode())

        _runner, llm, _pipeline, _usage = self.engine
        for opener, saved in ((http_error, "01.error.json"), (incomplete, "01.response.json")):
            with tempfile.TemporaryDirectory() as raw:
                transport, run_dir = self._transport(Path(raw), opener)
                with self.assertRaises(llm.LlmCallError):
                    transport.parse(Out, purpose="extract", system="S", document="D", instruction="I", slug="C1")
                ledger = json.loads((run_dir / "calls" / "01-extract.call.json").read_text())
                self.assertEqual(ledger["outcome"], "call_failed")
                self.assertTrue((run_dir / "calls" / saved).exists())


class ApprovalGateTest(unittest.TestCase):
    @staticmethod
    def _main(argv):
        import contextlib  # noqa: PLC0415

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = ev.main(argv)
        message = err.getvalue().strip().removeprefix("error: ")
        for expected in ("does not cover the Responses API", "OPENAI_API_KEY is not set"):
            if expected in message:
                message = expected
        return code, message

    def test_responses_needs_approval_naming_the_transport(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "cases.json").write_text(json.dumps({"cases": [{"case_id": "C1"}]}))
            approval = {"schema": ev.APPROVAL_SCHEMA, "model": ev.MODEL, "reasoning_effort": ev.EFFORT,
                        "approved_by": "t", "approved_at": "2026-11-26", "cases": ["C1"], "max_calls": 5}
            (root / "a.json").write_text(json.dumps(approval))
            argv = ["run", "--eval-dir", str(root), "--label", "x", "--mode", "live", "--approval", str(root / "a.json"),
                    "--transport", "responses", "--openai-key-file", str(root / "missing-key")]
            self.assertEqual(self._main(argv), (2, "does not cover the Responses API"))
            (root / "a.json").write_text(json.dumps(dict(approval, transport="openai_responses")))
            env = os.environ.pop("OPENAI_API_KEY", None)
            try:
                self.assertEqual(self._main(argv), (2, "OPENAI_API_KEY is not set"))
            finally:
                if env is not None:
                    os.environ["OPENAI_API_KEY"] = env



class KeyFileAndDefaultsTest(unittest.TestCase):
    def test_key_file_must_be_private_and_reads_codex_auth_or_plain_key(self):
        with tempfile.TemporaryDirectory() as raw:
            auth = Path(raw) / "auth.json"
            auth.write_text(json.dumps({"OPENAI_API_KEY": "sk-file"}))
            auth.chmod(0o644)
            with self.assertRaises(ev.EvalError):
                ev.read_api_key(str(auth))
            auth.chmod(0o600)
            self.assertEqual(ev.read_api_key(str(auth)), "sk-file")
            plain = Path(raw) / "key"
            plain.write_text("sk-plain\n")
            plain.chmod(0o600)
            self.assertEqual(ev.read_api_key(str(plain)), "sk-plain")
            env = os.environ.pop("OPENAI_API_KEY", None)
            try:
                with self.assertRaises(ev.EvalError):
                    ev.read_api_key(str(Path(raw) / "missing"))
                os.environ["OPENAI_API_KEY"] = "sk-env"
                self.assertEqual(ev.read_api_key(str(Path(raw) / "missing")), "sk-env")
            finally:
                os.environ.pop("OPENAI_API_KEY", None)
                if env is not None:
                    os.environ["OPENAI_API_KEY"] = env

    def test_default_transport_is_responses(self):
        import inspect  # noqa: PLC0415
        source = inspect.getsource(ev.main)
        self.assertIn('run.add_argument("--transport", choices=("codex", "responses"), default="responses"', source)

    def test_codex_run_refuses_an_approval_written_for_the_responses_api(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "cases.json").write_text(json.dumps({"cases": [{"case_id": "C1"}]}))
            approval = {"schema": ev.APPROVAL_SCHEMA, "model": ev.MODEL, "reasoning_effort": ev.EFFORT,
                        "approved_by": "t", "approved_at": "2026-11-27", "cases": ["C1"], "max_calls": 5,
                        "transport": "openai_responses"}
            (root / "a.json").write_text(json.dumps(approval))
            argv = ["run", "--eval-dir", str(root), "--label", "x", "--mode", "live", "--approval", str(root / "a.json"),
                    "--transport", "codex"]
            code, message = ApprovalGateTest._main(argv)
            self.assertEqual(code, 2)
            self.assertIn("does not cover the codex transport", message)


class ProductParityTest(unittest.TestCase):
    """The evaluation body and the product live engine body are the same bytes (ADR-0081)."""

    @classmethod
    def setUpClass(cls):
        ev._load_engine(ev.DEFAULT_ENGINE_SRC)
        from bid_deep_engine.live import framed, responses  # noqa: PLC0415
        cls.framed, cls.responses = framed, responses

    def test_request_body_matches_the_engine_builder_for_every_purpose(self):
        parts = ("SYSTEM", "\n\n# 문서\n\nDOC", "\n\n# 지시\n\nDO IT")
        for purpose in ("extract", "units", "match", "synth"):
            self.assertEqual(ev.responses_request(parts, purpose=purpose),
                             self.responses.request_body(parts, purpose=purpose), purpose)
        self.assertEqual(ev.RESPONSES_URL, self.responses.RESPONSES_URL)
        self.assertEqual(ev.LUNA_USD_PER_MTOK, self.responses.USD_PER_MTOK)

    def test_prompt_parts_match_the_engine_framing(self):
        from pydantic import BaseModel  # noqa: PLC0415

        class Out(BaseModel):
            value: int

        captured = {}

        class Capture(ev.RecordingTransport):
            def _complete(self, prompt):
                captured["parts"] = self.current_parts
                return '{"value": 1}'

        _runner, llm, _pipeline, token_usage = ev._load_engine(ev.DEFAULT_ENGINE_SRC)
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw) / "r1"
            run_dir.mkdir()
            Capture(llm, token_usage, run_dir).parse(Out, purpose="match", system="S", document="D", instruction="I", slug="C")
        self.assertEqual(captured["parts"], self.framed.parts(Out, system="S", document="D", instruction="I"))


if __name__ == "__main__":
    unittest.main()
