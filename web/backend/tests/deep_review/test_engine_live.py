"""Live engine review over the OpenAI Responses API (ADR-0081), end to end on a counting fake.

The fake endpoint stands in for `https://api.openai.com/v1/responses`. Its bodies follow the 83
live responses recorded on 2026-11-27 (`status`, `model`, `output[]` with reasoning items and one
assistant message, `usage.input_tokens_details.cached_tokens/cache_write_tokens`,
`output_tokens_details.reasoning_tokens`). No live error body was recorded, so error cases follow
the documented HTTP error behaviour only. The answer text is the deterministic engine mock's value
for the requested stage, so the real runner subprocess, pipeline and gates run unchanged. Nothing
leaves the process.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.models import AuditEvent
from app.deep_review.models import EngineCall, EngineReviewPreview, EngineRun, WorkJob
from datetime import UTC, datetime

from app.deep_review.services import engine_live, engine_live_wire as wire, engine_review as review, engine_runs
from tests.deep_review.engine_fixtures import seed_engine_input
from tests.deep_review.test_engine_review import (  # noqa: F401 - fixtures
    HEADERS, approve, bind, client, company_bundle, db, error, get_state, linked, post, preview, request,
)
from tests.postgres import migrated_engine, requires_postgres

ENGINE_SRC = Path(engine_runs.package_root())
SECRET = "sk-live-test-never-stored"


def _engine():
    if str(ENGINE_SRC) not in sys.path:
        sys.path.insert(0, str(ENGINE_SRC))
    from bid_deep_engine import runner  # noqa: PLC0415
    from bid_deep_engine.analysis.schemas import MatchOut, RfpFacts, SynthOut  # noqa: PLC0415
    from bid_deep_engine.analysis.workunits import WorkUnitAssignmentsOut  # noqa: PLC0415

    return runner, {"RfpFacts": RfpFacts, "MatchOut": MatchOut, "SynthOut": SynthOut,
                    "WorkUnitAssignmentsOut": WorkUnitAssignmentsOut}


PURPOSE_OF_TITLE = {"RfpFacts": "extract", "MatchOut": "match", "SynthOut": "synth", "WorkUnitAssignmentsOut": "units"}


def recorded_shape(text_value, *, status="completed", cached=0, written=900):
    return {
        "id": f"resp_{uuid4().hex[:8]}", "object": "response", "status": status, "model": "gpt-6-luna",
        "store": False, "error": None, "incomplete_details": None, "prompt_cache_key": None,
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text_value}]},
        ],
        "usage": {
            "input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
            "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": written},
            "output_tokens_details": {"reasoning_tokens": 50},
        },
    }


class FakeResponses:
    """Counts requests; answers each with the mock's value for the stage named in the schema."""

    def __init__(self, frozen, *, fail=None):
        runner, self.models = _engine()
        _, rfp = runner.document_from_blocks(frozen)
        self.mock = runner.MockTransport(rfp)
        self.fail = fail or {}
        self.requests = []

    def purpose(self, body):
        instruction = body["input"][1]["content"][1]["text"]
        schema = json.loads(instruction.rstrip().rsplit("\n\n", 1)[-1])
        return PURPOSE_OF_TITLE[schema["title"]]

    def __call__(self, url, raw, api_key, timeout):
        assert api_key == SECRET and url == wire.RESPONSES_URL
        body = json.loads(raw)
        self.requests.append(body)
        index = len(self.requests)
        action = self.fail.get(index)
        if action == "http_429":
            raise engine_live.HttpFailure(429, b'{"error":{"type":"rate_limit_error"}}')
        if action == "timeout":
            raise TimeoutError("read timed out")
        if action == "incomplete":
            return 200, json.dumps(recorded_shape("{}", status="incomplete")).encode()
        if callable(action):
            action()
        purpose = self.purpose(body)
        model = {"extract": "RfpFacts", "match": "MatchOut", "synth": "SynthOut", "units": "WorkUnitAssignmentsOut"}[purpose]
        value = self.mock.parse(self.models[model], purpose=purpose).parsed
        cached = 800 if purpose in {"match", "synth"} else 0
        return 200, json.dumps(recorded_shape(value.model_dump_json(), cached=cached,
                                              written=0 if cached else 900)).encode()


@pytest.fixture
def live(company_bundle, tmp_path, monkeypatch):
    key = tmp_path / "engine_openai_key"
    key.write_text(SECRET + "\n")
    key.chmod(0o600)
    for name, value in {
        "BIDOPS_ENGINE_REVIEW_MODE": "live", "BIDOPS_REFERENCE_WORKFLOW_MODE": "false",
        "BIDOPS_ENGINE_LIVE_DAILY_NOTICE_CAP": "1", "BIDOPS_ENGINE_LIVE_DAILY_CALL_CAP": "8",
        "BIDOPS_ENGINE_LIVE_NOTICE_CALL_CAP": "8", "BIDOPS_ENGINE_LIVE_DAILY_USD_CAP": "1.0",
        "BIDOPS_ENGINE_LIVE_KEY_FILE": str(key),
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


@pytest.fixture
def ready_live(db, live):
    seed = seed_engine_input(db, register_company=False)
    return linked(db, notice_id=seed["notice_id"])


def approved_run(db, client, notice_id):
    assert request(client, notice_id).status_code == 201
    frozen = preview(client, notice_id)
    response = approve(client, notice_id, frozen)
    assert response.status_code == 202, response.text
    run_id = UUID(response.json()["run_id"])
    return frozen, run_id, db.get(EngineRun, run_id).input_payload


def run_worker(db, fake):
    # The worker's own live branch; only the HTTP call is replaced by the counting fake.
    return engine_runs.run_once(
        db, "live-test", live_invoke=lambda session, **context: engine_runs.invoke_live(session, post=fake, **context),
    )


def calls(db, run_id=None):
    query = select(EngineCall).order_by(EngineCall.seq)
    if run_id is not None:
        query = query.where(EngineCall.engine_run_id == run_id)
    return db.scalars(query).all()


# --- wire contract ---------------------------------------------------------------------------

def _engine_responses_module():
    path = ENGINE_SRC / "bid_deep_engine/live/responses.py"
    spec = importlib.util.spec_from_file_location("engine_live_responses_by_path", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_supervisor_wire_matches_the_engine_builder_byte_for_byte():
    engine = _engine_responses_module()
    parts = ("SYSTEM", "\n\n# 문서\n\nDOC", "\n\n# 지시\n\nDO")
    for purpose in wire.PURPOSES:
        assert wire.request_body(parts, purpose=purpose) == engine.request_body(parts, purpose=purpose)
        assert wire.canonical(wire.request_body(parts, purpose=purpose)) == engine.canonical(
            engine.request_body(parts, purpose=purpose))
    for name in ("MODEL", "EFFORT", "TRANSPORT", "RESPONSES_URL", "WIRE_VERSION", "PRICE_SOURCE",
                 "USD_PER_MTOK", "LONG_CONTEXT_INPUT", "LONG_CONTEXT_MULTIPLIER"):
        assert getattr(wire, name) == getattr(engine, name), name
    counts = {"input_tokens": 300_000, "cached_input_tokens": 1000, "cache_write_input_tokens": 50,
              "output_tokens": 70, "reasoning_output_tokens": 1}
    assert wire.usd(counts) == pytest.approx(engine.api_equivalent(counts)["usd"])


def _frame(seq, purpose, document="\n\n# 문서\n\nDOC", **change):
    body = wire.request_body(("S", document, "\n\n# 지시\n\nI"), purpose=purpose)
    body.update(change)
    return {"frame": "call", "seq": seq, "purpose": purpose, "body": body}


def test_call_sequence_refuses_tampered_bodies_wrong_order_and_a_changed_document():
    first = _frame(1, "extract")
    good = wire.body_sha256(first["body"])
    sequence = wire.CallSequence(first_request_sha256=good)
    assert sequence.check(first)[0] == 1
    assert sequence.check(_frame(2, "units", document="UNITS DOC"))[1] == "units"
    assert sequence.check(_frame(3, "units", document="UNITS DOC"))[1] == "units"
    with pytest.raises(wire.WireRefusal, match="frame_order_invalid"):
        sequence.check(_frame(4, "units"))
    with pytest.raises(wire.WireRefusal, match="frame_document_changed"):
        sequence.check(_frame(4, "match", document="\n\n# 문서\n\nOTHER"))

    for change, code in (({"model": "gpt-6-luna-mini"}, "frame_body_invalid"),
                         ({"store": True}, "frame_body_invalid"),
                         ({"reasoning": {"effort": "low"}}, "frame_body_invalid"),
                         ({"tools": []}, "frame_body_invalid")):
        fresh = wire.CallSequence(first_request_sha256=good)
        with pytest.raises(wire.WireRefusal, match=code):
            fresh.check(_frame(1, "extract", **change))
    with pytest.raises(wire.WireRefusal, match="input_changed"):
        wire.CallSequence(first_request_sha256="0" * 64).check(first)
    with pytest.raises(wire.WireRefusal, match="frame_order_invalid"):
        wire.CallSequence(first_request_sha256=good).check(_frame(1, "match"))
    with pytest.raises(wire.WireRefusal, match="frame_order_invalid"):
        wire.CallSequence(first_request_sha256=good).check({**first, "seq": 2})
    with pytest.raises(wire.WireRefusal, match="frame_invalid"):
        wire.CallSequence(first_request_sha256=good).check({**first, "extra": 1})


# --- settings ---------------------------------------------------------------------------------

def test_live_mode_needs_positive_caps_and_prod_refuses_a_url_override(monkeypatch):
    monkeypatch.setenv("BIDOPS_ENGINE_REVIEW_MODE", "live")
    with pytest.raises(ValidationError, match="CAP"):
        Settings()
    for name in ("DAILY_NOTICE", "DAILY_CALL", "NOTICE_CALL"):
        monkeypatch.setenv(f"BIDOPS_ENGINE_LIVE_{name}_CAP", "1")
    with pytest.raises(ValidationError, match="USD_CAP"):
        Settings()
    monkeypatch.setenv("BIDOPS_ENGINE_LIVE_DAILY_USD_CAP", "1")
    assert Settings().engine_review_mode == "live"
    monkeypatch.setenv("BIDOPS_ENV", "prod")
    monkeypatch.setenv("BIDOPS_ENGINE_LIVE_RESPONSES_URL", "http://fake:8080/v1/responses")
    with pytest.raises(ValidationError, match="forbidden in prod"):
        Settings()


# --- end to end -------------------------------------------------------------------------------

@pytest.mark.parametrize("bind", ["sqlite", pytest.param("postgres", marks=requires_postgres)], indirect=True)
def test_approved_live_run_sends_each_call_once_and_records_the_ledger(db, client, ready_live, bind):
    notice_id, owner_id = ready_live
    frozen, run_id, payload = approved_run(db, client, notice_id)
    manifest = frozen["manifest"]
    assert manifest["mode"] == "live" and manifest["model"] == "gpt-6-luna"
    assert manifest["policy"] == "openai_responses" and manifest["planned_calls"] in (3, 5)
    plan = manifest["live"]
    assert plan["endpoint"] == "https://api.openai.com/v1/responses" and plan["store"] is False
    assert plan["caps"] == {"daily_notices": 1, "daily_calls": 8, "notice_calls": 8, "daily_usd": 1.0}
    assert frozen["budget"]["remaining_calls_today"] == 8 and frozen["budget"]["notice_allowed_today"]
    assert db.get(EngineRun, run_id).quality_status == "unmeasured_reference"

    fake = FakeResponses(payload)
    assert run_worker(db, fake)
    db.expire_all()
    row = db.get(EngineRun, run_id)
    assert row.status == "completed" and row.quality_status == "unmeasured_reference", row.error_code
    assert hashlib.sha256(wire.canonical(fake.requests[0])).hexdigest() == plan["first_request_sha256"]
    ledger = calls(db, run_id)
    assert [c.seq for c in ledger] == list(range(1, len(fake.requests) + 1))
    assert {c.state for c in ledger} == {"completed"} and all(c.usd is not None and c.usd > 0 for c in ledger)
    assert ledger[0].purpose == "extract" and [c.purpose for c in ledger][-2:] == ["match", "synth"]
    assert all(c.model == "gpt-6-luna" and c.transport == "openai_responses" for c in ledger)
    live_summary = row.result_payload["live"]
    assert live_summary["calls"] == len(ledger) and live_summary["usd"] == pytest.approx(
        float(sum((c.usd for c in ledger), Decimal(0))), abs=1e-5)
    state = get_state(client, notice_id)
    assert state["state"] == "result_ready" and state["current_result"]["quality_status"] == "unmeasured_reference"
    # The key is never stored anywhere a reader of the database could see it.
    dump = json.dumps([row.input_payload, row.result_payload], ensure_ascii=False)
    dump += json.dumps([str(e.safe_metadata) for e in db.scalars(select(AuditEvent)).all()])
    assert SECRET not in dump
    # Another notice the same KST day: the daily notice cap refuses its approval before any send.
    other, _ = linked(db)
    today = engine_live.kst_today(datetime.now(UTC))
    assert engine_live.budget_snapshot(db, notice_id=other, today=today)["notice_allowed_today"] is False
    assert engine_live.budget_snapshot(db, notice_id=notice_id, today=today)["notice_allowed_today"] is True
    with pytest.raises(engine_runs.EngineRunError, match="budget_exhausted"):
        review._require_live_budget(db, other, 3)
    assert len(fake.requests) == len(ledger)


@pytest.mark.parametrize("failure, state, code", [
    ({1: "http_429"}, "http_error", "http_error"),
    ({2: "timeout"}, "outcome_unknown", "outcome_unknown"),
    ({1: "incomplete"}, "incomplete", "response_incomplete"),
])
def test_failed_calls_are_recorded_once_and_never_resent(db, client, ready_live, failure, state, code):
    notice_id, _ = ready_live
    _, run_id, payload = approved_run(db, client, notice_id)
    fake = FakeResponses(payload, fail=failure)
    assert run_worker(db, fake)
    db.expire_all()
    row = db.get(EngineRun, run_id)
    sent = max(failure)
    assert row.status == "failed" and row.error_code == code
    assert len(fake.requests) == sent
    ledger = calls(db, run_id)
    assert len(ledger) == sent and ledger[-1].state == state
    assert get_state(client, notice_id)["reason"] in {"live_run_failed", "budget_exhausted"}


def test_notice_call_cap_stops_before_the_extra_request(db, client, ready_live, monkeypatch):
    monkeypatch.setenv("BIDOPS_ENGINE_LIVE_NOTICE_CALL_CAP", "2")
    get_settings.cache_clear()
    notice_id, _ = ready_live
    frozen, run_id, payload = approved_run(db, client, notice_id)
    assert frozen["manifest"]["planned_calls"] == 2
    fake = FakeResponses(payload)
    assert run_worker(db, fake)
    db.expire_all()
    assert db.get(EngineRun, run_id).status == "failed"
    assert db.get(EngineRun, run_id).error_code in {"planned_calls_exceeded", "budget_exhausted"}
    assert len(fake.requests) == 2 and len(calls(db, run_id)) == 2


def test_lost_lease_mid_run_sends_nothing_more(db, client, ready_live):
    notice_id, _ = ready_live
    _, run_id, payload = approved_run(db, client, notice_id)

    def steal():
        db.execute(update(WorkJob).where(WorkJob.aggregate_id == run_id).values(lease_fence=WorkJob.lease_fence + 7))
        db.commit()

    fake = FakeResponses(payload, fail={1: steal})
    assert run_worker(db, fake)
    assert len(fake.requests) == 1 and len(calls(db, run_id)) == 1


def test_audit_failure_after_a_call_stops_further_sends(db, client, ready_live, monkeypatch):
    notice_id, _ = ready_live
    _, run_id, payload = approved_run(db, client, notice_id)
    original = engine_live.Supervisor.finish

    def failing_finish(self, call_id, **kwargs):
        original(self, call_id, **kwargs)
        raise engine_live.LiveRunError("engine_live_audit_failed")

    monkeypatch.setattr(engine_live.Supervisor, "finish", failing_finish)
    fake = FakeResponses(payload)
    assert run_worker(db, fake)
    db.expire_all()
    assert len(fake.requests) == 1
    assert db.get(EngineRun, run_id).status == "failed"


def test_missing_key_fails_before_any_reservation(db, client, ready_live, live):
    notice_id, _ = ready_live
    _, run_id, payload = approved_run(db, client, notice_id)
    live.unlink()
    fake = FakeResponses(payload)
    assert run_worker(db, fake)
    db.expire_all()
    row = db.get(EngineRun, run_id)
    assert row.status == "failed" and row.error_code == "engine_live_key_unavailable"
    assert fake.requests == [] and calls(db) == []


def test_expired_lease_marks_reserved_calls_outcome_unknown(db, client, ready_live):
    notice_id, _ = ready_live
    _, run_id, payload = approved_run(db, client, notice_id)
    job = db.scalar(select(WorkJob).where(WorkJob.aggregate_id == run_id))
    row = db.get(EngineRun, run_id)
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    job.status, job.lease_owner, job.lease_expires_at, job.lease_fence = "running", "dead-worker", now - timedelta(seconds=1), 3
    row.status, row.started_at = "running", now
    db.commit()
    db.add(EngineCall(
        id=uuid4(), engine_run_id=run_id, notice_id=notice_id, seq=1, purpose="extract",
        transport="openai_responses", model="gpt-6-luna", kst_date=engine_live.kst_today(now), state="reserved",
        request_sha256="a" * 64, request_bytes=10, worker_id="dead-worker", lease_fence=3, reserved_at=now,
    ))
    db.commit()
    assert engine_runs.run_once(db, "recovering-worker")
    db.expire_all()
    assert db.get(EngineRun, run_id).error_code == "lease_expired"
    assert [c.state for c in calls(db, run_id)] == ["outcome_unknown"]


# --- database guards (PostgreSQL) -------------------------------------------------------------

@requires_postgres
def test_postgres_refuses_live_runs_without_an_approved_live_preview_and_keeps_calls_append_only(live):
    with migrated_engine() as engine, Session(engine) as session:
        seed = seed_engine_input(session, register_company=False)
        notice_id, _ = linked(session, notice_id=seed["notice_id"])
        bundle_id = seed["bundle_id"]
        payload = {"schema_version": "bidops.engine-input.v3", "mode": "live", "notice_id": notice_id,
                   "bundle_id": str(bundle_id), "company_bundle": {"slug": "acme", "bundle_sha256": "b" * 64}}
        run = EngineRun(id=uuid4(), request_id=uuid4(), notice_id=notice_id, bundle_id=bundle_id,
                        company_bundle_slug="acme", company_bundle_sha256="b" * 64, engine_version="bid-deep-engine.v1",
                        quality_status="unmeasured_reference", status="queued", input_sha256="c" * 64,
                        input_payload=payload, created_by_name="x")
        session.add(run)
        with pytest.raises(Exception, match="requires an approved live preview"):
            session.commit()
        session.rollback()
        session.add(EngineRun(**{**{c: getattr(run, c) for c in (
            "notice_id", "bundle_id", "company_bundle_slug", "company_bundle_sha256", "engine_version",
            "status", "input_sha256", "created_by_name")}, "id": uuid4(), "request_id": uuid4(),
            "quality_status": "mock_reference", "input_payload": payload}))
        with pytest.raises(Exception, match="ck_engine_run_quality"):
            session.commit()
        session.rollback()
        assert session.execute(text("SELECT count(*) FROM bidops.engine_call")).scalar() == 0
