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
from app.screening.ollama import ModelInspectionError, OllamaCallError, OllamaClient, OllamaTransport, ScreeningOrchestrator
from app.screening.policy import load_policy_file
from app.screening.prompts import PromptAssemblyError, assemble_counterargument_prompt, assemble_perspective_prompt, assemble_synthesis_prompt, project_notice_for_prompt, schema_for_stage
from tests.fakes import FakeOllamaTransport


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


def response(value: object, *, done: bool = True, **extra: object) -> dict[str, object]:
    return {"model": "qwen3.8:27b", "done": done, "done_reason": "stop", "response": json.dumps(value, ensure_ascii=False), **extra}


def perspective(name: str) -> dict[str, object]:
    return {"name": name, "assessment": "적합", "reason": "이 관점의 충분한 판단 근거입니다", "evidence": [{"source": "title", "status": "confirmed", "fact": "공고 제목을 확인했습니다"}]}


def valid_script() -> list[dict[str, object]]:
    items = [response(perspective(name)) for name in NAMES]
    counter = ["예산과 요구 역할의 세부 범위가 회사 수행 조건과 다를 수 있다"]
    items.append(response({"counterarguments": counter}))
    items.append(response({
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
    transport = FakeOllamaTransport(valid_script())
    result = ScreeningOrchestrator(OllamaClient(transport=transport)).run(
        execution_id="scr-test", notice_id="notice-1", policy=load_policy_file(), notice=NOTICE, profile_sections=PROFILE
    )
    assert len(transport.generate_requests) == 7
    first = transport.generate_requests[0]["payload"]
    assert first["model"] == "qwen3.8:27b"
    assert first["system"] == "JSON 외 텍스트를 출력하지 마라. 제공되지 않은 사실을 만들지 마라."
    assert first["stream"] is False and first["think"] is False
    assert first["options"] == {"num_ctx": 16384, "num_predict": 2048}
    assert "EXTRA" not in first["prompt"]
    for index, name in enumerate(NAMES):
        assert transport.generate_requests[index]["payload"]["format"]["properties"]["name"]["enum"] == [name]
        assert transport.generate_requests[index]["payload"]["format"]["additionalProperties"] is False
    assert transport.generate_requests[5]["payload"]["format"]["required"] == ["counterarguments"]
    assert transport.generate_requests[6]["payload"]["format"]["properties"]["exclusion_category"]["enum"][0] is None
    assert len(result.telemetry) == 7
    assert all(item.started_at.tzinfo is not None for item in result.telemetry)


def test_malformed_json_retries_once_without_raw_body_in_error() -> None:
    transport = FakeOllamaTransport([
        {"model": "qwen3.8:27b", "done": True, "response": "{not-json-secret"},
        response(perspective(NAMES[0])),
    ])
    client = OllamaClient(transport=transport)
    result = client.generate(
        "원래 입력", {}, stage=NAMES[0], validator=lambda value: validate_perspective(value, expected_name=NAMES[0])
    )
    assert result.metadata.attempt_no == 2
    assert len(transport.generate_requests) == 2
    assert "not-json-secret" not in str(result.metadata)


def test_raw_rejected_output_is_not_in_failure_exception_or_chaining() -> None:
    sentinel = "RAW_MODEL_RESPONSE_SENTINEL"
    bad = {"model": "qwen3.8:27b", "done": True, "response": sentinel}
    transport = FakeOllamaTransport([bad, bad])
    with pytest.raises(OllamaCallError) as caught:
        OllamaClient(transport=transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
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
    bad = {"model": "qwen3.8:27b", "done": True, "response": raw}
    transport = FakeOllamaTransport([bad, bad])
    with pytest.raises(OllamaCallError) as caught:
        OllamaClient(transport=transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
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
    transport = FakeOllamaTransport([response(value), response(value)])
    with pytest.raises(OllamaCallError) as caught:
        OllamaClient(transport=transport).generate(
            "prompt", {}, stage="counterargument", validator=lambda item: (_ for _ in ()).throw(
                ContractViolation("counterargument repetition", failure_type="counterargument_repetition")
            )
        )
    assert caught.value.failure_type == "counterargument_repetition"
    assert len(transport.generate_requests) == 1


def test_inspection_tag_or_digest_failure_is_distinguishable() -> None:
    with pytest.raises(ModelInspectionError) as caught:
        OllamaClient(transport=FakeOllamaTransport(inspect_response={"models": [{"name": "wrong", "model": "wrong", "digest": "a" * 64}]})).inspect_model()
    assert caught.value.status_code == 503
    assert caught.value.failure_type == "model_inspection"

    with pytest.raises(ModelInspectionError):
        OllamaClient(transport=FakeOllamaTransport(inspect_response={"models": [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": "A" * 64}]})).inspect_model()


@pytest.mark.parametrize(
    "models",
    [
        [],
        [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": "a" * 64}] * 2,
        [{"name": "wrong", "model": "wrong", "digest": "a" * 64}],
        [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": "sha256:" + "a" * 64}],
        [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": " " + "a" * 64}],
    ],
)
def test_inspection_requires_one_real_tags_entry_and_raw_digest(models: list[dict[str, str]]) -> None:
    with pytest.raises(ModelInspectionError) as caught:
        OllamaClient(transport=FakeOllamaTransport(inspect_response={"models": models})).inspect_model()
    assert caught.value.__cause__ is None
    assert "sha256" not in str(caught.value)


def test_inspection_get_has_no_request_body_and_identity_is_cached() -> None:
    transport = FakeOllamaTransport()
    client = OllamaClient(transport=transport)
    first = client.inspect_model()
    second = client.inspect_model()
    assert first == second
    assert transport.requests[0]["method"] == "GET"
    assert transport.requests[0]["path"] == "/api/tags"
    assert transport.requests[0]["payload"] is None
    assert len([request for request in transport.requests if request["path"] == "/api/tags"]) == 1


def test_inspection_refresh_rechecks_tags_and_rejects_cached_digest() -> None:
    responses = iter((
        {"models": [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": "a" * 64}]},
        {"models": [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": "b" * 64}]},
    ))
    transport = FakeOllamaTransport(inspect_response=lambda _request: next(responses))
    client = OllamaClient(transport=transport)
    assert client.inspect_model().digest == "a" * 64
    assert client.inspect_model().digest == "a" * 64
    assert client.inspect_model(refresh=True).digest == "b" * 64
    assert len([request for request in transport.requests if request["path"] == "/api/tags"]) == 2


def test_generate_inspection_failure_is_not_reclassified_and_has_no_cause_sentinel() -> None:
    sentinel = "INSPECTION_SECRET_SENTINEL"
    with pytest.raises(ModelInspectionError) as caught:
        OllamaClient(transport=FakeOllamaTransport(inspect_response=ConnectionResetError(sentinel))).generate(
            "prompt", {}, stage=NAMES[0]
        )
    assert caught.value.__cause__ is None
    assert sentinel not in str(caught.value)
    assert not isinstance(caught.value, OllamaCallError)


@pytest.mark.parametrize(
    "envelope",
    [
        {"name": "qwen3.8:27b"},
        {"tag": "qwen3.8:27b"},
        {"details": {"model": "qwen3.8:27b"}},
        {"model": "qwen3.8:27b", "digest": "sha256:" + "a" * 64},
        {"model": "qwen3.8:27b", "digest": " " + "a" * 64},
    ],
)
def test_generate_identity_requires_actual_model_and_raw_optional_digest(envelope: dict[str, object]) -> None:
    bad = {"done": True, "response": json.dumps(perspective(NAMES[0])), **envelope}
    transport = FakeOllamaTransport([bad, bad])
    with pytest.raises(OllamaCallError) as caught:
        OllamaClient(transport=transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert caught.value.failure_type == "schema_violation"


def test_public_transport_malformed_json_has_no_raw_exception_context(monkeypatch) -> None:
    class BadResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"secret":"TRANSPORT_RAW_SENTINEL"'

    import app.screening.ollama as module
    monkeypatch.setattr(module.urllib_request, "urlopen", lambda *args, **kwargs: BadResponse())
    with pytest.raises(ValueError) as caught:
        OllamaTransport("http://ollama").request("POST", "/api/generate", {}, timeout=1)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "TRANSPORT_RAW_SENTINEL" not in repr(caught.value)


@pytest.mark.parametrize("failure", [TimeoutError("secret"), ConnectionError("secret"), ConnectionResetError("secret")])
def test_timeout_transport_retry_is_same_prompt_with_fresh_span(failure: BaseException) -> None:
    transport = FakeOllamaTransport([failure, response(perspective(NAMES[0]))])
    client = OllamaClient(transport=transport)
    result = client.generate("fixed prompt", schema_for_stage(NAMES[0]), stage=NAMES[0], validator=lambda item: validate_perspective(item, expected_name=NAMES[0]))
    requests = transport.generate_requests
    assert [request["payload"]["prompt"] for request in requests] == ["fixed prompt", "fixed prompt"]
    assert result.attempts[0].attempt_no == 1 and result.metadata.attempt_no == 2
    assert result.attempts[0].trace_id == result.metadata.trace_id
    assert result.attempts[0].span_id != result.metadata.span_id
    assert result.attempts[0].failure_type == "timeout"


@pytest.mark.parametrize("termination", [{"done": False}, {"done": True, "done_reason": "length"}])
def test_truncation_retry_is_same_prompt_and_same_output_cap(termination: dict[str, object]) -> None:
    first = {"model": "qwen3.8:27b", "response": "{", **termination}
    transport = FakeOllamaTransport([first, response(perspective(NAMES[0]))])
    result = OllamaClient(transport=transport).generate(
        "fixed prompt", schema_for_stage(NAMES[0]), stage=NAMES[0], validator=lambda item: validate_perspective(item, expected_name=NAMES[0])
    )
    assert result.attempts[0].failure_type == "truncated_output"
    assert transport.generate_requests[0]["payload"]["prompt"] == transport.generate_requests[1]["payload"]["prompt"]
    assert transport.generate_requests[0]["payload"]["options"] == transport.generate_requests[1]["payload"]["options"]


@pytest.mark.parametrize("metric", [True, False, 1.0, "1", -1])
def test_invalid_metric_is_schema_violation_not_coerced(metric: object) -> None:
    bad = {"model": "qwen3.8:27b", "done": True, "response": json.dumps(perspective(NAMES[0])), "eval_count": metric}
    transport = FakeOllamaTransport([bad, bad])
    with pytest.raises(OllamaCallError) as caught:
        OllamaClient(transport=transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert caught.value.failure_type == "schema_violation"
    assert len(caught.value.attempts) == 2


def test_missing_metrics_are_nullable_and_done_reason_is_nullable() -> None:
    transport = FakeOllamaTransport([response(perspective(NAMES[0]))])
    result = OllamaClient(transport=transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert result.metadata.prompt_eval_count is None
    assert result.metadata.prompt_eval_duration_ns is None
    assert result.metadata.total_duration_ns is None
    assert result.metadata.done_reason == "stop"


def test_metrics_are_preserved_as_nonnegative_integer_nanoseconds() -> None:
    scripted = response(
        perspective(NAMES[0]),
        prompt_eval_count=0,
        eval_count=7,
        prompt_eval_duration=11,
        eval_duration=13,
        load_duration=17,
        total_duration=41,
    )
    result = OllamaClient(transport=FakeOllamaTransport([scripted])).generate(
        "p", schema_for_stage(NAMES[0]), stage=NAMES[0]
    )
    assert result.metadata.prompt_eval_count == 0
    assert result.metadata.eval_count == 7
    assert result.metadata.prompt_eval_duration_ns == 11
    assert result.metadata.eval_duration_ns == 13
    assert result.metadata.load_duration_ns == 17
    assert result.metadata.total_duration_ns == 41


def test_non_string_done_reason_is_schema_violation() -> None:
    bad = {"model": "qwen3.8:27b", "done": True, "done_reason": 3, "response": json.dumps(perspective(NAMES[0]))}
    transport = FakeOllamaTransport([bad, bad])
    with pytest.raises(OllamaCallError) as caught:
        OllamaClient(transport=transport).generate("p", schema_for_stage(NAMES[0]), stage=NAMES[0])
    assert caught.value.failure_type == "schema_violation"


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
    transport = FakeOllamaTransport([
        response(missing),
        response(perspective(NAMES[0])),
    ])
    result = OllamaClient(transport=transport).generate(
        "original frozen input", schema_for_stage(NAMES[0]), stage=NAMES[0],
        validator=lambda item: validate_perspective(item, expected_name=NAMES[0]),
    )
    assert result.attempts[0].failure_type == "evidence_missing"
    assert result.metadata.attempt_no == 2
    assert "원래 입력" in transport.generate_requests[1]["payload"]["prompt"]


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
