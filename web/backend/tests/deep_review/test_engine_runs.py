"""Engine subprocess + API + WorkJob + authoritative company/document store contracts."""

from datetime import datetime, UTC, timedelta
from uuid import uuid4
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.db import init_db, get_db
from app.core.config import get_settings
from app.deep_review.models import EngineRun, WorkJob, ContentObjectLocation
from app.deep_review.routers.engine_runs import router
from app.deep_review.schemas.engine_runs import EngineRunCreate
from app.deep_review.services import engine_runs as svc
from tests.deep_review.engine_fixtures import seed_engine_input
from tests.postgres import migrated_engine, requires_postgres


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def context(request, tmp_path, monkeypatch):
    monkeypatch.setenv("BIDOPS_TEST_MODE", "1")
    monkeypatch.setenv("BIDOPS_OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("BIDOPS_ATTACHMENTS_DIR", str(tmp_path))
    get_settings.cache_clear()

    def setup(bind):
        with Session(bind) as session:
            ids = seed_engine_input(session)
            app = FastAPI()
            app.include_router(router)
            app.dependency_overrides[get_db] = lambda: session
            with TestClient(app) as client:
                yield session, client, ids

    if request.param == "postgres":
        with migrated_engine() as bind:
            yield from setup(bind)
    else:
        bind = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        init_db(bind)
        yield from setup(bind)
        bind.dispose()
    get_settings.cache_clear()


def endpoint(ids):
    return f"/api/companies/{ids['company_id']}/notices/{ids['notice_id']}/engine-runs"


def body(ids, **kw):
    return {
        "request_id": str(uuid4()),
        "bundle_id": str(ids["bundle_id"]),
        "mode": "mock_reference",
        **kw,
    }


def enqueue(ctx):
    s, c, ids = ctx
    response = c.post(
        endpoint(ids), json=body(ids), headers={"X-BidOps-Actor-Name": "tester"}
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_real_pipeline_queue_and_store_partial_without_promoting_unknown(context):
    session, client, ids = context
    result = enqueue(context)
    assert result["status"] == "queued" and result["analysis"] is None
    assert svc.run_once(session, "engine-test")
    response = client.get("/api/engine-runs/" + result["id"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "partial", result
    assert result["quality_status"] == "mock_reference"
    assert result["analysis"]["facts"]["project"]["budget_krw"] is None
    assert result["analysis"]["usage"]["calls"] == 3
    # The product mock infers no eligibility from any sentence (D5). The scripted
    # SME_CERT gate path is covered in packages/bid-deep-engine/engine_tests/test_runner.py.
    assert result["analysis"]["facts"]["eligibility"] == []
    assert result["analysis"]["gates"] == []
    assert [(f["req_id"], f["fit"]) for f in result["analysis"]["fits"]] == [
        ("SFR-001", "UNKNOWN")
    ]
    project_evidence = result["analysis"]["facts"]["project"]["evidence"][0]
    assert project_evidence["verified"] is True
    located = {
        e["evidence_path"]: e for e in result["analysis"]["source_evidence"]
    }
    assert located["/facts/project/evidence/0"]["location_status"] == "exact"
    assert located["/fits/0/evidence"]["block_key"].startswith("table-")
    assert "company_profile_projection_incomplete" in result["warnings"]
    # D1: a fresh run is not "이전 기준 분석"; BidOps' binding hash is kept separately.
    assessment = result["analysis"]["assessment"]
    assert not {"stale_stage", "legacy_metadata"} & set(assessment["reason_codes"])
    assert "stale_analysis" not in [
        c["kind"] for c in assessment["provisional"]["conditions"]
    ]
    projection = result["analysis"]["company_projection"]
    assert projection["source_profile_sha256"] == result["profile_sha256"]
    assert (
        projection["engine_company_input_hash"]
        == result["analysis"]["company_input_hash"]
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(ContentObjectLocation)
            .where(ContentObjectLocation.object_key.like("structure/engine-runs/%"))
        )
        == 1
    )
    assert client.get(endpoint(ids)).json()["total"] == 1
    assert not svc.run_once(session, "engine-test")


def test_idempotency_live_denial_and_safe_errors(context):
    session, client, ids = context
    payload = body(ids)
    first = client.post(
        endpoint(ids), json=payload, headers={"X-BidOps-Actor-Name": "tester"}
    )
    second = client.post(
        endpoint(ids), json=payload, headers={"X-BidOps-Actor-Name": "tester"}
    )
    assert first.status_code == second.status_code == 202, (first.text, second.text)
    assert first.json()["id"] == second.json()["id"]
    conflict = client.post(
        endpoint(ids), json=payload, headers={"X-BidOps-Actor-Name": "other"}
    )
    assert conflict.status_code == 409
    denied = client.post(
        endpoint(ids),
        json=body(ids, mode="live"),
        headers={"X-BidOps-Actor-Name": "tester"},
    )
    assert (
        denied.status_code == 409
        and denied.json()["error"]["code"] == "engine_live_not_approved"
    )
    assert client.get("/api/engine-runs/" + str(uuid4())).status_code == 404
    assert client.post(endpoint(ids), json=body(ids), headers={}).status_code == 400
    assert (
        client.post(
            endpoint(ids),
            json=body(ids, source_path="/private/secret"),
            headers={"X-BidOps-Actor-Name": "tester"},
        ).status_code
        == 422
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(WorkJob)
            .where(WorkJob.job_type == svc.JOB_TYPE)
        )
        == 1
    )


def test_failed_subprocess_and_expired_lease_do_not_overwrite(context):
    session, client, ids = context
    result = enqueue(context)

    def fail(_):
        raise RuntimeError("/private/secret")

    assert svc.run_once(session, "engine-test", invoke=fail)
    row = client.get("/api/engine-runs/" + result["id"]).json()
    assert row["status"] == "failed" and row["analysis"] is None
    assert "/private" not in json.dumps(row)
    assert not svc.run_once(session, "other")
    result2 = enqueue(context)
    job = session.scalar(
        select(WorkJob).where(
            WorkJob.status == "queued", WorkJob.job_type == svc.JOB_TYPE
        )
    )
    row = session.get(EngineRun, job.aggregate_id)
    job.status = "running"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    job.lease_owner = "old"
    row.status = "running"
    row.started_at = datetime.now(UTC)
    session.commit()
    assert svc.run_once(
        session, "new", invoke=lambda _: pytest.fail("expired lease replayed")
    )
    assert (
        client.get("/api/engine-runs/" + result2["id"]).json()["error_code"]
        == "lease_expired"
    )


def test_newer_bundle_marks_pinned_result_stale(context):
    from app.deep_review.models import DocumentBundle

    session, client, ids = context
    result = enqueue(context)
    assert result["input_currentness"] == "current"
    assert len(result["engine_sha256"]) == 64
    session.add(
        DocumentBundle(
            id=uuid4(),
            notice_id=ids["notice_id"],
            revision=2,
            version=1,
            status="ready",
            issues_snapshot=[],
        )
    )
    session.commit()
    response = client.get("/api/engine-runs/" + result["id"]).json()
    assert response["input_currentness"] == "stale"
    assert response["bundle_id"] == str(ids["bundle_id"])


def test_stolen_fence_and_failed_object_store_never_publish_result(context):
    session, client, ids = context
    result = enqueue(context)

    def steal(payload):
        response = svc.invoke_engine(payload)
        job = session.scalar(
            select(WorkJob).where(
                WorkJob.aggregate_id == __import__("uuid").UUID(result["id"])
            )
        )
        job.lease_fence += 1
        job.lease_owner = "other"
        session.commit()
        return response

    assert svc.run_once(session, "old", invoke=steal)
    row = client.get("/api/engine-runs/" + result["id"]).json()
    assert row["status"] == "running" and row["analysis"] is None

    class FailingStore:
        def put(self, *args, **kwargs):
            raise RuntimeError("storage unavailable")

    failed = enqueue(context)
    assert svc.run_once(session, "worker", store=FailingStore())
    row = client.get("/api/engine-runs/" + failed["id"]).json()
    assert row["status"] == "failed" and row["error_code"] == "result_storage_failed"
    assert row["analysis"] is None


def test_postgres_input_and_terminal_results_are_immutable(context):
    from sqlalchemy.exc import DBAPIError

    session, client, ids = context
    if session.get_bind().dialect.name != "postgresql":
        pytest.skip("PostgreSQL guard")
    result = enqueue(context)
    for sql in [
        "UPDATE bidops.engine_run SET input_payload='{}' WHERE id=:id",
        "DELETE FROM bidops.engine_run WHERE id=:id",
    ]:
        with pytest.raises(DBAPIError):
            session.execute(text(sql), {"id": result["id"]})
            session.commit()
        session.rollback()
    assert svc.run_once(session, "worker")
    with pytest.raises(DBAPIError):
        session.execute(
            text("UPDATE bidops.engine_run SET result_sha256=:sha WHERE id=:id"),
            {"id": result["id"], "sha": "b" * 64},
        )
        session.commit()
    session.rollback()


def _engine_failure_records(caplog):
    return [
        r.bidops
        for r in caplog.records
        if getattr(r, "bidops", {}).get("event") == "engine_run.failed"
    ]


@pytest.mark.parametrize(
    "code",
    [
        "input_hash_mismatch",
        "engine_version_changed",
        "engine_unavailable",
        "engine_timeout",
        "engine_process_failed",
        "engine_output_invalid",
    ],
)
def test_worker_keeps_each_specific_failure_code_and_logs_it(context, caplog, code):
    import logging

    session, client, ids = context
    result = enqueue(context)

    def fail(_):
        raise svc.EngineRunError(code)

    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        assert svc.run_once(session, "engine-test", invoke=fail)
    row = client.get("/api/engine-runs/" + result["id"]).json()
    assert row["status"] == "failed" and row["error_code"] == code
    assert _engine_failure_records(caplog) == [
        {
            "event": "engine_run.failed",
            "run_id": result["id"],
            "worker_id": "engine-test",
            "error_code": code,
            "failure_type": "EngineRunError",
        }
    ]


def test_unexpected_worker_error_is_logged_by_class_without_its_message(context, caplog):
    import logging

    session, client, ids = context
    result = enqueue(context)

    def fail(_):
        raise RuntimeError("중소기업확인서를 제출해야 한다. /private/secret")

    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        assert svc.run_once(session, "engine-test", invoke=fail)
    row = client.get("/api/engine-runs/" + result["id"]).json()
    assert row["error_code"] == "engine_execution_failed"
    [record] = _engine_failure_records(caplog)
    assert record["failure_type"] == "RuntimeError"
    logged = json.dumps([r.__dict__ for r in caplog.records], default=str, ensure_ascii=False)
    assert "/private" not in logged and "중소기업확인서" not in logged


def test_runner_failure_code_passes_through_the_real_subprocess(context, caplog):
    import logging

    session, client, ids = context
    result = enqueue(context)

    def live_payload(frozen):
        # The service never freezes mode=live; this drives the runner's own refusal.
        return svc.invoke_engine({**frozen, "mode": "live"})

    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        assert svc.run_once(session, "engine-test", invoke=live_payload)
    row = client.get("/api/engine-runs/" + result["id"]).json()
    assert row["status"] == "failed"
    assert row["error_code"] == "engine_live_not_approved"
    [record] = _engine_failure_records(caplog)
    assert record["error_code"] == "engine_live_not_approved"
    assert record["failure_type"] == "EngineError"


def _fake_run(stdout_bytes=b"", returncode=0, raises=None):
    import subprocess

    def run(command, *, input, stdout, stderr, timeout, env, check):
        if raises is not None:
            raise raises
        stdout.write(stdout_bytes)
        stderr.write("원문 일부가 섞일 수 있는 stderr".encode())
        return subprocess.CompletedProcess(command, returncode)

    return run


def _envelope(**changes):
    value = {
        "schema_version": "bidops.engine-output.v1",
        "engine_version": svc.ENGINE_VERSION,
        "quality_status": "mock_reference",
        "status": "failed",
        "error_code": "structure_unavailable",
        "error_class": "EngineError",
        "warnings": [],
        "analysis": None,
        "artifacts": {},
    }
    value.update(changes)
    return json.dumps(value).encode()


@pytest.mark.parametrize(
    ("run", "code"),
    [
        (
            _fake_run(raises=__import__("subprocess").TimeoutExpired("engine", 90)),
            "engine_timeout",
        ),
        (_fake_run(_envelope(), returncode=1), "engine_process_failed"),
        (_fake_run(b"{not json"), "engine_output_invalid"),
        (_fake_run(b"\xff"), "engine_output_invalid"),
        (_fake_run(b"[]"), "engine_output_invalid"),
        (_fake_run(_envelope(error_code="made_up_code")), "engine_output_invalid"),
        (_fake_run(_envelope(status="partial", analysis=None)), "engine_output_invalid"),
    ],
)
def test_invoke_maps_process_failures_to_defined_codes(monkeypatch, run, code):
    monkeypatch.setattr(svc.subprocess, "run", run)
    with pytest.raises(svc.EngineRunError) as raised:
        svc.invoke_engine({"engine_sha256": svc.engine_digest()})
    assert raised.value.code == code


def test_invoke_rejects_changed_engine_code_and_keeps_runner_codes(monkeypatch):
    with pytest.raises(svc.EngineRunError) as raised:
        svc.invoke_engine({"engine_sha256": "0" * 64})
    assert raised.value.code == "engine_version_changed"
    monkeypatch.setattr(svc.subprocess, "run", _fake_run(_envelope(error_class="not a class!")))
    result = svc.invoke_engine({"engine_sha256": svc.engine_digest()})
    assert result["error_code"] == "structure_unavailable"
    assert result["error_class"] is None
