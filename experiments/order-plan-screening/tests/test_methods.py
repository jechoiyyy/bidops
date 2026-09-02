from __future__ import annotations

import json
import unittest

from helpers import make_population

from common import METHOD_RESULT_SCHEMA, ExperimentError, validate_method_result  # noqa: E402
from methods import (  # noqa: E402
    AdapterFailure,
    AdapterResult,
    FakeAdapter,
    KeywordAdapter,
    LunaAdapter,
    OllamaDenseAdapter,
    QwenAdapter,
    TfidfAdapter,
    plan_text,
    run_fixed_model_batches,
    validate_local_base_url,
    validate_model_batch_output,
    SafeJsonHttpClient,
)
from run_methods import (  # noqa: E402
    build_result,
    calculate_luna_cost,
    execute_adapter,
)


CAPABILITIES = {
    "profile_version": "profile-v1",
    "capabilities": [{"id": "cap-1", "summary": "최소 요약"}],
}


class RecordingClient:
    def __init__(self, response):  # type: ignore[no-untyped-def]
        self.response = response
        self.calls = []

    def post(self, url, body, headers):  # type: ignore[no-untyped-def]
        self.calls.append((url, body, headers))
        return self.response, 12


class DenseRecordingClient:
    def __init__(self):
        self.calls = []

    def get(self, url, headers):  # type: ignore[no-untyped-def]
        self.calls.append(("GET", url, None))
        return {
            "models": [
                {"name": "bge-m3:latest", "digest": "d" * 64}
            ]
        }, 2

    def post(self, url, body, headers):  # type: ignore[no-untyped-def]
        self.calls.append(("POST", url, body))
        inputs = body["input"]
        if inputs == ["최소 요약"]:
            return {"embeddings": [[1.0, 0.0]]}, 3
        return {"embeddings": [[1.0, 0.0], [0.0, 1.0]]}, 8


class MethodExecutionTests(unittest.TestCase):
    def test_model_batch_output_requires_exact_item_coverage(self) -> None:
        results = validate_model_batch_output(
            {
                "items": [
                    {
                        "item_id": 1,
                        "relevance": "uncertain",
                        "score": 0.4,
                        "reason": "제목만으로 판단이 어려움",
                    },
                    {
                        "item_id": 0,
                        "relevance": "relevant",
                        "score": 0.8,
                        "reason": "제목이 역량과 부합",
                    },
                ]
            },
            10,
            2,
            {"input_tokens": 5, "output_tokens": 3},
        )
        self.assertEqual([result.relevance for result in results], ["relevant", "uncertain"])
        self.assertEqual([result.evidence_fields for result in results], [["title"], ["title"]])
        self.assertEqual(sum(result.latency_ms for result in results), 10)
        self.assertEqual(sum(result.input_tokens or 0 for result in results), 5)
        self.assertEqual(sum(result.output_tokens or 0 for result in results), 3)
        with self.assertRaises(AdapterFailure):
            validate_model_batch_output(
                {
                    "items": [
                        {
                            "item_id": 0,
                            "relevance": "relevant",
                            "score": 0.8,
                            "reason": "첫 응답",
                        },
                        {
                            "item_id": 0,
                            "relevance": "not_relevant",
                            "score": 0.1,
                            "reason": "중복 응답",
                        },
                    ]
                },
                10,
                2,
            )

    def test_fixed_batch_failure_is_isolated_without_retry(self) -> None:
        plans = make_population(5)["items"]
        calls: list[list[str]] = []

        def score_batch(batch):  # type: ignore[no-untyped-def]
            calls.append([plan["plan_id"] for plan in batch])
            if batch[0]["plan_id"] == "P0002":
                raise AdapterFailure("malformed_response", 8)
            return [
                AdapterResult(
                    score=0.5,
                    reason="batch fixture",
                    latency_ms=1,
                    relevance="uncertain",
                    evidence_fields=["title"],
                )
                for _plan in batch
            ]

        outcomes = run_fixed_model_batches(plans, 2, score_batch)
        self.assertEqual(calls, [["P0000", "P0001"], ["P0002", "P0003"], ["P0004"]])
        self.assertIsInstance(outcomes[0], AdapterResult)
        self.assertIsInstance(outcomes[1], AdapterResult)
        self.assertIsInstance(outcomes[2], AdapterFailure)
        self.assertIsInstance(outcomes[3], AdapterFailure)
        self.assertIsInstance(outcomes[4], AdapterResult)
        self.assertEqual(sum(outcome.latency_ms or 0 for outcome in outcomes[2:4]), 8)

    def test_qwen_and_luna_send_the_same_minimal_batch_projection(self) -> None:
        plans = make_population(2)["items"]
        model_output = {
            "items": [
                {
                    "item_id": item_id,
                    "relevance": "uncertain",
                    "score": 0.5,
                    "reason": "제목 기준 fixture",
                }
                for item_id in range(2)
            ]
        }

        qwen = QwenAdapter.__new__(QwenAdapter)
        qwen.api_style = "ollama_native"
        qwen.url = "http://127.0.0.1:11434/api/chat"
        qwen.model_name = "qwen-fixed"
        qwen.prompt = "batch prompt"
        qwen.think = "high"
        qwen.max_output_tokens = 4096
        qwen.client = RecordingClient(
            {
                "done": True,
                "message": {"content": json.dumps(model_output, ensure_ascii=False)},
                "prompt_eval_count": 10,
                "eval_count": 4,
            }
        )
        qwen_results = qwen._score_batch(plans, CAPABILITIES)

        luna = LunaAdapter.__new__(LunaAdapter)
        luna.key = "fixture-key"
        luna.model_name = "gpt-fixed"
        luna.reasoning_effort = "xhigh"
        luna.prompt = "batch prompt"
        luna.max_output_tokens = 8192
        luna.client = RecordingClient(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(model_output, ensure_ascii=False),
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }
        )
        luna_results = luna._score_batch(plans, CAPABILITIES)

        qwen_input = json.loads(qwen.client.calls[0][1]["messages"][1]["content"])
        luna_input = json.loads(luna.client.calls[0][1]["input"])
        self.assertEqual(qwen_input, luna_input)
        self.assertEqual(
            qwen_input["items"],
            [
                {"item_id": 0, "title": "사업 0"},
                {"item_id": 1, "title": "사업 1"},
            ],
        )
        serialized = json.dumps(qwen_input, ensure_ascii=False)
        self.assertNotIn("plan_id", serialized)
        self.assertNotIn("agency_name", serialized)
        self.assertEqual([result.evidence_fields for result in qwen_results], [["title"]] * 2)
        self.assertEqual([result.evidence_fields for result in luna_results], [["title"]] * 2)

    def test_vllm_qwen_rejects_unexpected_served_model(self) -> None:
        qwen = QwenAdapter.__new__(QwenAdapter)
        qwen.api_style = "openai_compatible"
        qwen.url = "http://192.168.0.139:58765/v1/chat/completions"
        qwen.model_name = "qwen3.8:27b"
        qwen.prompt = "batch prompt"
        qwen.max_output_tokens = 8192
        qwen.chat_template_kwargs = {"enable_thinking": False}
        qwen.client = RecordingClient(
            {
                "model": "unexpected-model",
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            }
        )
        with self.assertRaisesRegex(AdapterFailure, "served_model_mismatch"):
            qwen._score_batch(make_population(1)["items"], CAPABILITIES)

    def test_vllm_qwen_sends_explicit_nonthinking_option(self) -> None:
        output = {
            "items": [
                {
                    "item_id": 0,
                    "relevance": "relevant",
                    "score": 0.9,
                    "reason": "fixture",
                }
            ]
        }
        qwen = QwenAdapter.__new__(QwenAdapter)
        qwen.api_style = "openai_compatible"
        qwen.url = "http://192.168.0.139:58765/v1/chat/completions"
        qwen.model_name = "qwen3.8-27B"
        qwen.prompt = "batch prompt"
        qwen.max_output_tokens = 8192
        qwen.chat_template_kwargs = {"enable_thinking": False}
        qwen.client = RecordingClient(
            {
                "model": "qwen3.8-27B",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(output)},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )
        qwen._score_batch(make_population(1)["items"], CAPABILITIES)
        self.assertEqual(
            {"enable_thinking": False},
            qwen.client.calls[0][1]["chat_template_kwargs"],
        )

    def test_keyword_and_bge_plan_side_are_title_only(self) -> None:
        config = {
            "positive_rules": [
                {"id": "ai", "fields": ["title"], "terms": ["AI"], "weight": 1}
            ],
            "negative_rules": [],
        }
        KeywordAdapter(config)
        forbidden = {
            **config,
            "positive_rules": [
                {"id": "agency", "fields": ["agency_name"], "terms": ["기관"], "weight": 1}
            ],
        }
        with self.assertRaises(ExperimentError):
            KeywordAdapter(forbidden)
        self.assertEqual(plan_text({"title": "AI 구축", "agency_name": "노이즈"}), "AI 구축")

    def test_tfidf_is_deterministic_and_uses_title_only(self) -> None:
        config = {
            "analyzer": "char",
            "ngram_min": 2,
            "ngram_max": 4,
            "tf": "sublinear",
            "idf": "smooth",
            "normalization": "l2",
            "capability_aggregation": "max_cosine",
        }
        adapter = TfidfAdapter(config)
        plans = [
            {"plan_id": "P1", "title": "데이터 분석 시스템", "agency_name": "노이즈 A"},
            {"plan_id": "P2", "title": "청사 조경 관리", "agency_name": "데이터 분석"},
        ]
        capabilities = {
            "capabilities": [{"id": "cap-data", "summary": "데이터 분석과 AI 시스템 구축"}]
        }
        first = adapter.score_all(plans, capabilities)
        second = adapter.score_all(plans, capabilities)
        self.assertEqual([row.score for row in first], [row.score for row in second])
        self.assertGreater(first[0].score, first[1].score)
        self.assertEqual(first[0].reason, "nearest_capability:cap-data")

    def test_ollama_dense_sends_only_capability_summaries_and_titles(self) -> None:
        adapter = OllamaDenseAdapter.__new__(OllamaDenseAdapter)
        adapter.url = "http://127.0.0.1:11434/api/embed"
        adapter.tags_url = "http://127.0.0.1:11434/api/tags"
        adapter.model_name = "bge-m3:latest"
        adapter.model_revision = "d" * 64
        adapter.batch_size = 2
        adapter.client = DenseRecordingClient()
        adapter._revision_verified = False
        plans = [
            {"plan_id": "P1", "title": "데이터 분석", "agency_name": "금지 기관"},
            {"plan_id": "P2", "title": "조경 관리", "budget_amount": 100},
        ]
        outcomes = adapter.score_many(plans, CAPABILITIES)
        self.assertTrue(all(isinstance(row, AdapterResult) for row in outcomes))
        self.assertEqual([round(row.score, 4) for row in outcomes], [1.0, 0.0])
        post_bodies = [call[2] for call in adapter.client.calls if call[0] == "POST"]
        self.assertEqual(post_bodies[0]["input"], ["최소 요약"])
        self.assertEqual(post_bodies[1]["input"], ["데이터 분석", "조경 관리"])
        serialized = json.dumps(post_bodies, ensure_ascii=False)
        self.assertNotIn("plan_id", serialized)
        self.assertNotIn("agency_name", serialized)
        self.assertNotIn("profile_version", serialized)

    def test_ties_and_top_50_are_deterministic(self) -> None:
        population = make_population(60)
        adapter = FakeAdapter(scores={item["plan_id"]: 0.5 for item in population["items"]})
        rows = execute_adapter(adapter, population["items"], CAPABILITIES, 50)
        selected = [row["plan_id"] for row in rows if row["selected"]]
        self.assertEqual(selected, [f"P{index:04d}" for index in range(50)])
        result = {
            "schema_version": METHOD_RESULT_SCHEMA,
            "run_id": population["run_id"],
            "created_at": "2026-08-28T12:00:00+09:00",
            "input_sha256": population["population_sha256"],
            "method": "qwen",
            "method_version": "fake-v1",
            "top_k": 50,
            "config_sha256": "a" * 64,
            "model": {"name": "fake", "revision": "a" * 64},
            "prompt": {"id": "fake-v1", "sha256": "b" * 64},
            "batching": {"mode": "fixed", "batch_size": 25, "batch_count": 3},
            "external_approval": None,
            "status": "success",
            "metrics": {
                "population_count": 60,
                "success_count": 60,
                "failure_count": 0,
                "selected_count": 50,
                "elapsed_ms": 75,
            },
            "items": rows,
        }
        for row in result["items"]:
            row["relevance"] = "relevant"
            row["evidence_fields"] = ["title"]
        validate_method_result(result, population, "qwen")

    def test_timeout_and_malformed_response_stay_failed_without_fallback(self) -> None:
        population = make_population(3)
        adapter = FakeAdapter(
            failures={"P0000": "timeout"},
            malformed_ids={"P0001"},
            scores={"P0002": 0.8},
        )
        rows = execute_adapter(adapter, population["items"], CAPABILITIES, 50)
        by_id = {row["plan_id"]: row for row in rows}
        self.assertEqual(by_id["P0000"]["error_code"], "timeout")
        self.assertEqual(by_id["P0001"]["error_code"], "malformed_response")
        self.assertIsNone(by_id["P0000"]["score"])
        self.assertFalse(by_id["P0000"]["selected"])
        self.assertEqual(adapter.calls, ["P0000", "P0001", "P0002"])

    def test_local_endpoint_is_fail_closed(self) -> None:
        self.assertEqual(
            validate_local_base_url("http://127.0.0.1:11434/v1", ["127.0.0.1"]),
            "http://127.0.0.1:11434/v1",
        )
        for value in (
            "https://example.com/v1",
            "http://127.0.0.1:11434/api",
            "http://127.0.0.1:11434/v1?token=secret",
        ):
            with self.assertRaises(ExperimentError):
                validate_local_base_url(value, ["127.0.0.1"])

    def test_http_client_can_install_an_explicit_interface_handler(self) -> None:
        client = SafeJsonHttpClient(5, bind_interface="eth1")
        self.assertTrue(
            any(type(handler).__name__ == "BoundHTTPHandler" for handler in client.opener.handlers)
        )
        self.assertEqual(
            validate_local_base_url(
                "http://127.0.0.1:11434", ["127.0.0.1"], "ollama_native"
            ),
            "http://127.0.0.1:11434",
        )
        with self.assertRaises(ExperimentError):
            validate_local_base_url(
                "http://127.0.0.1:11434/v1", ["127.0.0.1"], "ollama_native"
            )

    def test_cost_keeps_measured_zero_distinct_from_null(self) -> None:
        pricing = {"input": 0.2, "cached_input": 0.02, "output": 1.2}
        measured_zero = [
            {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        ]
        unknown = [
            {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None}
        ]
        self.assertEqual(calculate_luna_cost(measured_zero, pricing), 0.0)
        self.assertIsNone(calculate_luna_cost(unknown, pricing))


if __name__ == "__main__":
    unittest.main()
