import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "score_lexical_arms", SCRIPTS / "score_lexical_arms.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ScoreLexicalArmsTests(unittest.TestCase):
    def test_detail_preserves_both_arm_ranks(self):
        plans = {"R1": {"title": "AI 시스템"}}
        gold = type("Gold", (), {"priority": {"R1": "높음"}})()
        ranks = {"bm25": {"R1": 10}, "tfidf": {"R1": 20}}
        row = MODULE._detail("R1", plans, gold, ranks)
        self.assertEqual(10, row["bm25_rank"])
        self.assertEqual(20, row["tfidf_rank"])


if __name__ == "__main__":
    unittest.main()
