from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.deep_review.cli import main as deep_review_cli_main
from app.deep_review.cli.run_bc_e2e import _write_evidence
from app.screening.cli import main as screening_cli_main
from app.deep_review.services.bc_e2e import BcE2EError, JsonAcceptanceApi, actor_header_value
from app.deep_review.services.document_bundles import BundleServiceError, validate_actor


PRESPEC_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "deep_review" / "prespec-run"


def run_prespec_main(argv: list[str]) -> int:
    """`python -m app.deep_review.cli run-prespec-e2e <인자>`와 같은 경로."""

    return deep_review_cli_main(["run-prespec-e2e", *argv])


def run_bc_main(argv: list[str]) -> int:
    """`python -m app.deep_review.cli run-bc-e2e <기존 인자>`와 같은 경로."""

    return deep_review_cli_main(["run-bc-e2e", *argv])


def score_quality_main(argv: list[str]) -> int:
    """`python -m app.screening.cli score-candidate-quality <기존 인자>`와 같은 경로."""

    return screening_cli_main(["score-candidate-quality", *argv])


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
    assert validate_actor(encoded, "utf-8-percent-v1") == actor

    api = JsonAcceptanceApi("http://127.0.0.1:28787")
    observed = {}

    def send(request, *, retryable):
        observed["actor"] = request.get_header("X-bidops-actor-name")
        observed["actor_format"] = request.get_header("X-bidops-actor-name-format")
        observed["retryable"] = retryable
        return b"{}"

    monkeypatch.setattr(api, "_send", send)
    assert api.request_json("POST", "/api/example", payload={}, actor=actor) == {}
    assert observed == {"actor": encoded, "actor_format": "utf-8-percent-v1", "retryable": False}
    assert actor_header_value("E2E Operator") == "E2E Operator"
    prefixed_ascii = "UTF-8''E2E Operator"
    assert actor_header_value(prefixed_ascii) == prefixed_ascii
    assert validate_actor(prefixed_ascii) == prefixed_ascii
    percent_ascii = "UTF-8''E2E%20Operator"
    assert validate_actor(percent_ascii) == percent_ascii
    mixed_ascii = "UTF-8''Alice%C3%A9"
    assert actor_header_value(mixed_ascii) == mixed_ascii
    assert validate_actor(mixed_ascii) == mixed_ascii
    for invalid in ("UTF-8''", "UTF-8''%ZZ", "UTF-8''%0A"):
        with pytest.raises(BundleServiceError) as error:
            validate_actor(invalid, "utf-8-percent-v1")
        assert error.value.code in {"actor_name_required", "actor_name_invalid"}
    with pytest.raises(BundleServiceError):
        validate_actor(encoded, "unknown-format")


def test_agent_cli_dry_run_selects_the_agent_acceptance_plan(tmp_path: Path, capsys) -> None:
    manifest = _bc_manifest(tmp_path)

    assert run_bc_main([str(manifest), "--agent", "--dry-run"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema"] == "bidops.agent-e2e-plan.v1"
    assert output["workflow"] == "agent-mock-reference"
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


def test_prespec_cli_dry_run_describes_the_fixture_without_a_workspace(
    tmp_path: Path, capsys
) -> None:
    """dry-run은 fixture만 읽고 workspace를 만들지 않는다 (명세 §12)."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert run_prespec_main([
        "--fixture", str(PRESPEC_FIXTURE),
        "--workspace", str(workspace),
        "--dry-run",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema"] == "bidops.prespec-e2e-plan.v1"
    assert output["workflow"] == "prespec-mock-reference"
    assert output["notice_keys"] == ["pre-1", "pre-5"]
    assert output["unsupported_attachment_count"] == 2
    assert list(workspace.iterdir()) == []


def test_prespec_cli_rejects_a_fixture_without_an_attachment_manifest(
    tmp_path: Path, capsys
) -> None:
    """manifest 없는 입력은 변경 전에 fail closed한다."""

    fixture = tmp_path / "fixture"
    (fixture / "run").mkdir(parents=True)

    assert run_prespec_main([
        "--fixture", str(fixture),
        "--workspace", str(tmp_path),
        "--dry-run",
    ]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_fixture"
