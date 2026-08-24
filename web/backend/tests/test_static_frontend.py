from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import SPAStaticFiles, install_frontend


def test_client_route_falls_back_to_index_html(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>BidOps test</title>", encoding="utf-8")
    application = FastAPI()
    application.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True), name="frontend")

    response = TestClient(application).get("/profile")

    assert response.status_code == 200
    assert "BidOps test" in response.text


def test_missing_build_returns_explanatory_response_without_mount_failure(tmp_path):
    application = FastAPI()
    install_frontend(application, tmp_path / "missing-dist")

    response = TestClient(application).get("/profile")

    assert response.status_code == 503
    assert "npm run build" in response.json()["detail"]
