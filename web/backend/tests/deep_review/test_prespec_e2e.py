"""사전규격 mock 종단 실행 (명세 §2 완료 기준 1·§12).

저장소만으로 도는 검사다. vLLM·Ollama·나라장터 주소를 부르지 않고, 첨부는
fixture bytes이며 회사 원문·실제 공고는 들어 있지 않다.

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
    assert plan["attachment_count"] == 6
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

    assert evidence["attachments"]["completed"] == 4
    assert evidence["attachments"]["unsupported_excluded"] == 2
    for notice in evidence["notices"]:
        bundle = notice["bundle"]
        assert bundle["status"] == "ready"
        assert bundle["confirmed_by"] == "auto-preparation"
        assert bundle["blocking_issue_count"] == 0
        assert bundle["issue_codes"] == ["unsupported_attachment_excluded"]


def test_every_notice_gets_one_completed_overview_run(evidence: dict) -> None:
    """개요 슬롯이 mock transport로 두 건을 모두 `completed`로 닫는다.

    fixture 제안요청서에는 절 제목이 없으므로 범위는 fallback이고, 그 사실이
    사유 코드로 남는다 — 추측으로 자른 것이 아니다.
    """

    for notice in evidence["notices"]:
        overview = notice["overview"]
        assert overview["status"] == "completed"
        assert overview["range_source"] == "fallback"
        assert overview["range_reason_codes"][-1] == "range_fallback_head"
        # 초안 1회 + 의미 검토 1회. 재생성은 일어나지 않았다.
        assert overview["call_count"] == 2
    assert evidence["auto_started_notice_keys"] == ["pre-1"]


def test_sw_business_splits_automatic_start_from_the_human_click(evidence: dict) -> None:
    """SW=Y는 심층 검토까지, SW=N은 사람 클릭 자리에서 멈춘다.

    `not_sw_business`는 결함이 아니라 규칙이 그대로 동작한 결과다.
    """

    assert evidence["bundle_ready_notice_keys"] == []
    assert evidence["awaiting_click_notice_keys"] == ["pre-5"]
    by_key = {notice["notice_key"]: notice for notice in evidence["notices"]}
    assert all(notice["effective_grade"] == "우선 검토" for notice in by_key.values())
    assert by_key["pre-1"]["auto_preparation_status"] == "deep_review_started"
    assert by_key["pre-1"]["auto_preparation_reason"] is None
    assert by_key["pre-5"]["auto_preparation_status"] == "deep_review_ready_for_click"
    assert by_key["pre-5"]["auto_preparation_reason"] == "not_sw_business"
    assert by_key["pre-5"]["deep_review"] is None


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
