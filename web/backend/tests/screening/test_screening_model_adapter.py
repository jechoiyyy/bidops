from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.screening.contracts import (
    ContractViolation,
    add_two_axis_metadata,
    validate_counterargument,
    validate_judgment,
    validate_perspective,
    canonical_json,
)
from app.core.config import get_settings
from app.screening.contracts import ModelIdentity
from app.screening.model_adapter import (
    ModelInspectionError,
    ScreeningCallError,
    ScreeningModelClient,
    ScreeningStageRunner,
)
from app.screening.policy import load_policy_file
from app.screening.prompts import PromptAssemblyError, assemble_counterargument_prompt, assemble_perspective_prompt, assemble_synthesis_prompt, project_notice_for_prompt, schema_for_stage
from tests.fakes import DECLARED_REVISION, FakeScreeningTransport, completion


NAMES = ("기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합")
NOTICE = {
    "notice_id": "notice-1",
    "title": "데이터 플랫폼 구축",
    "agency": "기관",
    "procurement_class": "공공 SI",
    "focus_matches": ["AI/데이터"],
    "performance_matches": [],
    "unknown_fields": [],
}
PROFILE = {key: f"profile-{key}" for key in ("2.1", "2.2", "2.3", "2.4", "5.2", "4.1")}


MODEL = "qwen3.8-27B"


def _client(transport: FakeScreeningTransport) -> ScreeningModelClient:
    """설정 해석을 거치지 않고 주입된 transport로만 도는 어댑터."""

    return ScreeningModelClient(settings=get_settings(), transport=transport)


def perspective(name: str) -> dict[str, object]:
    return {"name": name, "assessment": "적합", "reason": "이 관점의 충분한 판단 근거입니다", "evidence": [{"source": "title", "status": "confirmed", "fact": "공고 제목을 확인했습니다"}]}


def valid_script() -> list[dict[str, object]]:
    items = [completion(perspective(name)) for name in NAMES]
    counter = ["예산과 요구 역할의 세부 범위가 회사 수행 조건과 다를 수 있다"]
    items.append(completion({"counterarguments": counter}))
    items.append(completion({
        "notice_id": "notice-1",
        "grade": "검토 권장",
        "readiness": "확인 완료",
        "primary_focus": "AI/데이터",
        "exclusion_category": None,
        "summary": "다섯 관점과 반론을 종합한 판단입니다",
        "perspectives": [perspective(name) for name in NAMES],
        "matched_performances": [],
        "counterarguments": counter,
        "counterargument_resolutions": [{"counterargument": counter[0], "status": "추가 확인", "reflection": "담당자가 범위를 추가 확인합니다"}],
        "verification_items": [],
        "next_action": "담당자가 원문 범위를 확인합니다",
    }))
    return items


def test_seven_stage_requests_are_strict_and_minimized() -> None:
    transport = FakeScreeningTransport(valid_script())
    result = ScreeningStageRunner(_client(transport)).run(
        execution_id="scr-test", notice_id="notice-1", policy=load_policy_file(), notice=NOTICE, profile_sections=PROFILE
    )
    assert len(transport.generate_requests) == 7
    first = transport.generate_requests[0]
    assert first["model"] == MODEL
    assert first["messages"][0] == {"role": "system", "content": "JSON 외 텍스트를 출력하지 마라. 제공되지 않은 사실을 만들지 마라."}
    assert first["messages"][1]["role"] == "user"
    assert first.get("stream") in (None, False)
    assert first["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    # num_predict는 OpenAI 호환 `max_tokens`로만 대응된다. num_ctx는 대응
    # 파라미터가 없으므로 요청이 아니라 attempt telemetry에만 남는다.
    assert first["max_tokens"] == 2048
    assert "num_ctx" not in first and "num_predict" not in first and "options" not in first
    assert first["timeout"] == 300.0
    assert "EXTRA" not in first["messages"][1]["content"]
    for index, name in enumerate(NAMES):
        schema = transport.generate_requests[index]["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["name"]["enum"] == [name]
        assert schema["additionalProperties"] is False
    assert transport.generate_requests[5]["response_format"]["json_schema"]["schema"]["required"] == ["counterarguments"]
    assert transport.generate_requests[6]["response_format"]["json_schema"]["schema"]["properties"]["exclusion_category"]["enum"][0] is None
    assert len(result.telemetry) == 7
    assert all(item.started_at.tzinfo is not None for item in result.telemetry)
    assert all(item.num_ctx == 16384 for item in result.telemetry)


def test_generation_config_maps_num_predict_to_max_tokens_per_stage() -> None:
    transport = FakeScreeningTransport(valid_script())
    ScreeningStageRunner(_client(transport)).run(
        execution_id="scr-test", notice_id="notice-1", policy=load_policy_file(), notice=NOTICE, profile_sections=PROFILE
    )
    budgets = [request["max_tokens"] for request in transport.generate_requests]
    assert budgets == [2048] * 6 + [4096]


def test_malformed_json_retries_once_without_raw_body_in_error() -> None:
    transport = FakeScreeningTransport([
        completion(None, raw="{not-json-secret"),
        completion(perspective(NAMES[0])),
    ])
    client = _client(transport)
    result = client.generate(
        "원래 입력", {}, stage=NAMES[0], validator=lambda value: validate_perspective(value, expected_name=NAMES[0])
    )
    assert result.metadata.attempt_no == 2
    assert len(transport.generate_requests) == 2
    assert "not-json-secret" not in str(result.metadata)


def test_raw_rejected_output_is_not_in_failure_exception_or_chaining() -> None:
    sentinel = "RAW_MODEL_RESPONSE_SENTINEL"
    bad = completion(None, raw=sentinel)
    transport = FakeScreeningTransport([bad, bad])
    with pytest.raises(ScreeningCallError) as caught:
        _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert sentinel not in repr(caught.value)
    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None
    assert all(sentinel not in repr(metadata) for metadata in caught.value.attempts)


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"name":"기술 적합성","name":"기술 적합성","assessment":"적합","reason":"충분한 관점별 판단 근거입니다","evidence":[]}',
        "[]",
    ],
)
def test_malformed_duplicate_or_non_object_json_is_bounded_schema_failure(raw: str) -> None:
    bad = completion(None, raw=raw)
    transport = FakeScreeningTransport([bad, bad])
    with pytest.raises(ScreeningCallError) as caught:
        _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert caught.value.failure_type == "schema_violation"
    assert len(caught.value.attempts) == 2


@pytest.mark.parametrize(
    "change",
    [
        lambda item: item.update({"extra": 1}),
        lambda item: item.pop("reason"),
        lambda item: item.update({"assessment": 1}),
        lambda item: item.update({"assessment": "invalid"}),
    ],
)
def test_perspective_extra_missing_type_enum_are_schema_violations(change) -> None:
    bad = perspective(NAMES[0])
    change(bad)
    with pytest.raises(ContractViolation) as caught:
        validate_perspective(bad, expected_name=NAMES[0])
    assert caught.value.failure_type == "schema_violation"


def test_counterargument_repetition_is_not_retried() -> None:
    value = {"counterarguments": ["추가 확인이 필요하다", "추가 확인이 필요하다"]}
    transport = FakeScreeningTransport([completion(value), completion(value)])
    with pytest.raises(ScreeningCallError) as caught:
        _client(transport).generate(
            "prompt", {}, stage="counterargument", validator=lambda item: (_ for _ in ()).throw(
                ContractViolation("counterargument repetition", failure_type="counterargument_repetition")
            )
        )
    assert caught.value.failure_type == "counterargument_repetition"
    assert len(transport.generate_requests) == 1


def test_inspection_served_id_or_declared_revision_failure_is_distinguishable() -> None:
    with pytest.raises(ModelInspectionError) as caught:
        _client(FakeScreeningTransport(models_document={"data": [{"id": "wrong"}]})).inspect_model()
    assert caught.value.status_code == 503
    assert caught.value.failure_type == "model_inspection"

    # 배포 선언 revision에 값이 있으면 64자 digest여야 한다.
    with pytest.raises(ModelInspectionError):
        _client(FakeScreeningTransport(model_revision="A" * 64)).inspect_model()
    with pytest.raises(ModelInspectionError):
        _client(FakeScreeningTransport(model_revision="a" * 63)).inspect_model()

    # 선언이 비면 대조할 기준이 없다. MVP 기간에는 통과한다(ADR-0050 완화).
    identity = _client(FakeScreeningTransport(model_revision="")).inspect_model()
    assert identity == ModelIdentity(MODEL, "")


@pytest.mark.parametrize(
    "document",
    [
        {"data": []},
        {"data": [{"id": "wrong"}]},
        {"data": "not-a-list"},
        {},
        {"data": [{"id": MODEL, "model_revision": "b" * 64}]},
    ],
)
def test_inspection_requires_the_configured_model_in_served_ids(document: dict[str, object]) -> None:
    with pytest.raises(ModelInspectionError) as caught:
        _client(FakeScreeningTransport(models_document=document)).inspect_model()
    assert caught.value.__cause__ is None
    assert "sha256" not in str(caught.value)


def test_inspection_reads_models_once_and_caches_identity() -> None:
    transport = FakeScreeningTransport()
    client = _client(transport)
    first = client.inspect_model()
    second = client.inspect_model()
    assert first == second
    assert first == ModelIdentity(MODEL, DECLARED_REVISION)
    assert transport.models_calls == 1


def test_inspection_refresh_rereads_served_models() -> None:
    documents = iter((
        {"data": [{"id": MODEL}]},
        {"data": [{"id": "다른 모델"}]},
    ))
    transport = FakeScreeningTransport(models_document=lambda: next(documents))
    client = _client(transport)
    assert client.inspect_model().digest == DECLARED_REVISION
    assert client.inspect_model().digest == DECLARED_REVISION
    with pytest.raises(ModelInspectionError):
        client.inspect_model(refresh=True)
    assert transport.models_calls == 2


def test_generate_inspection_failure_is_not_reclassified_and_has_no_cause_sentinel() -> None:
    sentinel = "INSPECTION_SECRET_SENTINEL"
    with pytest.raises(ModelInspectionError) as caught:
        _client(FakeScreeningTransport(models_document=ConnectionResetError(sentinel))).generate(
            "prompt", {}, stage=NAMES[0]
        )
    assert caught.value.__cause__ is None
    assert sentinel not in str(caught.value)
    assert not isinstance(caught.value, ScreeningCallError)


@pytest.mark.parametrize(
    "envelope",
    [
        {"model": "다른모델"},
        {"model": MODEL, "model_revision": "b" * 64},
        {"model": MODEL, "revision": "b" * 64},
    ],
)
def test_generate_identity_mismatch_is_a_bounded_failure(envelope: dict[str, object]) -> None:
    bad = {**completion(perspective(NAMES[0])), **envelope}
    transport = FakeScreeningTransport([bad, bad])
    with pytest.raises(ScreeningCallError) as caught:
        _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert caught.value.failure_type == "schema_violation"


@pytest.mark.parametrize("failure", [TimeoutError("secret"), ConnectionError("secret"), ConnectionResetError("secret")])
def test_timeout_transport_retry_is_same_prompt_with_fresh_span(failure: BaseException) -> None:
    transport = FakeScreeningTransport([failure, completion(perspective(NAMES[0]))])
    client = _client(transport)
    result = client.generate("fixed prompt", schema_for_stage(NAMES[0]), stage=NAMES[0], validator=lambda item: validate_perspective(item, expected_name=NAMES[0]))
    requests = transport.generate_requests
    assert [request["messages"][1]["content"] for request in requests] == ["fixed prompt", "fixed prompt"]
    assert result.attempts[0].attempt_no == 1 and result.metadata.attempt_no == 2
    assert result.attempts[0].trace_id == result.metadata.trace_id
    assert result.attempts[0].span_id != result.metadata.span_id
    assert result.attempts[0].failure_type == "timeout"


@pytest.mark.parametrize("finish_reason", ["length", "max_tokens"])
def test_truncation_retry_is_same_prompt_and_same_output_cap(finish_reason: str) -> None:
    first = completion(None, raw="{", finish_reason=finish_reason)
    transport = FakeScreeningTransport([first, completion(perspective(NAMES[0]))])
    result = _client(transport).generate(
        "fixed prompt", schema_for_stage(NAMES[0]), stage=NAMES[0], validator=lambda item: validate_perspective(item, expected_name=NAMES[0])
    )
    assert result.attempts[0].failure_type == "truncated_output"
    assert transport.generate_requests[0]["messages"] == transport.generate_requests[1]["messages"]
    assert transport.generate_requests[0]["max_tokens"] == transport.generate_requests[1]["max_tokens"]


@pytest.mark.parametrize("usage", [{"prompt_tokens": True}, {"eval_count": 1, "prompt_tokens": 1.0}, {"completion_tokens": "1"}, {"completion_tokens": -1}])
def test_invalid_usage_metric_is_schema_violation_not_coerced(usage: dict[str, object]) -> None:
    bad = completion(perspective(NAMES[0]), usage=usage)
    transport = FakeScreeningTransport([bad, bad])
    with pytest.raises(ScreeningCallError) as caught:
        _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert caught.value.failure_type == "schema_violation"
    assert len(caught.value.attempts) == 2


def test_missing_usage_is_nullable_and_finish_reason_becomes_done_reason() -> None:
    transport = FakeScreeningTransport([completion(perspective(NAMES[0]))])
    result = _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert result.metadata.prompt_eval_count is None
    assert result.metadata.eval_count is None
    assert result.metadata.done_reason == "stop"


def test_usage_tokens_map_to_counts_and_ollama_only_durations_stay_null() -> None:
    """OpenAI 호환 응답에는 서버 측 소요 시간 계측이 없다.

    없는 값을 client 측 경과 시간으로 채우면 지난 회차의 Ollama 계측과 뜻이
    다른 숫자가 같은 컬럼에 섞인다. 측정 불가는 `null`로 남긴다.
    """

    scripted = completion(perspective(NAMES[0]), usage={"prompt_tokens": 0, "completion_tokens": 7, "total_tokens": 7})
    result = _client(FakeScreeningTransport([scripted])).generate(
        "p", schema_for_stage(NAMES[0]), stage=NAMES[0]
    )
    assert result.metadata.prompt_eval_count == 0
    assert result.metadata.eval_count == 7
    assert result.metadata.prompt_eval_duration_ns is None
    assert result.metadata.eval_duration_ns is None
    assert result.metadata.load_duration_ns is None
    assert result.metadata.total_duration_ns is None


def test_non_string_finish_reason_is_schema_violation() -> None:
    bad = completion(perspective(NAMES[0]), finish_reason=3)
    transport = FakeScreeningTransport([bad, bad])
    with pytest.raises(ScreeningCallError) as caught:
        _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert caught.value.failure_type == "schema_violation"


def test_model_name_comes_from_settings_not_from_source_code() -> None:
    settings = get_settings().model_copy(update={"vllm_screening_model": "배포가-정한-모델"})
    transport = FakeScreeningTransport(
        [completion(perspective(NAMES[0]), model="배포가-정한-모델")],
        model="배포가-정한-모델",
    )
    client = ScreeningModelClient(settings=settings, transport=transport)
    assert client.inspect_model().model_name == "배포가-정한-모델"
    result = client.generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert transport.generate_requests[0]["model"] == "배포가-정한-모델"
    assert result.metadata.model_name == "배포가-정한-모델"


def test_a_malformed_declared_revision_fails_closed_before_any_call() -> None:
    """선언 revision에 값이 있는데 64자 hex가 아니면 부르기 전에 멈춘다."""

    transport = FakeScreeningTransport(model_revision="not-a-digest")
    with pytest.raises(ModelInspectionError):
        _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert transport.generate_requests == []


def test_a_missing_declared_revision_still_calls_the_model() -> None:
    """선언이 비면 통과한다 (ADR-0050 MVP 완화). 대조할 기준이 없을 뿐이다."""

    transport = FakeScreeningTransport([completion(perspective(NAMES[0]))], model_revision="")
    result = _client(transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert result.metadata.model_name == MODEL
    assert len(transport.generate_requests) == 1


def test_prompt_projection_excludes_raw_and_unknown_secret_and_accepts_braces_in_input() -> None:
    policy = load_policy_file()
    notice = {**NOTICE, "raw_source": "RAW_SECRET", "secret_body": "EXTRA_SECRET", "title": "{unsafe}"}
    perspectives = [perspective(name) for name in NAMES]
    counter = {"counterarguments": ["이 공고 예산 범위와 수행 역할이 다를 수 있다"]}
    counter_prompt = assemble_counterargument_prompt(policy, notice, perspectives)
    synthesis_prompt = assemble_synthesis_prompt(policy, notice, perspectives, counter)
    assert "RAW_SECRET" not in counter_prompt.user_message + synthesis_prompt.user_message
    assert "EXTRA_SECRET" not in counter_prompt.user_message + synthesis_prompt.user_message
    assert "{unsafe}" in counter_prompt.user_message + synthesis_prompt.user_message


def test_placeholder_values_are_single_pass_canonical_json_for_all_three_prompt_stages() -> None:
    policy = load_policy_file()
    notice = {
        **NOTICE,
        "title": 'literal {perspectives_json} and "quoted"',
        "attachments": [{"name": "file {counterarguments_json}", "quote": '"x"'}],
    }
    profile = {**PROFILE, "2.1": 'profile {company_profile_sections_json} "quoted"'}
    perspectives = [perspective(name) for name in NAMES]
    perspectives[0]["reason"] = 'reason with {counterarguments_json} and "quotes"'
    counter = {"counterarguments": ['specific {notice_json} "counter"']}

    perspective_prompt = assemble_perspective_prompt(policy, NAMES[0], notice, profile)
    counter_prompt = assemble_counterargument_prompt(policy, notice, perspectives)
    synthesis_prompt = assemble_synthesis_prompt(policy, notice, perspectives, counter)

    # The strings are canonical JSON values, so parse the exact inserted
    # lines and verify braces/quotes survived as data.
    perspective_notice = perspective_prompt.user_message.split("notice_json=", 1)[1].split("\n", 1)[0]
    perspective_profile = perspective_prompt.user_message.split("company_profile_sections_json=", 1)[1].split("\n", 1)[0]
    counter_notice = counter_prompt.user_message.split("notice_json=", 1)[1].split("\n", 1)[0]
    counter_perspectives = counter_prompt.user_message.split("perspectives_json=", 1)[1].split("\n", 1)[0]
    synthesis_notice = synthesis_prompt.user_message.split("notice_json=", 1)[1].split("\n", 1)[0]
    synthesis_perspectives = synthesis_prompt.user_message.split("perspectives_json=", 1)[1].split("\n", 1)[0]
    synthesis_counterarguments = synthesis_prompt.user_message.split("counterarguments_json=", 1)[1].split("\n", 1)[0]

    assert json.loads(perspective_notice) == {
        "title": notice["title"], "procurement_class": notice["procurement_class"],
        "focus_matches": notice["focus_matches"], "unknown_fields": notice["unknown_fields"],
    }
    assert json.loads(perspective_profile) == {"2.1": profile["2.1"], "2.2": PROFILE["2.2"]}
    assert json.loads(counter_notice) == project_notice_for_prompt(notice)
    assert json.loads(counter_perspectives) == perspectives
    assert json.loads(synthesis_notice) == json.loads(counter_notice)
    assert json.loads(synthesis_perspectives) == perspectives
    assert json.loads(synthesis_counterarguments) == counter
    assert canonical_json({"literal": "{perspectives_json}"})


def test_policy_perspective_allow_list_rejects_unknown_notice_field() -> None:
    policy = deepcopy(load_policy_file())
    policy["perspective_prompts"][NAMES[0]]["input_fields"].append("secret_body")
    with pytest.raises(PromptAssemblyError):
        assemble_perspective_prompt(policy, NAMES[0], NOTICE, PROFILE)


def test_unknown_unicode_placeholder_fails_closed() -> None:
    policy = deepcopy(load_policy_file())
    policy["perspective_prompts"][NAMES[0]]["template"] += "\n{악성자리표시자}"
    with pytest.raises(PromptAssemblyError):
        assemble_perspective_prompt(policy, NAMES[0], NOTICE, PROFILE)


def test_sentinal_unknown_key_does_not_appear_in_contract_error() -> None:
    sentinel = "UNKNOWN_KEY_SECRET_SENTINEL"
    with pytest.raises(ContractViolation) as caught:
        validate_perspective({sentinel: 1}, expected_name=NAMES[0])
    assert sentinel not in str(caught.value)


def test_evidence_missing_is_distinct_from_evidence_field_schema_error() -> None:
    missing = perspective(NAMES[0])
    missing.pop("evidence")
    with pytest.raises(ContractViolation) as first:
        validate_perspective(missing, expected_name=NAMES[0])
    assert first.value.failure_type == "evidence_missing"
    malformed = perspective(NAMES[0])
    malformed["evidence"] = [{"source": "x", "status": "wrong", "fact": "f"}]
    with pytest.raises(ContractViolation) as second:
        validate_perspective(malformed, expected_name=NAMES[0])
    assert second.value.failure_type == "schema_violation"


def test_judgment_requires_notice_identity_and_exact_id_equality() -> None:
    counter = ["예산 범위가 회사 조건과 다를 수 있다"]
    judgment = {
        "notice_id": NOTICE["notice_id"], "grade": "검토 권장", "readiness": "확인 완료",
        "primary_focus": "AI/데이터", "exclusion_category": None, "summary": "종합 판단 근거입니다",
        "perspectives": [perspective(name) for name in NAMES], "matched_performances": [],
        "counterarguments": counter, "counterargument_resolutions": [{"counterargument": counter[0], "status": "추가 확인", "reflection": "담당자가 조건을 확인합니다"}],
        "verification_items": [], "next_action": "담당자가 원문을 확인합니다",
    }
    with pytest.raises(ContractViolation):
        validate_judgment(judgment)
    for bad_notice in ({}, {"notice_id": 1}, {"notice_id": "  "}):
        with pytest.raises(ContractViolation):
            validate_judgment(judgment, notice=bad_notice)
    changed = deepcopy(judgment)
    changed["notice_id"] = "other"
    with pytest.raises(ContractViolation):
        validate_judgment(changed, notice=NOTICE)


def test_mixed_generic_counterargument_is_rejected_but_specific_items_pass() -> None:
    with pytest.raises(ContractViolation) as caught:
        validate_counterargument({"counterarguments": [
            "예산 범위가 공고 요구 역할과 다를 수 있다",
            "추가 확인이 필요하다",
        ]})
    assert caught.value.failure_type == "counterargument_repetition"
    valid = validate_counterargument({"counterarguments": [
        "예산 범위가 공고 요구 역할과 다를 수 있다",
        "첨부된 자격 요건의 지역 제한이 회사 등록 범위와 다를 수 있다",
    ]})
    assert len(valid["counterarguments"]) == 2


def test_evidence_missing_gets_one_correction_retry() -> None:
    missing = perspective(NAMES[0])
    missing.pop("evidence")
    transport = FakeScreeningTransport([
        completion(missing),
        completion(perspective(NAMES[0])),
    ])
    result = _client(transport).generate(
        "original frozen input", schema_for_stage(NAMES[0]), stage=NAMES[0],
        validator=lambda item: validate_perspective(item, expected_name=NAMES[0]),
    )
    assert result.attempts[0].failure_type == "evidence_missing"
    assert result.metadata.attempt_no == 2
    assert "원래 입력" in transport.generate_requests[1]["messages"][1]["content"]


def test_judgment_perspective_order_is_free_but_duplicate_name_fails_and_two_axis_does_not_rewrite_grade() -> None:
    counter = ["예산 범위와 수행 역할이 회사 조건과 다를 수 있다"]
    judgment = {
        "notice_id": NOTICE["notice_id"], "grade": "관찰 대상", "readiness": "부분 확인 필요",
        "primary_focus": "AI/데이터", "exclusion_category": None, "summary": "종합 판단 근거입니다",
        "perspectives": [perspective(name) for name in reversed(NAMES)], "matched_performances": [],
        "counterarguments": counter, "counterargument_resolutions": [{"counterargument": counter[0], "status": "추가 확인", "reflection": "담당자 확인이 필요합니다"}],
        "verification_items": [{"item": "자격", "why": "원문 확인", "blocking": False, "status": "미확인", "requires_attachment": False}],
        "next_action": "원문을 확인합니다",
    }
    checked = validate_judgment(judgment, notice=NOTICE)
    assert checked["grade"] == "관찰 대상"
    with pytest.raises(ContractViolation):
        duplicate = deepcopy(judgment)
        duplicate["perspectives"][0] = perspective(NAMES[1])
        validate_judgment(duplicate, notice=NOTICE)
    with_flag = add_two_axis_metadata(judgment)
    assert with_flag["grade"] == judgment["grade"]
    assert with_flag["two_axis_mixing_flag"] is False


def test_two_axis_flag_is_only_a_review_label() -> None:
    counter = ["도메인과 자격 범위가 공고 원문과 다를 수 있다"]
    judgment = {
        "notice_id": NOTICE["notice_id"], "grade": "제외", "readiness": "해당 없음",
        "primary_focus": "해당 없음", "exclusion_category": "도메인 불일치", "summary": "종합 판단 근거입니다",
        "perspectives": [perspective(name) for name in NAMES], "matched_performances": [],
        "counterarguments": counter, "counterargument_resolutions": [{"counterargument": counter[0], "status": "기각", "reflection": "도메인 불일치 근거가 확인되었습니다"}],
        "verification_items": [], "next_action": "담당자가 제외 사유를 검토합니다",
    }
    judgment["perspectives"][3]["assessment"] = "확인 불가"
    assert validate_judgment(judgment, notice=NOTICE)
    result = add_two_axis_metadata(judgment)
    assert result["grade"] == "제외"
    assert result["readiness"] == "해당 없음"
    assert result["two_axis_mixing_flag"] is True
    assert result["two_axis_mixing_label"] == "확인 요망"


@pytest.mark.parametrize("mutate", [
    lambda item: item.update({"readiness": "부분 확인 필요", "verification_items": []}),
    lambda item: item.update({"readiness": "확인 완료", "verification_items": [{"item": "x", "why": "y", "blocking": True, "status": "미확인", "requires_attachment": False}]}),
    lambda item: item.update({"readiness": "참여 불가 확인", "verification_items": []}),
    lambda item: item.update({"grade": "제외", "readiness": "확인 완료", "exclusion_category": "도메인 불일치"}),
    lambda item: item.update({"grade": "검토 권장", "exclusion_category": "도메인 불일치"}),
])
def test_judgment_cross_conditions_fail_closed(mutate) -> None:
    counter = ["예산 범위가 회사 조건과 다를 수 있다"]
    item = {
        "notice_id": NOTICE["notice_id"], "grade": "검토 권장", "readiness": "확인 완료",
        "primary_focus": "AI/데이터", "exclusion_category": None, "summary": "종합 판단 근거입니다",
        "perspectives": [perspective(name) for name in NAMES], "matched_performances": [],
        "counterarguments": counter, "counterargument_resolutions": [{"counterargument": counter[0], "status": "추가 확인", "reflection": "담당자가 조건을 확인합니다"}],
        "verification_items": [], "next_action": "담당자가 원문을 확인합니다",
    }
    mutate(item)
    with pytest.raises(ContractViolation):
        validate_judgment(item, notice=NOTICE)
