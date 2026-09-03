import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("score_arms", SCRIPTS / "score_arms.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ScoreArmsReferenceTests(unittest.TestCase):
    def test_loads_effective_labels_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.tsv"
            path.write_text(
                "plan_id\teffective_relevance\teffective_priority\tlabel_source\n"
                "R1\t관련\t높음\tdraft\n"
                "R2\t비관련\t해당없음\thuman\n",
                encoding="utf-8",
            )
            gold = MODULE._load_gold(
                path, "effective_relevance", "effective_priority", "label_source"
            )
        self.assertEqual({"R1": "관련", "R2": "비관련"}, gold.relevance)
        self.assertEqual({"draft": 1, "human": 1}, gold.label_source_counts)

    def test_rejects_duplicate_plan_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.tsv"
            path.write_text(
                "plan_id\thuman_relevance\thuman_priority\n"
                "R1\t관련\t높음\nR1\t비관련\t해당없음\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "중복"):
                MODULE._load_gold(path)


if __name__ == "__main__":
    unittest.main()
