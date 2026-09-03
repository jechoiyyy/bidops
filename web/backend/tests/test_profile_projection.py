from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db
import app.routers.profile as profile_module
from app.routers.profile import router as profile_router
from app.screening.profile_snapshot import create_profile_snapshot
from app.services.profile import PROFILE_PARSE_ERROR_CODES


def _assert_safe_profile_json(payload: object, *, sentinel: str, project_root: Path) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert sentinel not in encoded
    assert str(project_root) not in encoded

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert set(value).isdisjoint(
                {"source", "source_ref", "source_line", "raw", "raw_blocks", "parse_errors"}
            )
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)


def test_profile_routes_return_only_safe_projection_and_stable_read_errors(tmp_path: Path, monkeypatch) -> None:
    source = Path(__file__).parents[3] / "docs" / "reference" / "company-profile.md"
    sentinel = "대표 근거:"
    profile_path = tmp_path / "docs" / "reference" / "company-profile.md"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_bytes(source.read_bytes())

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        snapshot = create_profile_snapshot(session, project_root=tmp_path)
        snapshot_digest = snapshot.digest
        snapshot_version = snapshot.version
        session.commit()

    application = FastAPI()
    application.include_router(profile_router)
    monkeypatch.setattr(profile_module, "get_settings", lambda: Settings(bidops_root=tmp_path))

    def override_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_db

    with TestClient(application) as client:
        responses = [
            client.get("/api/profile/snapshots"),
            client.get("/api/profile/sections"),
            client.get("/api/profile/unknowns"),
        ]
        assert all(response.status_code == 200 for response in responses)
        for response in responses:
            _assert_safe_profile_json(response.json(), sentinel=sentinel, project_root=tmp_path)

        snapshots = responses[0].json()
        assert "source_ref" not in snapshots["items"][0]
        sections = responses[1].json()
        unknowns = responses[2].json()
        assert sections["schema_version"] == "bidops.profile-projection.v1"
        assert sections["profile_digest"] == snapshot_digest
        assert unknowns["profile_version"] == snapshot_version
        assert set(sections["error_codes"]).issubset(PROFILE_PARSE_ERROR_CODES)
        assert all("error_codes" in section for section in sections["sections"])

        (tmp_path / f"web/data/profile-snapshots/{snapshot_digest}.md").unlink()
        failed_responses = [
            client.get("/api/profile/sections"),
            client.get("/api/profile/unknowns"),
        ]
        assert all(response.status_code == 200 for response in failed_responses)
        for response in failed_responses:
            _assert_safe_profile_json(response.json(), sentinel=sentinel, project_root=tmp_path)
            assert response.json()["error_codes"] == ["profile_snapshot_unavailable"]
