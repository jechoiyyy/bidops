"""사전규격 mock 종단 실행 (명세 §2 완료 기준 1·§12).

저장소만으로 도는 검사다. vLLM·Ollama·나라장터 주소를 부르지 않고, 첨부는
fixture bytes, 판정·개요·심층은 mock transport이며 회사 원문·실제 공고는
들어 있지 않다.

**선별 모듈을 import하지 않는다.** 판정 적재는 lifecycle 확장점의 몫이므로
이 검사는 CLI에 확장점 제공자 이름을 문자열로 넘기고, deep_review 폴더의
경계 규칙(§4)을 그대로 지킨다.
"""

from __future__ import annotations

from importlib import import_module
import json
from pathlib import Path

import pytest

from app.deep_review.cli import main as deep_review_cli_main


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "deep_review" / "prespec-run"
#: 회차 적재 hook을 등록하는 제공자. 이름만 넘기고 import는 CLI가 한다.
SCREENING_PROVIDER = "app.screening:register_lifecycle_extensions"


def run_cli(argv: list[str]) -> int:
    """`python -m app.deep_review.cli run-prespec-e2e <인자>`와 같은 경로."""

    return deep_review_cli_main(["run-prespec-e2e", *argv])


def _mutating_argv(tmp_path: Path) -> list[str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return [
        "--fixture", str(FIXTURE),
        "--workspace", str(workspace),
        "--confirm-workspace", str(workspace),
        "--output", str(tmp_path / "prespec-e2e-result.json"),
        "--extension-provider", SCREENING_PROVIDER,
    ]


def _provider_available() -> bool:
    """판정 제공자가 이 배포에 있는가.

    모듈 격리 조합(`verify_module_isolation.sh`)은 선별 폴더 없이
    `tests/deep_review`를 돌린다. 그때는 회차 적재 hook이 없어 종단 실행이
    성립하지 않으므로, 조용히 통과시키지 않고 사유가 보이는 skip으로 남긴다.
    """

    module_name, _, attribute = SCREENING_PROVIDER.partition(":")
    try:
        return callable(getattr(import_module(module_name), attribute))
    except (ImportError, AttributeError):
        return False


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """한 번만 완주시키고 그 증거 JSON을 여러 검사가 나눠 본다."""

    if not _provider_available():
        pytest.skip(f"판정 제공자({SCREENING_PROVIDER})가 없어 종단 실행을 확인할 수 없다")
    tmp_path = tmp_path_factory.mktemp("prespec-e2e")
    argv = _mutating_argv(tmp_path)
    assert run_cli(argv) == 0
    return json.loads((tmp_path / "prespec-e2e-result.json").read_text(encoding="utf-8"))


def _notice(evidence: dict, notice_key: str) -> dict:
    return next(item for item in evidence["notices"] if item["notice_key"] == notice_key)


# --- CLI 계약 ----------------------------------------------------------------


def test_dry_run_prints_the_bounded_plan_without_touching_the_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert run_cli([
        "--fixture", str(FIXTURE),
        "--workspace", str(workspace),
        "--dry-run",
    ]) == 0

    plan = json.loads(capsys.readouterr().out)
    assert plan["schema"] == "bidops.prespec-e2e-plan.v1"
    assert plan["workflow"] == "prespec-mock-reference"
    assert plan["notice_count"] == 2
    assert plan["attachment_count"] == 5
    assert plan["unsupported_attachment_count"] == 2
    # dry-run은 아무것도 만들지 않는다.
    assert list(workspace.iterdir()) == []


def test_a_mutating_run_requires_the_exact_confirmed_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert run_cli([
        "--fixture", str(FIXTURE),
        "--workspace", str(workspace),
        "--confirm-workspace", str(tmp_path / "other"),
        "--output", str(tmp_path / "result.json"),
    ]) == 2

    assert json.loads(capsys.readouterr().out)["error"]["code"] == "workspace_not_confirmed"


def test_evidence_output_is_private_and_never_overwritten(tmp_path: Path) -> None:
    import os

    from app.deep_review.services.prespec_e2e import PreSpecE2EError, write_evidence

    output = tmp_path / "result.json"
    write_evidence(output, {"passed": True})

    assert json.loads(output.read_text(encoding="utf-8")) == {"passed": True}
    assert os.stat(output).st_mode & 0o777 == 0o600
    with pytest.raises(PreSpecE2EError) as error:
        write_evidence(output, {"passed": False})
    assert error.value.code == "invalid_output"
    assert json.loads(output.read_text(encoding="utf-8")) == {"passed": True}


# --- 종단 실행 ---------------------------------------------------------------


def test_the_run_ingests_the_round_and_records_the_mock_judgments(evidence: dict) -> None:
    assert evidence["schema"] == "bidops.prespec-e2e-result.v1"
    assert evidence["workflow"] == "prespec-mock-reference"
    assert evidence["passed"] is True
    assert evidence["ingest"]["notices"] == 2
    assert evidence["ingest"]["judgments"] == 2


def test_every_notice_reaches_a_confirmed_bundle_that_excludes_the_zip(evidence: dict) -> None:
    """형식 밖 첨부는 비차단 issue로만 남고 확정을 막지 않는다 (명세 §5·§6.2)."""

    assert evidence["attachments"]["completed"] == 3
    assert evidence["attachments"]["unsupported_excluded"] == 2
    for notice in evidence["notices"]:
        bundle = notice["bundle"]
        assert bundle["status"] == "ready"
        assert bundle["confirmed_by"] == "auto-preparation"
        assert bundle["blocking_issue_count"] == 0
        assert bundle["issue_codes"] == ["unsupported_attachment_excluded"]


def test_the_overview_completes_on_the_mock_transport(evidence: dict) -> None:
    for notice in evidence["notices"]:
        overview = notice["overview"]
        assert overview["status"] == "completed"
        assert overview["result"] == "추진 검토"
        assert overview["transport"] == "mock"
        # 결정적 mock attempt는 완료할 수 없다(ADR·DB CHECK). 그래서 이 실행의
        # 개요 표식은 `unmeasured_reference`이며 운영 완료 근거가 아니다.
        assert overview["quality_status"] == "unmeasured_reference"


def test_reference_flow_uses_human_creation_without_a_company_fit(evidence: dict) -> None:
    notice = _notice(evidence, "pre-1")

    assert notice["sw_business_status"] == "Y"
    assert notice["effective_grade"] == "우선 검토"
    assert notice["auto_preparation_status"] == "deep_review_started"
    assert notice["auto_preparation_reason"] is None
    review = notice["deep_review"]
    assert review is not None
    assert review["status"] == "completed"
    assert review["created_by_actor_kind"] == "human"
    assert review["analysis_transport"] == "mock"
    assert review["quality_status"] == "mock_reference"
    assert [stage["stage"] for stage in review["stages"]] == [
        "requirements_and_evaluation",
        "delivery_risk_economics",
        "synthesis_and_validation",
    ]


def test_a_non_sw_notice_waits_for_a_human_click(evidence: dict) -> None:
    notice = _notice(evidence, "pre-5")

    assert notice["sw_business_status"] == "N"
    assert notice["effective_grade"] == "우선 검토"
    assert notice["auto_preparation_status"] == "deep_review_ready_for_click"
    assert notice["auto_preparation_reason"] == "not_sw_business"
    assert notice["deep_review"] is None


def test_the_report_carries_the_deterministic_checks_and_the_bundle_limitation(
    evidence: dict,
) -> None:
    review = _notice(evidence, "pre-1")["deep_review"]

    assert review["validation_status"] == "passed"
    assert {check["check_type"] for check in review["validation_checks"]} >= {
        "report_contract",
        "requirement_inventory",
        "segment_coverage",
    }
    assert "document_bundle_limitations" in review["report_sections"]
    assert review["document_bundle_limitation_codes"] == ["unsupported_attachment_excluded"]


def test_the_final_opinion_closes_the_flow(evidence: dict) -> None:
    opinion = _notice(evidence, "pre-1")["deep_review"]["final_opinion"]

    assert opinion["sequence"] == 1
    assert opinion["validation_status_at_opinion"] == "passed"
    assert opinion["acknowledged_validation_failure"] is False


def test_the_evidence_carries_no_source_text_prompt_or_storage_location(
    evidence: dict,
) -> None:
    """증거 JSON에 원문·프롬프트·object key·경로가 없어야 한다 (명세 §7)."""

    encoded = json.dumps(evidence, ensure_ascii=False)
    for forbidden in ("model-response/", "quarantine/", "structure/", "source/", "/tmp/", "prompt"):
        assert forbidden not in encoded
    # 회사 프로필 본문과 첨부 원문 문장이 새어 나가지 않는다.
    assert "합성 사업 범위 문장" not in encoded
    assert "observed_activity_types" not in encoded
