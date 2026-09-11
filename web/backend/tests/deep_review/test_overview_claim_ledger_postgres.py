"""Real PostgreSQL boundaries for the claim ledger, publication and upgrades."""
from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.models import AuditEvent
from app.deep_review.models import (
    ContentObject, ContentObjectLocation, PrespecOverviewCallEvent,
    PrespecOverviewVerification, WorkJob,
)
from tests.deep_review.test_prespec_v4_postgres import _insert_target, _seed_snapshot
from tests.postgres import migrated_engine, requires_postgres, run_alembic

pytestmark = requires_postgres


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _seed_attempt(engine, *, legacy=False):
    with engine.connect() as conn:
        existing = conn.execute(text("SELECT notice_id,document_version_id,id FROM bidops.prespec_v4_pdf_snapshot LIMIT 1")).first()
    notice, document, snapshot = existing or _seed_snapshot(engine)
    identity = _sha(str(uuid4()))
    _insert_target(engine, notice_id=notice, document_id=document, snapshot_id=snapshot, identity=identity)
    with engine.begin() as conn:
        target = conn.scalar(text("SELECT id FROM bidops.prespec_v4_target WHERE identity_sha256=:hash"), {"hash": identity})
        sequence = conn.scalar(text("SELECT COALESCE(max(sequence),0)+1 FROM bidops.prespec_v4_attempt WHERE notice_id=:id"), {"id": notice})
    attempt_id, job_id, activation_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(WorkJob(id=job_id, job_type="prespec_v4_overview", aggregate_type="prespec_v4_target", aggregate_id=target, status="queued"))
        if not legacy:
            session.add(AuditEvent(id=activation_id, actor_kind="system", action="prespec_v4.activation", aggregate_type="prespec_v4_activation", aggregate_id=str(activation_id), safe_metadata={
                "schema": "bidops.prespec-v4-activation.v2", "status": "active", "policy_digest": "4" * 64,
                "binding": {"binding_digest": "5" * 64},
            }))
        session.flush()
        # Raw insert deliberately also works against the previous revision,
        # whose table does not yet have activation_id.
        columns = "id,notice_id,document_version_id,target_id,work_job_id,sequence,source_sha256,pdf_sha256,input_sha256,selection_manifest_sha256,policy_digest,model_name,model_digest,prompt_version,provider,binding_digest,quality_status,status,created_at"
        values = ":id,:notice,:document,:target,:job,:sequence,:source,:source,:input,:manifest,:policy,'fixture',:model,:prompt,'vllm',:binding,'unmeasured_reference','queued',:now"
        if not legacy:
            columns += ",activation_id"
            values += ",:activation"
        session.execute(text(f"INSERT INTO bidops.prespec_v4_attempt ({columns}) VALUES ({values})"), {
            "id": attempt_id, "notice": notice, "document": document, "target": target, "job": job_id,
            "source": "a" * 64, "input": "1" * 64, "manifest": "2" * 64, "policy": "4" * 64,
            "binding": "5" * 64, "model": "6" * 64, "prompt": "prespec-overview-v4" if legacy else "prespec-overview-v5",
            "now": now, "activation": activation_id, "sequence": sequence,
        })
    return attempt_id


def _start(engine, attempt_id):
    with engine.begin() as conn:
        params = {"id": attempt_id, "now": datetime.now(UTC), "expires": datetime.now(UTC) + timedelta(minutes=20)}
        conn.execute(text("UPDATE bidops.prespec_v4_attempt SET status='running',started_at=:now,lease_owner='fixture',lease_expires_at=:expires WHERE id=:id"), params)
        conn.execute(text("UPDATE bidops.work_job SET status='running',lease_owner='fixture',lease_expires_at=:expires WHERE id=(SELECT work_job_id FROM bidops.prespec_v4_attempt WHERE id=:id)"), params)


def _finish(connection, attempt_id, status, *, result=None, result_sha=None, raw_sha=None, job=True):
    params = {"id": attempt_id, "status": status, "now": datetime.now(UTC), "result": result, "sha": result_sha, "raw": raw_sha}
    connection.execute(text("UPDATE bidops.prespec_v4_attempt SET status=:status,completed_at=:now,lease_owner=NULL,lease_expires_at=NULL,result_id=:result,result_sha256=:sha,raw_response_sha256=COALESCE(:raw,raw_response_sha256) WHERE id=:id"), params)
    if job:
        connection.execute(text("UPDATE bidops.work_job SET status=:status,completed_at=:now,lease_owner=NULL,lease_expires_at=NULL,last_error_code=:code WHERE id=(SELECT work_job_id FROM bidops.prespec_v4_attempt WHERE id=:id)"), {
            **params, "status": "failed" if status == "needs_human_review" else status,
            "code": "claim_verification_required" if status == "needs_human_review" else None,
        })


def _dispatch(session, attempt_id, *, ordinal=1, stage="draft", call_id=None):
    row = PrespecOverviewCallEvent(id=uuid4(), call_id=call_id or uuid4(), attempt_id=attempt_id, ordinal=ordinal, stage=stage, event_kind="dispatch", input_sha256="1" * 64, prompt_sha256="7" * 64, binding_digest="5" * 64)
    session.add(row)
    session.flush()
    return row.call_id


def _response(session, attempt_id, call_id, *, ordinal=1, stage="draft"):
    digest = _sha(str(call_id))
    content = ContentObject(id=uuid4(), sha256=digest, size_bytes=2, detected_mime="application/json", retention_class="model-response-90d")
    session.add(content)
    session.flush()
    location = ContentObjectLocation(id=uuid4(), content_object_id=content.id, namespace_key="model-response", object_key="model-response/" + str(call_id), status="verified", encryption_key_ref="fixture-key", verified_at=datetime.now(UTC))
    session.add(location)
    session.flush()
    row = PrespecOverviewCallEvent(id=uuid4(), call_id=call_id, attempt_id=attempt_id, ordinal=ordinal, stage=stage, event_kind="response", input_sha256="1" * 64, prompt_sha256="7" * 64, binding_digest="5" * 64, raw_response_sha256=digest, raw_response_content_object_id=content.id, raw_response_location_id=location.id, prompt_tokens=1, output_tokens=2, latency_ms=3)
    session.add(row)
    session.flush()
    return row.id


def _verification(session, attempt_id, *, passed):
    evidence = {"page": 1, "quote": "검토", "start_char": 0, "end_char": 2, "page_text_sha256": "b" * 64}
    checks = [{"claim_id": claim, "section": section, "text": "검토", "deterministic": {"status": "passed", "reason_codes": [], "verified_evidence": [evidence]}, "semantic": {"status": "supported" if passed else "insufficient", "reason_codes": [] if passed else ["insufficient_evidence"]}} for claim, section in (("c1", "business_overview"), ("c2", "main_tasks"))]
    payload = {"schema_version": "bidops.prespec-overview-claim-checks.v1", "attempt_id": str(attempt_id), "draft_sha256": "8" * 64, "input_sha256": "1" * 64, "policy_digest": "4" * 64, "binding_digest": "5" * 64, "validator_version": "prespec-claim-evidence.v1", "checks": checks, "analysis": [], "unknowns": [], "analysis_checks": [], "unknown_checks": [], "reason_codes": [], "overall": "passed" if passed else "needs_human_review"}
    row = PrespecOverviewVerification(id=uuid4(), attempt_id=attempt_id, schema_version=payload["schema_version"], draft_sha256=payload["draft_sha256"], input_sha256=payload["input_sha256"], policy_digest=payload["policy_digest"], binding_digest=payload["binding_digest"], model_digest="6" * 64, validator_version=payload["validator_version"], payload_jsonb=payload, payload_sha256=_sha(payload), overall=payload["overall"])
    session.add(row)
    session.flush()
    return row


def _result(session, attempt_id, verification=None):
    # Query only pre-0025 columns so this helper also proves historical v3 rows
    # survive an actual previous-head upgrade.
    a = session.execute(text("SELECT notice_id,document_version_id FROM bidops.prespec_v4_attempt WHERE id=:id"), {"id": attempt_id}).one()
    location = session.scalar(text("SELECT pdf_location_id FROM bidops.prespec_v4_pdf_snapshot WHERE document_version_id=:id"), {"id": a.document_version_id})
    if verification is None:
        payload = {"schema_version": "bidops.prespec-overview-page-review.v3", "business_overview": [{"text": "검토", "evidence_pages": [1]}], "main_tasks": [{"text": "검토", "evidence_pages": [1]}], "budget_and_period": [], "important_conditions": [], "reviewer_analysis": ["범위 확인"], "unknowns": [], "input_limitations": ["앞부분"]}
    else:
        facts = [{"claim_id": check["claim_id"], "text": check["text"], "evidence": check["deterministic"]["verified_evidence"]} for check in verification.payload_jsonb["checks"]]
        payload = {"schema_version": "bidops.prespec-overview-page-review.v4", "business_overview": [facts[0]], "main_tasks": [facts[1]], "budget_and_period": [], "important_conditions": [], "reviewer_analysis": [], "unknowns": [], "input_limitations": ["앞부분"], "verification_id": str(verification.id), "verification_sha256": verification.payload_sha256}
    result_id, digest = uuid4(), _sha(payload)
    columns = "id,run_id,notice_id,document_version_id,input_location_id,pdf_location_id,schema_version,source_sha256,pdf_sha256,payload_sha256,import_sha256,input_sha256,model_digest,policy_digest,model_name,prompt_version,pdf_page_count,reviewed_pages,payload_jsonb,validation_status,validation_errors,evidence_check_status,evidence_check_errors,validator_version,quality_status,created_at"
    values = ":id,:attempt,:notice,:document,:location,:location,:schema,:source,:source,:sha,:sha,:input,:model,:policy,'fixture',:prompt,1,'[1]'::jsonb,CAST(:payload AS jsonb),'passed','[]'::jsonb,'passed','[]'::jsonb,'fixture','unmeasured_reference',:now"
    if verification is not None:
        columns += ",verification_id,verification_sha256"
        values += ",:verification,:verification_sha"
    session.execute(text(f"INSERT INTO bidops.prespec_page_overview ({columns}) VALUES ({values})"), {
        "id": result_id, "attempt": attempt_id, "notice": a.notice_id, "document": a.document_version_id, "location": location,
        "schema": payload["schema_version"], "source": "a" * 64, "sha": digest, "input": "1" * 64, "model": "6" * 64, "policy": "4" * 64,
        "prompt": "prespec-overview-v5" if verification else "prespec-overview-v4", "payload": json.dumps(payload), "now": datetime.now(UTC),
        "verification": verification.id if verification else None, "verification_sha": verification.payload_sha256 if verification else None,
    })
    return result_id, digest


def test_empty_upgrade_downgrade_and_previous_head_rows_survive():
    with migrated_engine() as engine:
        url = engine.url.render_as_string(hide_password=False)
        assert run_alembic(url, "downgrade", "0024_section_candidates").returncode == 0
        completed = _seed_attempt(engine, legacy=True)
        _start(engine, completed)
        with Session(engine) as session, session.begin():
            result_id, digest = _result(session, completed)
            _finish(session, completed, "completed", result=result_id, result_sha=digest, raw_sha="c" * 64)
        failed = _seed_attempt(engine, legacy=True)
        queued = _seed_attempt(engine, legacy=True)
        with engine.begin() as conn:
            _finish(conn, failed, "failed")
        with engine.connect() as conn:
            before = conn.execute(text("SELECT id,to_jsonb(a) FROM bidops.prespec_v4_attempt a ORDER BY id")).all()
            old_result = conn.scalar(text("SELECT to_jsonb(r) FROM bidops.prespec_page_overview r"))
        result = run_alembic(url, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id,to_jsonb(a)-'activation_id' FROM bidops.prespec_v4_attempt a ORDER BY id")).all() == before
            assert conn.scalar(text("SELECT to_jsonb(r)-'verification_id'-'verification_sha256' FROM bidops.prespec_page_overview r")) == old_result
            assert conn.scalar(text("SELECT status FROM bidops.prespec_v4_attempt WHERE id=:id"), {"id": queued}) == "queued"
            assert conn.scalar(text("SELECT character_maximum_length FROM information_schema.columns WHERE table_schema='bidops' AND table_name='prespec_v4_attempt' AND column_name='status'")) == 32
        assert run_alembic(url, "upgrade", "head").returncode == 0


def test_call_identity_duplicates_budgets_late_response_and_immutability():
    with migrated_engine() as engine:
        attempt = _seed_attempt(engine)
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            _dispatch(session, attempt)
        _start(engine, attempt)
        with Session(engine) as session, session.begin():
            call = _dispatch(session, attempt)
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            _dispatch(session, attempt, call_id=call)
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            _dispatch(session, attempt, ordinal=3)
        with engine.begin() as conn:
            _finish(conn, attempt, "cancelled")
        with Session(engine) as session, session.begin():
            response_id = _response(session, attempt, call)
        # Cancellation preserves provenance but permits neither redispatch nor
        # verification/publication and never mutates the terminal attempt.
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            _dispatch(session, attempt, ordinal=2)
        with pytest.raises(ValueError), Session(engine) as session, session.begin():
            _verification(session, attempt, passed=False)
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text("INSERT INTO bidops.prespec_overview_call_event (id,call_id,attempt_id,ordinal,stage,event_kind,input_sha256,prompt_sha256,binding_digest,error_code,created_at) SELECT :id,call_id,attempt_id,ordinal,stage,'error',input_sha256,prompt_sha256,binding_digest,'timeout',created_at FROM bidops.prespec_overview_call_event WHERE id=:source"), {"id": uuid4(), "source": response_id})
        for table, key in (("prespec_v4_attempt", attempt), ("prespec_overview_call_event", response_id)):
            for mutation in (f"DELETE FROM bidops.{table} WHERE id=:id", f"UPDATE bidops.{table} SET created_at=created_at WHERE id=:id"):
                with pytest.raises(DBAPIError), engine.begin() as conn:
                    conn.execute(text(mutation), {"id": key})
        with pytest.raises(ValueError), Session(engine) as session, session.begin():
            row = session.get(PrespecOverviewCallEvent, response_id)
            row.latency_ms = 50


def test_verification_and_human_review_job_are_atomic():
    with migrated_engine() as engine:
        attempt = _seed_attempt(engine)
        _start(engine, attempt)
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            _verification(session, attempt, passed=False)
        with pytest.raises(DBAPIError), engine.begin() as conn:
            _finish(conn, attempt, "needs_human_review")
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            _verification(session, attempt, passed=False)
            _finish(session, attempt, "needs_human_review", job=False)
        with Session(engine) as session, session.begin():
            verification = _verification(session, attempt, passed=False)
            verification_id = verification.id
            _finish(session, attempt, "needs_human_review")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT a.status,a.result_id,j.status,j.last_error_code FROM bidops.prespec_v4_attempt a JOIN bidops.work_job j ON a.work_job_id=j.id WHERE a.id=:id"), {"id": attempt}).one() == ("needs_human_review", None, "failed", "claim_verification_required")
        for statement in ("UPDATE bidops.prespec_overview_verification SET overall='passed' WHERE id=:id", "DELETE FROM bidops.prespec_overview_verification WHERE id=:id"):
            with pytest.raises(DBAPIError), engine.begin() as conn:
                conn.execute(text(statement), {"id": verification_id})
        assert run_alembic(engine.url.render_as_string(hide_password=False), "downgrade", "0024_section_candidates").returncode != 0


def test_completed_requires_verified_result_and_persisted_semantic_response():
    with migrated_engine() as engine:
        attempt = _seed_attempt(engine)
        _start(engine, attempt)
        with Session(engine) as session, session.begin():
            draft = _dispatch(session, attempt)
            _response(session, attempt, draft)
            semantic = _dispatch(session, attempt, ordinal=2, stage="semantic")
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            v = _verification(session, attempt, passed=True)
            result, sha = _result(session, attempt, v)
            _finish(session, attempt, "completed", result=result, result_sha=sha)
        with Session(engine) as session, session.begin():
            _response(session, attempt, semantic, ordinal=2, stage="semantic")
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            _dispatch(session, attempt, ordinal=3, stage="semantic")
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            v = _verification(session, attempt, passed=True)
            _result(session, attempt, v)
        with pytest.raises(DBAPIError, match="facts differ"), Session(engine) as session, session.begin():
            v = _verification(session, attempt, passed=True)
            v.payload_jsonb["checks"][0]["text"] = "검증 후 변경한 주장"
            _result(session, attempt, v)
        with Session(engine) as session, session.begin():
            v = _verification(session, attempt, passed=True)
            result, sha = _result(session, attempt, v)
            _finish(session, attempt, "completed", result=result, result_sha=sha)
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM bidops.prespec_page_overview WHERE run_id=:id"), {"id": attempt}) == 1
            assert conn.scalar(text("SELECT count(*) FROM bidops.prespec_overview_verification WHERE attempt_id=:id"), {"id": attempt}) == 1


def test_activation_fk_and_encrypted_response_reference_binding():
    with migrated_engine() as engine:
        attempt = _seed_attempt(engine)
        for patch in ({"activation_id": None}, {"activation_id": str(uuid4())}):
            with pytest.raises(DBAPIError, match="activation"), engine.begin() as conn:
                conn.execute(text("INSERT INTO bidops.prespec_v4_attempt SELECT (jsonb_populate_record(NULL::bidops.prespec_v4_attempt,to_jsonb(a)||CAST(:patch AS jsonb))).* FROM bidops.prespec_v4_attempt a WHERE id=:id"), {"id": attempt, "patch": json.dumps({"id": str(uuid4()), "sequence": 2, **patch})})
        _start(engine, attempt)
        with Session(engine) as session, session.begin():
            call = _dispatch(session, attempt)
            response = _response(session, attempt, call)
        with Session(engine) as session, session.begin():
            second_call = _dispatch(session, attempt, ordinal=2)
        for patch, error in (
            ({"attempt_id": str(uuid4())}, "attempt missing"),
            ({"prompt_sha256": "9" * 64}, "dispatch mismatch"),
            ({"raw_response_sha256": "9" * 64}, "storage binding"),
            ({"raw_response_location_id": str(uuid4())}, "storage binding"),
            ({"raw_response_content_object_id": None, "raw_response_location_id": None}, "ck_overview_call_outcome"),
        ):
            with pytest.raises(DBAPIError, match=error), engine.begin() as conn:
                conn.execute(text("INSERT INTO bidops.prespec_overview_call_event SELECT (jsonb_populate_record(NULL::bidops.prespec_overview_call_event,to_jsonb(e)||CAST(:patch AS jsonb))).* FROM bidops.prespec_overview_call_event e WHERE id=:id"), {"id": response, "patch": json.dumps({"id": str(uuid4()), "call_id": str(second_call), "ordinal": 2, "created_at": datetime.now(UTC).isoformat(), **patch})})


def test_response_error_race_has_exactly_one_outcome():
    with migrated_engine() as engine:
        attempt = _seed_attempt(engine)
        _start(engine, attempt)
        with Session(engine) as session, session.begin():
            call = _dispatch(session, attempt)
        barrier = Barrier(2)

        def write(kind):
            try:
                with Session(engine) as session, session.begin():
                    barrier.wait(timeout=10)
                    if kind == "response":
                        _response(session, attempt, call)
                    else:
                        session.add(PrespecOverviewCallEvent(id=uuid4(), call_id=call, attempt_id=attempt, ordinal=1, stage="draft", event_kind="error", input_sha256="1" * 64, prompt_sha256="7" * 64, binding_digest="5" * 64, error_code="timeout"))
                return "inserted"
            except DBAPIError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(write, ("response", "error")))
        assert sorted(outcomes) == ["inserted", "rejected"]
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM bidops.prespec_overview_call_event WHERE call_id=:id AND event_kind IN ('response','error')"), {"id": call}) == 1
