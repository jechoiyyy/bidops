"""PS-01 카드 lineage 실행기·현재성·공존·응답 v2·가져오기 (T5~T9, MVP 가져오기)."""

from __future__ import annotations

from datetime import timedelta
import json
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.core.models import AuditEvent
from app.deep_review.cli import import_company_fit_judgments as import_cli
from app.deep_review.models import DeepReview, PreSpecCompanyFitAttempt
from app.deep_review.routers.deep_reviews import pre_spec_overview_router
from app.deep_review.services import company_fit as fit, company_fit_runner as worker, effective_grade
from app.deep_review.services.company_fit_card import load_business_scope_card
from app.deep_review.services.company_fit_import import (
    CompanyFitImportError,
    import_company_fit_judgments,
    parse_judgment_bundle,
)
from tests.deep_review.company_fit_card_fixtures import (
    CARD,
    NOW,
    REVISION,
    CardClient,
    add_notice,
    add_overview_run,
    card_env,
    card_input,
    card_output,
    card_row,
    replace_card,
    track,
)
from tests.deep_review.test_company_fit import (
    Client as ProfileClient,
    _FakeStore,
    enqueue as enqueue_profile,
    output as profile_output,
    ready_bundle,
    setup_inputs,
)


@pytest.fixture
def engine():
    bind = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind)
    yield bind
    bind.dispose()
    get_settings.cache_clear()


@pytest.fixture
def session(engine, monkeypatch):
    # The view reads auto-preparation fields; the C-1 grade seam is not under test here.
    from app.deep_review.services import auto_preparation

    monkeypatch.setattr(auto_preparation, "effective_grades", lambda s, ids: {})
    with Session(engine) as value:
        yield value


def _runner(client=None):
    return worker.PreSpecCompanyFitRunner(client=client, raw_response_store=_FakeStore(), clock=lambda: NOW)


def _card_rows(session):
    return list(session.scalars(select(PreSpecCompanyFitAttempt).where(
        PreSpecCompanyFitAttempt.card_sha256.is_not(None)).order_by(PreSpecCompanyFitAttempt.created_at)))


def _profile_rows(session):
    return list(session.scalars(select(PreSpecCompanyFitAttempt).where(
        PreSpecCompanyFitAttempt.company_id.is_(None), PreSpecCompanyFitAttempt.card_sha256.is_(None))))


def _drain_enqueue(session):
    runner = _runner()
    card = load_business_scope_card(get_settings())
    while True:
        before = len(_card_rows(session))
        runner._enqueue_card(session, card, NOW)
        if len(_card_rows(session)) == before:
            return {row.notice_id for row in _card_rows(session)}


@pytest.fixture
def no_deep_start(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("card fits must never start a deep review")

    monkeypatch.setattr(worker, "maybe_auto_start_deep_review", forbidden)


# --- T5 enqueue 대상 -----------------------------------------------------------


def test_t5_enqueue_targets_ignore_grade_and_respect_scope(session, tmp_path, monkeypatch):
    card_env(monkeypatch, tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the C-1 grade is never read by the card lineage")

    monkeypatch.setattr(effective_grade, "priority_notice_ids", forbidden)
    monkeypatch.setattr(effective_grade, "effective_grades", forbidden)
    open_notice = add_notice(session)                                   # 우선 검토 아님
    unknown_deadline = add_notice(session, deadline=None)
    passed = add_notice(session, deadline=NOW - timedelta(days=1))
    passed_tracked = add_notice(session, deadline=NOW - timedelta(days=1))
    track(session, passed_tracked, "보류")
    not_sw = add_notice(session, sw="N")
    failed_overview = add_notice(session, overview="failed")
    human_overview = add_notice(session, overview="needs_human_review")
    unchecked = add_notice(session, checks="failed")
    already_failed = add_notice(session)
    session.commit()
    previous = card_row(card_input(session, already_failed), status="failed")
    previous.error_code = "company_fit_execution_failed"
    session.add(previous)
    session.commit()

    created = _drain_enqueue(session)

    assert created == {open_notice.id, unknown_deadline.id, passed_tracked.id, already_failed.id}
    rows = [row for row in _card_rows(session) if row.status == "queued"]
    assert {row.notice_id for row in rows} == {open_notice.id, unknown_deadline.id, passed_tracked.id}
    assert all(row.profile_version_id is None and row.deep_policy_version_id is None for row in rows)
    assert all(row.input_jsonb["judged_by"] == "model" for row in rows)
    assert passed.id not in created and not_sw.id not in created
    assert {failed_overview.id, human_overview.id, unchecked.id}.isdisjoint(created)
    # 감사 metadata는 프로필 키 + 카드 신원이다.
    audit = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == str(rows[0].id))).one()
    assert audit.safe_metadata["lineage"] == "card"
    assert audit.safe_metadata["card_sha256"] == rows[0].card_sha256
    assert audit.safe_metadata["card_version"] == "bidops.business-scope-card.v1.2"
    assert {"notice_id", "status", "reason_code", "input_sha256", "quality_status", "validation_retry"} <= set(
        audit.safe_metadata)


def test_t5_enqueue_order_is_deadline_order_and_one_per_poll(session, tmp_path, monkeypatch):
    card_env(monkeypatch, tmp_path)
    later = add_notice(session, deadline=NOW + timedelta(days=3))
    unknown = add_notice(session, deadline=None)
    passed_tracked = add_notice(session, deadline=NOW - timedelta(days=2))
    track(session, passed_tracked)
    huge = add_notice(session, deadline=NOW + timedelta(hours=1), title="가" * 30000)
    soon = add_notice(session, deadline=NOW + timedelta(days=1))
    session.commit()
    runner = _runner()
    card = load_business_scope_card(get_settings())
    order = []
    for _ in range(6):
        before = {row.notice_id for row in _card_rows(session)}
        runner._enqueue_card(session, card, NOW)
        new = {row.notice_id for row in _card_rows(session)} - before
        assert len(new) <= 1
        order.extend(new)
    # 너무 큰 입력은 건너뛰고 다음 공고를 막지 않는다.
    assert order == [soon.id, later.id, passed_tracked.id, unknown.id]
    assert huge.id not in order


def test_t5_mode_off_enqueues_nothing(session, tmp_path, monkeypatch, no_deep_start):
    card_env(monkeypatch, tmp_path, mode="off")
    add_notice(session)
    session.commit()
    client = CardClient(card_output())
    assert not _runner(client).run_once(session, "worker")
    assert _card_rows(session) == [] and client.calls == 0


# --- T6 실행 ------------------------------------------------------------------


def test_t6_card_row_runs_without_profile_or_policy_and_never_starts_deep_review(
    session, tmp_path, monkeypatch, no_deep_start
):
    card_env(monkeypatch, tmp_path)
    notice = add_notice(session)
    session.commit()
    client = CardClient(card_output("matched"))
    assert _runner(client).run_once(session, "worker")
    row = _card_rows(session)[0]
    assert row.status == "completed" and row.result_jsonb["decision"] == "matched"
    assert row.notice_id == notice.id and row.prompt_tokens == 300
    assert client.calls == 1 and client.seeds == [None]
    assert list(client.inputs[0]) == ["schema_version", "notice_id", "notice_facts", "input_limitations",
                                      "company_facts", "model_name", "prompt_version"]
    assert client.inputs[0]["schema_version"] == "bidops.prespec-company-fit-input.v2"
    assert client.policies[0] == row.input_jsonb["fit_policy"]
    assert session.scalar(select(func.count()).select_from(DeepReview)) == 0
    assert _profile_rows(session) == []
    statuses = [event.safe_metadata["status"] for event in session.scalars(
        select(AuditEvent).where(AuditEvent.aggregate_id == str(row.id)))]
    assert sorted(statuses) == ["completed", "queued", "running"]
    # 같은 입력은 다시 부르지 않는다.
    assert not _runner(client).run_once(session, "worker") and client.calls == 1


def _invalid():
    result = card_output()
    result["reasons"][0]["company_refs"] = ["scope:missing"]
    return result


@pytest.mark.parametrize("retry,status,calls", [(card_output("unknown"), "completed", 2), (_invalid(), "needs_human_review", 2)])
def test_t6_validation_retry_once_then_human_review(session, tmp_path, monkeypatch, no_deep_start, retry, status, calls):
    card_env(monkeypatch, tmp_path)
    add_notice(session)
    session.commit()
    client = CardClient(_invalid(), retry_result=retry)
    assert _runner(client).run_once(session, "worker")
    row = _card_rows(session)[0]
    assert row.status == status and client.calls == calls and client.seeds == [None, 1]
    if status == "needs_human_review":
        assert row.result_jsonb is None and row.error_code == "company_fit_validation_failed"


def test_t6_identity_mismatch_calls_no_model(session, tmp_path, monkeypatch, no_deep_start):
    card_env(monkeypatch, tmp_path)
    add_notice(session)
    session.commit()
    client = CardClient(card_output(), revision="c" * 64)
    assert _runner(client).run_once(session, "worker")
    row = _card_rows(session)[0]
    assert row.status == "failed" and row.error_code == "company_fit_execution_failed"
    assert client.calls == 0


# --- T7 현재성 ----------------------------------------------------------------


def _completed(session, tmp_path, monkeypatch, decision="matched"):
    path = card_env(monkeypatch, tmp_path)
    notice = add_notice(session)
    session.commit()
    row = card_row(card_input(session, notice), status="completed", result=card_output(decision))
    session.add(row)
    session.commit()
    return path, notice, row


def test_t7_display_currentness(session, tmp_path, monkeypatch):
    path, notice, row = _completed(session, tmp_path, monkeypatch)
    assert fit.card_current_flags(session, [row])[row.id] is True
    # MVP 3: 모델 binding은 표시용 현재성에 쓰지 않는다.
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_MODEL_REVISION", "c" * 64)
    get_settings.cache_clear()
    assert fit.card_current_flags(session, [row])[row.id] is True
    # 카드 sha가 바뀌면 현재가 아니다.
    changed = json.loads(json.dumps(CARD))
    changed["scopes"][0]["summary"] = "다른 요약"
    replace_card(monkeypatch, path, changed)
    assert fit.card_current_flags(session, [row])[row.id] is False
    replace_card(monkeypatch, path, CARD)
    assert fit.card_current_flags(session, [row])[row.id] is True
    # 카드를 읽을 수 없으면 모든 카드 행이 현재가 아니다.
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH", "")
    get_settings.cache_clear()
    assert fit.card_current_flags(session, [row])[row.id] is False
    replace_card(monkeypatch, path, CARD)
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH", str(path))
    get_settings.cache_clear()
    # 새 개요 run이 현재가 되면 현재가 아니다.
    add_overview_run(session, notice, created_at=NOW + timedelta(days=1))
    session.commit()
    assert fit.current_flags(session, [row])[row.id] is False


def test_t7_claim_rechecks_overview_and_model_binding(session, tmp_path, monkeypatch, no_deep_start):
    card_env(monkeypatch, tmp_path)
    notice = add_notice(session)
    session.commit()
    stale = card_row(card_input(session, notice), created_at=NOW - timedelta(hours=1))
    session.add(stale)
    session.commit()
    add_overview_run(session, notice, created_at=NOW + timedelta(days=1))
    session.commit()
    client = CardClient(card_output())
    assert _runner(client).run_once(session, "worker")
    session.refresh(stale)
    assert stale.status == "failed" and stale.error_code == "inputs_changed" and client.calls == 0

    other = add_notice(session)
    session.commit()
    queued = card_row(card_input(session, other), created_at=NOW - timedelta(minutes=30))
    session.add(queued)
    session.commit()
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_MODEL_REVISION", "c" * 64)
    get_settings.cache_clear()
    assert _runner(client).run_once(session, "worker")
    session.refresh(queued)
    assert queued.status == "failed" and queued.error_code == "inputs_changed" and client.calls == 0


# --- T8 공존 ------------------------------------------------------------------


@pytest.fixture
def profile_world(session, tmp_path, monkeypatch):
    """활성 프로필·정책과 프로필 lineage가 enqueue할 수 있는 우선 검토 공고."""

    card_env(monkeypatch, tmp_path)
    source, _profile, _policy, inputs = setup_inputs(session, tmp_path, monkeypatch)
    monkeypatch.setattr(effective_grade, "priority_notice_ids", lambda s, ids: frozenset(ids))
    monkeypatch.setattr(worker, "priority_notice_ids", lambda s, ids: frozenset(ids))
    from app.deep_review.services import auto_preparation
    monkeypatch.setattr(auto_preparation, "effective_grades", lambda s, ids: {})
    ready_bundle(session, inputs)  # SW=Y, 자동 확정 묶음
    return inputs


def test_t8_card_mode_pauses_the_profile_lineage(session, profile_world, monkeypatch, no_deep_start):
    inputs = profile_world
    queued_profile = enqueue_profile(session, inputs)
    runner = _runner(CardClient(card_output()))
    called = []
    monkeypatch.setattr(runner, "_enqueue_one", lambda s: called.append(s))
    assert runner.run_once(session, "worker")
    assert called == []
    card = _card_rows(session)
    assert len(card) == 1 and card[0].status == "completed"
    assert not runner.run_once(session, "worker")
    session.refresh(queued_profile)
    assert queued_profile.status == "queued"
    assert [row.id for row in _profile_rows(session)] == [queued_profile.id]
    # 프로필 lineage 질의는 카드 행을 섞지 않는다.
    assert fit.latest_attempts(session, [inputs["notice_id"]])[inputs["notice_id"]].id == queued_profile.id
    # 우선 검토 공고도 회사 핏을 통한 심층 자동 시작이 막힌다.
    assert fit.gate_reasons(session, [inputs["notice_id"]]) == {inputs["notice_id"]: "company_fit_suggest_only"}


def test_t8_mode_off_keeps_the_profile_lineage(session, profile_world, monkeypatch):
    inputs = profile_world
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE", "off")
    get_settings.cache_clear()
    monkeypatch.setattr(worker, "maybe_auto_start_deep_review", lambda *args: None)
    client = ProfileClient(profile_output())
    assert _runner(client).run_once(session, "worker")
    assert _card_rows(session) == []
    rows = _profile_rows(session)
    assert len(rows) == 1 and rows[0].status == "completed" and client.calls == 1
    assert fit.gate_reasons(session, [inputs["notice_id"]]) == {inputs["notice_id"]: None}


# --- T9 응답 v2 ---------------------------------------------------------------


def _view(session, notice_id):
    get_settings.cache_clear()
    return fit.company_fit_view(session, notice_id)


@pytest.mark.parametrize("decision,suggested", [("matched", True), ("mismatch", False), ("unknown", False)])
def test_t9_card_view_and_engine_suggestion(session, tmp_path, monkeypatch, decision, suggested):
    _path, notice, row = _completed(session, tmp_path, monkeypatch, decision)
    view = _view(session, notice.id)
    assert view.schema_version == "bidops.prespec-company-fit.v2"
    assert view.automation_enabled is True
    assert view.mode.effective is True and view.mode.mode == "suggest"
    assert view.engine_suggested is suggested
    attempt = view.attempts[0]
    assert attempt.lineage == "card" and attempt.judged_by == "model" and attempt.is_current
    assert attempt.card_sha256 == row.card_sha256 and attempt.card_version == row.card_version
    assert attempt.profile_version_id is None and attempt.profile_sha256 is None
    assert attempt.company_fact_labels["policy:no-bid"] == "수행하지 않는 사업"
    assert attempt.result.decision == decision


def test_t9_engine_suggestion_needs_suggest_mode_and_currentness(session, tmp_path, monkeypatch):
    _path, notice, _row = _completed(session, tmp_path, monkeypatch)
    # MVP 4: 실행기 실효(mode.effective)는 요구하지 않는다.
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "false")
    view = _view(session, notice.id)
    assert view.engine_suggested is True and view.mode.effective is False
    assert view.automation_enabled is False
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_ENABLED", "true")
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE", "off")
    view = _view(session, notice.id)
    assert view.engine_suggested is False and view.mode.reason_code == "switch_off"
    assert view.attempts[0].lineage == "card"
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE", "suggest")
    add_overview_run(session, notice, created_at=NOW + timedelta(days=1))
    session.commit()
    view = _view(session, notice.id)
    assert view.engine_suggested is False and view.attempts[0].is_current is False


def test_t9_latest_lineage_wins_and_profile_rows_keep_v1_fields(session, profile_world, monkeypatch):
    inputs = profile_world
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE", "off")
    get_settings.cache_clear()
    profile_row = enqueue_profile(session, inputs)
    view = _view(session, inputs["notice_id"])
    assert view.automation_enabled is True and view.engine_suggested is False
    attempt = view.attempts[0]
    assert attempt.lineage == "profile" and attempt.id == profile_row.id
    assert attempt.card_version is None and attempt.card_sha256 is None and attempt.judged_by is None
    assert attempt.company_fact_labels is None
    assert attempt.profile_version_id == UUID(inputs["profile_version_id"])
    # 더 최근의 카드 행이 생기면 카드 행만 보인다.
    newer = card_row(card_input(session, session.get(fit.Notice, inputs["notice_id"])), status="completed",
                     created_at=profile_row.created_at + timedelta(seconds=1))
    session.add(newer)
    session.commit()
    assert [a.id for a in _view(session, inputs["notice_id"]).attempts] == [newer.id]


def test_t9_router_returns_v2_json(session, tmp_path, monkeypatch):
    _path, notice, _row = _completed(session, tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(pre_spec_overview_router)
    app.dependency_overrides[get_db] = lambda: session
    body = TestClient(app).get(f"/api/pre-specs/{notice.id}/company-fit").json()
    assert body["schema_version"] == "bidops.prespec-company-fit.v2"
    assert set(body["mode"]) == {"mode", "effective", "reason_code", "card_version", "card_sha256", "prompt_version",
                                 "set_by", "set_at"}
    assert body["engine_suggested"] is True
    assert body["attempts"][0]["lineage"] == "card"
    assert "business-scope-card.yaml" not in json.dumps(body)


# --- MVP 5 가져오기 -----------------------------------------------------------


def _bundle(tmp_path, card_sha, rows, name="judgments.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"judged_by": "claude_reference", "card_sha256": card_sha, "rows": rows},
                               ensure_ascii=False), encoding="utf-8")
    return path


def test_import_judgments_creates_completed_claude_rows_idempotently(session, tmp_path, monkeypatch):
    card_env(monkeypatch, tmp_path)
    good = add_notice(session)
    bad = add_notice(session)
    missing_overview = add_notice(session, overview=None)
    session.commit()
    card_sha = load_business_scope_card(get_settings()).card_sha256
    invalid = card_output()
    invalid["reasons"][0]["notice_refs"] = ["fabricated:0"]
    path = _bundle(tmp_path, card_sha, [
        {"notice_id": good.id, "result": card_output("matched")},
        {"notice_id": bad.id, "result": invalid},
        {"notice_id": missing_overview.id, "result": card_output()},
    ])
    payload, file_sha = parse_judgment_bundle(path.read_bytes())
    result = import_company_fit_judgments(session, payload, file_sha256=file_sha, actor="테스터")
    assert [item["notice_id"] for item in result.imported] == [good.id]
    assert {(item["notice_id"], item["reason"]) for item in result.skipped} == {
        (bad.id, "result_invalid"), (missing_overview.id, "overview_not_completed")}
    row = _card_rows(session)[0]
    assert row.status == "completed" and row.completed_at is not None and row.lease_owner is None
    assert row.input_jsonb["judged_by"] == "claude_reference"
    assert row.model_name == "claude-reference-judgment" and row.model_revision == file_sha
    assert row.policy_digest == fit.digest(fit.card_fit_policy("claude-reference-judgment"))
    audit = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == str(row.id))).one()
    assert audit.actor_kind == "human" and audit.claimed_name == "테스터"
    assert audit.safe_metadata["judged_by"] == "claude_reference"
    # 표시: 현재·matched·suggest → 추천이 켜진다.
    view = _view(session, good.id)
    assert view.attempts[0].judged_by == "claude_reference" and view.engine_suggested is True
    # 같은 파일을 다시 넣어도 행은 그대로 하나다.
    again = import_company_fit_judgments(session, payload, file_sha256=file_sha, actor="테스터")
    assert again.imported == [] and (good.id, "already_imported") in {
        (item["notice_id"], item["reason"]) for item in again.skipped}
    assert len(_card_rows(session)) == 1
    # 실행기는 가져온 행을 다시 부르지 않는다(완료 행이며 judged_by가 model이 아니다).
    assert fit.card_current_flags(session, [row])[row.id] is True


def test_import_dry_run_writes_nothing(session, tmp_path, monkeypatch):
    card_env(monkeypatch, tmp_path)
    notice = add_notice(session)
    session.commit()
    card_sha = load_business_scope_card(get_settings()).card_sha256
    payload, file_sha = parse_judgment_bundle(
        _bundle(tmp_path, card_sha, [{"notice_id": notice.id, "result": card_output()}]).read_bytes())
    result = import_company_fit_judgments(session, payload, file_sha256=file_sha, actor="테스터", dry_run=True)
    assert result.imported[0]["attempt_id"] is None
    assert _card_rows(session) == []


@pytest.mark.parametrize("bundle", [
    {"judged_by": "model", "card_sha256": "x", "rows": []},
    {"judged_by": "claude_reference", "card_sha256": "x", "rows": [{"notice_id": "1", "result": {}}]},
    {"judged_by": "claude_reference", "rows": []},
])
def test_import_rejects_malformed_bundles(bundle):
    with pytest.raises(CompanyFitImportError) as error:
        parse_judgment_bundle(json.dumps(bundle).encode())
    assert error.value.code == "input_invalid"


def test_import_cli_exit_codes(engine, session, tmp_path, monkeypatch, capsys):
    card_env(monkeypatch, tmp_path)
    notice = add_notice(session)
    session.commit()
    monkeypatch.setattr(import_cli, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(import_cli, "init_db", lambda: None)
    card_sha = load_business_scope_card(get_settings()).card_sha256
    wrong = _bundle(tmp_path, "0" * 64, [{"notice_id": notice.id, "result": card_output()}], "wrong.json")
    assert import_cli.main(["--file", str(wrong), "--actor", "테스터"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["errors"] == ["card_sha256_mismatch"]
    assert captured.err.strip() == "card_sha256_mismatch"
    # 설정 sha와 파일 sha가 다를 때도 전체 거부다.
    good = _bundle(tmp_path, card_sha, [{"notice_id": notice.id, "result": card_output()}])
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256", "1" * 64)
    get_settings.cache_clear()
    assert import_cli.main(["--file", str(good), "--actor", "테스터"]) == 2
    assert json.loads(capsys.readouterr().out)["errors"] == ["card_sha256_mismatch"]
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256", card_sha)
    get_settings.cache_clear()
    assert import_cli.main(["--file", str(tmp_path / "absent.json"), "--actor", "테스터"]) == 2
    capsys.readouterr()
    assert import_cli.main(["--file", str(good), "--actor", "테스터"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert len(body["imported"]) == 1 and body["errors"] == []
    assert import_cli.main(["--file", str(good), "--actor", "테스터"]) == 0
    assert json.loads(capsys.readouterr().out)["skipped"][0]["reason"] == "already_imported"
    session.expire_all()
    assert len(_card_rows(session)) == 1


def test_t5_enqueue_skips_notices_collected_before_the_observed_from_cutoff(session, tmp_path, monkeypatch):
    """2026-11-27 user decision: already-collected notices are never judged; only later collections."""

    from app.lifecycle.models import NoticeObservation, Run

    card_env(monkeypatch, tmp_path)
    cutoff = NOW - timedelta(hours=6)
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_OBSERVED_FROM", cutoff.isoformat())
    get_settings.cache_clear()
    runs: dict[str, Run] = {}

    def observe(notice, *moments):
        # One observation per (notice, run): each collection moment is its own run.
        for moment in moments:
            run_id = f"lifecycle-cutoff--{moment:%Y%m%dT%H%M%S}Z"
            if run_id not in runs:
                runs[run_id] = Run(id=run_id, generated_at=moment)
                session.add(runs[run_id])
                session.flush()
            session.add(NoticeObservation(notice_id=notice.id, run_id=run_id, observed_at=moment))
        session.flush()

    old = add_notice(session)                       # first seen before the cutoff
    observe(old, cutoff - timedelta(days=3))
    reobserved = add_notice(session)                # seen again after the cutoff, but first seen before
    observe(reobserved, cutoff - timedelta(days=1), cutoff + timedelta(hours=1))
    new = add_notice(session)                       # first seen after the cutoff
    observe(new, cutoff + timedelta(hours=2))
    at_cutoff = add_notice(session)                 # boundary is inclusive
    observe(at_cutoff, cutoff)
    never_seen = add_notice(session)                # no observation at all: not judged
    session.commit()

    assert _drain_enqueue(session) == {new.id, at_cutoff.id}
    assert {old.id, reobserved.id, never_seen.id}.isdisjoint({row.notice_id for row in _card_rows(session)})

    # An empty value keeps the previous behaviour (no cutoff).
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_OBSERVED_FROM", "")
    get_settings.cache_clear()
    assert get_settings().prespec_company_fit_card_observed_from is None
    assert _drain_enqueue(session) == {new.id, at_cutoff.id, old.id, reobserved.id, never_seen.id}


def test_observed_from_must_carry_a_timezone(monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_OBSERVED_FROM", "2026-11-27T21:15:00")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()
    monkeypatch.delenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_OBSERVED_FROM")
    get_settings.cache_clear()
