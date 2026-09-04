"""T-14 deterministic screening transport tests."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import socket

import pytest

import app.screening.mock_transport as mock_transport_module
from app.core.config import Settings
from app.screening.contracts import (
    canonical_json,
    validate_judgment,
    validate_perspective,
)
from app.screening.mock_transport import (
    MOCK_MODEL_DIGEST,
    MockScreeningTransport,
    MockScreeningTransportError,
)
from app.screening.model_adapter import ScreeningCallError, ScreeningModelClient, ScreeningStageRunner
from app.screening.policy import load_policy_file
from app.screening.prompts import (
    schema_for_stage,
)


NAMES = (
    "기술 적합성",
    "실적 정합성",
    "공공 SI 적합성",
    "사업성·자격 제약",
    "전략 부합",
)
PROFILE = {key: "모의 프로필 자리표시자" for key in ("2.1", "2.2", "2.3", "2.4", "5.2", "4.1")}


def _notice(notice_id: str) -> dict[str, object]:
    return {
        "notice_id": notice_id,
        "title": "모의 공고 제목",
        "agency": "모의 기관",
        "procurement_class": "공공 SI",
        "focus_matches": ["AI/데이터"],
        "performance_matches": [],
        "unknown_fields": [],
    }


def _base_judgment(value: dict[str, object]) -> dict[str, object]:
    return {
        key: value[key]
        for key in (
            "notice_id",
            "grade",
            "readiness",
            "primary_focus",
            "exclusion_category",
            "summary",
            "perspectives",
            "matched_performances",
            "counterarguments",
            "counterargument_resolutions",
            "verification_items",
            "next_action",
        )
    }


def _run(notice_id: str, *, transport: MockScreeningTransport | None = None):
    notice = _notice(notice_id)
    chosen = transport or MockScreeningTransport()
    result = ScreeningStageRunner(ScreeningModelClient(transport=chosen)).run(
        execution_id="mock-execution",
        notice_id=notice_id,
        policy=load_policy_file(),
        notice=notice,
        profile_sections=PROFILE,
    )
    return chosen, notice, result


def test_mock_transport_runs_all_seven_calls_through_the_real_adapter() -> None:
    transport, notice, result = _run("notice-1")

    assert len(transport.generate_requests) == 7
    assert [item.stage for item in result.telemetry] == [*NAMES, "counterargument", "synthesis"]
    assert all(item.model_digest == MOCK_MODEL_DIGEST for item in result.telemetry)
    checked = validate_judgment(_base_judgment(result.judgment), notice=notice)
    assert checked["notice_id"] == notice["notice_id"]

    match = checked["matched_performances"][0]
    assert match["status"] == "unknown"
    assert "모의" in match["name"] and "실적" in match["name"]
    assert "모의" in match["source"] and "모의" in match["match_reason"]
    evidence = checked["perspectives"][0]["evidence"][0]
    assert evidence["status"] == "unknown"
    assert "모의" in evidence["source"] and "모의" in evidence["fact"]


def test_mock_judgment_is_validated_by_the_authoritative_validator() -> None:
    transport, notice, result = _run("notice-2")
    judgment = _base_judgment(result.judgment)

    # The orchestrator's synthesis call supplied validate_judgment as its
    # validator.  Calling the same validator again also proves the mock did
    # not rely on an alternate output contract.
    assert validate_judgment(judgment, notice=notice) == judgment
    assert len(transport.generate_requests) == 7


def test_same_notice_produces_byte_identical_mock_judgment_output() -> None:
    first_transport, first_notice, first = _run("notice-17")
    second_transport, second_notice, second = _run("notice-17")

    first_bytes = canonical_json(_base_judgment(first.judgment)).encode("utf-8")
    second_bytes = canonical_json(_base_judgment(second.judgment)).encode("utf-8")
    assert first_bytes == second_bytes
    assert first_notice == second_notice
    assert first_transport.generate_requests[-1]["response_format"] == second_transport.generate_requests[-1]["response_format"]


def test_mock_covers_all_grades_and_valid_readiness_cross_rules() -> None:
    rows: list[dict[str, object]] = []
    for number in range(1, 41):
        _transport, notice, result = _run(f"notice-{number}")
        judgment = _base_judgment(result.judgment)
        assert validate_judgment(judgment, notice=notice)
        rows.append(judgment)

    assert {row["grade"] for row in rows} == {"우선 검토", "검토 권장", "관찰 대상", "제외"}
    assert {row["readiness"] for row in rows} >= {"확인 완료", "부분 확인 필요", "참여 불가 확인", "해당 없음"}
    for row in rows:
        if row["grade"] == "제외":
            assert row["readiness"] in {"해당 없음", "참여 불가 확인"}
            assert isinstance(row["exclusion_category"], str)
        else:
            assert row["exclusion_category"] is None
        blocking_unknown = [
            item
            for item in row["verification_items"]
            if item["blocking"] is True and item["status"] == "미확인"
        ]
        if row["readiness"] == "확인 완료":
            assert not blocking_unknown
        if row["readiness"] == "부분 확인 필요":
            assert row["verification_items"]
        if row["readiness"] == "참여 불가 확인":
            assert any(item["blocking"] is True for item in row["verification_items"])


@pytest.mark.parametrize("failure_mode", ["schema_violation", "evidence_missing"])
def test_failure_mode_is_retried_twice_then_raises_a_bounded_call_error(failure_mode: str) -> None:
    transport = MockScreeningTransport(failure_mode=failure_mode)
    with pytest.raises(ScreeningCallError) as caught:
        ScreeningModelClient(transport=transport).generate(
            "모의 입력",
            schema_for_stage(NAMES[0]),
            stage=NAMES[0],
            validator=lambda value: validate_perspective(value, expected_name=NAMES[0]),
        )

    assert caught.value.failure_type == failure_mode
    assert len(caught.value.attempts) == 2
    assert len(transport.generate_requests) == 2


def _create(transport: MockScreeningTransport, prompt: str, schema: object) -> dict:
    """어댑터가 보내는 것과 같은 모양의 요청 하나."""

    return transport.create(
        model=Settings().vllm_screening_model,
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": prompt}],
        response_format={"type": "json_schema", "json_schema": {"name": "n", "strict": True, "schema": schema}},
        max_tokens=2048,
    )


def _content(response: dict) -> dict:
    return json.loads(response["choices"][0]["message"]["content"])


def test_judgment_notice_identity_is_strictly_extracted_from_canonical_json() -> None:
    schema = schema_for_stage("judgment.v3")
    valid_prompt = "notice_json=" + canonical_json(_notice("notice-strict"))
    transport = MockScreeningTransport()
    valid = _create(transport, valid_prompt, schema)
    assert _content(valid)["notice_id"] == "notice-strict"

    with pytest.raises(MockScreeningTransportError, match="canonical"):
        _create(transport, "notice_json={}", schema)
    with pytest.raises(MockScreeningTransportError, match="missing"):
        _create(transport, "no notice", schema)


def test_screening_mock_setting_is_explicit_and_defaults_to_vllm() -> None:
    assert Settings().screening_provider == "vllm"
    with pytest.raises(ValueError, match="mock screening provider"):
        Settings(screening_provider="mock", reference_workflow_mode=False)
    settings = Settings(screening_provider="mock", reference_workflow_mode=True)
    assert settings.screening_provider == "mock"


def test_application_runtime_injects_mock_only_for_the_explicit_provider(tmp_path: Path) -> None:
    from app.runtime import ApplicationRuntime

    settings = Settings(
        bidops_root=tmp_path,
        data_dir=tmp_path / "data",
        attachments_dir=tmp_path / "attachments",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        screening_provider="mock",
        reference_workflow_mode=True,
    )
    runtime = ApplicationRuntime(settings)
    try:
        assert isinstance(runtime.model_client.transport, MockScreeningTransport)
        assert runtime.model_client.inspect_model().digest == MOCK_MODEL_DIGEST
    finally:
        runtime.shutdown()


def test_mock_identity_and_telemetry_use_the_named_synthetic_revision() -> None:
    transport = MockScreeningTransport()
    identity = ScreeningModelClient(transport=transport).inspect_model()
    assert identity.digest == MOCK_MODEL_DIGEST
    assert identity.digest != "a" * 64


def test_mock_transport_does_not_import_or_open_network_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    module_source = inspect.getsource(mock_transport_module)
    assert "urllib" not in module_source
    assert "socket" not in module_source

    def fail_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("screening mock must not open a socket")

    monkeypatch.setattr(socket, "socket", fail_socket)
    transport = MockScreeningTransport()
    served = transport.models()
    generated = _create(transport, "not a stage prompt", schema_for_stage(NAMES[0]))
    assert served["data"][0]["model_revision"] == MOCK_MODEL_DIGEST
    assert served["data"][0]["id"] == Settings().vllm_screening_model
    assert _content(generated)["name"] == NAMES[0]


def test_stage_selection_uses_format_required_keys_not_prompt_text() -> None:
    transport = MockScreeningTransport()
    response = _create(
        transport,
        "이 텍스트는 synthesis judgment counterargument라는 단어를 포함한다.",
        schema_for_stage(NAMES[1]),
    )
    assert _content(response)["name"] == NAMES[1]
