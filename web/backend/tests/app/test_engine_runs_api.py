"""Full assembly guard: reference engine is available with demo and RL disabled."""

from uuid import uuid4
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.core.db import get_db
from app.main import create_app
from tests.deep_review.test_engine_runs import context, endpoint, body


def test_real_company_engine_route_survives_main_middleware(context, monkeypatch):
    session, _, ids = context
    monkeypatch.setenv("BIDOPS_DEMO_ENABLED", "false")
    monkeypatch.setenv("BIDOPS_RL_ANALYSIS_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app(modules=("lifecycle", "deep_review"), mount_frontend=False)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        response = client.get(endpoint(ids))
        assert response.status_code == 200, response.text
        created = client.post(
            endpoint(ids), json=body(ids), headers={"X-BidOps-Actor-Name": "tester"}
        )
        assert created.status_code == 202, created.text
        assert client.get("/api/engine-runs/" + created.json()["id"]).status_code == 200
        denied = client.post(
            endpoint(ids),
            json=body(ids, mode="live"),
            headers={"X-BidOps-Actor-Name": "tester"},
        )
        assert denied.status_code == 409
        assert client.get("/api/pre-specs/not-an-int/company-comparison").status_code == 404
    get_settings.cache_clear()
