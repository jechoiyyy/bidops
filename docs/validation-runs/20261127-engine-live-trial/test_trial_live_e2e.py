"""Isolated live-engine trial: real PostgreSQL, real REST router, real worker branch, real HTTP.

Unlike `tests/deep_review/test_engine_live.py`, nothing is injected into the worker: `run_once` takes
its default `invoke_live`, which reads the key file and calls `post_responses` over the trial Docker
network to `fake_responses.py` in another container. Run with `run-trial.sh` (this folder).
"""

import json
import os

import pytest
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.deep_review.models import EngineCall, EngineRun
from app.deep_review.services import engine_live, engine_runs
from tests.deep_review.engine_fixtures import seed_engine_input
from tests.deep_review.test_engine_review import (  # noqa: F401 - fixtures
    approve, bind, client, company_bundle, db, get_state, linked, post, preview, request,
)

TRIAL = "/trial"


@pytest.mark.parametrize("bind", ["postgres"], indirect=True)
def test_trial_live_review_end_to_end(db, client, company_bundle, monkeypatch, tmp_path, bind):
    key = tmp_path / "engine_openai_key"
    key.write_text("sk-trial-not-a-real-key\n")
    key.chmod(0o600)
    for name, value in {
        "BIDOPS_ENV": "dev", "BIDOPS_ENGINE_REVIEW_MODE": "live", "BIDOPS_REFERENCE_WORKFLOW_MODE": "false",
        "BIDOPS_ENGINE_LIVE_DAILY_NOTICE_CAP": "1", "BIDOPS_ENGINE_LIVE_DAILY_CALL_CAP": "8",
        "BIDOPS_ENGINE_LIVE_NOTICE_CALL_CAP": "8", "BIDOPS_ENGINE_LIVE_DAILY_USD_CAP": "1",
        "BIDOPS_ENGINE_LIVE_KEY_FILE": str(key),
        "BIDOPS_ENGINE_LIVE_RESPONSES_URL": os.environ["TRIAL_RESPONSES_URL"],
        "HTTPS_PROXY": "http://proxy.invalid:9", "HTTP_PROXY": "http://proxy.invalid:9",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    assert db.get_bind().dialect.name == "postgresql"

    notice_id, _ = linked(db, notice_id=seed_engine_input(db, register_company=False)["notice_id"])
    assert request(client, notice_id).status_code == 201
    frozen = preview(client, notice_id)
    manifest = frozen["manifest"]
    approved = approve(client, notice_id, frozen)
    assert approved.status_code == 202, approved.text
    run_id = UUID(approved.json()["run_id"])
    payload = db.get(EngineRun, run_id).input_payload
    with open(f"{TRIAL}/frozen.json", "w", encoding="utf-8") as out:
        json.dump(payload, out, ensure_ascii=False)

    assert engine_runs.run_once(db, "trial-worker")  # default invoke_live, real post_responses
    db.expire_all()
    run = db.get(EngineRun, run_id)
    sent = [json.loads(line) for line in open(f"{TRIAL}/requests.jsonl", encoding="utf-8")]
    calls = db.scalars(select(EngineCall).where(EngineCall.engine_run_id == run_id).order_by(EngineCall.seq)).all()
    summary = {
        "run_status": run.status, "quality_status": run.quality_status, "error_code": run.error_code,
        "planned_calls": manifest["planned_calls"], "sent": [r["purpose"] for r in sent],
        "ledger": [(c.seq, c.purpose, c.state, c.http_status, str(c.usd)) for c in calls],
        "first_request_bound": calls[0].request_sha256 == sent[0]["sha256"] if calls and sent else None,
        "manifest_first_request_sha256": manifest["live"]["first_request_sha256"],
        "live": run.result_payload.get("live") if run.result_payload else None,
        "state_after": get_state(client, notice_id)["state"],
    }
    with open(f"{TRIAL}/summary.json", "w", encoding="utf-8") as out:
        json.dump(summary, out, ensure_ascii=False, indent=1)
    assert run.status == "completed" and run.quality_status == "unmeasured_reference"
    assert len(sent) == len(calls) >= 3 and all(r["authorized"] and r["store"] is False for r in sent)
    assert [c.purpose for c in calls] == [r["purpose"] for r in sent]
    assert all(c.state == "completed" and c.http_status == 200 for c in calls)
    assert calls[0].request_sha256 == manifest["live"]["first_request_sha256"] == sent[0]["sha256"]
    assert summary["state_after"] == "result_ready"
    today = engine_live.kst_today(run.completed_at)
    assert engine_live.budget_snapshot(db, notice_id=notice_id, today=today)["calls_today"] == len(calls)
