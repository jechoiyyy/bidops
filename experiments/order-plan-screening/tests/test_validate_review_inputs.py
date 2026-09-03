from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "validate_review_inputs", SCRIPTS / "validate_review_inputs.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

from common import ExperimentError, digest_json, sha256_file  # noqa: E402


class ReviewInputsValidationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        company_dir = root / "company"
        prompt_dir = root / "prompts"
        company_dir.mkdir(parents=True)
        prompt_dir.mkdir()
        projection = {
            "profile_version": "profile-v1",
            "capabilities": [{"id": "data", "summary": "데이터 플랫폼 구축"}],
        }
        capabilities = {
            "schema_version": "bidops.order-plan-capabilities.v1",
            "approval_status": "approved",
            "profile_version": projection["profile_version"],
            "summary_sha256": digest_json(projection),
            "approved_by": "reviewer",
            "approved_at": "2026-09-01T10:00:00+09:00",
            "capabilities": projection["capabilities"],
        }
        capabilities_path = company_dir / "capabilities.json"
        capabilities_path.write_text(
            json.dumps(capabilities, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        prompt_path = prompt_dir / "prompt.txt"
        prompt_path.write_text("JSON으로만 판정한다.\n", encoding="utf-8")
        manifest = {
            "schema_version": MODULE.MANIFEST_SCHEMA,
            "updated_at": "2026-09-01T10:01:00+09:00",
            "active_company_capabilities": "company/capabilities.json",
            "active_prompt": "prompts/prompt.txt",
            "documents": [
                {
                    "kind": "company_capabilities",
                    "path": "company/capabilities.json",
                    "version": "profile-v1",
                    "status": "approved",
                    "execution_allowed": True,
                    "sha256": sha256_file(capabilities_path),
                    "source_path": "legacy/capabilities.json",
                },
                {
                    "kind": "prompt",
                    "path": "prompts/prompt.txt",
                    "version": "prompt-v1",
                    "status": "approved",
                    "execution_allowed": True,
                    "sha256": sha256_file(prompt_path),
                    "source_path": "legacy/prompt.txt",
                },
            ],
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_validates_approved_active_files_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            result = MODULE.validate_review_inputs(root)
            self.assertEqual(result["document_count"], 2)
            self.assertEqual(result["active_prompt"], "prompts/prompt.txt")

    def test_rejects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            (root / "prompts/prompt.txt").write_text("변경된 prompt\n", encoding="utf-8")
            with self.assertRaises(ExperimentError) as caught:
                MODULE.validate_review_inputs(root)
            self.assertEqual(caught.exception.code, "hash_mismatch")

    def test_rejects_draft_as_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["documents"][1]["status"] = "draft"
            manifest["documents"][1]["execution_allowed"] = False
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ExperimentError) as caught:
                MODULE.validate_review_inputs(root)
            self.assertEqual(caught.exception.code, "active_review_input_invalid")


if __name__ == "__main__":
    unittest.main()
