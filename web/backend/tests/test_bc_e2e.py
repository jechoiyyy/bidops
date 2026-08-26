from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.bc_e2e import BcE2EError, BcE2EManifest, run_bc_e2e


class FakeApi:
    def __init__(self, *, unsafe: bool = False, fail_once: bool = False, existing_document: bool = False, existing_filename: str = "existing.hwp") -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.unsafe = unsafe
        self.fail_once = fail_once
        self.existing_document = existing_document
        self.existing_filename = existing_filename
        self.review_reads = 0
        self.retry_calls = 0

    def request_json(self, method, path, *, payload=None, actor=None, retryable=False):  # type: ignore[no-untyped-def]
        self.calls.append((method, path, payload))
        if path.endswith("/document-bundles"):
            documents = []
            if self.existing_document:
                documents.append({
                    "id": "document-existing", "version": 4, "original_filename": self.existing_filename,
                    "safety_status": "safe", "structure_status": "ready", "role": "공고",
                })
            return {"id": "bundle-1", "version": 1, "status": "draft", "documents": documents}
        if path.startswith("/api/document-versions/"):
            return {
                "id": "document-1", "version": 2, "original_filename": "representative.pdf",
                "safety_status": "safe", "structure_status": "ready", "role": payload["role"],
            }
        if path.endswith("/confirm"):
            return {"id": "bundle-1", "revision": 1, "version": 2, "status": "ready", "issues": []}
        if path.endswith("/deep-reviews"):
            return {"id": "review-1", "status": "queued"}
        if path.endswith("/attempts"):
            self.retry_calls += 1
            return {"id": "attempt-2", "status": "queued"}
        if path == "/api/deep-reviews/review-1":
            self.review_reads += 1
            if self.fail_once and self.retry_calls == 0:
                return {"id": "review-1", "status": "failed", "current_attempt": {"sequence": 1, "stages": []}}
            return {
                "id": "review-1", "status": "completed",
                "current_attempt": {
                    "sequence": 1 + self.retry_calls,
                    "stages": [
                        {"stage": "requirements_and_evaluation", "status": "completed"},
                        {"stage": "delivery_risk_economics", "status": "completed"},
                        {"stage": "synthesis_and_validation", "status": "completed"},
                    ],
                },
            }
        if path.endswith("/report"):
            return {
                "current_revision_id": "revision-1",
                "report": {
                    "deep_review_id": "review-1", "bundle_id": "bundle-1", "system_recommendation": "보류",
                    "claims": [{"claim_id": "claim-1", "evidence_ids": ["evidence-1"]}],
                },
                "validation": {"validation_run_id": "validation-1", "status": "passed"},
                "history": [{"origin": "machine"}],
            }
        if path == "/api/evidence/evidence-1":
            return {"evidence_id": "evidence-1", "source_kind": "document", "source_sha256": "a" * 64, "locator_type": "page", "locator": {"page": 1}}
        raise AssertionError(path)

    def upload_document(self, bundle_id: str, *, filename: str, media_type: str, content: bytes, request_id: str, actor: str):
        self.calls.append(("POST", f"/api/document-bundles/{bundle_id}/documents", {"request_id": request_id}))
        assert filename == "representative.pdf"
        assert media_type == "application/pdf"
        assert content == b"%PDF-1.4\nfixture"
        return {
            "id": "document-1", "version": 1,
            "safety_status": "blocked" if self.unsafe else "safe",
            "structure_status": "failed" if self.unsafe else "ready",
            "replaces_document_version_id": "document-existing" if self.existing_filename == filename else None,
        }


def _manifest(tmp_path: Path, *, retry_limit: int = 0) -> BcE2EManifest:
    document = tmp_path / "representative.pdf"
    document.write_bytes(b"%PDF-1.4\nfixture")
    return BcE2EManifest.model_validate({
        "schema": "bidops.bc-e2e-run.v1",
        "api_base": "http://127.0.0.1:28787",
        "notice_id": 7,
        "actor_name": "E2E 담당자",
        "documents": [{"path": str(document), "role": "제안요청서", "effective_date": None}],
        "analysis_retry_limit": retry_limit,
    })


def test_bc_e2e_joins_ready_bundle_to_completed_machine_report(tmp_path: Path) -> None:
    api = FakeApi()
    result = run_bc_e2e(_manifest(tmp_path), api, sleep=lambda _seconds: None)

    assert result["passed"] is True
    assert result["bundle"]["id"] == "bundle-1"
    assert result["report"]["evidence"][0]["evidence_id"] == "evidence-1"
    assert result["deep_review"]["status"] == "completed"
    assert [stage["stage"] for stage in result["deep_review"]["stages"]] == [
        "requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation",
    ]
    confirm = next(payload for method, path, payload in api.calls if path.endswith("/confirm"))
    assert confirm["confirmed_documents"] == [{"document_version_id": "document-1", "version": 2}]


def test_bc_e2e_confirms_existing_current_documents_with_new_uploads(tmp_path: Path) -> None:
    api = FakeApi(existing_document=True)
    result = run_bc_e2e(_manifest(tmp_path), api, sleep=lambda _seconds: None)

    confirm = next(payload for method, path, payload in api.calls if path.endswith("/confirm"))
    assert confirm["confirmed_documents"] == [
        {"document_version_id": "document-existing", "version": 4},
        {"document_version_id": "document-1", "version": 2},
    ]
    assert result["bundle"]["documents"][0]["uploaded_in_run"] is False
    assert result["bundle"]["documents"][1]["source_sha256"] is not None


def test_bc_e2e_replaces_seeded_same_filename_and_preserves_ancestry(tmp_path: Path) -> None:
    api = FakeApi(existing_document=True, existing_filename="representative.pdf")
    run_bc_e2e(_manifest(tmp_path), api, sleep=lambda _seconds: None)

    patch = next(payload for method, path, payload in api.calls if method == "PATCH")
    confirm = next(payload for method, path, payload in api.calls if path.endswith("/confirm"))
    assert patch["replaces_document_version_id"] == "document-existing"
    assert confirm["confirmed_documents"] == [{"document_version_id": "document-1", "version": 2}]


def test_bc_e2e_can_append_one_explicit_retry_attempt(tmp_path: Path) -> None:
    api = FakeApi(fail_once=True)
    result = run_bc_e2e(_manifest(tmp_path, retry_limit=1), api, sleep=lambda _seconds: None)
    assert result["deep_review"]["analysis_retries_used"] == 1
    assert api.retry_calls == 1


def test_bc_e2e_stops_before_analysis_when_document_is_not_ready(tmp_path: Path) -> None:
    api = FakeApi(unsafe=True)
    with pytest.raises(BcE2EError) as error:
        run_bc_e2e(_manifest(tmp_path), api, sleep=lambda _seconds: None)
    assert error.value.code == "document_not_ready"
    assert not any(path.endswith("/deep-reviews") for _method, path, _payload in api.calls)


def test_bc_e2e_manifest_requires_https_for_non_loopback_and_unique_documents(tmp_path: Path) -> None:
    document = tmp_path / "fixture.pdf"
    document.write_bytes(b"x")
    payload = {
        "schema": "bidops.bc-e2e-run.v1",
        "api_base": "http://preprod.example.test:8787",
        "notice_id": 1,
        "actor_name": "담당자",
        "documents": [
            {"path": str(document), "role": "기타"},
            {"path": str(document), "role": "기타"},
        ],
    }
    with pytest.raises(ValidationError):
        BcE2EManifest.model_validate(payload)
