from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import errno
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import CompanyProfileSnapshot, Run, ScreeningExecution, ScreeningPolicy
from app.routers.profile import router as profile_router
from app.routers.screening import router as screening_router


def _app(tmp_path: Path) -> tuple[FastAPI, str]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    digest = "a" * 64
    execution_id = "scr-" + "1" * 32
    with Session(engine) as session:
        session.add(
            Run(
                id="run-1",
                window_from=date(2026, 8, 26),
                window_to=date(2026, 8, 26),
                timezone="Asia/Seoul",
                generated_at=now,
                screening_basis="candidate_pool",
                status="active",
                counts_json={},
            )
        )
        session.add(
            ScreeningPolicy(
                policy_version="policy-1",
                schema_version="bidops.screening-policy.v1",
                prompt_version="prompt-1",
                content_digest=digest,
                status="activation_candidate",
                perspective_prompts_json={},
                counterargument_prompt_json={},
                synthesis_prompt_json={},
                candidate_selection_json={},
                thresholds_json={},
                created_at=now,
                created_by="operator",
            )
        )
        session.add(
            CompanyProfileSnapshot(
                digest=digest,
                version=f"company-profile.sha256:{digest}",
                source_kind="working_tree",
                source_ref="docs/reference/company-profile.md",
                artifact_path=f"web/data/profile-snapshots/{digest}.md",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScreeningExecution(
                execution_id=execution_id,
                trigger="manual_run",
                source_run_id="run-1",
                scope="full_run",
                status="대기",
                requested_by="operator",
                policy_version="policy-1",
                prompt_version="prompt-1",
                model_name="qwen3.8:27b",
                model_digest=digest,
                company_profile_version=f"company-profile.sha256:{digest}",
                company_profile_digest=digest,
                input_artifact_path=f"data/screening-executions/{execution_id}/screening-input.json",
                input_artifact_digest=digest,
                artifact_dir=f"data/screening-executions/{execution_id}",
                queued_at=now,
                candidate_count=0,
            )
        )
        session.commit()

    application = FastAPI()
    application.include_router(screening_router)
    application.include_router(profile_router)

    def override_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    return application, execution_id


def test_screening_and_profile_metadata_contracts(tmp_path: Path) -> None:
    application, execution_id = _app(tmp_path)
    with TestClient(application) as client:
        listed = client.get("/api/screening/executions")
        assert listed.status_code == 200
        item = listed.json()["items"][0]
        assert item["queue_position"] == 1
        assert set(item) == {
            "queue_no", "execution_id", "trigger", "source_run_id", "scope", "notice_id",
            "status", "requested_by", "policy_version", "prompt_version", "model_name",
            "model_digest", "company_profile_version", "company_profile_digest",
            "input_artifact_digest", "queued_at", "started_at", "finished_at", "heartbeat_at",
            "stop_requested_at", "stop_requested_by", "stop_reason", "candidate_count",
            "completed_count", "failure_count", "published_run_id", "error_summary",
            "queue_position", "current_notice_id", "current_stage", "result_urls",
        }
        snapshots = client.get("/api/profile/snapshots")
        assert snapshots.status_code == 200
        assert set(snapshots.json()["items"][0]) == {
            "version", "digest", "source_kind", "source_ref", "created_at"
        }
        assert "artifact_path" not in snapshots.text

        stopped = client.post(
            f"/api/screening/executions/{execution_id}/stop",
            json={"requested_by": " operator "},
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "중단됨"
        conflict = client.post(
            f"/api/screening/executions/{execution_id}/stop",
            json={"requested_by": "operator"},
        )
        assert conflict.status_code == 409


def test_screening_artifact_kind_and_missing_file_are_safe(tmp_path: Path, monkeypatch) -> None:
    application, execution_id = _app(tmp_path)
    import app.routers.screening as screening
    from app.config import Settings

    monkeypatch.setattr(screening, "get_settings", lambda: Settings(bidops_root=tmp_path))
    directory = tmp_path / "data" / "screening-executions" / execution_id
    directory.mkdir(parents=True)
    (directory / "screening-decisions.json").write_text("{}", encoding="utf-8")
    with TestClient(application) as client:
        response = client.get(
            f"/api/screening/executions/{execution_id}/artifacts/decisions"
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        missing = client.get(
            f"/api/screening/executions/{execution_id}/artifacts/telemetry"
        )
        assert missing.status_code == 404


def test_screening_artifact_rejects_hardlinks_and_survives_symlink_swap(
    tmp_path: Path, monkeypatch
) -> None:
    application, execution_id = _app(tmp_path)
    import app.routers.screening as screening
    from app.config import Settings

    monkeypatch.setattr(screening, "get_settings", lambda: Settings(bidops_root=tmp_path))
    directory = tmp_path / "data" / "screening-executions" / execution_id
    directory.mkdir(parents=True)
    artifact = directory / "screening-decisions.json"
    artifact.write_bytes(b'{"safe":true}')

    # A hard link can be beneath the approved directory while referring to a
    # different file identity.  The endpoint rejects it before streaming.
    outside = tmp_path / "outside.json"
    outside.write_bytes(b'{"secret":"must-not-leak"}')
    artifact.unlink()
    os.link(outside, artifact)
    with TestClient(application) as client:
        assert client.get(
            f"/api/screening/executions/{execution_id}/artifacts/decisions"
        ).status_code == 404

    artifact.unlink()
    artifact.write_bytes(b'{"safe":true}')
    original_open = screening.os.open

    def swap_after_open(path, flags, mode=0o777, *, dir_fd=None):  # type: ignore[no-untyped-def]
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == artifact.name and dir_fd is not None:
            artifact.unlink()
            artifact.symlink_to("/etc/passwd")
        return descriptor

    monkeypatch.setattr(screening.os, "open", swap_after_open)
    with TestClient(application) as client:
        response = client.get(
            f"/api/screening/executions/{execution_id}/artifacts/decisions"
        )
    # The validated inode is unlinked before the response is built.  The
    # endpoint treats that replacement race as unavailable and never follows
    # the newly installed symlink into a host file.
    assert response.status_code == 404
    assert b"root:" not in response.content


def test_artifact_response_closes_fd_on_normal_and_send_failure(
    tmp_path: Path, monkeypatch
) -> None:
    import app.routers.screening as screening
    from app.config import Settings

    monkeypatch.setattr(screening, "get_settings", lambda: Settings(bidops_root=tmp_path))
    execution_id = "scr-" + "2" * 32
    directory = tmp_path / "data" / "screening-executions" / execution_id
    directory.mkdir(parents=True)
    (directory / "screening-decisions.json").write_bytes(b'{"safe":true}')
    row = ScreeningExecution(
        execution_id=execution_id,
        artifact_dir=f"data/screening-executions/{execution_id}",
    )

    async def call_response(response, *, send_failure: bool = False):  # type: ignore[no-untyped-def]
        messages = []

        async def receive():
            return {"type": "http.request"}

        async def send(message):  # type: ignore[no-untyped-def]
            messages.append(message)
            if send_failure and message["type"] == "http.response.body" and message["body"]:
                raise OSError("client disconnected")

        error = None
        try:
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )
        except BaseException as exc:  # client disconnect is Starlette-specific
            error = exc
        return messages, error

    opened = screening._open_artifact_fd(row, "screening-decisions.json")
    assert opened is not None
    descriptor, size = opened
    owner = screening._ArtifactFdOwner(descriptor)
    response = screening._ArtifactFdResponse(owner, size, "application/json")
    messages, error = asyncio.run(call_response(response))
    assert error is None
    assert messages[-1]["more_body"] is False
    assert owner.descriptor is None
    with pytest.raises(OSError) as normal_closed:
        os.fstat(descriptor)
    assert normal_closed.value.errno == errno.EBADF

    # A send-side disconnect must clean up on every request, with no second
    # close against a descriptor number that could have been reused.
    for _ in range(3):
        opened = screening._open_artifact_fd(row, "screening-decisions.json")
        assert opened is not None
        descriptor, size = opened
        owner = screening._ArtifactFdOwner(descriptor)
        response = screening._ArtifactFdResponse(owner, size, "application/json")
        _messages, error = asyncio.run(call_response(response, send_failure=True))
        assert error is not None
        assert owner.descriptor is None
        with pytest.raises(OSError) as failed_closed:
            os.fstat(descriptor)
        assert failed_closed.value.errno == errno.EBADF


def test_artifact_response_closes_fd_on_disconnect_read_error_and_cancel(
    tmp_path: Path, monkeypatch
) -> None:
    import app.routers.screening as screening
    from app.config import Settings

    monkeypatch.setattr(screening, "get_settings", lambda: Settings(bidops_root=tmp_path))
    execution_id = "scr-" + "3" * 32
    directory = tmp_path / "data" / "screening-executions" / execution_id
    directory.mkdir(parents=True)
    (directory / "screening-decisions.json").write_bytes(b'{"safe":true}')
    row = ScreeningExecution(
        execution_id=execution_id,
        artifact_dir=f"data/screening-executions/{execution_id}",
    )

    async def call_response(response, *, mode: str):  # type: ignore[no-untyped-def]
        async def receive():
            if mode == "disconnect":
                return {"type": "http.disconnect"}
            return {"type": "http.request"}

        async def send(message):  # type: ignore[no-untyped-def]
            if mode == "cancel" and message["type"] == "http.response.body" and message["body"]:
                asyncio.current_task().cancel()
                await asyncio.sleep(0)

        error = None
        try:
            await response(
                {"type": "http", "asgi": {"spec_version": "2.3" if mode == "disconnect" else "2.4"}},
                receive,
                send,
            )
        except BaseException as exc:
            error = exc
        return error

    def build_response():  # type: ignore[no-untyped-def]
        opened = screening._open_artifact_fd(row, "screening-decisions.json")
        assert opened is not None
        descriptor, size = opened
        owner = screening._ArtifactFdOwner(descriptor)
        return descriptor, owner, screening._ArtifactFdResponse(owner, size, "application/json")

    for _ in range(3):
        descriptor, owner, response = build_response()
        asyncio.run(call_response(response, mode="disconnect"))
        assert owner.descriptor is None
        with pytest.raises(OSError) as disconnected_closed:
            os.fstat(descriptor)
        assert disconnected_closed.value.errno == errno.EBADF

    descriptor, owner, response = build_response()
    original_read = screening.os.read

    def fail_read(current_descriptor, count):  # type: ignore[no-untyped-def]
        if current_descriptor == descriptor:
            raise OSError("artifact read failed")
        return original_read(current_descriptor, count)

    monkeypatch.setattr(screening.os, "read", fail_read)
    asyncio.run(call_response(response, mode="read_error"))
    assert owner.descriptor is None
    with pytest.raises(OSError) as read_closed:
        os.fstat(descriptor)
    assert read_closed.value.errno == errno.EBADF

    # Restore os.read before opening the cancellation case so the cleanup
    # assertion exercises the normal read path.
    monkeypatch.setattr(screening.os, "read", original_read)
    descriptor, owner, response = build_response()
    asyncio.run(call_response(response, mode="cancel"))
    assert owner.descriptor is None
    with pytest.raises(OSError) as cancelled_closed:
        os.fstat(descriptor)
    assert cancelled_closed.value.errno == errno.EBADF
