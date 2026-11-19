"""`GET /api/feature-flags` — 꺼진 기능을 미리 알리는 읽기 전용 신호(설계고도화안 C-4)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main_module


def _client(monkeypatch: pytest.MonkeyPatch, **settings: object) -> TestClient:
    values = {"demo_enabled": False, **settings}
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(**values))
    return TestClient(main_module.create_app(modules=("lifecycle",), mount_frontend=False))


def test_feature_flags_default_off_and_booleans_only(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/api/feature-flags")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    # 설정이 없으면 꺼짐이다. 값은 참·거짓만이며 다른 키(host·모델·경로)는 없다.
    assert response.json() == {
        "schema_version": "feature-flags.v1",
        "rl_analysis": False,
        "prespec_overview": False,
        "engine_analysis": False,
    }


def test_feature_flags_reflect_environment_switches_without_leaking_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(
        monkeypatch,
        rl_analysis_enabled=True,
        prespec_overview_enabled=True,
        engine_analysis_enabled=True,
        model_name="secret-model",
        g2b_api_key="secret-key",
        database_url="postgresql://user:pass@db/bidops",
    )
    response = client.get("/api/feature-flags")
    body = response.json()
    assert body == {
        "schema_version": "feature-flags.v1",
        "rl_analysis": True,
        "prespec_overview": True,
        "engine_analysis": True,
    }
    for secret in ("secret-model", "secret-key", "pass@db"):
        assert secret not in response.text


def test_feature_flags_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, "/api/feature-flags").status_code == 405
