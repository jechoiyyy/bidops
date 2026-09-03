import importlib.util
from pathlib import Path
import sys
import unittest

from helpers import make_population


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "score_qwen_reference", SCRIPTS / "score_qwen_reference.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ScoreQwenReferenceTests(unittest.TestCase):
    def test_execution_metrics_preserve_time_and_token_measurements(self):
        result = {
            "batching": {"mode": "fixed", "batch_size": 25, "batch_count": 2},
            "metrics": {
                "success_count": 50,
                "elapsed_ms": 10000,
                "total_latency_ms": 9500,
                "average_latency_ms": 190,
                "input_tokens": 2000,
                "cached_input_tokens": 500,
                "output_tokens": 1000,
                "device": "vllm",
            },
        }
        metrics = MODULE._execution_metrics(result)
        self.assertEqual(3000, metrics["total_tokens"])
        self.assertEqual(5.0, metrics["records_per_second"])
        self.assertEqual(100.0, metrics["output_tokens_per_second"])

    def test_retained_metric_counts_uncertain_without_hiding_false_negative(self):
        population = make_population(3)
        run = {"run_id": population["run_id"]}
        result = {
            "status": "success",
            "model": {"name": "qwen", "revision": "a" * 64},
            "prompt": {"id": "p", "sha256": "b" * 64},
            "batching": {"mode": "fixed", "batch_size": 3, "batch_count": 1},
            "metrics": {
                "success_count": 3,
                "elapsed_ms": 100,
                "total_latency_ms": 90,
                "average_latency_ms": 30,
                "input_tokens": 30,
                "cached_input_tokens": 0,
                "output_tokens": 15,
                "device": "fixture",
            },
            "items": [
                {"plan_id": "P0000", "status": "success", "relevance": "relevant", "score": .9, "reason": "r"},
                {"plan_id": "P0001", "status": "success", "relevance": "uncertain", "score": .5, "reason": "u"},
                {"plan_id": "P0002", "status": "success", "relevance": "not_relevant", "score": .1, "reason": "n"},
            ],
        }
        reference = {
            "P0000": {"effective_relevance": "관련", "effective_priority": "높음", "label_source": "draft"},
            "P0001": {"effective_relevance": "관련", "effective_priority": "보통", "label_source": "draft"},
            "P0002": {"effective_relevance": "관련", "effective_priority": "낮음", "label_source": "draft"},
        }
        original = MODULE.sha256_file
        MODULE.sha256_file = lambda _path: "f" * 64
        try:
            scored = MODULE.build_scoring(
                run, population, result, reference, Path("reference.tsv"), Path("qwen.json")
            )
        finally:
            MODULE.sha256_file = original
        self.assertEqual(0.3333, scored["metrics"]["strict_relevant"]["recall"])
        self.assertEqual(0.6667, scored["metrics"]["review_retained_relevant_or_uncertain"]["recall"])
        self.assertEqual(1, len(scored["false_negatives"]))
        self.assertEqual(1, len(scored["uncertain_relevant"]))


if __name__ == "__main__":
    unittest.main()
