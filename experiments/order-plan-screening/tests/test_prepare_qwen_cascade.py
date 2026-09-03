import importlib.util
from pathlib import Path
import sys
import unittest

from helpers import make_population


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "prepare_qwen_cascade", SCRIPTS / "prepare_qwen_cascade.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeBM25:
    def __init__(self, _config):
        pass

    def score_all(self, plans, _capabilities):
        return [type("R", (), {"score": float(plan["plan_id"][1:])})() for plan in plans]


class PrepareQwenCascadeTests(unittest.TestCase):
    def test_bm25_selection_is_top_k_and_deterministic(self):
        population = make_population(5)
        original = MODULE.BM25Adapter
        MODULE.BM25Adapter = FakeBM25
        try:
            selected, scores = MODULE.select(population, "bm25", 2, {}, {}, None)
        finally:
            MODULE.BM25Adapter = original
        self.assertEqual(["P0004", "P0003"], selected)
        self.assertEqual(5, len(scores))

    def test_rrf_uses_both_rankings(self):
        scores = MODULE._rrf([["A", "B"], ["B", "A"]])
        self.assertEqual(scores["A"], scores["B"])
        self.assertEqual(["A", "B"], MODULE._ranked(scores))


if __name__ == "__main__":
    unittest.main()
