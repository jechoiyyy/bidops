"""Focused tests for the Phase 1 BM25 ranker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rank_order_plans_bm25.py"
SPEC = importlib.util.spec_from_file_location("bidops_rank_order_plans_bm25", SCRIPT)
assert SPEC and SPEC.loader
RANKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RANKER)

REPO_ROOT = SCRIPT.parents[3]
POLICY_TEMPLATE_PATH = REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-policy.v1.json"
BINDING_TEMPLATE_PATH = REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json"


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(RANKER.PHASE0.canonical_json_bytes(value))


def synthetic_references(root: Path) -> dict[str, Any]:
    profile = {
        "schema_version": "bidops.order-plan-capabilities.v1",
        "approval_status": "approved",
        "profile_version": "synthetic-capabilities-v1",
        "summary_sha256": "",
        "approved_by": "synthetic-test",
        "approved_at": "2026-09-01T00:00:00+09:00",
        "capabilities": [{"id": "cap-ai", "summary": "AI 데이터 플랫폼"}],
    }
    profile["summary_sha256"] = RANKER.PHASE0.digest_json({
        "profile_version": profile["profile_version"],
        "capabilities": profile["capabilities"],
    })
    profile_path = root / "synthetic-capabilities.json"
    write_json(profile_path, profile)
    profile_sha256 = RANKER.PHASE0.sha256_file(profile_path)

    policy = json.loads(POLICY_TEMPLATE_PATH.read_text(encoding="utf-8"))
    policy["stage2"]["company_profile"].update({
        "version": profile["profile_version"],
        "sha256": profile_sha256,
    })
    policy["bindings"]["company_profile_sha256"] = profile_sha256
    policy_path = root / "synthetic-policy.json"
    write_json(policy_path, policy)
    policy_sha256 = RANKER.PHASE0.sha256_file(policy_path)

    binding = json.loads(BINDING_TEMPLATE_PATH.read_text(encoding="utf-8"))
    binding["policy"].update({"path": policy_path.name, "sha256": policy_sha256})
    binding["stage2_binding"].update({
        "company_profile_version": profile["profile_version"],
        "company_profile_sha256": profile_sha256,
    })
    binding["review_inputs"].update({
        "active_company_capabilities_path": profile_path.name,
        "active_company_capabilities_sha256": profile_sha256,
    })
    binding_path = root / "synthetic-phase0-binding.json"
    write_json(binding_path, binding)
    return {
        "profile": profile_path,
        "policy": policy_path,
        "binding": binding_path,
        "policy_document": policy,
        "binding_document": binding,
    }


def input_document(items: list[dict[str, str]], references: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "bidops.order-plan-screening-input.v1",
        "producer": "order-plan-screening-orchestrator",
        "consumer": "order-plan-screening-worker",
        "execution_id": "exec-phase1-fixture",
        "source_run_id": "source-phase1-fixture",
        "source_artifact": {
            "name": "collected-order-plans.json",
            "schema_version": "bidops.collected-order-plans.v1",
            "sha256": "a" * 64,
        },
        "population_count": len(items),
        "population_sha256": RANKER.PHASE0.digest_json(items),
        "policy": {"version": references["policy_document"]["policy_version"], "sha256": RANKER.PHASE0.sha256_file(references["policy"])},
        "stage1_binding": {"version": "bm25-fixture-v1", "sha256": references["binding_document"]["stage1_binding"]["sha256"]},
        "stage2_binding": {"version": "qwen-fixture-v1", "sha256": RANKER.PHASE0.sha256_file(references["binding"])},
        "items": items,
        "status": "frozen",
        "created_at": "2026-09-01T00:00:00+09:00",
    }


def rank(input_path: Path, output_path: Path, references: dict[str, Any]) -> dict[str, Any]:
    return RANKER.rank_order_plans(
        input_path,
        references["profile"],
        output_path,
        policy_path=references["policy"],
        binding_path=references["binding"],
    )


class RankOrderPlansBm25Tests(unittest.TestCase):
    def test_nfkc_casefold_whitespace_and_character_boundaries(self) -> None:
        self.assertEqual("ai data platform", RANKER.normalize_title(" ＡＩ\t  Data\nPlatform "))
        grams = RANKER.character_ngrams("ＡＩ")
        self.assertIn("ai", grams)
        self.assertNotIn("a", grams)
        self.assertTrue(all(2 <= len(term) <= 5 for term in grams))
        self.assertEqual([], list(RANKER.character_ngrams("a")))

    def test_binary_capability_queries_take_the_maximum(self) -> None:
        items = [
            {"plan_id": "p-1", "title": "AI 데이터 플랫폼 운영"},
            {"plan_id": "p-2", "title": "건물 시설 관리"},
        ]
        capabilities = [
            {"id": "cap-z", "summary": "AI 데이터 플랫폼"},
            {"id": "cap-a", "summary": "시설 관리"},
        ]
        scores = RANKER.bm25_scores(items, capabilities)
        self.assertEqual({"p-1", "p-2"}, {row["plan_id"] for row in scores})
        by_id = {row["plan_id"]: row for row in scores}
        self.assertEqual("cap-z", by_id["p-1"]["nearest_capability"])
        self.assertEqual("cap-a", by_id["p-2"]["nearest_capability"])
        self.assertGreater(by_id["p-1"]["score"], 0.0)
        self.assertGreater(by_id["p-2"]["score"], 0.0)

    def test_tie_break_and_exact_625_to_300_plus_325(self) -> None:
        items = [
            {"plan_id": f"plan-{index:04d}", "title": "AI 데이터 플랫폼"}
            for index in range(625)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = synthetic_references(root)
            input_path = root / "input.json"
            output_path = root / "ranking.json"
            write_json(input_path, input_document(items, references))
            artifact = rank(input_path, output_path, references)
            self.assertEqual(625, artifact["population_count"])
            self.assertEqual(300, artifact["selected_count"])
            self.assertEqual(325, artifact["filtered_out_count"])
            self.assertEqual(625, len(artifact["items"]))
            self.assertEqual("selected", artifact["items"][299]["stage1_status"])
            self.assertEqual("filtered_out", artifact["items"][300]["stage1_status"])
            self.assertEqual(list(range(1, 626)), [row["rank"] for row in artifact["items"]])

            tie_items = [
                {"plan_id": "plan-2", "title": "같은 제목"},
                {"plan_id": "plan-10", "title": "같은 제목"},
            ]
            tie_input = root / "tie-input.json"
            tie_output = root / "tie-ranking.json"
            write_json(tie_input, input_document(tie_items, references))
            rank(tie_input, tie_output, references)
            tie = json.loads(tie_output.read_text(encoding="utf-8"))
            self.assertEqual(["plan-10", "plan-2"], [row["plan_id"] for row in tie["items"]])

    def test_at_or_below_top_k_selects_all(self) -> None:
        items = [{"plan_id": f"p-{index:03d}", "title": "AI"} for index in range(300)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = synthetic_references(root)
            input_path = root / "input.json"
            output_path = root / "ranking.json"
            write_json(input_path, input_document(items, references))
            artifact = rank(input_path, output_path, references)
            self.assertEqual(300, artifact["selected_count"])
            self.assertEqual(0, artifact["filtered_out_count"])
            self.assertTrue(all(row["stage1_status"] == "selected" for row in artifact["items"]))

    def test_same_input_is_byte_stable_and_output_is_not_overwritten(self) -> None:
        items = [{"plan_id": "p-1", "title": " ＡＩ   데이터 "}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = synthetic_references(root)
            input_path = root / "input.json"
            first_path = root / "first.json"
            second_path = root / "second.json"
            write_json(input_path, input_document(items, references))
            rank(input_path, first_path, references)
            rank(input_path, second_path, references)
            first = first_path.read_bytes()
            second = second_path.read_bytes()
            self.assertEqual(first, second)
            self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
            with self.assertRaises(RANKER.ContractError) as raised:
                rank(input_path, first_path, references)
            self.assertEqual("output_exists", raised.exception.code)

    def test_frozen_input_and_capability_contracts_fail_closed(self) -> None:
        items = [{"plan_id": "p-1", "title": "AI"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = synthetic_references(root)
            input_path = root / "input.json"
            output_path = root / "ranking.json"
            document = input_document(items, references)
            document["population_sha256"] = "e" * 64
            write_json(input_path, document)
            with self.assertRaises(RANKER.ContractError) as raised:
                rank(input_path, output_path, references)
            self.assertEqual("hash_mismatch", raised.exception.code)

    def test_requires_approved_references_and_profile_file_digest(self) -> None:
        items = [{"plan_id": "p-1", "title": "AI"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = synthetic_references(root)
            input_path = root / "input.json"
            output_path = root / "ranking.json"
            arbitrary_capabilities = root / "arbitrary-capabilities.json"
            write_json(input_path, input_document(items, references))
            write_json(arbitrary_capabilities, [{"id": "cap", "summary": "AI"}])
            with self.assertRaises(RANKER.ContractError) as raised:
                RANKER.rank_order_plans(input_path, references["profile"], output_path)
            self.assertEqual("missing_reference", raised.exception.code)
            with self.assertRaises(RANKER.ContractError) as raised:
                RANKER.rank_order_plans(
                    input_path,
                    arbitrary_capabilities,
                    output_path,
                    policy_path=references["policy"],
                    binding_path=references["binding"],
                )
            self.assertEqual("hash_mismatch", raised.exception.code)

    def test_rejects_policy_stage1_config_binding_mismatches(self) -> None:
        for field, value in (("sha256", "f" * 64), ("method_version", "other-bm25")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                references = synthetic_references(root)
                policy = json.loads(references["policy"].read_text(encoding="utf-8"))
                policy["stage1"]["config"][field] = value
                write_json(references["policy"], policy)
                binding = json.loads(references["binding"].read_text(encoding="utf-8"))
                binding["policy"]["sha256"] = RANKER.PHASE0.sha256_file(references["policy"])
                write_json(references["binding"], binding)
                references.update(policy_document=policy, binding_document=binding)
                input_path = root / "input.json"
                write_json(input_path, input_document([{"plan_id": "p-1", "title": "AI"}], references))
                with self.assertRaises(RANKER.ContractError) as raised:
                    rank(input_path, root / "ranking.json", references)
                self.assertEqual("binding_mismatch", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
