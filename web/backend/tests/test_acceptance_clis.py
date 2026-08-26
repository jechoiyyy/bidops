from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.cli.run_bc_e2e import _write_evidence, main as run_bc_main
from app.cli.score_candidate_quality import main as score_quality_main
from app.services.bc_e2e import BcE2EError, JsonAcceptanceApi, actor_header_value
from app.services.document_bundles import BundleServiceError, validate_actor


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _quality_manifest() -> dict:
    return {
        "schema": "bidops.qwen-quality-evaluation.v1",
        "model_name": "qwen3.8-27B",
        "model_artifact_digest": "abcdef123456",
        "policy_sha256": "1" * 64,
        "samples": [
            {
                "sample_id": "hwp-55",
                "source_format": "hwp",
                "source_sha256": "2" * 64,
                "coverage_tags": ["requirements-55"],
                "required_items": [
                    {"item_id": f"REQ-{index:03d}", "detected": True}
                    for index in range(1, 56)
                ],
                "judgments": [{
                    "claim_id": "hwp-claim",
                    "model_status": "supported",
                    "human_status": "supported",
                    "evidence_sufficient": True,
                }],
            },
            {
                "sample_id": "pdf",
                "source_format": "pdf",
                "source_sha256": "3" * 64,
                "coverage_tags": ["representative"],
                "required_items": [{"item_id": "PDF-001", "detected": True}],
                "judgments": [{
                    "claim_id": "pdf-claim",
                    "model_status": "supported",
                    "human_status": "supported",
                    "evidence_sufficient": True,
                }],
            },
        ],
    }


def _bc_manifest(tmp_path: Path) -> Path:
    document = tmp_path / "representative.pdf"
    document.write_bytes(b"%PDF-1.4\nfixture")
    return _write_json(tmp_path / "bc.json", {
        "schema": "bidops.bc-e2e-run.v1",
        "api_base": "http://127.0.0.1:28787",
        "notice_id": 7,
        "actor_name": "E2E 담당자",
        "documents": [{"path": str(document), "role": "제안요청서"}],
        "analysis_retry_limit": 1,
    })


def test_quality_cli_emits_import_arguments_only_for_a_pass(tmp_path: Path, capsys) -> None:
    manifest = _write_json(tmp_path / "quality.json", _quality_manifest())

    assert score_quality_main([str(manifest)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema"] == "bidops.qwen-quality-result.v1"
    assert output["passed"] is True
    assert output["policy_import_arguments"][:2] == ["--expected-policy-sha256", "1" * 64]


def test_bc_cli_dry_run_validates_without_mutating_the_api(tmp_path: Path, capsys) -> None:
    manifest = _bc_manifest(tmp_path)

    assert run_bc_main([str(manifest), "--dry-run"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "analysis_retry_limit": 1,
        "api_base": "http://127.0.0.1:28787",
        "document_count": 1,
        "document_identities": [{"filename": "representative.pdf", "role": "제안요청서", "size_bytes": 16}],
        "notice_id": 7,
        "schema": "bidops.bc-e2e-plan.v1",
    }


def test_acceptance_actor_header_round_trips_unicode_without_raw_header_bytes(monkeypatch) -> None:
    actor = "E2E 담당자"
    encoded = actor_header_value(actor)
    assert encoded.isascii()
    assert validate_actor(encoded) == actor

    api = JsonAcceptanceApi("http://127.0.0.1:28787")
    observed = {}

    def send(request, *, retryable):
        observed["actor"] = request.get_header("X-bidops-actor-name")
        observed["retryable"] = retryable
        return b"{}"

    monkeypatch.setattr(api, "_send", send)
    assert api.request_json("POST", "/api/example", payload={}, actor=actor) == {}
    assert observed == {"actor": encoded, "retryable": False}
    assert actor_header_value("E2E Operator") == "E2E Operator"
    prefixed_ascii = "UTF-8''E2E Operator"
    assert actor_header_value(prefixed_ascii) == prefixed_ascii
    assert validate_actor(prefixed_ascii) == prefixed_ascii
    percent_ascii = "UTF-8''E2E%20Operator"
    assert validate_actor(percent_ascii) == percent_ascii
    for invalid in ("UTF-8''", "UTF-8''%ZZ", "UTF-8''%0A"):
        with pytest.raises(BundleServiceError) as error:
            validate_actor(invalid)
        assert error.value.code in {"actor_name_required", "actor_name_invalid"}


def test_t7_cli_dry_run_selects_the_agent_acceptance_plan(tmp_path: Path, capsys) -> None:
    manifest = _bc_manifest(tmp_path)

    assert run_bc_main([str(manifest), "--t7", "--dry-run"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema"] == "bidops.t7-e2e-plan.v1"
    assert output["workflow"] == "t7-mock-reference"
    assert output["api_base"] == "http://127.0.0.1:28787"
    assert output["document_count"] == 1


def test_bc_cli_refuses_a_target_that_was_not_exactly_confirmed(tmp_path: Path, capsys) -> None:
    manifest = _bc_manifest(tmp_path)

    assert run_bc_main([str(manifest), "--confirm-target", "http://127.0.0.1:38787"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["error"]["code"] == "target_not_confirmed"


def test_bc_evidence_publish_is_private_and_never_overwrites(tmp_path: Path) -> None:
    output = tmp_path / "bc-result.json"
    _write_evidence(output, {"passed": True})

    assert json.loads(output.read_text(encoding="utf-8")) == {"passed": True}
    assert os.stat(output).st_mode & 0o777 == 0o600
    with pytest.raises(BcE2EError) as error:
        _write_evidence(output, {"passed": False})
    assert error.value.code == "invalid_output"
    assert json.loads(output.read_text(encoding="utf-8")) == {"passed": True}
