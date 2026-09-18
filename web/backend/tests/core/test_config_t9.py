from __future__ import annotations

from typing import get_args

import pytest

from app.core.config import Settings


def test_screening_provider_is_limited_to_vllm_and_mock() -> None:
    """C-1도 승인된 OpenAI 호환 배치와 mock 둘뿐이다. Ollama 경로는 제거됐다."""

    field = Settings.model_fields["screening_provider"]
    assert set(get_args(field.annotation)) == {"vllm", "mock"}
    with pytest.raises(ValueError):
        Settings(screening_provider="ollama")


def test_removed_ollama_settings_have_no_replacement_alias() -> None:
    """설정 표면에 Ollama 전용 항목이 남아 있으면 fail closed가 무너진다.

    이름만 남겨 두면 배포가 그 값을 채우고도 아무 효과가 없는 상태가 되고,
    endpoint·모델명이 두 곳에서 정의되는 것처럼 보인다.
    """

    names = set(Settings.model_fields)
    assert not [name for name in names if "ollama" in name.lower()]
    for removed in ("model_name", "model_base_url", "model_timeout", "model_keep_alive", "live_test"):
        assert removed not in names
        assert not hasattr(Settings, removed)
    aliases = {str(field.validation_alias) for field in Settings.model_fields.values()}
    assert not [alias for alias in aliases if "OLLAMA" in alias]


def test_screening_model_name_comes_from_one_setting() -> None:
    assert Settings.model_fields["vllm_screening_model"].validation_alias == "BIDOPS_VLLM_SCREENING_MODEL"
    assert Settings().vllm_screening_model == "qwen3.8-27B"
    assert Settings(vllm_screening_model="배포가-정한-모델").vllm_screening_model == "배포가-정한-모델"


def test_analysis_provider_is_limited_to_vllm_and_mock() -> None:
    """Deep review keeps exactly two providers; the removed external adapter must not return."""

    field = Settings.model_fields["analysis_provider"]
    assert set(get_args(field.annotation)) == {"vllm", "mock"}
    with pytest.raises(ValueError):
        Settings(analysis_provider="external-reference")
    assert not [name for name in Settings.model_fields if "codex" in name.lower()]
    assert not [name for name in dir(Settings) if "codex" in name.lower()]


def test_gpu_rest_and_c2_daily_trigger_default_off() -> None:
    """GPU 휴지와 C-2 일일 자동 실행은 기본 꺼짐이다 (docs/0918_daily-operation/spec.md §10, §3.4)."""

    settings = Settings()
    assert settings.gpu_busy_limit_seconds == 0.0
    assert settings.gpu_rest_seconds == 0.0
    assert settings.c2_daily_trigger_enabled is False


def test_gpu_rest_and_c2_daily_trigger_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIDOPS_GPU_BUSY_LIMIT_SECONDS", "1800")
    monkeypatch.setenv("BIDOPS_GPU_REST_SECONDS", "600")
    monkeypatch.setenv("BIDOPS_C2_DAILY_TRIGGER_ENABLED", "true")
    settings = Settings()
    assert settings.gpu_busy_limit_seconds == 1800.0
    assert settings.gpu_rest_seconds == 600.0
    assert settings.c2_daily_trigger_enabled is True


def test_gpu_rest_seconds_reject_negative_and_non_finite() -> None:
    with pytest.raises(ValueError):
        Settings(gpu_busy_limit_seconds=-1)
    with pytest.raises(ValueError):
        Settings(gpu_rest_seconds=-1)
    with pytest.raises(ValueError):
        Settings(gpu_busy_limit_seconds=float("nan"))
    with pytest.raises(ValueError):
        Settings(gpu_busy_limit_seconds=float("inf"))
    with pytest.raises(ValueError):
        Settings(gpu_rest_seconds=float("nan"))
    with pytest.raises(ValueError):
        Settings(gpu_rest_seconds=float("inf"))
