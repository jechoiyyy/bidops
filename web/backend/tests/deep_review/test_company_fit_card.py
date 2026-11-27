"""PS-01 C1·C2·C4(MVP): 카드 로드·투영, 카드 동결 입력, 카드 모드 실효 순서 (T1·T2·T3)."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base
from app.deep_review.services import company_fit as fit
from app.deep_review.services.company_fit_card import (
    POLICY_LABELS,
    BusinessScopeCardError,
    card_or_reason,
    load_business_scope_card,
)
from tests.deep_review.company_fit_card_fixtures import (
    CARD,
    EXPECTED_FACTS,
    EXPECTED_LABELS,
    REVISION,
    add_notice,
    card_env,
    card_input,
    replace_card,
    write_card,
)

#: 측정 실행기 `fit_probe.INSTRUCTION`(v3.1)의 UTF-8 sha256. 구현 때 한 번 계산해 고정했다
#: (release 이미지에는 `docs/`가 없어 원문 파일을 읽지 않는다).
PROBE_INSTRUCTION_SHA256 = "dc706c916cfeb99dbbd86e31fbaf575c885c9c4b6f8e3af0d8973f6969471acb"

C2_KEYS = {
    "schema_version", "notice_id", "overview_kind", "overview_id", "document_version_id",
    "overview_sha256", "notice_facts", "input_limitations", "card_version", "card_sha256",
    "company_facts", "company_fact_labels", "policy_digest", "model_name", "model_revision",
    "prompt_version", "quality_status", "fit_policy",
}


@pytest.fixture(autouse=True)
def _clean_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- T1 ---------------------------------------------------------------------


def test_t1_valid_card_projects_like_the_probe_with_key_order(tmp_path, monkeypatch):
    card_env(monkeypatch, tmp_path)
    card = load_business_scope_card(get_settings())
    assert card.card_version == "bidops.business-scope-card.v1.2"
    raw = (tmp_path / "business-scope-card.yaml").read_bytes()
    assert card.card_sha256 == hashlib.sha256(raw).hexdigest()
    assert card.company_facts == EXPECTED_FACTS
    # 순서까지 같아야 측정 입력과 같은 JSON이 된다.
    assert [list(fact) for fact in card.company_facts] == [list(fact) for fact in EXPECTED_FACTS]
    assert [list(fact["value"]) for fact in card.company_facts] == [list(f["value"]) for f in EXPECTED_FACTS]
    assert card.company_fact_labels == EXPECTED_LABELS
    # 모델에 보내지 않는 키는 투영되지 않는다.
    blob = json.dumps(card.company_facts, ensure_ascii=False)
    for key in ("questions", "level", "basis", "합성 회사", "Q8"):
        assert key not in blob
    assert POLICY_LABELS["policy:mixed-scope"] == "섞인 사업 판단"


def _broken(change):
    card = deepcopy(CARD)
    change(card)
    return card


@pytest.mark.parametrize("change", [
    lambda c: c["scopes"].append(dict(c["scopes"][0])),          # scope id 중복
    lambda c: c.update(policies=[]),                              # policies 빈 목록
    lambda c: c["policies"][0].update(summary=""),               # policy summary 빈 문자열
    lambda c: c["scopes"][0].update(name="  "),                  # scope name 공백
    lambda c: c["scopes"][0].update(id="web"),                   # scope: 접두 없음
    lambda c: c.update(schema_version="other.card.v1"),           # schema 접두 없음
    lambda c: c.update(schema_version="bidops.business-scope-card." + "x" * 60),  # 64자 초과
    lambda c: c["scopes"][0].update(includes=["https://example.invalid/x"]),       # sanitize 불일치
], ids=["dup_scope", "empty_policies", "blank_policy_summary", "blank_scope_name", "scope_prefix",
        "schema_prefix", "schema_too_long", "unsafe_text"])
def test_t1_structure_violations_are_card_unavailable(tmp_path, monkeypatch, change):
    path = card_env(monkeypatch, tmp_path)
    replace_card(monkeypatch, path, _broken(change))
    assert card_or_reason(get_settings()) == (None, "card_unavailable")


def test_t1_sha_mismatch_and_path_errors(tmp_path, monkeypatch):
    path = card_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256", "0" * 64)
    get_settings.cache_clear()
    assert card_or_reason(get_settings()) == (None, "card_sha256_mismatch")
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256", hashlib.sha256(path.read_bytes()).hexdigest().upper())
    get_settings.cache_clear()
    assert card_or_reason(get_settings()) == (None, "card_sha256_mismatch")
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH", "")
    get_settings.cache_clear()
    assert card_or_reason(get_settings()) == (None, "card_unavailable")
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH", str(tmp_path / "missing.yaml"))
    get_settings.cache_clear()
    with pytest.raises(BusinessScopeCardError) as error:
        load_business_scope_card(get_settings())
    assert error.value.code == "card_unavailable"
    # 구조 위반이 sha 불일치보다 먼저다(C4 순서 4 → 5).
    (tmp_path / "broken.yaml").write_text("schema_version: [", encoding="utf-8")
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH", str(tmp_path / "broken.yaml"))
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256", "0" * 64)
    get_settings.cache_clear()
    assert card_or_reason(get_settings()) == (None, "card_unavailable")


def test_mode_env_rejects_unknown_values(monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE", "auto_request")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()
    monkeypatch.delenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE")
    get_settings.cache_clear()
    assert get_settings().prespec_company_fit_card_mode == "off"


# --- T2 ---------------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_t2_frozen_card_input_keys_model_input_labels_and_instruction(session, tmp_path, monkeypatch):
    card_env(monkeypatch, tmp_path)
    notice = add_notice(session, title="합성 업무 시스템 구축")
    session.commit()
    inputs = card_input(session, notice)
    assert set(inputs) == C2_KEYS | {"judged_by"}
    assert inputs["schema_version"] == "bidops.prespec-company-fit-input.v2"
    assert inputs["prompt_version"] == "prespec-company-fit-v3.1"
    assert inputs["judged_by"] == "model"
    assert inputs["model_name"] == "test-fit" and inputs["model_revision"] == REVISION
    assert inputs["company_facts"] == EXPECTED_FACTS
    assert inputs["company_fact_labels"] == EXPECTED_LABELS
    assert inputs["notice_facts"][0] == {"ref": "notice:title", "text": "합성 업무 시스템 구축",
                                         "pages": [], "block_key": None}
    assert [fact["ref"] for fact in inputs["notice_facts"][1:]] == ["business_overview:0", "main_tasks:0"]
    policy = inputs["fit_policy"]
    assert inputs["policy_digest"] == fit.digest(fit.card_fit_policy("test-fit")) == fit.digest(policy)
    assert policy["prompt_version"] == "prespec-company-fit-v3.1"
    assert policy["stages"] == [{"stage": "company_fit", "instruction": fit.INSTRUCTION_CARD_V31}]
    assert hashlib.sha256(policy["stages"][0]["instruction"].encode()).hexdigest() == PROBE_INSTRUCTION_SHA256
    # SYSTEM_PROMPT·출력 계약·generation은 v1과 같다.
    v1 = fit.fit_policy("test-fit")
    assert {k: v for k, v in policy.items() if k not in {"prompt_version", "stages"}} == {
        k: v for k, v in v1.items() if k not in {"prompt_version", "stages"}}
    model_inputs = fit.card_model_input(inputs)
    assert list(model_inputs) == ["schema_version", "notice_id", "notice_facts", "input_limitations",
                                  "company_facts", "model_name", "prompt_version"]
    assert "company_fact_labels" not in json.dumps(model_inputs, ensure_ascii=False)


def test_t2_oversized_input_is_rejected(session, tmp_path, monkeypatch):
    card_env(monkeypatch, tmp_path)
    notice = add_notice(session, title="가" * 30000)
    session.commit()
    with pytest.raises(ValueError, match="company_fit_input_too_large"):
        card_input(session, notice)


# --- T3 (MVP: env 스위치) ----------------------------------------------------


def _state():
    get_settings.cache_clear()
    return fit.card_mode_state(get_settings())


def test_t3_mode_reason_order(tmp_path, monkeypatch):
    path = card_env(monkeypatch, tmp_path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    state = _state()
    assert state == {"mode": "suggest", "effective": True, "reason_code": None,
                     "card_version": "bidops.business-scope-card.v1.2", "card_sha256": sha,
                     "prompt_version": "prespec-company-fit-v3.1"}

    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE", "off")
    assert _state()["reason_code"] == "switch_off"
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256", "f" * 64)
    assert _state()["reason_code"] == "card_sha256_mismatch"
    assert _state()["card_sha256"] is None
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH", "")
    assert _state()["reason_code"] == "card_unavailable"
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_MODEL_REVISION", "")
    assert _state()["reason_code"] == "company_fit_model_unavailable"
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "false")
    assert _state()["reason_code"] == "company_fit_reference_only"
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "false")
    state = _state()
    assert state["reason_code"] == "company_fit_disabled" and state["effective"] is False
    assert state["mode"] == "off"


def test_t3_card_fields_are_filled_even_when_an_earlier_condition_fails(tmp_path, monkeypatch):
    path = card_env(monkeypatch, tmp_path)
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "false")
    state = _state()
    assert state["reason_code"] == "company_fit_disabled"
    assert state["card_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert state["card_version"] == "bidops.business-scope-card.v1.2"
    # 모델 이름이 없어도 같은 사유(조건 3)다.
    card_env(monkeypatch, tmp_path)
    monkeypatch.delenv("BIDOPS_PRESPEC_COMPANY_FIT_MODEL")
    assert _state()["reason_code"] == "company_fit_model_unavailable"


def test_card_file_is_never_written_by_the_loader(tmp_path, monkeypatch):
    path = card_env(monkeypatch, tmp_path)
    before = path.read_bytes()
    load_business_scope_card(get_settings())
    assert path.read_bytes() == before
    assert write_card(tmp_path / "copy.yaml") == hashlib.sha256(before).hexdigest()
