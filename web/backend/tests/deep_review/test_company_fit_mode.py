"""Audited company-fit card mode (PS-01 C4 conditions 6–8, C8 REST·CLI, ADR-0080). No model call."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import get_db, init_db
from app.core.models import AuditEvent
from app.deep_review.models import PreSpecCompanyFitMode
from app.deep_review.routers.deep_reviews import pre_spec_overview_router
from app.deep_review.services import company_fit as fit, company_fit_mode
from tests.deep_review.company_fit_card_fixtures import card_env, replace_card, CARD
from tests.postgres import migrated_engine, requires_postgres

HEADERS = {"X-BidOps-Actor-Name": "operator"}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def session(request):
    if request.param == "postgres":
        with migrated_engine() as engine, Session(engine, expire_on_commit=False) as db:
            yield db
        return
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


@pytest.fixture
def real_rows(monkeypatch, tmp_path):
    """Card settings with env cap `suggest` and NO emulated row: only real rows count."""
    path = card_env(monkeypatch, tmp_path, mode_row=False)
    yield path
    get_settings.cache_clear()


@pytest.fixture
def client(session):
    app = FastAPI()
    app.include_router(pre_spec_overview_router)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client


def post(client, mode, *, request_id=None, reason=None, headers=HEADERS):
    return client.post("/api/pre-specs/company-fit/mode", headers=headers,
                       json={"mode": mode, "reason": reason, "request_id": str(request_id or uuid4())})


def test_no_row_is_off_and_a_suggest_row_bound_to_the_card_is_effective(session, client, real_rows):
    assert client.get("/api/pre-specs/company-fit/mode").json()["reason_code"] == "switch_off"
    request_id = uuid4()
    created = post(client, "suggest", request_id=request_id, reason="관찰 시작")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["effective"] is True and body["mode"] == "suggest" and body["set_by"] == "operator"
    # Same request: 200, no second row, no second audit event.
    again = post(client, "suggest", request_id=request_id, reason="관찰 시작")
    assert again.status_code == 200 and again.json()["effective"] is True
    assert session.scalar(select(func.count()).select_from(PreSpecCompanyFitMode)) == 1
    events = session.scalars(select(AuditEvent).where(AuditEvent.action == "prespec_company_fit.mode")).all()
    assert len(events) == 1 and events[0].claimed_name == "operator"
    assert events[0].safe_metadata["card_sha256"] == body["card_sha256"]
    conflict = post(client, "off", request_id=request_id)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "request_id_conflict"


def test_conditions_6_to_8_and_the_env_cap(session, client, real_rows, monkeypatch):
    assert post(client, "suggest").status_code == 201
    # 7: the card changed after the switch was recorded.
    replace_card(monkeypatch, real_rows, {**CARD, "basis": "합성 카드 (수정)"})
    state = fit.card_mode_state(get_settings(), session)
    assert state["reason_code"] == "switch_bound_to_other_card" and state["mode"] == "suggest"
    # A new suggest row binds the current card again.
    assert post(client, "suggest").status_code == 201
    assert fit.card_mode_state(get_settings(), session)["effective"] is True
    # 8: a row recorded for another prompt version.
    session.add(PreSpecCompanyFitMode(
        id=uuid4(), mode="suggest", prompt_version="prespec-company-fit-v9", card_version="v",
        card_sha256=fit.card_mode_state(get_settings(), session)["card_sha256"], set_by="x",
        set_at=datetime.now(UTC), request_id=uuid4(),
    ))
    session.commit()
    assert fit.card_mode_state(get_settings(), session)["reason_code"] == "switch_bound_to_other_prompt"
    # 6: env cap off wins over a suggest row; suggest cannot be recorded under the cap.
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE", "off")
    get_settings.cache_clear()
    assert fit.card_mode_state(get_settings(), session)["reason_code"] == "switch_off"
    refused = post(client, "suggest")
    assert refused.status_code == 409 and refused.json()["error"]["details"] == {"reason_code": "switch_capped_off"}
    # off is always allowed.
    assert post(client, "off").status_code == 201
    assert fit.card_mode_state(get_settings(), session)["mode"] == "off"


def test_suggest_needs_prerequisites_and_auto_request_is_not_available(session, client, real_rows, monkeypatch):
    assert post(client, "auto_request").status_code == 422
    assert post(client, "auto_request").json()["error"]["code"] == "mode_not_available"
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "false")
    get_settings.cache_clear()
    refused = post(client, "suggest")
    assert refused.status_code == 409
    assert refused.json()["error"] == {"code": "prerequisites_unmet", "message": refused.json()["error"]["message"],
                                       "details": {"reason_code": "company_fit_disabled"}}
    assert post(client, "suggest", headers={}).json()["error"]["code"] == "actor_name_required"
    assert post(client, "off", reason="   ").status_code == 422
    assert session.scalar(select(func.count()).select_from(PreSpecCompanyFitMode)) == 0


def test_cli_uses_the_same_service(session, real_rows, monkeypatch, capsys):
    from app.deep_review.cli import set_company_fit_mode as cli

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    session.close = lambda: None  # keep the test session usable after the CLI's `with`
    assert cli.main(["--mode", "suggest", "--actor", "operator", "--reason", "관찰"]) == 0
    assert '"effective": true' in capsys.readouterr().out
    assert cli.main(["--mode", "auto_request", "--actor", "operator"]) == 2
    assert "mode_not_available" in capsys.readouterr().err
    assert cli.main(["--mode", "off", "--actor", "system"]) == 2


@requires_postgres
def test_postgres_mode_rows_are_append_only(real_rows):
    with migrated_engine() as engine, Session(engine) as db:
        state, _ = company_fit_mode.set_mode(db, mode="suggest", reason=None, request_id=uuid4(), actor="operator")
        row = db.scalars(select(PreSpecCompanyFitMode)).one()
        row.reason = "changed"
        with pytest.raises(Exception, match="append-only"):
            db.commit()
