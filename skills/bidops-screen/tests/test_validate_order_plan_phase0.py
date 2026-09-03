"""Focused tests for the read-only C-2 Phase 0 contract gate."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_order_plan_phase0.py"
SPEC = importlib.util.spec_from_file_location("bidops_validate_order_plan_phase0", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


PHASE0_EVIDENCE_PATHS = (
    ROOT / VALIDATOR.SOURCE_RELATIVE,
    ROOT / VALIDATOR.REVIEW_INPUTS_RELATIVE / "manifest.json",
    ROOT / VALIDATOR.POPULATION_RELATIVE,
    ROOT / VALIDATOR.SELECTION_RELATIVE,
    ROOT / VALIDATOR.GOLD_MANIFEST_RELATIVE,
    ROOT / "experiments/order-plan-screening/review-inputs/company/company-capabilities-v1-approved.json",
    ROOT / "experiments/order-plan-screening/review-inputs/prompts/order-plan-batch-relevance-v3-approved.txt",
)
PHASE0_EVIDENCE_PROVISIONED = all(path.is_file() for path in PHASE0_EVIDENCE_PATHS) and (
    ROOT / VALIDATOR.SOURCE_RELATIVE
).parent.joinpath("raw").is_dir()
REQUIRES_PHASE0_EVIDENCE = unittest.skipUnless(
    PHASE0_EVIDENCE_PROVISIONED,
    "Phase 0 evidence integration inputs are not provisioned in this checkout",
)


class Phase0ContractTests(unittest.TestCase):
    @REQUIRES_PHASE0_EVIDENCE
    def test_current_contract_is_valid_but_not_activatable(self) -> None:
        result = VALIDATOR.validate_phase0(ROOT)

        self.assertEqual("valid_but_blocked", result["status"])
        self.assertEqual(9, result["contract_count"])
        self.assertEqual(625, result["population_count"])
        self.assertEqual(22, result["human_adjudication_count"])
        self.assertEqual(603, result["draft_label_count"])
        self.assertEqual(87, result["remaining_confirmation_count"])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["activation_allowed"])
        self.assertIn("c1_gold_incomplete", result["blockers"])

    @REQUIRES_PHASE0_EVIDENCE
    def test_cli_reports_only_safe_contract_metadata(self) -> None:
        completed = subprocess.run(
            ["python3", str(SCRIPT), "--repo-root", str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode)
        self.assertIn("phase0=valid_but_blocked", completed.stdout)
        self.assertNotIn("생성형 AI·LLM 기반", completed.stdout)
        self.assertNotIn("qwen3.8-27B", completed.stderr)

    def test_all_machine_contracts_parse_and_have_provenance(self) -> None:
        self.assertEqual(9, VALIDATOR.validate_schema_catalog())
        for path in (ROOT / "skills/bidops-screen/contracts").glob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(document, dict)

    def test_contract_schema_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            source_dir = ROOT / "skills/bidops-screen/contracts"
            copied_dir = temporary_root / "skills/bidops-screen/contracts"
            shutil.copytree(source_dir, copied_dir)
            schema_path = copied_dir / "bidops.order-plan-screening-ranking.v1.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["title"] = "tampered"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_schema_catalog(temporary_root)
        self.assertEqual("hash_mismatch", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_policy_top_k_change_is_rejected(self) -> None:
        review = VALIDATOR.validate_review_inputs(ROOT)
        policy_path = ROOT / VALIDATOR.POLICY_RELATIVE
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["stage1"]["top_k"] = 299
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / policy_path.name
            candidate.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_policy_artifact(ROOT, review, path=candidate)
        self.assertEqual("policy_binding_mismatch", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_unapproved_audit_policy_is_rejected(self) -> None:
        review = VALIDATOR.validate_review_inputs(ROOT)
        policy_path = ROOT / VALIDATOR.POLICY_RELATIVE
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["audit_sample"]["enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / policy_path.name
            candidate.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_policy_artifact(ROOT, review, path=candidate)
        self.assertEqual("audit_policy_not_approved", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_source_count_tampering_fails_closed(self) -> None:
        source_dir = ROOT / VALIDATOR.SOURCE_RELATIVE
        with tempfile.TemporaryDirectory() as directory:
            copied_dir = Path(directory) / source_dir.parent.name
            shutil.copytree(source_dir.parent, copied_dir)
            source_path = copied_dir / source_dir.name
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["counts"]["total"] += 1
            source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_collected_artifact(ROOT, source_path)
        self.assertEqual("count_mismatch", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_source_incomplete_is_not_usable(self) -> None:
        source_dir = ROOT / VALIDATOR.SOURCE_RELATIVE
        with tempfile.TemporaryDirectory() as directory:
            copied_dir = Path(directory) / source_dir.parent.name
            shutil.copytree(source_dir.parent, copied_dir)
            source_path = copied_dir / source_dir.name
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["metadata"]["collection"]["complete"] = False
            source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_collected_artifact(ROOT, source_path)
        self.assertEqual("source_incomplete", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_raw_query_tampering_is_rejected(self) -> None:
        source_dir = ROOT / VALIDATOR.SOURCE_RELATIVE
        with tempfile.TemporaryDirectory() as directory:
            copied_dir = Path(directory) / source_dir.parent.name
            shutil.copytree(source_dir.parent, copied_dir)
            raw_path = copied_dir / "raw/page-00001.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["query"]["inqryEndDt"] = "202608312359"
            raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            source_path = copied_dir / source_dir.name
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_collected_artifact(ROOT, source_path)
        self.assertEqual("source_binding_mismatch", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_duplicate_source_plan_id_is_rejected(self) -> None:
        source_dir = ROOT / VALIDATOR.SOURCE_RELATIVE
        with tempfile.TemporaryDirectory() as directory:
            copied_dir = Path(directory) / source_dir.parent.name
            shutil.copytree(source_dir.parent, copied_dir)
            source_path = copied_dir / source_dir.name
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["order_plans"][1]["order_plan_unty_no"] = source["order_plans"][0]["order_plan_unty_no"]
            source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_collected_artifact(ROOT, source_path)
        self.assertEqual("duplicate_plan_id", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_binding_policy_digest_tampering_is_rejected(self) -> None:
        binding_path = ROOT / VALIDATOR.BINDING_RELATIVE
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        binding["policy"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / binding_path.name
            candidate.write_text(json.dumps(binding, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_phase0(ROOT, binding_path=candidate)
        self.assertEqual("hash_mismatch", raised.exception.code)

    @REQUIRES_PHASE0_EVIDENCE
    def test_gold_is_partial_and_cannot_claim_human_completion(self) -> None:
        gold = VALIDATOR.validate_gold_artifact(ROOT)
        self.assertEqual("partially_human_adjudicated", gold["status"])
        self.assertEqual(22, gold["human_adjudication_count"])
        self.assertEqual(603, gold["draft_label_count"])
        self.assertEqual(87, gold["remaining_confirmation_count"])

        manifest_path = ROOT / VALIDATOR.GOLD_MANIFEST_RELATIVE
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            for relative in (
                "data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2",
                "data/experiments/order-plan-screening/20260827-20260830-gold-draft-v2",
            ):
                shutil.copytree(ROOT / relative, temporary_root / relative)
            candidate = temporary_root / VALIDATOR.GOLD_MANIFEST_RELATIVE
            altered = json.loads(candidate.read_text(encoding="utf-8"))
            altered["status"] = "human_adjudicated"
            candidate.write_text(json.dumps(altered, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(VALIDATOR.ContractError) as raised:
                VALIDATOR.validate_gold_artifact(temporary_root, candidate)
        self.assertEqual("gold_status_invalid", raised.exception.code)

    def test_path_traversal_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe.txt").write_text("safe", encoding="utf-8")
            outside = root.parent / f"{root.name}-outside.txt"
            outside.write_text("outside", encoding="utf-8")
            try:
                with self.assertRaises(VALIDATOR.ContractError) as traversal:
                    VALIDATOR.resolve_child_file(root, "../outside.txt", "fixture")
                self.assertEqual("unsafe_path", traversal.exception.code)
                link = root / "link.txt"
                link.symlink_to(outside)
                with self.assertRaises(VALIDATOR.ContractError) as symlink:
                    VALIDATOR.resolve_child_file(root, "link.txt", "fixture")
                self.assertEqual("unsafe_path", symlink.exception.code)
            finally:
                outside.unlink(missing_ok=True)

    def test_result_schema_rejects_impossible_stage_combination(self) -> None:
        try:
            import jsonschema
        except ModuleNotFoundError:
            self.skipTest("jsonschema is not installed")

        schema = json.loads(
            (ROOT / "skills/bidops-screen/contracts/bidops.order-plan-screening-result.v1.json").read_text(
                encoding="utf-8"
            )
        )
        base = {
            "schema_version": "bidops.order-plan-screening-result.v1",
            "producer": "order-plan-screening-merge",
            "consumer": "postgres-loader-and-review-api",
            "execution_id": "execution-1",
            "source_run_id": "source-1",
            "input_artifact_sha256": "0" * 64,
            "policy_version": "policy-1",
            "policy_sha256": "1" * 64,
            "status": "부분 성공",
            "partial_artifact": True,
            "counts": {
                "population": 1,
                "stage1_selected": 0,
                "stage1_filtered_out": 1,
                "stage1_failed": 0,
                "stage2_relevant": 0,
                "stage2_not_relevant": 0,
                "stage2_uncertain": 0,
                "stage2_failed": 0,
                "stage2_rejected": 0,
                "human_review_count": 0,
            },
            "items": [
                {
                    "plan_id": "plan-1",
                    "stage1_status": "filtered_out",
                    "stage1_rank": 301,
                    "stage1_score": 0.5,
                    "nearest_capability": "capability-1",
                    "stage2_status": "not_attempted",
                    "qwen_relevance": None,
                    "qwen_score": None,
                    "qwen_reason": None,
                    "batch_id": None,
                    "attempt_no": None,
                    "failure_code": None,
                }
            ],
            "created_at": "2026-09-01T00:00:00+00:00",
        }
        validator = jsonschema.Draft202012Validator(schema)
        self.assertEqual([], list(validator.iter_errors(base)))
        impossible = json.loads(json.dumps(base))
        impossible["items"][0]["stage2_status"] = "success"
        impossible["items"][0]["qwen_relevance"] = "relevant"
        self.assertTrue(list(validator.iter_errors(impossible)))


if __name__ == "__main__":
    unittest.main()
