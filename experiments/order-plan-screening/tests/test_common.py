from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import SCRIPT_DIR, make_population, make_result, make_run

from common import (  # noqa: E402
    CAPABILITIES_SCHEMA,
    EXTERNAL_APPROVAL_SCHEMA,
    ExperimentError,
    capabilities_projection,
    digest_json,
    external_preview,
    load_json,
    model_batch_payload,
    title_plan_projection,
    validate_method_result,
    validate_external_approval,
    validate_population,
    validate_result_run_binding,
    write_json_new,
)


class CommonContractTests(unittest.TestCase):
    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(ExperimentError, "중복 JSON 키"):
                load_json(path)

    def test_write_json_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "artifact.json"
            write_json_new(path, {"value": 1})
            with self.assertRaises(ExperimentError) as caught:
                write_json_new(path, {"value": 2})
            self.assertEqual(caught.exception.code, "artifact_exists")
            self.assertEqual(load_json(path), {"value": 1})

    def test_approved_capability_hash_is_required(self) -> None:
        projection = {
            "profile_version": "profile-v1",
            "capabilities": [{"id": "cap-1", "summary": "승인된 최소 요약"}],
        }
        document = {
            "schema_version": CAPABILITIES_SCHEMA,
            "approval_status": "approved",
            "profile_version": "profile-v1",
            "summary_sha256": digest_json(projection),
            "approved_by": "검토자",
            "approved_at": "2026-08-28T10:00:00+09:00",
            "capabilities": projection["capabilities"],
        }
        self.assertEqual(capabilities_projection(document), projection)
        document["summary_sha256"] = "0" * 64
        with self.assertRaises(ExperimentError) as caught:
            capabilities_projection(document)
        self.assertEqual(caught.exception.code, "hash_mismatch")

    def test_model_projection_contains_only_title_and_batch_local_id(self) -> None:
        plan = {"plan_id": "P1", "title": "사업", "budget_amount": None, "private": "금지"}
        self.assertEqual(title_plan_projection(plan), {"title": "사업"})
        payload = model_batch_payload(
            [plan, {"plan_id": "P2", "title": "다른 사업"}],
            {"profile_version": "v1", "capabilities": []},
        )
        self.assertEqual(
            payload["items"],
            [{"item_id": 0, "title": "사업"}, {"item_id": 1, "title": "다른 사업"}],
        )
        self.assertNotIn("plan_id", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("private", json.dumps(payload, ensure_ascii=False))
        with self.assertRaises(ExperimentError):
            title_plan_projection({"plan_id": "P1", "title": None})

    def test_population_and_result_cover_every_id_once(self) -> None:
        population = validate_population(make_population(3))
        result = make_result(population, "keyword", {"P0000", "P0001"})
        validate_method_result(result, population, "keyword")
        result["items"].pop()
        with self.assertRaises(ExperimentError) as caught:
            validate_method_result(result, population, "keyword")
        self.assertEqual(caught.exception.code, "population_coverage_mismatch")

    def test_result_requires_every_successful_top_k_row(self) -> None:
        population = validate_population(make_population(4))
        result = make_result(population, "keyword", {"P0000", "P0001"})
        result["items"][1]["selected"] = False
        with self.assertRaises(ExperimentError) as caught:
            validate_method_result(result, population, "keyword")
        self.assertEqual(caught.exception.code, "invalid_selection")

    def test_external_approval_binds_prompt_and_preview_hash(self) -> None:
        population = validate_population(make_population(1))
        run = make_run(population)
        capabilities = {
            "profile_version": "profile-v1",
            "capabilities": [{"id": "cap-1", "summary": "승인된 최소 요약"}],
        }
        preview = external_preview(
            population,
            capabilities,
            ["title"],
            "gpt-5.6-luna-fixed",
            "a" * 64,
            25,
        )
        self.assertEqual(preview["payload_fields"], ["title"])
        self.assertEqual(preview["batch_size"], 25)
        self.assertEqual(preview["batch_count"], 1)
        approval = {
            "schema_version": EXTERNAL_APPROVAL_SCHEMA,
            "run_id": run["run_id"],
            **preview,
            "approved_by": "검토자",
            "approved_at": "2026-08-28T10:00:00+09:00",
        }
        validate_external_approval(approval, run, preview)
        approval["prompt_sha256"] = "b" * 64
        with self.assertRaises(ExperimentError) as caught:
            validate_external_approval(approval, run, preview)
        self.assertEqual(caught.exception.code, "approval_mismatch")

    def test_method_result_is_bound_to_run_config_and_model(self) -> None:
        population = validate_population(make_population(3))
        run = make_run(population)
        result = make_result(population, "keyword", {"P0000", "P0001"})
        validate_result_run_binding(result, run)
        result["config_sha256"] = "f" * 64
        with self.assertRaises(ExperimentError) as caught:
            validate_result_run_binding(result, run)
        self.assertEqual(caught.exception.code, "method_binding_mismatch")

    def test_dense_batch_binding_does_not_require_judgment_evidence(self) -> None:
        population = validate_population(make_population(3))
        run = make_run(population)
        result = make_result(population, "bge_m3_dense", {"P0000", "P0001"})
        validate_method_result(result, population, "bge_m3_dense")
        validate_result_run_binding(result, run)


if __name__ == "__main__":
    unittest.main()
