"""RL-04 STEP-006 T6: the proposal REST (8 endpoints), edit overlay, review/stage transitions, export seam.

Through the real FastAPI app (``lifecycle`` + ``deep_review``) with the test
session.  The world is the STEP-005 one (real Rootlab v2 company outside Git,
a completed RL-03 card-v1 verdict, the imported proposal policy and approval);
sections are produced by the real proposal worker with the scripted fake Luna.
The PDF renderer (STEP-007) does not exist yet: exports answer 503
``pdf_unavailable``; the success wiring is exercised with a test-only renderer
module double.  Runs on SQLite and, with ``BIDOPS_TEST_POSTGRES_URL``, on migrated
PostgreSQL 17.  No model transport or network is used.
"""

from __future__ import annotations

import hashlib
import sys
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import IdempotencyRecord
from app.deep_review.models import ContentObject, ProposalDraft, ProposalExport, ProposalSentenceEdit
from app.deep_review.services.input_versions import PROPOSAL_SECTION_KEYS
from app.deep_review.services.proposal_draft import latest_sections
from app.deep_review.services.proposal_export import overlay_inputs, overlay_sha256
from app.main import create_app
from tests.app import test_transfer_policy as rl_tp
from tests.app.test_proposal_draft import (
    FakeProposalLuna,
    bad_quote,
    run_all,
    verdict_world,
    worker,
)
from tests.app.test_verdict_trigger_postgres import flow_engine, no_model_transport  # noqa: F401
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401
from tests.postgres import requires_postgres, temporary_database


pytestmark = rl_tp.needs_rootlab

ACTOR = {"X-BidOps-Actor-Name": "jechoi"}
SECTION_KEYS = {"section_key", "title", "revision", "status", "paragraphs", "requirement_links", "error_code"}
DRAFT_KEYS = {"draft_id", "status", "stage", "created_at", "sections", "requirement_coverage", "counters",
              "latest_export"}
SENTENCE_KEYS = {"sentence_id", "text", "kind", "sources", "placeholder_hint", "edited"}


@pytest.fixture
def client_for():
    clients = []

    def make(session: Session) -> TestClient:
        application = create_app(modules=("lifecycle", "deep_review"), mount_frontend=False)
        application.dependency_overrides[get_db] = lambda: session
        client = TestClient(application)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def _envelope(response, code: str, status: int, request_id=None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code and body["error"]["details"] is None
    assert body["request_id"] == (str(request_id) if request_id else None)


def _completed_world(session: Session, monkeypatch, client_for, *, script=None, daily_cap: int = 3):
    w = verdict_world(session, monkeypatch, daily_cap=daily_cap)
    client = client_for(session)
    created = client.post(f"/api/opportunities/{w.opportunity_id}/proposal-requests",
                          json={"request_id": str(uuid4())}, headers=ACTOR)
    assert created.status_code == 202, created.text
    draft_id = UUID(created.json()["draft_id"])
    run_all(session, worker(FakeProposalLuna(session.get_bind(), script)))
    return w, client, draft_id


def _sentence(view: dict, section_key: str, kind: str = "statement") -> dict:
    section = next(row for row in view["draft"]["sections"] if row["section_key"] == section_key)
    return next(s for p in section["paragraphs"] for s in p["sentences"] if s["kind"] == kind)


# --- GET / POST draft ------------------------------------------------------------------------


def test_t6_view_none_create_replay_queued_view_and_errors(flow_engine, monkeypatch, client_for) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        client = client_for(session)
        url = f"/api/opportunities/{w.opportunity_id}/proposal"
        assert client.get(url).json() == {"schema_version": "bidops.proposal.v1", "draft": None}
        _envelope(client.get("/api/opportunities/999999/proposal"), "opportunity_not_found", 404)
        request_id = uuid4()
        requests_url = f"/api/opportunities/{w.opportunity_id}/proposal-requests"
        _envelope(client.post(requests_url, json={"request_id": str(request_id)}), "actor_name_required", 400,
                  request_id)
        assert client.post(requests_url, json={}, headers=ACTOR).status_code == 422
        assert "detail" in client.post(requests_url, json={"request_id": "x"}, headers=ACTOR).json()
        created = client.post(requests_url, json={"request_id": str(request_id)}, headers=ACTOR)
        assert created.status_code == 202 and set(created.json()) == {"draft_id", "status"}
        assert created.json()["status"] == "queued"
        replay = client.post(requests_url, json={"request_id": str(request_id)}, headers=ACTOR)
        assert replay.status_code == 202 and replay.json() == created.json()
        busy = client.post(requests_url, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "draft_in_progress"
        view = client.get(url).json()
        draft = view["draft"]
        assert set(draft) == DRAFT_KEYS and draft["draft_id"] == created.json()["draft_id"]
        assert (draft["status"], draft["stage"], draft["latest_export"]) == ("queued", "toc", None)
        assert [row["section_key"] for row in draft["sections"]] == list(PROPOSAL_SECTION_KEYS)
        assert all(set(row) == SECTION_KEYS and row["status"] == "queued" and row["paragraphs"] == []
                   and row["revision"] == 1 and row["error_code"] is None for row in draft["sections"])
        assert draft["counters"] == {"sentences_to_confirm": 0, "placeholders": 0, "proposed_figures": 0,
                                     "reviewed_sections": 0}
        coverage = draft["requirement_coverage"]
        assert coverage["total"] > 0 and coverage["linked"] == 0 and len(coverage["unlinked_unit_ids"]) == coverage["total"]
        _envelope(client.get(url, params={"draft_id": str(uuid4())}), "not_found", 404)


def test_t6_rl_off_hides_every_proposal_path(flow_engine, monkeypatch, client_for) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w, client, draft_id = _completed_world(session, monkeypatch, client_for)
        monkeypatch.setenv("BIDOPS_RL_ANALYSIS_ENABLED", "false")
        get_settings.cache_clear()
        body = {"request_id": str(uuid4())}
        sentence = uuid4()
        calls = [
            ("get", f"/api/opportunities/{w.opportunity_id}/proposal", None),
            ("post", f"/api/opportunities/{w.opportunity_id}/proposal-requests", body),
            ("post", f"/api/proposals/{draft_id}/sections/overview/regenerations", body),
            ("patch", f"/api/proposals/{draft_id}/sections/overview/review", body),
            ("post", f"/api/proposals/{draft_id}/sentences/{sentence}/edits", {**body, "text": "x"}),
            ("post", f"/api/proposals/{draft_id}/exports", body),
            ("get", f"/api/proposals/{draft_id}/exports/{uuid4()}.pdf", None),
            ("patch", f"/api/proposals/{draft_id}/stage", {**body, "stage": "ready"}),
        ]
        for method, path, payload in calls:
            response = getattr(client, method)(path, headers=ACTOR, **({"json": payload} if payload else {}))
            assert response.status_code == 404 and response.json() == {"detail": "Not Found"}, path


# --- overlay ----------------------------------------------------------------------------------


def test_t6_completed_view_overlay_and_edit_idempotency(flow_engine, monkeypatch, client_for) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w, client, draft_id = _completed_world(session, monkeypatch, client_for)
        url = f"/api/opportunities/{w.opportunity_id}/proposal"
        view = client.get(url).json()
        draft = view["draft"]
        assert (draft["status"], draft["stage"]) == ("completed", "draft")
        stored = latest_sections(session, draft_id)
        for section in draft["sections"]:
            payload = stored[section["section_key"]].payload
            assert [p["paragraph_id"] for p in section["paragraphs"]] == [p["paragraph_id"] for p in payload["paragraphs"]]
            for paragraph, original in zip(section["paragraphs"], payload["paragraphs"]):
                for sentence, raw in zip(paragraph["sentences"], original["sentences"]):
                    assert set(sentence) == SENTENCE_KEYS and sentence["edited"] is False
                    assert {k: sentence[k] for k in SENTENCE_KEYS - {"edited"}} == raw
            assert {link["fit_status"] for link in section["requirement_links"]} <= {"met", "gap", "unknown"}
        coverage = draft["requirement_coverage"]
        assert coverage["linked"] == coverage["total"] and coverage["unlinked_unit_ids"] == []
        placeholders = sum(s["kind"] == "placeholder" for row in stored.values()
                           for p in row.payload["paragraphs"] for s in p["sentences"])
        assert draft["counters"]["placeholders"] == placeholders == draft["counters"]["sentences_to_confirm"]
        text = str(view)
        for word in ("policy", "model", "token", "input_sha256", "result_sha256", "gpt-6-luna"):
            assert word not in text, word

        sentence = _sentence(view, "requirements")
        edit_url = f"/api/proposals/{draft_id}/sentences/{sentence['sentence_id']}/edits"
        request_id = uuid4()
        first = client.post(edit_url, json={"text": "  수정한 문장이다.  ", "request_id": str(request_id)},
                            headers=ACTOR)
        assert first.status_code == 201 and set(first.json()) == {"edit_id"}
        replay = client.post(edit_url, json={"text": "  수정한 문장이다.  ", "request_id": str(request_id)},
                             headers=ACTOR)
        assert replay.status_code == 201 and replay.json() == first.json()
        _envelope(client.post(edit_url, json={"text": "다른 문장", "request_id": str(request_id)}, headers=ACTOR),
                  "idempotency_conflict", 409, request_id)
        edited = _sentence(client.get(url).json(), "requirements")
        assert edited["sentence_id"] == sentence["sentence_id"]
        assert (edited["text"], edited["edited"]) == ("수정한 문장이다.", True)
        # the latest edit wins; the stored model payload is never changed
        second = client.post(edit_url, json={"text": "두 번째 수정.", "request_id": str(uuid4())}, headers=ACTOR)
        assert second.status_code == 201
        assert _sentence(client.get(url).json(), "requirements")["text"] == "두 번째 수정."
        session.expire_all()
        assert latest_sections(session, draft_id)["requirements"].payload == stored["requirements"].payload
        assert int(session.scalar(select(func.count()).select_from(ProposalSentenceEdit)) or 0) == 2
        # errors
        _envelope(client.post(f"/api/proposals/{draft_id}/sentences/{uuid4()}/edits",
                              json={"text": "x", "request_id": str(request_id)}, headers=ACTOR),
                  "sentence_not_found", 404, request_id)
        _envelope(client.post(edit_url, json={"text": "   ", "request_id": str(request_id)}, headers=ACTOR),
                  "invalid_request", 422, request_id)
        assert client.post(edit_url, json={"text": "가" * 401, "request_id": str(uuid4())},
                           headers=ACTOR).status_code == 422
        _envelope(client.post(f"/api/proposals/{uuid4()}/sentences/{sentence['sentence_id']}/edits",
                              json={"text": "x", "request_id": str(request_id)}, headers=ACTOR),
                  "not_found", 404, request_id)
        _envelope(client.post(edit_url, json={"text": "x", "request_id": str(request_id)}),
                  "actor_name_required", 400, request_id)


# --- review and stage ------------------------------------------------------------------------


def test_t6_review_moves_the_draft_to_reviewed_and_stage_ready_once(flow_engine, monkeypatch, client_for) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        client = client_for(session)
        created = client.post(f"/api/opportunities/{w.opportunity_id}/proposal-requests",
                              json={"request_id": str(uuid4())}, headers=ACTOR).json()
        draft_id = created["draft_id"]
        review = f"/api/proposals/{draft_id}/sections/overview/review"
        request_id = uuid4()
        _envelope(client.patch(review, json={"request_id": str(request_id)}, headers=ACTOR),
                  "section_not_completed", 409, request_id)
        run_all(session, worker(FakeProposalLuna(session.get_bind())))
        stage_url = f"/api/proposals/{draft_id}/stage"
        _envelope(client.patch(stage_url, json={"stage": "ready", "request_id": str(request_id)}, headers=ACTOR),
                  "stage_transition_invalid", 409, request_id)
        for index, key in enumerate(PROPOSAL_SECTION_KEYS):
            rid = uuid4()
            response = client.patch(f"/api/proposals/{draft_id}/sections/{key}/review",
                                    json={"request_id": str(rid)}, headers=ACTOR)
            assert response.status_code == 200, response.text
            body = response.json()
            assert set(body) == SECTION_KEYS and (body["section_key"], body["status"]) == (key, "reviewed")
            replay = client.patch(f"/api/proposals/{draft_id}/sections/{key}/review",
                                  json={"request_id": str(rid)}, headers=ACTOR)
            assert replay.status_code == 200 and replay.json() == body
            session.expire_all()
            stage = session.get(ProposalDraft, UUID(draft_id)).stage
            assert stage == ("reviewed" if index == len(PROPOSAL_SECTION_KEYS) - 1 else "draft")
        view = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()["draft"]
        assert view["stage"] == "reviewed" and view["counters"]["reviewed_sections"] == 6
        row = latest_sections(session, UUID(draft_id))["overview"]
        assert (row.reviewed_by, row.reviewed_at is not None) == ("jechoi", True)
        # an already reviewed section answers its current view
        again = client.patch(review, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert again.status_code == 200 and again.json()["status"] == "reviewed"
        assert client.patch(stage_url, json={"stage": "draft", "request_id": str(uuid4())},
                            headers=ACTOR).status_code == 422
        ready_id = uuid4()
        ready = client.patch(stage_url, json={"stage": "ready", "request_id": str(ready_id)}, headers=ACTOR)
        assert ready.status_code == 200 and ready.json() == {"stage": "ready"}
        assert client.patch(stage_url, json={"stage": "ready", "request_id": str(ready_id)},
                            headers=ACTOR).json() == {"stage": "ready"}
        late = client.patch(stage_url, json={"stage": "ready", "request_id": str(uuid4())}, headers=ACTOR)
        assert late.status_code == 409 and late.json()["error"]["code"] == "stage_transition_invalid"
        _envelope(client.patch(f"/api/proposals/{draft_id}/sections/pricing/review",
                               json={"request_id": str(request_id)}, headers=ACTOR), "not_found", 404, request_id)
        _envelope(client.patch(f"/api/proposals/{uuid4()}/stage", json={"stage": "ready",
                                                                         "request_id": str(request_id)},
                               headers=ACTOR), "not_found", 404, request_id)
        receipts = int(session.scalar(select(func.count()).select_from(IdempotencyRecord).where(
            IdempotencyRecord.aggregate_type == "proposal_draft")) or 0)
        assert receipts == 6 + 1 + 1  # six reviews, the extra review, one ready


# --- regeneration --------------------------------------------------------------------------------


def test_t6_regeneration_route(flow_engine, monkeypatch, client_for) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w, client, draft_id = _completed_world(session, monkeypatch, client_for, script={"requirements": [bad_quote]})
        url = f"/api/proposals/{draft_id}/sections/requirements/regenerations"
        request_id = uuid4()
        response = client.post(url, json={"request_id": str(request_id)}, headers=ACTOR)
        assert response.status_code == 202 and set(response.json()) == {"section_id", "revision"}
        assert response.json()["revision"] == 2
        assert client.post(url, json={"request_id": str(request_id)}, headers=ACTOR).json() == response.json()
        busy = client.post(url, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "section_in_progress"
        _envelope(client.post(f"/api/proposals/{uuid4()}/sections/requirements/regenerations",
                              json={"request_id": str(request_id)}, headers=ACTOR), "not_found", 404, request_id)
        view = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()["draft"]
        requirements = next(row for row in view["sections"] if row["section_key"] == "requirements")
        assert (requirements["revision"], requirements["status"], requirements["paragraphs"]) == (2, "queued", [])
        assert view["status"] == "partial"


# --- exports ---------------------------------------------------------------------------------------


def test_t6_exports_fail_closed_without_the_renderer(flow_engine, monkeypatch, client_for, tmp_path) -> None:  # noqa: F811
    # STEP-007: the renderer exists; without the image font it is still pdf_unavailable.
    monkeypatch.setenv("BIDOPS_PDF_FONT_DIR", str(tmp_path / "no-fonts"))
    get_settings.cache_clear()
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        client = client_for(session)
        draft_id = client.post(f"/api/opportunities/{w.opportunity_id}/proposal-requests",
                               json={"request_id": str(uuid4())}, headers=ACTOR).json()["draft_id"]
        exports = f"/api/proposals/{draft_id}/exports"
        request_id = uuid4()
        _envelope(client.post(exports, json={"request_id": str(request_id)}, headers=ACTOR),
                  "draft_not_completed", 409, request_id)
        run_all(session, worker(FakeProposalLuna(session.get_bind())))
        for _ in range(2):  # no receipt is stored for a failed render
            _envelope(client.post(exports, json={"request_id": str(request_id)}, headers=ACTOR),
                      "pdf_unavailable", 503, request_id)
        assert int(session.scalar(select(func.count()).select_from(ProposalExport)) or 0) == 0
        _envelope(client.get(f"/api/proposals/{draft_id}/exports/{uuid4()}.pdf"), "not_found", 404)
        # a stored row (STEP-007) without the renderer cannot be read either
        content = ContentObject(id=uuid4(), sha256="a" * 64, size_bytes=10, detected_mime="application/pdf",
                                retention_class="proposal-pdf-365d")
        session.add(content)
        session.flush()
        row = ProposalExport(draft_id=UUID(draft_id), overlay_sha256="b" * 64, renderer_version="reportlab==5.0.1",
                             font_sha256="c" * 64, content_object_id=content.id, pdf_sha256="a" * 64, page_count=1,
                             created_by="jechoi")
        session.add(row)
        session.commit()
        _envelope(client.get(f"/api/proposals/{draft_id}/exports/{row.id}.pdf"), "pdf_unavailable", 503)
        _envelope(client.get(f"/api/proposals/{uuid4()}/exports/{row.id}.pdf"), "not_found", 404)
        latest = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()["draft"]["latest_export"]
        assert latest["export_id"] == str(row.id) and latest["pdf_sha256"] == "a" * 64


def test_t6_export_wiring_with_a_test_renderer_double(flow_engine, monkeypatch, client_for) -> None:  # noqa: F811
    """Route and seam wiring only: a test double stands in for the STEP-007 renderer module."""

    with Session(flow_engine) as session:
        w, client, draft_id = _completed_world(session, monkeypatch, client_for)
        rendered: list[dict] = []
        pdf = b"%PDF-test-double"

        def render_proposal_export(session, *, draft, view, actor, overlay):  # noqa: ANN001
            rendered.append(overlay)
            existing = session.scalar(select(ProposalExport).where(
                ProposalExport.draft_id == draft.id, ProposalExport.overlay_sha256 == overlay["overlay_sha256"]))
            if existing is not None:
                return {"export_id": existing.id, "pdf_sha256": existing.pdf_sha256, "created": False}
            digest = hashlib.sha256(pdf).hexdigest()
            content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest))
            if content is None:  # same bytes → one content object (sha256 is unique)
                content = ContentObject(id=uuid4(), sha256=digest, size_bytes=len(pdf),
                                        detected_mime="application/pdf", retention_class="proposal-pdf-365d")
                session.add(content)
                session.flush()
            row = ProposalExport(draft_id=draft.id, overlay_sha256=overlay["overlay_sha256"],
                                 renderer_version=overlay["renderer_version"], font_sha256=overlay["font_sha256"],
                                 content_object_id=content.id, pdf_sha256=content.sha256, page_count=1,
                                 created_by=actor)
            session.add(row)
            session.flush()
            return {"export_id": row.id, "pdf_sha256": row.pdf_sha256, "created": True}

        double = ModuleType("app.deep_review.services.proposal_render")
        double.renderer_identity = lambda: ("reportlab==5.0.1", "f" * 64)
        double.render_proposal_export = render_proposal_export
        double.read_proposal_export = lambda session, *, row: pdf
        monkeypatch.setitem(sys.modules, "app.deep_review.services.proposal_render", double)

        exports = f"/api/proposals/{draft_id}/exports"
        first = client.post(exports, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert first.status_code == 201 and set(first.json()) == {"export_id", "pdf_sha256", "created"}
        assert first.json()["created"] is True
        again = client.post(exports, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert again.status_code == 201 and again.json() == {**first.json(), "created": False}
        overlay = rendered[0]
        assert set(overlay) == {"draft_id", "sections", "edit_ids", "renderer_version", "font_sha256", "overlay_sha256"}
        pdf_response = client.get(f"/api/proposals/{draft_id}/exports/{first.json()['export_id']}.pdf")
        assert pdf_response.status_code == 200 and pdf_response.content == pdf
        assert pdf_response.headers["content-type"] == "application/pdf"
        assert pdf_response.headers["X-BidOps-Export-Sha256"] == first.json()["pdf_sha256"]
        # an edit changes the overlay, so the next export is a new row
        view = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()
        sentence = _sentence(view, "overview")
        client.post(f"/api/proposals/{draft_id}/sentences/{sentence['sentence_id']}/edits",
                    json={"text": "고친 문장.", "request_id": str(uuid4())}, headers=ACTOR)
        third = client.post(exports, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert third.status_code == 201, third.text
        assert third.json()["created"] is True and third.json()["export_id"] != first.json()["export_id"]
        assert rendered[2]["overlay_sha256"] != rendered[0]["overlay_sha256"] and len(rendered[2]["edit_ids"]) == 1


def test_t6_overlay_sha_covers_revisions_edits_renderer_and_font(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch, daily_cap=2)
        from app.deep_review.services.proposal_draft import create_proposal_draft, request_section_regeneration

        draft_id = UUID(create_proposal_draft(session, opportunity_id=w.opportunity_id, actor="jechoi",
                                              request_id=uuid4())["draft_id"])
        run_all(session, worker(FakeProposalLuna(session.get_bind())))
        draft = session.get(ProposalDraft, draft_id)
        base = overlay_inputs(session, draft)
        first = overlay_sha256(base, renderer_version="reportlab==5.0.1", font_sha256="f" * 64)
        assert first == overlay_sha256(overlay_inputs(session, draft), renderer_version="reportlab==5.0.1",
                                       font_sha256="f" * 64)
        assert first != overlay_sha256(base, renderer_version="reportlab==5.0.2", font_sha256="f" * 64)
        assert first != overlay_sha256(base, renderer_version="reportlab==5.0.1", font_sha256="e" * 64)
        section = latest_sections(session, draft_id)["overview"]
        sentence_id = section.payload["paragraphs"][0]["sentences"][0]["sentence_id"]
        session.add(ProposalSentenceEdit(section_id=section.id, sentence_id=UUID(sentence_id), text="고침",
                                         actor="jechoi", request_id=uuid4()))
        session.commit()
        edited = overlay_sha256(overlay_inputs(session, draft), renderer_version="reportlab==5.0.1",
                                font_sha256="f" * 64)
        assert edited != first
        request_section_regeneration(session, draft_id=draft_id, section_key="overview", actor="jechoi",
                                     request_id=uuid4())
        run_all(session, worker(FakeProposalLuna(session.get_bind())))
        regenerated = overlay_inputs(session, session.get(ProposalDraft, draft_id))
        assert overlay_sha256(regenerated, renderer_version="reportlab==5.0.1", font_sha256="f" * 64) not in {
            first, edited}
        # the new revision has no edits yet: the old revision's edit leaves the set
        assert regenerated["edit_ids"] == []
        with pytest.raises(ValueError):
            overlay_sha256(base, renderer_version="", font_sha256="f" * 64)


# --- activity ---------------------------------------------------------------------------------------


def test_t6_activity_feed_carries_draft_prepared(flow_engine, monkeypatch, client_for) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w, client, draft_id = _completed_world(session, monkeypatch, client_for)
        feed = client.get(f"/api/opportunities/{w.opportunity_id}/activity").json()
        items = [row for row in feed["items"] if row["kind"] == "draft_prepared"]
        assert len(items) == 1
        item = items[0]
        assert item["item_id"] == f"draft_prepared:{draft_id}" and item["title"] == "제안서 초안 준비"
        assert item["link"] == {"label": "제안서 보기",
                                "path": f"/opportunities/{w.opportunity_id}/proposal?draft_id={draft_id}"}
        # RL-03's verdict item is still there (separate provider owner)
        assert any(row["kind"] == "verdict_completed" for row in feed["items"])


# --- runtime role (PostgreSQL) -----------------------------------------------------------------


@requires_postgres
def test_t6_web_mutations_run_under_the_app_runtime_role(monkeypatch) -> None:
    from sqlalchemy import create_engine, event

    from app.core.db import _json_serializer, schema_bound
    from app.deep_review.workers.proposal import run_once
    from tests.app.test_proposal_draft import create, mock_verdict_world
    from tests.app.test_runtime_database_privileges import _apply_policy, _ensure_roles

    _ensure_roles()
    with temporary_database() as database_url:
        policy_engine = _apply_policy(database_url)
        owner = schema_bound(create_engine(database_url, json_serializer=_json_serializer, future=True))
        app_base = create_engine(database_url, json_serializer=_json_serializer, future=True)

        @event.listens_for(app_base, "connect")
        def _app_role(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("SET ROLE app")
            cursor.close()
            dbapi_connection.commit()

        try:
            with Session(owner) as session:
                w = mock_verdict_world(session, monkeypatch)
                draft_id = UUID(create(session, w)["draft_id"])
                for _ in range(6):
                    assert run_once(session, "worker-proposal") is True
            with Session(schema_bound(app_base)) as session:
                assert session.execute(select(func.current_user())).scalar() == "app"
                application = create_app(modules=("lifecycle", "deep_review"), mount_frontend=False)
                application.dependency_overrides[get_db] = lambda: session
                with TestClient(application) as client:
                    view = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()
                    assert view["draft"]["status"] == "completed"
                    sentence = _sentence(view, "overview")
                    edit = client.post(f"/api/proposals/{draft_id}/sentences/{sentence['sentence_id']}/edits",
                                       json={"text": "고친 문장.", "request_id": str(uuid4())}, headers=ACTOR)
                    assert edit.status_code == 201, edit.text
                    for key in PROPOSAL_SECTION_KEYS:
                        response = client.patch(f"/api/proposals/{draft_id}/sections/{key}/review",
                                                json={"request_id": str(uuid4())}, headers=ACTOR)
                        assert response.status_code == 200, response.text
                    ready = client.patch(f"/api/proposals/{draft_id}/stage",
                                         json={"stage": "ready", "request_id": str(uuid4())}, headers=ACTOR)
                    assert ready.status_code == 200 and ready.json() == {"stage": "ready"}
                    export = client.post(f"/api/proposals/{draft_id}/exports",
                                         json={"request_id": str(uuid4())}, headers=ACTOR)
                    if _fonts_available():
                        # STEP-007: the web role stores the PDF, its content object/location and the row
                        assert export.status_code == 201, export.text
                        pdf = client.get(f"/api/proposals/{draft_id}/exports/{export.json()['export_id']}.pdf")
                        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
                    else:
                        assert export.status_code == 503 and export.json()["error"]["code"] == "pdf_unavailable"
                    regenerated = client.post(f"/api/proposals/{draft_id}/sections/overview/regenerations",
                                              json={"request_id": str(uuid4())}, headers=ACTOR)
                    # a ready draft is not rewritten (decision B50); the app-role regeneration INSERT
                    # path is exercised in test_proposal_draft's runtime-role test
                    assert regenerated.status_code == 409, regenerated.text
                    assert regenerated.json()["error"]["code"] == "stage_transition_invalid"
            with Session(owner) as session:
                assert session.get(ProposalDraft, draft_id).stage == "ready"
        finally:
            app_base.dispose()
            owner.dispose()
            policy_engine.dispose()


# --- STEP-007: real PDFs -------------------------------------------------------------------------


def _fonts_available() -> bool:
    get_settings.cache_clear()
    from app.deep_review.services.proposal_render import FONT_FILES

    directory = get_settings().pdf_font_dir
    return all((directory / name).is_file() for name in FONT_FILES)


needs_fonts = pytest.mark.skipif(
    not _fonts_available(),
    reason="NanumGothic.ttf/NanumGothicBold.ttf not found at BIDOPS_PDF_FONT_DIR (image font; not in the repo)",
)


@needs_fonts
def test_t7_real_export_is_stored_once_per_overlay_and_read_back_verified(  # noqa: F811
    flow_engine, monkeypatch, client_for, object_store,  # noqa: F811
) -> None:
    from app.deep_review.models import ContentObjectLocation
    from app.deep_review.services.proposal_render import renderer_identity

    with Session(flow_engine) as session:
        w, client, draft_id = _completed_world(session, monkeypatch, client_for, script={"strategy": [bad_quote]})
        exports = f"/api/proposals/{draft_id}/exports"
        first = client.post(exports, json={"request_id": str(uuid4())}, headers=ACTOR)  # partial is allowed
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["created"] is True
        session.expire_all()
        row = session.get(ProposalExport, UUID(body["export_id"]))
        version, font_sha256 = renderer_identity()
        assert (row.renderer_version, row.font_sha256, row.pdf_sha256) == (version, font_sha256, body["pdf_sha256"])
        assert row.page_count >= 9 and row.created_by == "jechoi"
        draft = session.get(ProposalDraft, draft_id)
        assert row.overlay_sha256 == overlay_sha256(overlay_inputs(session, draft), renderer_version=version,
                                                    font_sha256=font_sha256)
        content = session.get(ContentObject, row.content_object_id)
        assert (content.sha256, content.detected_mime, content.retention_class) == (
            body["pdf_sha256"], "application/pdf", "proposal-pdf-365d")
        location = session.scalar(select(ContentObjectLocation).where(
            ContentObjectLocation.content_object_id == content.id))
        assert location.namespace_key == "proposal-pdf" and location.object_key.startswith("proposal-pdf/")
        assert location.encryption_key_ref is None and location.status == "verified"
        pdf = client.get(f"/api/proposals/{draft_id}/exports/{body['export_id']}.pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        assert hashlib.sha256(pdf.content).hexdigest() == body["pdf_sha256"] == pdf.headers["X-BidOps-Export-Sha256"]
        # the same overlay reuses the row and the object (no second render or upload)
        stored = len(object_store)
        again = client.post(exports, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert again.status_code == 201 and again.json() == {**body, "created": False}
        assert len(object_store) == stored
        assert int(session.scalar(select(func.count()).select_from(ProposalExport)) or 0) == 1
        # an edit is a new overlay: new export with different bytes
        view = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()
        sentence = _sentence(view, "overview")
        assert client.post(f"/api/proposals/{draft_id}/sentences/{sentence['sentence_id']}/edits",
                           json={"text": "고친 문장이다.", "request_id": str(uuid4())}, headers=ACTOR).status_code == 201
        third = client.post(exports, json={"request_id": str(uuid4())}, headers=ACTOR).json()
        assert third["created"] is True and third["pdf_sha256"] != body["pdf_sha256"]
        latest = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()["draft"]["latest_export"]
        assert latest["export_id"] == third["export_id"]
        # stored bytes that no longer match pdf_sha256 are never served
        key = (location.namespace_key, location.object_key)
        data, metadata = object_store[key]
        object_store[key] = (data + b"tampered", metadata)
        _envelope(client.get(f"/api/proposals/{draft_id}/exports/{body['export_id']}.pdf"), "pdf_unavailable", 503)


# --- review decision B50 -------------------------------------------------------------------------


def test_b50_rest_refuses_rewrite_after_review_and_mutations_on_a_superseded_draft(  # noqa: F811
    flow_engine, monkeypatch, client_for,
) -> None:
    with Session(flow_engine) as session:
        w, client, draft_id = _completed_world(session, monkeypatch, client_for)
        regen = f"/api/proposals/{draft_id}/sections/overview/regenerations"
        for key in PROPOSAL_SECTION_KEYS:
            assert client.patch(f"/api/proposals/{draft_id}/sections/{key}/review",
                                json={"request_id": str(uuid4())}, headers=ACTOR).status_code == 200
        request_id = uuid4()
        _envelope(client.post(regen, json={"request_id": str(request_id)}, headers=ACTOR),
                  "stage_transition_invalid", 409, request_id)
        assert client.patch(f"/api/proposals/{draft_id}/stage", json={"stage": "ready", "request_id": str(uuid4())},
                            headers=ACTOR).status_code == 200
        _envelope(client.post(regen, json={"request_id": str(request_id)}, headers=ACTOR),
                  "stage_transition_invalid", 409, request_id)
        old_view = client.get(f"/api/opportunities/{w.opportunity_id}/proposal").json()
        sentence = _sentence(old_view, "overview")
        # a new draft supersedes this one; the old draft is read-only through the API too
        created = client.post(f"/api/opportunities/{w.opportunity_id}/proposal-requests",
                              json={"request_id": str(uuid4())}, headers=ACTOR)
        assert created.status_code == 202, created.text
        edit_id = uuid4()
        _envelope(client.post(f"/api/proposals/{draft_id}/sentences/{sentence['sentence_id']}/edits",
                              json={"text": "고친 문장.", "request_id": str(edit_id)}, headers=ACTOR),
                  "stage_transition_invalid", 409, edit_id)
        review_id = uuid4()
        _envelope(client.patch(f"/api/proposals/{draft_id}/sections/overview/review",
                               json={"request_id": str(review_id)}, headers=ACTOR),
                  "stage_transition_invalid", 409, review_id)
        assert int(session.scalar(select(func.count()).select_from(ProposalSentenceEdit)) or 0) == 0
