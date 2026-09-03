from __future__ import annotations

from typing import get_args

import pytest

from app.config import Settings


@pytest.mark.parametrize("value", ["not a url", "bogus", "file:///tmp/ollama", "http://user:pass@example.test"])
def test_ollama_base_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        Settings(model_base_url=value)


@pytest.mark.parametrize("value", ["http://ollama.example:11434", "https://ollama.example/v1"])
def test_ollama_base_url_accepts_absolute_http_urls(value: str) -> None:
    assert Settings(model_base_url=value).model_base_url == value


@pytest.mark.parametrize("value", ["30m", "1.5h", "0", "-1", 0, -1, 123456])
def test_ollama_keep_alive_preserves_supported_duration_forms(value) -> None:
    assert Settings(model_keep_alive=value).model_keep_alive == value


@pytest.mark.parametrize("value", ["bogus", "30", "-2", True])
def test_ollama_keep_alive_rejects_invalid_duration_forms(value) -> None:
    with pytest.raises(ValueError):
        Settings(model_keep_alive=value)


def test_analysis_provider_is_limited_to_vllm_and_mock() -> None:
    """Deep review keeps exactly two providers; the removed external adapter must not return."""

    field = Settings.model_fields["analysis_provider"]
    assert set(get_args(field.annotation)) == {"vllm", "mock"}
    with pytest.raises(ValueError):
        Settings(analysis_provider="external-reference")
    assert not [name for name in Settings.model_fields if "codex" in name.lower()]
    assert not [name for name in dir(Settings) if "codex" in name.lower()]
