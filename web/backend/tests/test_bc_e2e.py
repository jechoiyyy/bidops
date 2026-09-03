from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.services.bc_e2e import BcE2EError, BcE2EManifest, run_bc_e2e
from app.services.agent_e2e import AgentProjectionSnapshot, run_t7_e2e


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


def _uuid(number: int) -> str:
    return str(UUID(int=number))


class T7FakeProjection:
    def __init__(self, payload: dict[str, Any], lineage: str) -> None:
        self.payload = payload
        self.correlation_id = UUID(lineage)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self.payload


class T7FakeProjectionReader:
    def __init__(self, api: "T7FakeApi") -> None:
        self.api = api
        self.reads: list[tuple[str, str]] = []

    def validate_mock_context(self) -> None:
        return None

    @staticmethod
    def _view(
        *,
        run_id: str,
        status: str,
        current_step: str | None,
        outcome: str | None,
        lineage: str,
        wait: dict[str, str] | None,
        actions: list[str],
        input_types: list[str],
        output_types: list[str],
    ) -> T7FakeProjection:
        def refs(types: list[str]) -> list[dict[str, str]]:
            return [{"artifact_type": value, "artifact_id": _uuid(index + 1)} for index, value in enumerate(types)]

        return T7FakeProjection({
            "run_id": run_id,
            "status": status,
            "current_step": current_step,
            "outcome_code": outcome,
            "input_refs": refs(input_types),
            "output_refs": refs(output_types),
            "wait": wait,
            "available_actions": actions,
            "correlation_id": lineage,
        }, lineage)

    def read(self, bundle_id: str, review_id: str) -> AgentProjectionSnapshot:
        self.reads.append((bundle_id, review_id))
        flow = self.api.review_records[review_id]
        lineage = flow["lineage"]
        attempt_id = flow["attempt_id"]
        document_status = self.api.bundle_records[bundle_id]["status"]
        if document_status == "superseded":
            document = self._view(
                run_id=f"document-preparation:{bundle_id}",
                status="superseded",
                current_step=None,
                outcome="superseded_by_new_bundle",
                lineage=lineage,
                wait=None,
                actions=[],
                input_types=[],
                output_types=["document_structure", "document_bundle"],
            )
        else:
            document = self._view(
                run_id=f"document-preparation:{bundle_id}",
                status="completed",
                current_step=None,
                outcome="ready_bundle",
                lineage=lineage,
                wait=None,
                actions=[],
                input_types=[],
                output_types=["document_structure", "document_bundle"],
            )
        deep_review = self._view(
            run_id=f"deep-review:{review_id}:attempt:{attempt_id}",
            status="completed",
            current_step=None,
            outcome="report_ready_validated",
            lineage=lineage,
            wait=None,
            actions=["retry_attempt"],
            input_types=["document_bundle", "profile_version", "policy_version"],
            output_types=[
                "deep_review_stage", "deep_review_stage", "deep_review_stage",
                "report_revision", "validation_run", "evidence",
            ],
        )
        state = flow["state"]
        if state == "machine":
            decision = self._view(
                run_id=f"decision:{review_id}",
                status="waiting_human",
                current_step="review_report_and_evidence",
                outcome=None,
                lineage=lineage,
                wait={"reason_code": "report_review_required"},
                actions=["create_full_revision", "record_final_opinion"],
                input_types=["report_revision", "validation_run", "evidence"],
                output_types=[],
            )
        elif state == "human":
            decision = self._view(
                run_id=f"decision:{review_id}",
                status="waiting_human",
                current_step="record_final_opinion",
                outcome=None,
                lineage=lineage,
                wait={"reason_code": "final_opinion_required"},
                actions=["create_full_revision", "record_final_opinion"],
                input_types=["report_revision", "validation_run", "evidence"],
                output_types=["report_revision", "validation_run"],
            )
        else:
            decision = self._view(
                run_id=f"decision:{review_id}",
                status="completed",
                current_step=None,
                outcome="final_opinion_recorded",
                lineage=lineage,
                wait=None,
                actions=["create_full_revision"],
                input_types=["report_revision", "validation_run", "evidence"],
                output_types=["report_revision", "validation_run", "final_opinion"],
            )
        return AgentProjectionSnapshot(document, deep_review, decision)

    def active_work_jobs(self) -> int:
        return 0

    def provider_context(self, review_ids: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        return [{
            "review_id": review_id,
            "provider": "mock-analysis",
            "model": "bidops-deterministic-mock-v1",
            "policy_model": "bidops-deterministic-mock-v1",
            "reference_workflow_mode": True,
            "external_provider_approved": False,
            "external_calls": {"openai": 0, "qwen": 0, "total": 0},
        } for review_id in review_ids]


class T7FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.flow_count = 0
        self.document_count = 0
        self.bundle_records: dict[str, dict[str, Any]] = {}
        self.review_records: dict[str, dict[str, Any]] = {}
        self.report_records: dict[str, dict[str, Any]] = {}

    def request_json(self, method, path, *, payload=None, actor=None, retryable=False):  # type: ignore[no-untyped-def]
        self.calls.append((method, path, payload))
        if method == "POST" and path.endswith("/document-bundles"):
            self.flow_count += 1
            bundle_id = _uuid(100 + self.flow_count)
            self.bundle_records[bundle_id] = {"status": "draft", "flow": self.flow_count, "documents": []}
            return {"id": bundle_id, "version": 1, "status": "draft", "documents": []}
        if method == "GET" and path.endswith("/document-bundles"):
            return {"items": [
                {"id": bundle_id, "status": record["status"]}
                for bundle_id, record in self.bundle_records.items()
            ]}
        if method == "PATCH" and path.startswith("/api/document-versions/"):
            document_id = path.rsplit("/", 1)[-1]
            return {
                "id": document_id, "version": 2, "original_filename": "representative.pdf",
                "safety_status": "safe", "structure_status": "ready", "role": payload["role"],
            }
        if method == "POST" and path.endswith("/confirm"):
            bundle_id = path.split("/")[-2]
            record = self.bundle_records[bundle_id]
            for prior in self.bundle_records.values():
                if prior["status"] == "ready":
                    prior["status"] = "superseded"
            record["status"] = "ready"
            record["documents"] = list(payload["confirmed_documents"])
            return {"id": bundle_id, "revision": record["flow"], "version": 2, "status": "ready", "issues": []}
        if method == "POST" and path.endswith("/deep-reviews"):
            flow = self.flow_count
            bundle_id = next(bundle_id for bundle_id, record in self.bundle_records.items() if record["flow"] == flow)
            review_id = _uuid(300 + flow)
            attempt_id = _uuid(400 + flow)
            self.review_records[review_id] = {
                "bundle_id": bundle_id, "attempt_id": attempt_id, "lineage": _uuid(1000 + flow), "state": "machine",
            }
            machine_revision = _uuid(500 + flow)
            machine_validation = _uuid(600 + flow)
            evidence_id = _uuid(700 + flow)
            self.report_records[review_id] = {
                "machine_revision": machine_revision,
                "machine_validation": machine_validation,
                "evidence_id": evidence_id,
                "human_revision": _uuid(800 + flow),
                "human_validation": _uuid(900 + flow),
                "opinion_id": _uuid(1000 + flow),
                "human_report": None,
                "opinion": None,
            }
            return {"id": review_id, "status": "queued"}
        if method == "GET" and path.startswith("/api/deep-reviews/") and path.count("/") == 3:
            review_id = path.rsplit("/", 1)[-1]
            record = self.review_records[review_id]
            stages = [
                {"stage": "requirements_and_evaluation", "status": "completed"},
                {"stage": "delivery_risk_economics", "status": "completed"},
                {"stage": "synthesis_and_validation", "status": "completed"},
            ]
            return {
                "id": review_id, "status": "completed",
                "current_attempt": {"id": record["attempt_id"], "sequence": 1, "stages": stages},
                "attempts": [{"id": record["attempt_id"], "sequence": 1}],
            }
        if method == "GET" and path.endswith("/report"):
            review_id = path.split("/")[3]
            record = self.review_records[review_id]
            revisions = self.report_records[review_id]
            if revisions["human_report"] is None:
                current_revision = revisions["machine_revision"]
                history = [{"revision_id": current_revision, "sequence": 1, "origin": "machine", "validation_status": "passed"}]
                report_payload = {
                    "deep_review_id": review_id, "bundle_id": record["bundle_id"],
                    "system_recommendation": "보류", "sections": [{"title": "Machine"}],
                    "claims": [{"claim_id": _uuid(1100 + self.bundle_records[record["bundle_id"]]["flow"]), "evidence_ids": [revisions["evidence_id"]]}],
                }
            else:
                current_revision = revisions["human_revision"]
                history = [
                    {"revision_id": revisions["machine_revision"], "sequence": 1, "origin": "machine", "validation_status": "passed"},
                    {"revision_id": current_revision, "sequence": 2, "origin": "human", "validation_status": "passed"},
                ]
                report_payload = revisions["human_report"]
            validation_id = revisions["machine_validation"] if revisions["human_report"] is None else revisions["human_validation"]
            return {
                "current_revision_id": current_revision,
                "report": report_payload,
                "validation": {"validation_run_id": validation_id, "status": "passed"},
                "history": history,
                "final_opinion": revisions["opinion"],
            }
        if method == "POST" and path.endswith("/report-revisions"):
            review_id = path.split("/")[3]
            revisions = self.report_records[review_id]
            self.review_records[review_id]["state"] = "human"
            human_report = dict(payload["report"])
            human_report["deep_review_id"] = review_id
            human_report["bundle_id"] = self.review_records[review_id]["bundle_id"]
            revisions["human_report"] = human_report
            return {
                "current_revision_id": revisions["human_revision"],
                "report": human_report,
                "validation": {"validation_run_id": revisions["human_validation"], "status": "passed"},
                "history": [
                    {"revision_id": revisions["machine_revision"], "sequence": 1, "origin": "machine", "validation_status": "passed"},
                    {"revision_id": revisions["human_revision"], "sequence": 2, "origin": "human", "validation_status": "passed"},
                ],
                "final_opinion": None,
            }
        if method == "POST" and path.endswith("/final-opinions"):
            review_id = path.split("/")[3]
            revisions = self.report_records[review_id]
            self.review_records[review_id]["state"] = "final"
            opinion = {
                "id": revisions["opinion_id"], "value": payload["value"], "claimed_name": actor,
            }
            revisions["opinion"] = opinion
            return opinion
        if method == "GET" and path.startswith("/api/evidence/"):
            evidence_id = path.rsplit("/", 1)[-1]
            return {
                "evidence_id": evidence_id, "source_kind": "document", "source_sha256": "a" * 64,
                "locator_type": "page", "locator": {"page": 1},
            }
        raise AssertionError((method, path))

    def upload_document(self, bundle_id: str, *, filename: str, media_type: str, content: bytes, request_id: str, actor: str):
        self.document_count += 1
        document_id = _uuid(200 + self.document_count)
        self.bundle_records[bundle_id]["documents"].append({"document_version_id": document_id, "version": 2})
        return {
            "id": document_id, "version": 1, "safety_status": "safe", "structure_status": "ready",
            "replaces_document_version_id": None,
        }


def test_t7_e2e_preserves_human_history_and_verifies_persisted_projections(tmp_path: Path) -> None:
    api = T7FakeApi()
    reader = T7FakeProjectionReader(api)
    result = run_t7_e2e(_manifest(tmp_path), api, reader, sleep=lambda _seconds: None)

    assert result["passed"] is True
    assert result["first_flow"]["lineage"] != result["second_flow"]["lineage"]
    assert result["first_flow"]["preserved_history"]["revision_ids"] == [_uuid(501), _uuid(801)]
    assert result["first_flow"]["projections"]["preserved_after_second_flow"]["document_preparation"]["status"] == "superseded"
    assert result["provider_model"]["external_calls"]["total"] == 0
    assert result["mock_quality"]["evaluated"] is False
    assert result["work_jobs"]["active"] == 0
    assert len(reader.reads) == 5
