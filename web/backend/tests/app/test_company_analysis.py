"""DEMO-03 company-fit product path with fake LiteLLM transport (spec T4·T8).

``enqueue-company-fit`` freezes a CompanyAnalysisInput; the composed runner
claims it, calls the ``overview`` purpose client through an injected fake
transport (no socket), validates the v2 result and stores it.  Legacy
single-company rows keep their own builder/validator.  PostgreSQL variants
prove the 0036 schema: purpose-specific policy FK, graph composite FKs, frozen
provenance, triggers and the append-only policy table.
"""

from __future__ import annotations

from copy import deepcopy
import json
import logging
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import ALEMBIC_HEAD
from app.core.model_client import ModelClient
from app.core.models import AuditEvent
from app.deep_review.models import (
    DocumentBundle,
    PreSpecCompanyFitAttempt,
    PrespecOverviewRun,
    WorkJob,
)
from app.deep_review.services import company_fit as fit
from app.deep_review.services import company_fit_runner as worker
from app.deep_review.services.input_versions import import_policy_version
from app.lifecycle.models import Notice
from tests.deep_review.test_company_fit import _FakeStore, ready_bundle, setup_inputs
from tests.deep_review.test_company_fit_enqueue import (  # noqa: F401 - shared fixtures
    FIXTURES,
    OVERVIEW_RESULT,
    World,
    build_world,
    configure,
    engine,
    enqueue,
    import_company,
    object_store,
    sqlite_engine,
)
from tests.fakes.model_transport import completion
from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database


MODEL = "local-agent-main"


class FakeLiteLLM:
    """OpenAI-compatible LiteLLM surface: `/models`, `/model/info`, completions."""

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def models(self):
        return {"data": [{"id": MODEL, "object": "model"}]}

    def model_info(self):
        return {"data": [{"model_name": MODEL, "litellm_params": {"model": "hidden-upstream"},
                          "model_info": {"max_input_tokens": 262144}}]}

    def create(self, **request):
        self.requests.append(request)
        value = self.responses.pop(0)
        value = value(request) if callable(value) else value
        return completion(value, model=MODEL)


@pytest.fixture
def transport(monkeypatch):
    fake = FakeLiteLLM()
    calls: list[tuple[str, str, str]] = []
    real = ModelClient.for_purpose.__func__

    def for_purpose(cls, purpose, **kwargs):
        calls.append((purpose, kwargs["model"], kwargs["output_contract"].name))
        return real(cls, purpose, completion_create=fake.create, models_list=fake.models,
                    model_info_list=fake.model_info, **kwargs)

    monkeypatch.setattr(ModelClient, "for_purpose", classmethod(for_purpose))
    fake.for_purpose_calls = calls
    return fake


@pytest.fixture
def auto_start_calls(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(worker, "maybe_auto_start_deep_review", lambda _s, notice_id: calls.append(notice_id))
    return calls


def valid_payload(inputs: dict) -> dict:
    requirement = next(row for row in inputs["requirements"] if row["id"].endswith("main_tasks:0"))
    indexes = [index for index, path in enumerate(inputs["graph_paths"])
               if path["requirement_id"] == requirement["id"] and path["relation"] == "direct"]
    facts = {row["fact_key"]: row for row in inputs["profile_facts"]}
    fact = next(node for node in inputs["graph_paths"][indexes[0]]["node_ids"]
                if node != "company" and node in facts and facts[node]["status"] == "confirmed")
    return {
        "schema_version": "bidops.prespec-company-fit-result.v2",
        "decision": "matched",
        "summary": "데이터 플랫폼 과업과 회사의 확인된 주력 역량이 연결됩니다.",
        "reasons": [{
            "kind": "scope_match",
            "explanation": "공고의 데이터 플랫폼 구축 과업과 회사의 확인된 주력 역량을 대조했습니다.",
            "notice_refs": [requirement["id"]],
            "company_refs": [fact],
            "graph_path_indexes": indexes[:1],
        }],
        "verification_items": [],
    }


def _runner(**kwargs) -> worker.PreSpecCompanyFitRunner:
    return worker.PreSpecCompanyFitRunner(raw_response_store=kwargs.pop("store", _FakeStore()), **kwargs)


def _audits(session: Session, row_id: UUID) -> list[AuditEvent]:
    return list(session.scalars(select(AuditEvent).where(
        AuditEvent.action == "prespec_company_fit.attempt", AuditEvent.aggregate_id == str(row_id))))


def _prompt(request: dict) -> str:
    return "\n".join(str(message["content"]) for message in request["messages"])


# --- T4 fake end-to-end -------------------------------------------------------------


def test_t4_fit_enqueue_claim_and_complete(engine, monkeypatch, transport, auto_start_calls, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with Session(engine) as session:
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        frozen_input, frozen_provenance = deepcopy(row.input_jsonb), deepcopy(row.provenance_jsonb)
        payload = valid_payload(frozen_input)
        transport.responses.append(payload)
        store = _FakeStore()

        assert _runner(store=store).run_once(session, "fit-worker")

        session.expire_all()
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        assert row.status == "completed" and row.error_code is None
        assert row.result_jsonb == payload and row.result_sha256 == fit.digest(payload)
        assert row.input_jsonb == frozen_input and row.provenance_jsonb == frozen_provenance
        # The fit freezes the notice's current document set (no bundle here: its current
        # documents); the multi-document comparable case is tests/app/test_company_e2e.py.
        assert [item["document_version_id"] for item in row.provenance_jsonb["documents"]] == (
            row.input_jsonb["document_version_ids"]) == [str(world.document_id)]
        assert row.raw_response_sha256 and len(store.calls) == 1
        assert row.lease_owner is None and row.completed_at is not None
        assert transport.for_purpose_calls == [("overview", MODEL, "prespec_company_fit_v2")]
        assert len(transport.requests) == 1
        prompt = _prompt(transport.requests[0])
        assert payload["reasons"][0]["notice_refs"][0] in prompt and "graph_paths" in prompt
        assert "prespec-company-fit-input.v1" not in prompt and "fit_policy" not in prompt
        assert transport.requests[0]["model"] == MODEL
        assert fit.validate_company_fit_result(row.result_jsonb, row.input_jsonb).decision == "matched"
        assert fit.current_flags(session, [row]) == {row.id: True}
        # No deep review is started from a company fit, and nothing else is queued.
        assert auto_start_calls == []
        assert not _runner().run_once(session, "fit-worker") and len(transport.requests) == 1
        statuses = [audit.safe_metadata["status"] for audit in _audits(session, row.id)]
        assert sorted(statuses) == ["completed", "queued", "running"]
        for audit in _audits(session, row.id):
            assert audit.safe_metadata["company_id"] == str(world.company_id)
            body = json.dumps(audit.safe_metadata, ensure_ascii=False)
            assert "데이터 플랫폼" not in body and "explanation" not in body
    logs = caplog.text
    assert "데이터 플랫폼" not in logs and "주력 역량" not in logs
    get_settings.cache_clear()


def test_t4_bad_graph_path_index_retries_once_then_needs_human_review(sqlite_engine, monkeypatch, transport, auto_start_calls) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        bad = valid_payload(row.input_jsonb)
        bad["reasons"][0]["graph_path_indexes"] = [len(row.input_jsonb["graph_paths"]) + 5]
        transport.responses.extend([bad, bad])
        store = _FakeStore()
        assert _runner(store=store).run_once(session, "fit-worker")
        session.expire_all()
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        assert row.status == "needs_human_review" and row.error_code == "company_fit_validation_failed"
        assert row.result_jsonb is None and row.result_sha256 is None
        assert len(transport.requests) == 2 and len(store.calls) == 2
        correction = transport.requests[1]["messages"][-1]["content"]
        assert "graph_path_index_invalid" in correction
        retry = next(a.safe_metadata for a in _audits(session, row.id)
                     if a.safe_metadata["status"] == "needs_human_review")["validation_retry"]
        assert retry["count"] == 1 and retry["first_error_codes"] == ["graph_path_index_invalid"]
        assert auto_start_calls == []
    get_settings.cache_clear()


def test_t4_validation_retry_can_complete_with_the_second_response(sqlite_engine, monkeypatch, transport) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        good = valid_payload(row.input_jsonb)
        other = next(index for index, path in enumerate(row.input_jsonb["graph_paths"])
                     if path["requirement_id"] != good["reasons"][0]["notice_refs"][0])
        bad = deepcopy(good)
        bad["reasons"][0]["graph_path_indexes"] = [other]
        transport.responses.extend([bad, good])
        assert _runner().run_once(session, "fit-worker")
        session.expire_all()
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        assert row.status == "completed" and row.result_jsonb == good and len(transport.requests) == 2
    get_settings.cache_clear()


@pytest.fixture
def frozen(sqlite_engine, monkeypatch):
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        yield deepcopy(session.get(PreSpecCompanyFitAttempt, queued.attempt_id).input_jsonb)
    get_settings.cache_clear()


def _unknown_fact(inputs: dict) -> str:
    return next(row["fact_key"] for row in inputs["profile_facts"] if row["status"] == "unknown")


@pytest.mark.parametrize("change,code", [
    (lambda p, i: p.update(schema_version="bidops.prespec-company-fit-result.v1"), None),
    (lambda p, i: p["reasons"][0].pop("graph_path_indexes"), None),
    (lambda p, i: p["reasons"][0].update(graph_path_indexes=[True]), None),
    (lambda p, i: p["reasons"][0].update(notice_refs=["main_tasks:0"]), "evidence_not_in_input"),
    (lambda p, i: p["reasons"][0].update(company_refs=["company:0"]), "evidence_not_in_input"),
    (lambda p, i: p["reasons"][0].update(company_refs=[_unknown_fact(i)]), "unconfirmed_company_evidence"),
    (lambda p, i: p["reasons"][0].update(company_refs=[]), "unconfirmed_company_evidence"),
    (lambda p, i: p["reasons"][0].update(graph_path_indexes=p["reasons"][0]["graph_path_indexes"] * 2), "graph_path_index_invalid"),
    (lambda p, i: p["reasons"][0].update(graph_path_indexes=[-1]), "graph_path_index_invalid"),
    (lambda p, i: p["reasons"][0].update(graph_path_indexes=[next(
        n for n, path in enumerate(i["graph_paths"]) if path["requirement_id"] != p["reasons"][0]["notice_refs"][0])]),
     "graph_path_index_invalid"),
    (lambda p, i: p["reasons"][0].update(explanation="회사는 수행 실적 999건이 있습니다."), "unsupported_number"),
    (lambda p, i: p.update(summary="회사 수행 실적 999건"), "unsupported_summary_number"),
    (lambda p, i: p["reasons"][0].update(explanation="   "), "blank_reason"),
    (lambda p, i: p["reasons"][0].update(notice_refs=p["reasons"][0]["notice_refs"] * 2), "duplicate_evidence"),
])
def test_v2_result_validation_is_deterministic(frozen, change, code) -> None:
    payload = valid_payload(frozen)
    change(payload, frozen)
    with pytest.raises(ValueError) as error:
        fit.validate_company_fit_result(payload, frozen)
    if code is not None:
        assert getattr(error.value, "code", None) == code


def test_v2_unknown_facts_are_inputs_not_mismatch(frozen) -> None:
    unknown = _unknown_fact(frozen)
    requirement = next(row["id"] for row in frozen["requirements"] if row["id"].endswith("main_tasks:1"))
    payload = {
        "schema_version": "bidops.prespec-company-fit-result.v2", "decision": "unknown",
        "summary": "보안 인증 보유 여부가 확인되지 않았습니다.",
        "reasons": [{"kind": "information_gap", "explanation": "회사 프로필에서 해당 인증은 미확인 상태입니다.",
                     "notice_refs": [requirement], "company_refs": [unknown], "graph_path_indexes": []}],
        "verification_items": ["인증 보유 여부를 확인해 주세요."],
    }
    assert fit.validate_company_fit_result(payload, frozen).decision == "unknown"
    payload["decision"] = "mismatch"
    payload["reasons"][0]["kind"] = "scope_mismatch"
    with pytest.raises(ValueError):
        fit.validate_company_fit_result(payload, frozen)


# --- T8 legacy separation and fail-closed runner ------------------------------------


def test_t8_runner_never_routes_company_rows_through_the_v1_builder(sqlite_engine, monkeypatch, transport, auto_start_calls) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        transport.responses.append(valid_payload(row.input_jsonb))

        def forbidden(*_args, **_kwargs):
            raise AssertionError("legacy v1 path used for a company row")

        for name in ("validate_result", "frozen_input", "priority_notice_ids"):
            monkeypatch.setattr(worker, name, forbidden)
        monkeypatch.setattr(fit, "validate_result", forbidden)
        monkeypatch.setattr(worker.PreSpecCompanyFitRunner, "_eligible", forbidden)
        assert _runner().run_once(session, "fit-worker")
        session.expire_all()
        assert session.get(PreSpecCompanyFitAttempt, queued.attempt_id).status == "completed"
        assert auto_start_calls == []
    get_settings.cache_clear()


def _second_source(slug: str = "demo-data-ai") -> bytes:
    payload = json.loads((FIXTURES / "companies" / f"{slug}.v1.json").read_bytes())
    payload["scenario_version"] = f"{payload['scenario_version']}-rebound"
    return json.dumps(payload, ensure_ascii=False, indent=2).encode()


@pytest.mark.parametrize("change", ["binding", "sw", "overview", "policy_setting", "model_dialect"])
def test_t8_changed_inputs_fail_closed_with_zero_transport_calls(sqlite_engine, monkeypatch, transport, change) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        if change == "binding":
            import_company(session, raw=_second_source())
            session.commit()
        elif change == "sw":
            session.get(Notice, world.notice_id).qualification_flags_json = {"sw_business_status": "N"}
            session.commit()
        elif change == "overview":
            current = session.get(PrespecOverviewRun, world.run_id)
            job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                          aggregate_id=uuid4(), status="queued")
            session.add(job)
            session.flush()
            session.add(PrespecOverviewRun(
                id=uuid4(), notice_id=world.notice_id, document_version_id=world.document_id,
                work_job_id=job.id, status="queued", range_source="auto", range_reason_codes=[],
                policy_digest="0" * 64, model_name=MODEL, warnings_json=[], reason_codes=[],
                call_count=0, raw_response_refs=[], created_at=current.created_at.replace(year=current.created_at.year + 1),
            ))
            session.commit()
        elif change == "policy_setting":
            configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(uuid4()))
        else:
            configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(world.policy_id),
                      BIDOPS_VLLM_OVERVIEW_API_DIALECT="vllm")
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        assert fit.current_flags(session, [row]) == {row.id: False}
        assert _runner().run_once(session, "fit-worker")
        session.expire_all()
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        assert row.status == "failed" and row.error_code == "inputs_changed"
        assert transport.requests == [] and transport.for_purpose_calls == []
    get_settings.cache_clear()


def test_t8_demo_disabled_leaves_company_rows_untouched(sqlite_engine, monkeypatch, transport) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(world.policy_id),
                  BIDOPS_DEMO_ENABLED="false")
        assert not _runner().run_once(session, "fit-worker")
        session.expire_all()
        assert session.get(PreSpecCompanyFitAttempt, queued.attempt_id).status == "queued"
        assert transport.requests == []
    get_settings.cache_clear()


def test_t8_legacy_auto_enqueue_creates_only_null_rows(sqlite_engine, monkeypatch, tmp_path) -> None:
    with Session(sqlite_engine) as session:
        # Legacy single-company world first (its fixture pins profile version 1).
        _source, legacy_profile, legacy_policy, inputs = setup_inputs(session, tmp_path, monkeypatch)
        ready_bundle(session, inputs)
        world = build_world(session, monkeypatch)
        queued = enqueue(session, world)
        company_row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        before = (company_row.status, deepcopy(company_row.input_jsonb), company_row.input_sha256)
        # Re-enable the legacy automation next to the company configuration.
        configure(
            monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(world.policy_id),
            BIDOPS_PRESPEC_COMPANY_FIT_MODEL="test-fit", BIDOPS_VLLM_OVERVIEW_MODEL_REVISION="b" * 64,
            BIDOPS_ACTIVE_PROFILE_VERSION_ID=str(legacy_profile.id),
            BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID=str(legacy_policy.id),
        )
        from app.deep_review.services import auto_preparation, effective_grade
        monkeypatch.setattr(effective_grade, "priority_notice_ids", lambda _s, ids: frozenset(ids))
        monkeypatch.setattr(worker, "priority_notice_ids", lambda _s, ids: frozenset(ids))
        monkeypatch.setattr(auto_preparation, "effective_grades", lambda _s, ids: {})
        runner = worker.PreSpecCompanyFitRunner()
        for _ in range(3):
            runner._enqueue_one(session)
        rows = session.scalars(select(PreSpecCompanyFitAttempt)).all()
        legacy = [row for row in rows if row.id != company_row.id]
        assert legacy and all(row.company_id is None and row.deep_policy_version_id is not None for row in legacy)
        assert all(row.graph_version_id is None and row.company_fit_policy_version_id is None for row in legacy)
        assert session.scalar(select(func.count()).select_from(PreSpecCompanyFitAttempt).where(
            PreSpecCompanyFitAttempt.company_id.is_not(None))) == 1
        session.refresh(company_row)
        assert (company_row.status, company_row.input_jsonb, company_row.input_sha256) == before
        flags = fit.current_flags(session, [*legacy, company_row])
        assert set(flags) == {row.id for row in [*legacy, company_row]}
        assert all(isinstance(value, bool) for value in flags.values())
        # Legacy read projections stay NULL-lineage only.
        assert all(row.company_id is None for row in fit.latest_attempts(session, [world.notice_id]).values())
        assert all(view.id != company_row.id for view in fit.company_fit_view(session, world.notice_id).attempts)
    get_settings.cache_clear()


# --- PostgreSQL schema --------------------------------------------------------------


def _copy_attempt(connection, source_id: UUID, patch: dict) -> None:
    connection.execute(text(
        """INSERT INTO bidops.prespec_company_fit_attempt
           SELECT (jsonb_populate_record(NULL::bidops.prespec_company_fit_attempt,
                   to_jsonb(r) || CAST(:patch AS jsonb))).*
           FROM bidops.prespec_company_fit_attempt r WHERE id = :id"""),
        {"id": source_id, "patch": json.dumps(patch)})


def _patched_copy(row: PreSpecCompanyFitAttempt, **changes) -> dict:
    new_id = str(uuid4())
    inputs = deepcopy(row.input_jsonb)
    inputs["execution_nonce"] = new_id
    provenance = deepcopy(row.provenance_jsonb)
    for key, value in changes.pop("input", {}).items():
        inputs[key] = value
        if key in provenance:
            provenance[key] = value
    digest = fit.digest(inputs)
    provenance["input_sha256"] = digest
    patch = {"id": new_id, "input_jsonb": inputs, "input_sha256": digest, "provenance_jsonb": provenance}
    patch.update(changes)
    return patch


def _expect(engine, statement_or_patch, match: str, *, row_id: UUID | None = None, replica: bool = False) -> None:
    with pytest.raises(DBAPIError, match=match):
        with engine.begin() as connection:
            if replica:
                connection.execute(text("SET LOCAL session_replication_role = replica"))
            if row_id is None:
                connection.execute(text(statement_or_patch))
            else:
                _copy_attempt(connection, row_id, statement_or_patch)


@requires_postgres
def test_pg_0036_constraints_triggers_and_policy_immutability(monkeypatch) -> None:
    with migrated_engine() as engine:
        with Session(engine) as session:
            world = build_world(session, monkeypatch)
            other = import_company(session, "demo-public-si")
            session.commit()
            queued = enqueue(session, world)
            row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
            analysis_policy = import_policy_version(session, created_by_name="tester")
            session.commit()
            row_id = row.id
            assert session.scalar(text("SELECT version_num FROM bidops.alembic_version")) == ALEMBIC_HEAD
            assert ALEMBIC_HEAD == "0036_company_analysis"

            # A consistent copy is accepted (sanity for the helpers below).
            with engine.begin() as connection:
                _copy_attempt(connection, row_id, _patched_copy(row))
            # Purpose-specific policy FK, graph scope and provenance are CHECKed.
            _expect(engine, _patched_copy(row, deep_policy_version_id=str(analysis_policy.id)),
                    "ck_prespec_company_fit_policy_scope", row_id=row_id, replica=True)
            _expect(engine, _patched_copy(row, company_id=None, company_fit_policy_version_id=None,
                                          deep_policy_version_id=str(analysis_policy.id)),
                    "ck_prespec_company_fit_graph_scope", row_id=row_id, replica=True)
            _expect(engine, _patched_copy(row, provenance_jsonb=None), "ck_prespec_company_fit_provenance",
                    row_id=row_id, replica=True)
            _expect(engine, _patched_copy(row, model_revision="not-hex"), "ck_prespec_company_fit_hashes",
                    row_id=row_id, replica=True)
            # The guard binds the frozen input to the row identity.
            stale_nonce = _patched_copy(row)
            stale_nonce["input_jsonb"]["execution_nonce"] = str(row.id)
            stale_nonce["input_sha256"] = fit.digest(stale_nonce["input_jsonb"])
            stale_nonce["provenance_jsonb"]["input_sha256"] = stale_nonce["input_sha256"]
            _expect(engine, stale_nonce, "company fit input binding rejected", row_id=row_id)
            # The frozen document set (input and provenance) must contain the row's
            # overview document; a multi-document set that contains it is accepted.
            foreign_document = str(uuid4())

            def documents_copy(input_ids: list[str], provenance_ids: list[str]) -> dict:
                patch = _patched_copy(row)
                patch["input_jsonb"]["document_version_ids"] = sorted(input_ids)
                patch["provenance_jsonb"]["documents"] = [
                    {"document_version_id": value, "source_sha256": "a" * 64} for value in sorted(provenance_ids)]
                patch["input_sha256"] = fit.digest(patch["input_jsonb"])
                patch["provenance_jsonb"]["input_sha256"] = patch["input_sha256"]
                return patch

            own = str(row.document_version_id)
            _expect(engine, documents_copy([foreign_document], [own]), "company fit input binding rejected", row_id=row_id)
            _expect(engine, documents_copy([own], [foreign_document]), "company fit input binding rejected", row_id=row_id)
            with engine.begin() as connection:
                _copy_attempt(connection, row_id, documents_copy([own, foreign_document], [own, foreign_document]))
            # Another company's graph cannot be combined with this company/profile.
            _expect(engine, _patched_copy(row, graph_version_id=str(other.graph_version_id),
                                          input={"graph_version_id": str(other.graph_version_id)}),
                    "fk_prespec_company_fit_graph_scope", row_id=row_id)
            # The policy table is append-only.
            _expect(engine, "UPDATE bidops.company_fit_policy_version SET payload = payload", "append-only")
            _expect(engine, "DELETE FROM bidops.company_fit_policy_version", "append-only")
            # Frozen inputs, graph and provenance stay immutable while queued.
            _expect(engine, f"UPDATE bidops.prespec_company_fit_attempt SET provenance_jsonb = '{{}}' WHERE id = '{row_id}'",
                    "immutable")

            bundle = DocumentBundle(id=uuid4(), notice_id=world.notice_id, revision=7, version=1, status="ready",
                                    issues_snapshot=[], created_by_name="tester")
            session.add(bundle)
            session.commit()
            base = (f"INSERT INTO bidops.deep_review_preview (id, notice_id, bundle_id, profile_version_id, "
                    f"policy_version_id, input_sha256, input_snapshot, created_at, company_id, graph_version_id, "
                    f"provenance_jsonb) VALUES ('{{id}}', {world.notice_id}, '{bundle.id}', "
                    f"'{world.profile_version_id}', '{analysis_policy.id}', '{'a' * 64}', '{{{{}}}}', now(), "
                    "{company}, {graph}, {provenance})")

            def preview(company, graph, provenance) -> str:
                return base.format(id=uuid4(), company=company, graph=graph, provenance=provenance)

            company = f"'{world.company_id}'"
            graph = f"'{world.graph_version_id}'"
            # NULL company with a company profile: the MATCH SIMPLE bypass is closed by trigger.
            _expect(engine, preview("NULL", "NULL", "NULL"), "profile and analysis company scopes differ")
            _expect(engine, preview(company, "NULL", "'{}'"), "ck_deep_review_preview_graph_scope")
            _expect(engine, preview(company, graph, "NULL"), "ck_deep_review_preview_provenance")
            _expect(engine, preview(company, f"'{other.graph_version_id}'", "'{}'"),
                    "fk_deep_review_preview_graph_scope")
            with engine.begin() as connection:
                connection.execute(text(preview(company, graph, "'{}'")))
            review = (f"INSERT INTO bidops.deep_review (id, company_id, notice_id, bundle_id, profile_version_id, "
                      f"policy_version_id, effective_grade_at_start, status, created_at, graph_version_id) VALUES "
                      f"('{uuid4()}', {company}, {world.notice_id}, '{bundle.id}', '{world.profile_version_id}', "
                      f"'{analysis_policy.id}', 'unknown', 'queued', now(), {{graph}})")
            _expect(engine, review.format(graph="NULL"), "ck_deep_review_graph_scope")
            with engine.begin() as connection:
                connection.execute(text(review.format(graph=graph)))
            index = session.scalar(text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'bidops' AND indexname = 'uq_deep_review_company_inputs'"))
            assert "company_id, notice_id, bundle_id, profile_version_id, policy_version_id, graph_version_id" in index
            assert "WHERE (company_id IS NOT NULL)" in index
            approval_columns = set(session.scalars(text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'bidops' "
                "AND table_name = 'deep_review_approval'")))
            assert "company_id" in approval_columns
        get_settings.cache_clear()


@requires_postgres
def test_pg_0036_downgrades_and_reupgrades_an_empty_database() -> None:
    with temporary_database() as url:
        down = run_alembic(url, "downgrade", "0035_company_knowledge")
        assert down.returncode == 0, down.stdout + down.stderr
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT version_num FROM bidops.alembic_version")) == "0035_company_knowledge"
                assert connection.scalar(text("SELECT to_regclass('bidops.company_fit_policy_version')")) is None
                nullable = connection.scalar(text(
                    "SELECT is_nullable FROM information_schema.columns WHERE table_schema = 'bidops' "
                    "AND table_name = 'prespec_company_fit_attempt' AND column_name = 'deep_policy_version_id'"))
                assert nullable == "NO"
        finally:
            engine.dispose()
        up = run_alembic(url, "upgrade", "head")
        assert up.returncode == 0, up.stdout + up.stderr
