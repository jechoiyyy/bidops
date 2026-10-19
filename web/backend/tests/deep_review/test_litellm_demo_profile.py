"""LiteLLM 데모 실행 한도 (DEMO-05 STEP-005, 데모 브랜치 범위).

`local-agent-main`(문맥 32768)에서 개요가 호출 timeout 300초와 출력 예약
16384에 막히던 것을 승인된 LiteLLM 전용 프로필(900초·8192)로 푼다. 새 불변
정책 파일 `prespec-overview-policy-v7-litellm-v2.json`만 그 프로필을 선언하고,
기존 v7·v8·litellm-v1 파일은 그대로 기존 값으로 읽힌다.

실제 정책 파일과 실제 `structured_request_capacity`·`_Caller`를 지나며 모델은
부르지 않는다(가짜 client가 호출 직전에 멈춘다).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.core.model_client import (
    ModelEndpointError,
    ModelInvocationError,
    structured_request_capacity,
)
from app.deep_review.models import WorkJob
from app.deep_review.services import overview_runs
from app.deep_review.services.prespec_overview_claim_policy import (
    CLAIMS_STAGE,
    LIMITS,
    SEMANTIC_STAGE,
    build_claims_prompt,
    build_claims_stage_input,
    load_claims_policy,
)
from tests.deep_review.test_overview_runs import context, seed  # noqa: F401 - shared fixtures


POLICY_DIR = Path(__file__).resolve().parents[2] / "app" / "deep_review" / "policies"
V7 = POLICY_DIR / "prespec-overview-policy-v7.json"
V8 = POLICY_DIR / "prespec-overview-policy-v8.json"
LITELLM_V1 = POLICY_DIR / "prespec-overview-policy-v7-litellm-v1.json"
LITELLM_V2 = POLICY_DIR / "prespec-overview-policy-v7-litellm-v2.json"
#: 실측 LiteLLM `/model/info` max_input_tokens (2026-10-12/13, qwen3.8:27b-ctx32k).
LITELLM_CONTEXT = 32768
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def _document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(tmp_path: Path, name: str, value: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# --- 정책 파일 ---------------------------------------------------------------------


def test_v2_is_v1_with_only_the_litellm_execution_profile_changed() -> None:
    v1 = _document(LITELLM_V1)
    v2 = _document(LITELLM_V2)
    expected = deepcopy(v1)
    # limits는 loader가 파일과 같은지 검사하므로 호출 timeout과 그 timeout을
    # 덮는 lease를 함께 선언한다(max_calls × 900 + dispatch reserve).
    expected["limits"]["timeout_seconds"] = 900
    expected["limits"]["lease_seconds"] = 3 * 900 + 360
    for stage in expected["stages"]:
        stage["chunking"]["timeout_seconds"] = 900
        stage["generation"]["max_completion_tokens"] = 8192
    assert v2 == expected
    # 프롬프트·계약·prompt_version·identity는 v1과 같다.
    assert [s["system_prompt"] for s in v2["stages"]] == [s["system_prompt"] for s in v1["stages"]]
    assert v2["prompt_version"] == v1["prompt_version"] == "prespec-overview-v7-litellm-v1"
    # 같은 형식(2칸 들여쓰기·비 ASCII 보존·끝 줄바꿈)으로 쓴 불변 파일이다.
    assert LITELLM_V2.read_text(encoding="utf-8") == json.dumps(v2, ensure_ascii=False, indent=2) + "\n"


def test_v2_loads_with_its_own_limits_and_a_distinct_digest() -> None:
    v1 = load_claims_policy(LITELLM_V1)
    v2 = load_claims_policy(LITELLM_V2)
    assert v2.digest != v1.digest
    limits = v2.document["limits"]
    assert limits == {**LIMITS, "timeout_seconds": 900, "lease_seconds": 3060}
    # lease는 최악의 경우(호출 상한 × 호출 timeout + dispatch 예약)를 덮는다.
    assert limits["lease_seconds"] >= limits["max_calls"] * limits["timeout_seconds"] + limits["dispatch_reserve_seconds"]
    for stage in (CLAIMS_STAGE, SEMANTIC_STAGE):
        stage_policy = v2.stage_policy(stage)
        assert stage_policy["chunking"] == {"retries": 0, "timeout_seconds": 900}
        assert stage_policy["generation"] == {
            "enable_thinking": False, "max_completion_tokens": 8192, "seed": 0,
            "temperature": 0.7, "top_k": 20, "top_p": 0.8,
        }


@pytest.mark.parametrize("path", [V7, V8, LITELLM_V1])
def test_existing_policies_keep_the_standard_profile(path: Path) -> None:
    policy = load_claims_policy(path)
    assert policy.document["limits"] == LIMITS
    assert (LIMITS["timeout_seconds"], LIMITS["lease_seconds"]) == (300, 1200)
    for row in policy.document["stages"]:
        assert row["chunking"] == {"retries": 0, "timeout_seconds": 300}
        assert row["generation"]["max_completion_tokens"] == 16384


def _litellm_profile(value: dict) -> dict:
    value = deepcopy(value)
    value["limits"].update(timeout_seconds=900, lease_seconds=3060)
    for stage in value["stages"]:
        stage["chunking"]["timeout_seconds"] = 900
        stage["generation"]["max_completion_tokens"] = 8192
    return value


def _mutations():
    v2 = _document(LITELLM_V2)
    v1 = _document(LITELLM_V1)

    def stage_only(value):  # 호출 값만 바꾸고 limits는 기존 그대로
        value = deepcopy(v1)
        for stage in value["stages"]:
            stage["chunking"]["timeout_seconds"] = 900
            stage["generation"]["max_completion_tokens"] = 8192
        return value

    def limits_only(_value):
        value = deepcopy(v1)
        value["limits"].update(timeout_seconds=900, lease_seconds=3060)
        return value

    def mixed_stages(_value):
        value = deepcopy(v2)
        value["stages"][1]["generation"]["max_completion_tokens"] = 16384
        value["stages"][1]["chunking"]["timeout_seconds"] = 300
        return value

    def short_lease(_value):
        value = deepcopy(v2)
        value["limits"]["lease_seconds"] = 1200
        return value

    def timeout_only(_value):
        value = deepcopy(v2)
        for stage in value["stages"]:
            stage["generation"]["max_completion_tokens"] = 16384
        return value

    def other_value(_value):
        value = deepcopy(v2)
        for stage in value["stages"]:
            stage["generation"]["temperature"] = 0.2
        return value

    return [stage_only, limits_only, mixed_stages, short_lease, timeout_only, other_value]


@pytest.mark.parametrize("mutate", _mutations(), ids=lambda f: f.__name__)
def test_loader_accepts_only_the_exact_litellm_profile(tmp_path: Path, mutate) -> None:
    path = _write(tmp_path, "candidate.json", mutate(None))
    with pytest.raises(ValueError, match="overview_policy_invalid"):
        load_claims_policy(path)


@pytest.mark.parametrize("source", [V7, V8], ids=["v7", "v8"])
def test_vllm_policies_cannot_declare_the_litellm_profile(tmp_path: Path, source: Path) -> None:
    path = _write(tmp_path, "vllm-litellm-profile.json", _litellm_profile(_document(source)))
    with pytest.raises(ValueError, match="overview_policy_invalid"):
        load_claims_policy(path)


# --- 용량 사전검사와 호출 seam ---------------------------------------------------


class _StopBeforeCall:
    """capacity를 통과한 뒤 client.invoke에 도달했는지만 기록하고 멈춘다."""

    api_dialect = "litellm"
    model_context_tokens = LITELLM_CONTEXT

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(self, stage, input_slice, stage_policy, **kwargs):
        self.calls.append({"stage": stage, "chunking": stage_policy["chunking"],
                           "generation": stage_policy["generation"], **kwargs})
        raise ModelInvocationError("timeout", ())


def _stage_input_of_request_bytes(target: int) -> dict:
    """LiteLLM 요청 JSON이 약 ``target`` byte가 되는 한 쪽짜리 개요 입력."""

    policy = load_claims_policy(LITELLM_V1)

    def request_bytes(chars: int) -> int:
        prompt = build_claims_prompt(policy, CLAIMS_STAGE, build_claims_stage_input({1: "가" * chars}))
        return structured_request_capacity(
            model="local-agent-main", prompt=prompt,
            contract=policy.structured_output_contract(CLAIMS_STAGE), api_dialect="litellm",
            max_model_len=None, policy_context_ceiling=LIMITS["max_model_context_tokens"],
        ).input_token_upper_bound

    base = request_bytes(1)
    chars = 1 + (target - base) // 3  # 한글 한 글자 = UTF-8 3 byte
    stage_input = build_claims_stage_input({1: "가" * chars})
    assert abs(request_bytes(chars) - target) <= 3
    return stage_input


def _caller(path: Path, client) -> overview_runs._Caller:
    run = SimpleNamespace(call_count=0, model_name="local-agent-main", warnings_json=[], raw_response_refs=[])
    return overview_runs._Caller(None, run, client, load_claims_policy(path), settings=None, clock=lambda: NOW)


def test_capacity_preflight_reserves_the_policy_output_budget() -> None:
    # 문맥 32768에서 입력 상계 예산: v1 = 32768 - 16384 - 1024 = 15360 byte,
    # v2 = 32768 - 8192 - 1024 = 23552 byte. 그 사이(약 20,000 byte) 요청은
    # v1에서 호출 전에 막히고 v2에서는 호출까지 간다.
    stage_input = _stage_input_of_request_bytes(20_000)

    v1_client = _StopBeforeCall()
    with pytest.raises(overview_runs._RunFailure) as failure:
        _caller(LITELLM_V1, v1_client).invoke(CLAIMS_STAGE, "draft", stage_input)
    assert failure.value.code == "input_capacity_exceeded"
    assert v1_client.calls == []

    v2_client = _StopBeforeCall()
    caller = _caller(LITELLM_V2, v2_client)
    with pytest.raises(ModelInvocationError):
        caller.invoke(CLAIMS_STAGE, "draft", stage_input)
    assert len(v2_client.calls) == 1 and caller.run.call_count == 1
    sent = v2_client.calls[0]
    assert sent["chunking"] == {"retries": 0, "timeout_seconds": 900}
    assert sent["generation"]["max_completion_tokens"] == 8192


def test_v2_capacity_boundary_is_the_8192_output_reservation() -> None:
    policy = load_claims_policy(LITELLM_V2)
    generation = policy.stage_policy(CLAIMS_STAGE)["generation"]
    budget = LITELLM_CONTEXT - generation["max_completion_tokens"] - LIMITS["chat_template_reserve_tokens"]
    assert budget == 23552
    over = _stage_input_of_request_bytes(budget + 300)
    client = _StopBeforeCall()
    with pytest.raises(overview_runs._RunFailure) as failure:
        _caller(LITELLM_V2, client).invoke(CLAIMS_STAGE, "draft", over)
    assert failure.value.code == "input_capacity_exceeded" and client.calls == []


# --- 개요 worker lease ------------------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    (None, 1200),          # 기본 v7: 기존 값 그대로
    (LITELLM_V1, 1200),    # litellm-v1: 기존 값 그대로
    (LITELLM_V2, 3060),    # litellm-v2: 3 × 900 + 360
])
def test_claim_lease_follows_the_selected_policy(context, monkeypatch, path, expected) -> None:  # noqa: F811
    session, store = context
    if path is not None:
        monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH", str(path))
    get_settings.cache_clear()
    notice, _document_row, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()
    seen: list[float] = []

    def factory(_policy):
        job = session.get(WorkJob, run.work_job_id)
        leased = job.lease_expires_at
        seen.append((leased.replace(tzinfo=None) - NOW.replace(tzinfo=None)).total_seconds())
        raise ModelEndpointError("stop before any call")

    result = overview_runs.run_once(
        session, "lease-worker", settings=get_settings(), client_factory=factory,
        store=store, clock=lambda: NOW,
    )
    assert seen == [expected], result
