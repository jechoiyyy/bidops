"""Focused tests for the Phase 1 full-population merge."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_order_plan_screening_results.py"
SPEC = importlib.util.spec_from_file_location("bidops_build_order_plan_screening_results", SCRIPT)
assert SPEC and SPEC.loader
MERGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MERGE)

REPO_ROOT = SCRIPT.parents[3]
POLICY_TEMPLATE_PATH = REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-policy.v1.json"
BINDING_TEMPLATE_PATH = REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json"


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(MERGE.PHASE0.canonical_json_bytes(value))


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
    profile["summary_sha256"] = MERGE.PHASE0.digest_json({
        "profile_version": profile["profile_version"],
        "capabilities": profile["capabilities"],
    })
    profile_path = root / "synthetic-capabilities.json"
    write_json(profile_path, profile)
    profile_sha256 = MERGE.PHASE0.sha256_file(profile_path)

    policy = json.loads(POLICY_TEMPLATE_PATH.read_text(encoding="utf-8"))
    policy["stage2"]["company_profile"].update({
        "version": profile["profile_version"],
        "sha256": profile_sha256,
    })
    policy["bindings"]["company_profile_sha256"] = profile_sha256
    policy_path = root / "synthetic-policy.json"
    write_json(policy_path, policy)
    policy_sha256 = MERGE.PHASE0.sha256_file(policy_path)

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
        "execution_id": "exec-merge-fixture",
        "source_run_id": "source-merge-fixture",
        "source_artifact": {
            "name": "collected-order-plans.json",
            "schema_version": "bidops.collected-order-plans.v1",
            "sha256": "a" * 64,
        },
        "population_count": len(items),
        "population_sha256": MERGE.PHASE0.digest_json(items),
        "policy": {"version": references["policy_document"]["policy_version"], "sha256": MERGE.PHASE0.sha256_file(references["policy"])},
        "stage1_binding": {"version": "bm25-fixture-v1", "sha256": references["binding_document"]["stage1_binding"]["sha256"]},
        "stage2_binding": {"version": "qwen-fixture-v1", "sha256": MERGE.PHASE0.sha256_file(references["binding"])},
        "items": items,
        "status": "frozen",
        "created_at": "2026-09-01T00:00:00+09:00",
    }


def merge(paths: dict[str, Path], output_path: Path) -> dict[str, Any]:
    return MERGE.build_order_plan_screening_results(
        paths["input"],
        paths["ranking"],
        paths["decisions"],
        paths["failures"],
        paths["telemetry"],
        output_path,
        policy_path=paths["policy"],
        binding_path=paths["binding"],
    )


def measurement() -> dict[str, Any]:
    return {
        "started_at": "2026-09-01T00:00:00+09:00",
        "finished_at": "2026-09-01T00:00:00.001000+09:00",
        "duration_ms": 1,
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "output_tokens": 10,
        "total_tokens": 20,
    }


def build_fixture(
    root: Path,
    count: int,
    failing_sequences: set[int] | None = None,
    *,
    failure_outcome: str = "failed",
    failure_type: str = "timeout",
) -> dict[str, Path]:
    failing_sequences = failing_sequences or set()
    root.mkdir(parents=True, exist_ok=True)
    references = synthetic_references(root)
    items = [{"plan_id": f"plan-{index:04d}", "title": "AI 데이터 플랫폼"} for index in range(count)]
    input_path = root / "input.json"
    ranking_path = root / "ranking.json"
    decisions_path = root / "decisions.json"
    failures_path = root / "failures.json"
    telemetry_path = root / "telemetry.json"
    write_json(input_path, input_document(items, references))
    MERGE.RANKER.rank_order_plans(
        input_path,
        references["profile"],
        ranking_path,
        policy_path=references["policy"],
        binding_path=references["binding"],
    )
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    candidate_ids = [item["plan_id"] for item in ranking["items"] if item["stage1_status"] == "selected"]
    batches = []
    decision_items = []
    failures = []
    telemetry_batches = []
    for sequence, start in enumerate(range(0, len(candidate_ids), 25), start=1):
        plan_ids = candidate_ids[start : start + 25]
        batch_id = f"batch-{sequence:03d}"
        is_failed = sequence in failing_sequences
        batch_status = "rejected" if is_failed and failure_outcome == "rejected" else "failed" if is_failed else "success"
        batches.append({
            "batch_id": batch_id,
            "sequence": sequence,
            "plan_ids": plan_ids,
            "attempt_count": 1,
            "status": batch_status,
        })
        if not is_failed:
            for offset, plan_id in enumerate(plan_ids):
                decision_items.append({
                    "plan_id": plan_id,
                    "batch_id": batch_id,
                    "attempt_no": 1,
                    "relevance": "uncertain" if offset % 3 == 0 else "relevant" if offset % 2 == 0 else "not_relevant",
                    "score": 0.5,
                    "reason": "fixture decision with a bounded explanation",
                })
        else:
            failures.append({
                "batch_id": batch_id,
                "sequence": sequence,
                "plan_ids": plan_ids,
                "attempt_count": 1,
                "max_attempts": 2,
                "failure_type": failure_type,
                "outcome": failure_outcome,
                "status": "human_review_required",
                "error_code": "fixture_timeout",
            })
        telemetry_status = "unknown" if is_failed and failure_outcome == "unknown" else batch_status
        telemetry_batches.append({
            "batch_id": batch_id,
            "sequence": sequence,
            "status": telemetry_status,
            "attempts": [{
                "attempt_no": 1,
                "status": batch_status,
                "started_at": "2026-09-01T00:00:00+09:00",
                "finished_at": "2026-09-01T00:00:00.001000+09:00",
                "measurement": measurement(),
            }],
        })
    decisions_status = "성공" if not failures else "부분 성공" if decision_items else "실패"
    decisions = {
        "schema_version": "bidops.order-plan-screening-decisions.v1",
        "producer": "order-plan-screening-qwen-worker",
        "consumer": "order-plan-screening-merge",
        "execution_id": "exec-merge-fixture",
        "source_run_id": "source-merge-fixture",
        "input_artifact_sha256": MERGE.PHASE0.sha256_file(input_path),
        "ranking_artifact_sha256": MERGE.PHASE0.sha256_file(ranking_path),
        "binding": {
            "model_name": references["binding_document"]["stage2_binding"]["model_name"],
            "model_digest": references["binding_document"]["stage2_binding"]["model_digest"],
            "prompt_version": references["binding_document"]["stage2_binding"]["prompt_version"],
            "prompt_sha256": references["binding_document"]["stage2_binding"]["prompt_sha256"],
            "company_profile_version": references["binding_document"]["stage2_binding"]["company_profile_version"],
            "company_profile_sha256": references["binding_document"]["stage2_binding"]["company_profile_sha256"],
            "generation_config_sha256": references["binding_document"]["stage2_binding"]["generation_config_sha256"],
        },
        "status": decisions_status,
        "candidate_count": len(candidate_ids),
        "success_count": len(decision_items),
        "failure_count": len(failures),
        "batch_count": len(batches),
        "batches": batches,
        "items": decision_items,
        "created_at": "2026-09-01T00:00:00+09:00",
    }
    failures_document = {
        "schema_version": "bidops.order-plan-screening-failures.v1",
        "producer": "order-plan-screening-worker",
        "consumer": "order-plan-screening-review-and-merge",
        "execution_id": "exec-merge-fixture",
        "source_run_id": "source-merge-fixture",
        "status": "none" if not failures else "partial" if failure_outcome == "unknown" else failure_outcome,
        "failure_count": len(failures),
        "failures": failures,
        "created_at": "2026-09-01T00:00:00+09:00",
    }
    telemetry = {
        "schema_version": "bidops.order-plan-screening-telemetry.v1",
        "producer": "order-plan-screening-worker",
        "consumer": "observability-and-merge",
        "execution_id": "exec-merge-fixture",
        "source_run_id": "source-merge-fixture",
        "status": "complete",
        "execution": measurement(),
        "batches": telemetry_batches,
        "created_at": "2026-09-01T00:00:00+09:00",
    }
    write_json(decisions_path, decisions)
    write_json(failures_path, failures_document)
    write_json(telemetry_path, telemetry)
    return {
        "input": input_path,
        "ranking": ranking_path,
        "decisions": decisions_path,
        "failures": failures_path,
        "telemetry": telemetry_path,
        "policy": references["policy"],
        "binding": references["binding"],
    }


class BuildOrderPlanScreeningResultsTests(unittest.TestCase):
    def test_rejects_decisions_binding_value_mismatch_against_approved_phase0_stage2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26)
            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions["binding"]["model_name"] = "unapproved-model"
            bad_decisions = root / "bad-decisions-binding.json"
            write_json(bad_decisions, decisions)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**paths, "decisions": bad_decisions}, root / "bad-binding-result.json")
            self.assertEqual("binding_mismatch", raised.exception.code)

    def test_rejects_tampered_ranking_score_and_plan_id_tie_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26)
            ranking = json.loads(paths["ranking"].read_text(encoding="utf-8"))
            ranking["items"][0], ranking["items"][1] = ranking["items"][1], ranking["items"][0]
            ranking["items"][0]["rank"] = 1
            ranking["items"][1]["rank"] = 2
            bad_ranking = root / "bad-ranking-order.json"
            write_json(bad_ranking, ranking)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**paths, "ranking": bad_ranking}, root / "bad-ranking-order-result.json")
            self.assertEqual("ranking_invalid", raised.exception.code)

    def test_rejects_decision_item_bound_to_earlier_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26)
            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions["batches"][0]["attempt_count"] = 2
            bad_decisions = root / "bad-decisions-attempt.json"
            write_json(bad_decisions, decisions)

            telemetry = json.loads(paths["telemetry"].read_text(encoding="utf-8"))
            first_attempt = dict(telemetry["batches"][0]["attempts"][0])
            first_attempt["status"] = "failed"
            second_attempt = dict(telemetry["batches"][0]["attempts"][0])
            second_attempt["attempt_no"] = 2
            telemetry["batches"][0]["attempts"] = [first_attempt, second_attempt]
            bad_telemetry = root / "bad-telemetry-attempt.json"
            write_json(bad_telemetry, telemetry)

            with self.assertRaises(MERGE.ContractError) as raised:
                merge(
                    {**paths, "decisions": bad_decisions, "telemetry": bad_telemetry},
                    root / "bad-attempt-result.json",
                )
            self.assertEqual("batch_mismatch", raised.exception.code)

    def test_rejects_any_attempt_after_rejected_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26)
            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            batch_id = decisions["batches"][0]["batch_id"]
            decisions["batches"][0]["attempt_count"] = 2
            for item in decisions["items"]:
                if item["batch_id"] == batch_id:
                    item["attempt_no"] = 2
            bad_decisions = root / "rejected-then-retried-decisions.json"
            write_json(bad_decisions, decisions)

            telemetry = json.loads(paths["telemetry"].read_text(encoding="utf-8"))
            first_attempt = dict(telemetry["batches"][0]["attempts"][0])
            first_attempt["status"] = "rejected"
            second_attempt = dict(telemetry["batches"][0]["attempts"][0])
            second_attempt["attempt_no"] = 2
            telemetry["batches"][0]["attempts"] = [first_attempt, second_attempt]
            bad_telemetry = root / "rejected-then-retried-telemetry.json"
            write_json(bad_telemetry, telemetry)

            with self.assertRaises(MERGE.ContractError) as raised:
                merge(
                    {**paths, "decisions": bad_decisions, "telemetry": bad_telemetry},
                    root / "rejected-then-retried-result.json",
                )
            self.assertEqual("batch_mismatch", raised.exception.code)

    def test_rejects_final_telemetry_status_mismatch_for_failed_rejected_and_unknown(self) -> None:
        cases = (
            ("timeout", "failed", "rejected"),
            ("model_mismatch", "rejected", "failed"),
            ("unknown", "unknown", "rejected"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (failure_type, failure_outcome, mismatched_status) in enumerate(cases):
                with self.subTest(failure_type=failure_type, failure_outcome=failure_outcome):
                    case_root = root / str(index)
                    paths = build_fixture(
                        case_root,
                        26,
                        {2},
                        failure_outcome=failure_outcome,
                        failure_type=failure_type,
                    )
                    telemetry = json.loads(paths["telemetry"].read_text(encoding="utf-8"))
                    batch = next(batch for batch in telemetry["batches"] if batch["sequence"] == 2)
                    batch["attempts"][-1]["status"] = mismatched_status
                    bad_telemetry = case_root / "mismatched-telemetry.json"
                    write_json(bad_telemetry, telemetry)
                    with self.assertRaises(MERGE.ContractError) as raised:
                        merge(
                            {**paths, "telemetry": bad_telemetry},
                            case_root / "mismatched-result.json",
                        )
                    self.assertEqual("batch_mismatch", raised.exception.code)

    def test_merges_failed_ranking_items_as_full_population_not_attempted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 2)

            ranking = json.loads(paths["ranking"].read_text(encoding="utf-8"))
            for index, status in enumerate(("failed", "rejected")):
                ranking["items"][index].update({
                    "rank": None,
                    "score": None,
                    "nearest_capability": None,
                    "stage1_status": status,
                })
            ranking["status"] = "실패"
            ranking["selected_count"] = 0
            ranking["filtered_out_count"] = 0
            bad_ranking = root / "failed-ranking.json"
            write_json(bad_ranking, ranking)

            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions.update({
                "ranking_artifact_sha256": MERGE.PHASE0.sha256_file(bad_ranking),
                "status": "실패",
                "candidate_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "batch_count": 0,
                "batches": [],
                "items": [],
            })
            bad_decisions = root / "failed-decisions.json"
            write_json(bad_decisions, decisions)

            telemetry = json.loads(paths["telemetry"].read_text(encoding="utf-8"))
            telemetry.update({
                "status": "not_measured",
                "execution": {field: None for field in MERGE.MEASUREMENT_KEYS},
                "batches": [],
            })
            bad_telemetry = root / "failed-telemetry.json"
            write_json(bad_telemetry, telemetry)

            result = merge(
                {
                    **paths,
                    "ranking": bad_ranking,
                    "decisions": bad_decisions,
                    "telemetry": bad_telemetry,
                },
                root / "failed-result.json",
            )

            self.assertEqual("실패", result["status"])
            self.assertTrue(result["partial_artifact"])
            self.assertEqual(2, result["counts"]["population"])
            self.assertEqual(2, result["counts"]["stage1_failed"])
            self.assertEqual(2, result["counts"]["human_review_count"])
            self.assertTrue(all(item["stage2_status"] == "not_attempted" for item in result["items"]))
            self.assertTrue(all(
                all(item[field] is None for field in (
                    "qwen_relevance",
                    "qwen_score",
                    "qwen_reason",
                    "batch_id",
                    "attempt_no",
                    "failure_code",
                ))
                for item in result["items"]
            ))

    def test_full_population_merge_keeps_filtered_out_as_unattempted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 625)
            output_path = root / "result.json"
            result = merge(paths, output_path)
            self.assertEqual("성공", result["status"])
            self.assertFalse(result["partial_artifact"])
            self.assertEqual(625, len(result["items"]))
            self.assertEqual(300, result["counts"]["stage1_selected"])
            self.assertEqual(325, result["counts"]["stage1_filtered_out"])
            filtered = [item for item in result["items"] if item["stage1_status"] == "filtered_out"]
            self.assertEqual(325, len(filtered))
            self.assertTrue(all(item["stage2_status"] == "not_attempted" for item in filtered))
            self.assertTrue(all(item["qwen_relevance"] is None for item in filtered))
            self.assertNotEqual(325, result["counts"]["stage2_not_relevant"])

    def test_partial_batch_prefix_keeps_unprocessed_selected_items_not_attempted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 51)
            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions.update({
                "status": "부분 성공",
                "success_count": 25,
                "failure_count": 0,
                "batch_count": 1,
                "batches": decisions["batches"][:1],
                "items": decisions["items"][:25],
            })
            write_json(paths["decisions"], decisions)
            telemetry = json.loads(paths["telemetry"].read_text(encoding="utf-8"))
            telemetry.update({"status": "partial", "batches": telemetry["batches"][:1]})
            write_json(paths["telemetry"], telemetry)

            result = merge(paths, root / "partial-prefix-result.json")

            self.assertEqual("부분 성공", result["status"])
            self.assertEqual(51, len(result["items"]))
            self.assertEqual(25, result["counts"]["stage2_relevant"] + result["counts"]["stage2_not_relevant"] + result["counts"]["stage2_uncertain"])
            unprocessed = result["items"][25:]
            self.assertEqual(26, len(unprocessed))
            self.assertTrue(all(item["stage2_status"] == "not_attempted" for item in unprocessed))
            self.assertTrue(all(item["failure_code"] is None for item in unprocessed))

    def test_partial_failure_and_unknown_are_honest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26, {2}, failure_outcome="unknown", failure_type="unknown")
            output_path = root / "result.json"
            result = merge(paths, output_path)
            self.assertEqual("부분 성공", result["status"])
            self.assertTrue(result["partial_artifact"])
            unknown = [item for item in result["items"] if item["stage2_status"] == "unknown"]
            self.assertEqual(1, len(unknown))
            self.assertIsNone(unknown[0]["qwen_relevance"])
            self.assertEqual(18, result["counts"]["human_review_count"])

    def test_failure_type_outcome_mapping_is_deterministic(self) -> None:
        valid_cases = (
            ("timeout", "failed"),
            ("truncated_output", "failed"),
            ("schema_violation", "failed"),
            ("id_mismatch", "failed"),
            ("transport", "failed"),
            ("model_mismatch", "rejected"),
            ("binding_mismatch", "rejected"),
            ("payload_not_approved", "rejected"),
            ("policy_rejected", "rejected"),
            ("unknown", "unknown"),
        )
        invalid_cases = (
            ("timeout", "unknown"),
            ("truncated_output", "unknown"),
            ("schema_violation", "unknown"),
            ("id_mismatch", "unknown"),
            ("transport", "unknown"),
            ("timeout", "rejected"),
            ("model_mismatch", "failed"),
            ("unknown", "failed"),
        )
        expected_count = {
            "failed": "stage2_failed",
            "rejected": "stage2_rejected",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (failure_type, failure_outcome) in enumerate(valid_cases):
                with self.subTest(failure_type=failure_type, failure_outcome=failure_outcome):
                    case_root = root / "valid" / str(index)
                    paths = build_fixture(
                        case_root,
                        26,
                        {2},
                        failure_outcome=failure_outcome,
                        failure_type=failure_type,
                    )
                    result = merge(paths, case_root / "result.json")
                    if failure_outcome == "unknown":
                        self.assertEqual(1, sum(item["stage2_status"] == "unknown" for item in result["items"]))
                    else:
                        self.assertEqual(1, result["counts"][expected_count[failure_outcome]])

            for index, (failure_type, failure_outcome) in enumerate(invalid_cases):
                with self.subTest(failure_type=failure_type, failure_outcome=failure_outcome):
                    case_root = root / "invalid" / str(index)
                    paths = build_fixture(
                        case_root,
                        26,
                        {2},
                        failure_outcome=failure_outcome,
                        failure_type=failure_type,
                    )
                    with self.assertRaises(MERGE.ContractError) as raised:
                        merge(paths, case_root / "result.json")
                    self.assertEqual("invalid_field", raised.exception.code)

    def test_all_candidate_rejections_publish_rejected_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 2, {1}, failure_outcome="rejected", failure_type="model_mismatch")
            result = merge(paths, root / "result.json")
            self.assertEqual("거부됨", result["status"])

    def test_stage1_failure_is_not_masked_by_candidate_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(
                root,
                301,
                set(range(1, 13)),
                failure_outcome="rejected",
                failure_type="model_mismatch",
            )
            ranking = json.loads(paths["ranking"].read_text(encoding="utf-8"))
            ranking["items"][-1].update(
                {"rank": None, "score": None, "nearest_capability": None, "stage1_status": "failed"}
            )
            ranking.update({"status": "실패", "filtered_out_count": 0})
            write_json(paths["ranking"], ranking)
            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions["ranking_artifact_sha256"] = MERGE.PHASE0.sha256_file(paths["ranking"])
            write_json(paths["decisions"], decisions)
            result = merge(paths, root / "result.json")
            self.assertEqual("실패", result["status"])

    def test_rejects_noncandidate_results_duplicate_batches_and_missing_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26)
            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions["items"][0]["plan_id"] = "not-a-candidate"
            bad_decisions = root / "bad-decisions.json"
            write_json(bad_decisions, decisions)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**paths, "decisions": bad_decisions}, root / "bad-result.json")
            self.assertEqual("noncandidate_result", raised.exception.code)

            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions["batches"][1]["batch_id"] = decisions["batches"][0]["batch_id"]
            duplicate_batch = root / "duplicate-batch.json"
            write_json(duplicate_batch, decisions)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**paths, "decisions": duplicate_batch}, root / "duplicate-result.json")
            self.assertEqual("duplicate_batch_id", raised.exception.code)

            partial = build_fixture(root / "partial", 26, {2})
            failures = json.loads(partial["failures"].read_text(encoding="utf-8"))
            failures["failures"] = []
            failures["failure_count"] = 0
            failures["status"] = "none"
            missing_failure = root / "missing-failure.json"
            write_json(missing_failure, failures)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**partial, "failures": missing_failure}, root / "missing-failure-result.json")
            self.assertEqual("batch_mismatch", raised.exception.code)

    def test_rejects_population_digest_and_telemetry_binding_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26)
            ranking = json.loads(paths["ranking"].read_text(encoding="utf-8"))
            ranking["population_count"] = 25
            bad_ranking = root / "bad-ranking.json"
            write_json(bad_ranking, ranking)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**paths, "ranking": bad_ranking}, root / "bad-population-result.json")
            self.assertEqual("population_mismatch", raised.exception.code)

            decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
            decisions["ranking_artifact_sha256"] = "0" * 64
            bad_binding = root / "bad-binding.json"
            write_json(bad_binding, decisions)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**paths, "decisions": bad_binding}, root / "bad-binding-result.json")
            self.assertEqual("digest_mismatch", raised.exception.code)

            telemetry = json.loads(paths["telemetry"].read_text(encoding="utf-8"))
            telemetry["batches"] = []
            bad_telemetry = root / "bad-telemetry.json"
            write_json(bad_telemetry, telemetry)
            with self.assertRaises(MERGE.ContractError) as raised:
                merge({**paths, "telemetry": bad_telemetry}, root / "bad-telemetry-result.json")
            self.assertEqual("batch_mismatch", raised.exception.code)

    def test_merged_bytes_are_stable_and_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = build_fixture(root, 26)
            first_path = root / "result-1.json"
            second_path = root / "result-2.json"
            merge(paths, first_path)
            merge(paths, second_path)
            first = first_path.read_bytes()
            second = second_path.read_bytes()
            self.assertEqual(first, second)
            self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
            with self.assertRaises(MERGE.ContractError) as raised:
                merge(paths, first_path)
            self.assertEqual("output_exists", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
