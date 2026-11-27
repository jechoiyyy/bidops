#!/usr/bin/env python3
"""Token usage and API-equivalent cost recording in scripts/engine-eval.py.

The fake ``codex`` below emits the event shape seen in real ``codex exec --json`` runs
(2026-11-26 measurement, ``.sdlc/local-runtime/20261126-luna-token-measure``):
``thread.started`` -> ``turn.started`` -> ``item.completed`` (agent_message) ->
``turn.completed`` with ``usage``. It writes the last message to the ``-o`` path like the
real CLI. No network, no model, no database; the engine package is imported from this checkout.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("ENGINE_EVAL_SCRIPT", ROOT / "scripts/engine-eval.py"))


def _load_module():
    spec = importlib.util.spec_from_file_location("engine_eval_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = _load_module()

# One real call (N4174 extract, 2026-11-26): input includes the cached part.
REAL_USAGE = {"input_tokens": 72725, "cached_input_tokens": 19712, "cache_write_input_tokens": 0,
              "output_tokens": 4236, "reasoning_output_tokens": 631}


def _stream(*usages, answer='{"value": 1}') -> bytes:
    lines = [{"type": "thread.started", "thread_id": "01a21633-e5c2-7292-8be1-aee9ffbd8b4a"}]
    for usage in usages:
        lines += [
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": answer}},
            {"type": "turn.completed", "usage": usage},
        ]
    return "\n".join(json.dumps(x) for x in lines).encode() + b"\n"


class CodexUsageTest(unittest.TestCase):
    def test_sums_turn_completed_and_counts_turns(self):
        usage = ev.codex_usage(_stream(REAL_USAGE))
        self.assertEqual(usage["input_tokens"], 72725)
        self.assertEqual(usage["cached_input_tokens"], 19712)
        self.assertEqual(usage["output_tokens"], 4236)
        self.assertEqual(usage["reasoning_output_tokens"], 631)
        self.assertEqual(usage["turns"], 1)
        two = ev.codex_usage(_stream(REAL_USAGE, REAL_USAGE))
        self.assertEqual((two["input_tokens"], two["turns"]), (145450, 2))

    def test_no_completed_turn_is_unmeasured_not_zero(self):
        self.assertIsNone(ev.codex_usage(b""))
        self.assertIsNone(ev.codex_usage(b'{"type":"turn.started"}\nnot json\n'))

    def test_malformed_values_do_not_count(self):
        bad = dict(REAL_USAGE, output_tokens=-5, reasoning_output_tokens="7")
        usage = ev.codex_usage(_stream(bad))
        self.assertEqual((usage["output_tokens"], usage["reasoning_output_tokens"]), (0, 0))


class ApiEquivalentTest(unittest.TestCase):
    def test_standard_rate(self):
        priced = ev.luna_api_equivalent(dict(REAL_USAGE, turns=1))
        self.assertEqual(priced["fresh_input_tokens"], 72725 - 19712)
        self.assertEqual(priced["cache_read_input_tokens"], 19712)
        self.assertFalse(priced["long_context"])
        expected = (53013 * 0.10 + 19712 * 0.01 + 4236 * 0.50) / 1_000_000
        self.assertAlmostEqual(priced["usd"], expected, places=12)

    def test_long_context_applies_to_whole_request(self):
        # N3235 match call: 408,957 input (19,712 cached) is above the 272K threshold.
        usage = {"input_tokens": 408957, "cached_input_tokens": 19712, "cache_write_input_tokens": 0,
                 "output_tokens": 20000, "reasoning_output_tokens": 0, "turns": 1}
        priced = ev.luna_api_equivalent(usage)
        self.assertTrue(priced["long_context"])
        expected = ((408957 - 19712) * 0.10 * 2 + 19712 * 0.01 * 2 + 20000 * 0.50 * 1.5) / 1_000_000
        self.assertAlmostEqual(priced["usd"], expected, places=12)
        at_threshold = dict(usage, input_tokens=272_000, cached_input_tokens=0)
        self.assertFalse(ev.luna_api_equivalent(at_threshold)["long_context"])

    def test_cache_write_is_part_of_input(self):
        usage = dict(REAL_USAGE, cache_write_input_tokens=1000, turns=1)
        priced = ev.luna_api_equivalent(usage)
        self.assertEqual(priced["fresh_input_tokens"], 72725 - 19712 - 1000)
        expected = (52013 * 0.10 + 19712 * 0.01 + 1000 * 0.125 + 4236 * 0.50) / 1_000_000
        self.assertAlmostEqual(priced["usd"], expected, places=12)


FAKE_CODEX = r'''#!{python}
import json, sys
argv = sys.argv[1:]
out = argv[argv.index("-o") + 1]
sys.stdin.read()
answer = {answer!r}
open(out, "w").write(answer)
if "--json" in argv:
    sys.stdout.write({stream!r})
'''


class CodexTransportTest(unittest.TestCase):
    """CodexLunaTransport end to end with a fake codex binary and the real engine types."""

    @classmethod
    def setUpClass(cls):
        cls.engine = ev._load_engine(ev.DEFAULT_ENGINE_SRC)

    def _transport(self, tmp: Path, approval_cap=5):
        runner, llm, _pipeline, token_usage = self.engine
        answer = '{"value": 1}'
        fake = tmp / "codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable, answer=answer,
                                          stream=_stream(REAL_USAGE, answer=answer).decode()))
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        root = tmp / "eval"
        run_dir = root / "runs" / "t" / "C1" / "r1"
        run_dir.mkdir(parents=True)
        budget = ev._CallBudget(root, {"max_calls": approval_cap})
        return ev.CodexLunaTransport(llm, token_usage, run_dir, codex_bin=str(fake), budget=budget), run_dir

    def test_records_usage_in_parse_result_record_and_ledger(self):
        from pydantic import BaseModel

        class Out(BaseModel):
            value: int

        with tempfile.TemporaryDirectory() as raw:
            transport, run_dir = self._transport(Path(raw))
            result = transport.parse(Out, purpose="extract", system="s", document="d", instruction="i", slug="C1")
            self.assertEqual(result.parsed.value, 1)
            # Engine token fields: input is the uncached part, cache read is separate.
            self.assertEqual(result.usage.input_tokens, 72725 - 19712)
            self.assertEqual(result.usage.cache_read_input_tokens, 19712)
            self.assertEqual(result.usage.output_tokens, 4236)
            expected = (53013 * 0.10 + 19712 * 0.01 + 4236 * 0.50) / 1_000_000
            record = result.record
            self.assertEqual(record.cost_basis, "subscription")
            self.assertEqual(record.price_model, "gpt-6-luna")
            self.assertEqual(record.input_tokens, 53013)
            self.assertAlmostEqual(record.cost_usd, expected, places=12)
            ledger = json.loads((run_dir / "calls" / "01-extract.call.json").read_text())
            self.assertEqual(ledger["usage"]["input_tokens"], 72725)
            self.assertEqual(ledger["usage"]["reasoning_output_tokens"], 631)
            self.assertAlmostEqual(ledger["api_equivalent_usd"], expected, places=12)
            self.assertEqual(ledger["price_source"], ev.LUNA_PRICE_SOURCE)
            trace = run_dir / "calls" / "01.trace.jsonl"
            self.assertTrue(trace.exists())
            self.assertEqual(stat.S_IMODE(trace.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
