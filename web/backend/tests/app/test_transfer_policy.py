"""RL-03 STEP-003: policy-level transfer approval, gate order and the transfer audit (spec T2·T3·T10).

The world is the real Rootlab v2 company (``~/orca/fixtures/company/rootlab``,
outside Git) registered into an isolated SQLite database, the approved
``analysis-policy-luna-rl-v1`` row selected by
``BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID``, an SW사업대상=Y pre-spec **without
any overview run** and a ready bundle whose stored structure carries the six
heading sections and a requirement card table (real HP-01 manifest).

No model, transport or network is called anywhere (an autouse guard fails the
test otherwise); the card-v1 stage runner (STEP-005) is replaced by a recording
fake where T10 observes the audit before the first call, and by the ``None``
seam where T10 checks the unconnected fail-closed path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import init_db
from app.core.model_client import ModelClient
from app.core.models import AuditEvent
from app.deep_review.cli import approve_transfer_policy as approve_cli
from app.deep_review.cli import revoke_transfer_policy as revoke_cli
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentStructure,
    DocumentVersion,
    PrespecOverviewRun,
    TransferPolicyApproval,
    WorkJob,
)
from app.deep_review.services import assets, document_segments, transfer_policy
from app.deep_review.services import company_deep_review as cdr
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge,
)
from app.deep_review.services.deep_reviews import DeepReviewService, DeepReviewServiceError
from app.deep_review.services.input_versions import (
    HP_LUNA_POLICY_FILE,
    RL_LUNA_POLICY_FILE,
    RL_LUNA_POLICY_FILE_V2,
    RL_LUNA_POLICY_FILE_V3,
    RL_LUNA_POLICY_FILE_V4,
    RL_LUNA_POLICY_FILE_V5,
    RL_LUNA_POLICY_FILE_V6,
    RL_LUNA_POLICY_FILE_V7,
    RL_LUNA_POLICY_FILE_V8,
    RL_LUNA_POLICY_FILE_V9,
    RL_LUNA_POLICY_FILE_V10,
    InputVersionError,
    import_policy_version,
)
from app.lifecycle.models import Notice
from tests.app.test_deep_reviews import _FixtureStore
from tests.deep_review.test_company_fit_enqueue import ready_bundle
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store


ROOTLAB_DIR = Path(os.environ.get("BIDOPS_ROOTLAB_FIXTURE_DIR", str(Path.home() / "orca/fixtures/company/rootlab")))
ROOTLAB_SOURCE = ROOTLAB_DIR / "rootlab.source.v2.json"
ROOTLAB_ONTOLOGY = ROOTLAB_DIR / "ontology.v2.json"
needs_rootlab = pytest.mark.skipif(
    not (ROOTLAB_SOURCE.is_file() and ROOTLAB_ONTOLOGY.is_file()),
    reason="Rootlab v2 fixture (outside Git) is not available",
)


# --- environment ------------------------------------------------------------------


def configure(monkeypatch, **overrides: str | None) -> None:
    values: dict[str, str | None] = {
        "BIDOPS_DEMO_ENABLED": "false",
        "BIDOPS_RL_ANALYSIS_ENABLED": "true",
        "BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED": "false",
        "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
        "BIDOPS_LUNA_DEEP_REVIEW_ENABLED": "true",
        "BIDOPS_ANALYSIS_PROVIDER": "vllm",
        "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED": "false",
        "BIDOPS_PRESPEC_OVERVIEW_ENABLED": "false",
        "BIDOPS_VLLM_OVERVIEW_BASE_URL": "http://127.0.0.1:9/v1",
        "BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS": "127.0.0.1",
        "BIDOPS_VLLM_OVERVIEW_API_DIALECT": "litellm",
        "BIDOPS_VLLM_OVERVIEW_MODEL_REVISION": "",
        "BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID": None,
        "BIDOPS_ACTIVE_PROFILE_VERSION_ID": None,
        "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": None,
        # The config default is the v2 file (결정 B23); worlds built on the v1
        # row pin the v1 file explicitly so the identity/sha check matches.
        "BIDOPS_RL_ANALYSIS_POLICY_PATH": str(RL_LUNA_POLICY_FILE),
        "BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID": None,
    }
    values.update(overrides)
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("model")
        raise AssertionError("model transport called")

    from app.deep_review.services import luna_client

    monkeypatch.setattr(ModelClient, "for_purpose", classmethod(forbidden))
    monkeypatch.setattr(luna_client.LunaClient, "__init__", forbidden)
    yield calls
    assert calls == []
    get_settings.cache_clear()


def _sqlite_engine():
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    with bind.begin() as connection:
        for index_name in ("uq_deep_review_attempt_active", "uq_work_job_active"):
            connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        connection.execute(text("CREATE UNIQUE INDEX uq_deep_review_attempt_active ON deep_review_attempt "
                                "(deep_review_id) WHERE status IN ('queued','running')"))
        connection.execute(text("CREATE UNIQUE INDEX uq_work_job_active ON work_job "
                                "(job_type, aggregate_type, aggregate_id) WHERE status IN ('queued','running')"))
    return bind


@pytest.fixture
def engine():
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


# --- world ------------------------------------------------------------------------


def _block(key: str, text_value: str, *, kind: str = "paragraph", table: str | None = None,
           row: int | None = None, column: int | None = None, page: int = 1) -> dict:
    attributes: dict[str, object] = {}
    if table is not None:
        attributes["table_key"] = table
    if row is not None:
        attributes["row"] = row
    if column is not None:
        attributes["column"] = column
    return {"block_key": key, "parent_block_key": f"{table}-block" if kind == "table_cell" else None,
            "type": kind, "page": page, "bbox": None, "text": text_value, "confidence": None,
            "attributes": attributes}


def _structure_blocks() -> list[dict]:
    table = "card-table-1"
    blocks = [
        _block("h-overview", "제1장 사업개요"),
        _block("b-overview", "대학 홈페이지 유지관리 용역의 목적을 기술한다."),
        _block("h-schedule", "1.1 사업기간"),
        _block("b-schedule", "계약일로부터 12개월"),
        _block("h-budget", "1.2 사업예산"),
        _block("b-budget", "추정가격 금150,000,000원(부가세 포함)"),
        _block("h-eligibility", "제2장 입찰참가자격"),
        _block("b-eligibility", "소프트웨어사업자(컴퓨터관련서비스사업)로 신고한 자", page=2),
        _block("h-evaluation", "제3장 제안서 평가기준"),
        _block("b-evaluation", "기술 90점, 가격 10점", page=2),
        _block("h-contract", "제4장 계약조건"),
        _block("b-contract", "지체상금은 관련 법령에 따른다.", page=2),
        _block("h-req", "제5장 기능 요구사항", page=3),
        {"block_key": f"{table}-block", "parent_block_key": None, "type": "table", "page": 3, "bbox": None,
         "text": "", "confidence": None, "attributes": {"table_key": table}},
    ]
    fields = [
        ("요구사항분류", "기능"), ("요구사항고유번호", "SFR-001"), ("요구사항명칭", "게시판 기능 개선"),
        ("정의", "게시판 검색 기능을 개선한다"), ("세부내용", "통합 검색을 제공한다"),
    ]
    for row_index, (label, value) in enumerate(fields):
        for column, cell in enumerate((label, value)):
            blocks.append(_block(f"{table}-r{row_index}-c{column}", cell, kind="table_cell", table=table,
                                 row=row_index, column=column, page=3))
    return blocks


def _structure_payload(structure: DocumentStructure) -> dict:
    return {
        "schema": "bidops.document-structure.v1", "structure_id": str(structure.id),
        "document_version_id": str(structure.document_version_id), "source_sha256": structure.source_sha256,
        "media_type": structure.media_type,
        "extractor": {"name": structure.extractor_name, "version": structure.extractor_version,
                      "upstream_commit": structure.upstream_commit},
        "pages": [{"number": page, "width": 612, "height": 792, "image_content_object_id": None}
                  for page in (1, 2, 3)],
        "blocks": _structure_blocks(), "warnings": [], "created_at": "2026-10-17T00:00:00+09:00",
    }


def _store_structure(session: Session, document: DocumentVersion) -> DocumentStructure:
    content = session.get(ContentObject, document.content_object_id)
    structure = DocumentStructure(
        id=uuid4(), document_version_id=document.id, source_sha256=content.sha256, extractor_name="fixture",
        extractor_version="1", upstream_commit=None, page_count=3, block_count=len(_structure_blocks()),
        validation_status="ready", media_type="application/pdf",
    )
    payload = _structure_payload(structure)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    _path, metadata = assets.store_named("structure", f"structure/{digest}.json", raw, content_type="application/json")
    stored = ContentObject(id=uuid4(), sha256=digest, size_bytes=len(raw), detected_mime="application/json",
                           retention_class="document-structure")
    session.add(stored)
    session.flush()
    session.add(ContentObjectLocation(
        content_object_id=stored.id, namespace_key="structure", object_key=metadata.object_key,
        object_version_id=metadata.object_version_id, etag=metadata.etag, status="verified",
        verified_at=datetime.now(UTC),
    ))
    structure.payload_content_object_id, structure.payload_sha256 = stored.id, digest
    session.add(structure)
    session.flush()
    document_segments.store_manifest(session, payload)
    return structure


def _seed_notice(session: Session, *, sw: str = "Y") -> tuple[Notice, DocumentVersion]:
    notice = Notice(notice_key=f"rl-verdict:{uuid4()}", source_type="pre_spec", title="루트랩 사전규격",
                    qualification_flags_json={"sw_business_status": sw})
    session.add(notice)
    session.flush()
    content = ContentObject(id=uuid4(), sha256=uuid4().hex + uuid4().hex, size_bytes=10,
                            detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=1,
                               source_kind="manual", original_filename="제안요청서.hwp", role="제안요청서",
                               is_current=True, safety_status="safe")
    session.add(document)
    session.flush()
    _store_structure(session, document)
    return notice, document


@dataclass(frozen=True)
class RLWorld:
    company_id: UUID
    notice_id: int
    bundle_id: UUID
    policy_id: UUID
    policy_sha256: str
    graph_version_id: UUID
    profile_version_id: UUID


def _import_rootlab(session: Session):
    prepared = prepare_company_knowledge(ROOTLAB_ONTOLOGY.read_bytes(), ROOTLAB_SOURCE.read_bytes())
    imported = import_company_knowledge(session, prepared, actor="등록 담당자")
    activate_company_knowledge(session, company_id=imported.company_id,
                               graph_version_id=imported.graph_version_id, actor="활성 담당자")
    session.flush()
    return imported


def _structure_loader(_session, structure):
    return _structure_payload(structure)


def service() -> DeepReviewService:
    return DeepReviewService(structure_loader=_structure_loader, raw_response_store=_FixtureStore())


#: Policy files of the RL identities (결정 B23·B30·B33).
RL_POLICY_FILES = {"analysis-policy-luna-rl-v1": RL_LUNA_POLICY_FILE,
                   "analysis-policy-luna-rl-v2": RL_LUNA_POLICY_FILE_V2,
                   "analysis-policy-luna-rl-v3": RL_LUNA_POLICY_FILE_V3,
                   "analysis-policy-luna-rl-v4": RL_LUNA_POLICY_FILE_V4,
                   "analysis-policy-luna-rl-v5": RL_LUNA_POLICY_FILE_V5,
                   "analysis-policy-luna-rl-v6": RL_LUNA_POLICY_FILE_V6,
                   "analysis-policy-luna-rl-v7": RL_LUNA_POLICY_FILE_V7,
                   "analysis-policy-luna-rl-v8": RL_LUNA_POLICY_FILE_V8,
                   "analysis-policy-luna-rl-v9": RL_LUNA_POLICY_FILE_V9,
                   "analysis-policy-luna-rl-v10": RL_LUNA_POLICY_FILE_V10}


def build_world(session: Session, monkeypatch, *, sw: str = "Y",
                policy_identity: str = "analysis-policy-luna-rl-v1") -> RLWorld:
    policy_file = RL_POLICY_FILES[policy_identity]
    configure(monkeypatch, BIDOPS_RL_ANALYSIS_POLICY_PATH=str(policy_file))
    imported = _import_rootlab(session)
    notice, document = _seed_notice(session, sw=sw)
    bundle_id = ready_bundle(session, notice.id, document.id)
    policy = import_policy_version(session, policy_file, created_by_name="정책 담당자",
                                   label=policy_identity)
    session.commit()
    configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(policy.id),
              BIDOPS_RL_ANALYSIS_POLICY_PATH=str(policy_file))
    return RLWorld(company_id=imported.company_id, notice_id=notice.id, bundle_id=bundle_id,
                   policy_id=policy.id, policy_sha256=policy.policy_sha256,
                   graph_version_id=imported.graph_version_id, profile_version_id=imported.profile_version_id)


@pytest.fixture
def world(engine, monkeypatch):
    with Session(engine) as session:
        yield session, build_world(session, monkeypatch)


def approve(session: Session, *, daily_cap: int = 10, actor: str = "jechoi",
            policy_identity: str = "analysis-policy-luna-rl-v1") -> dict:
    result = transfer_policy.approve_transfer_policy(
        session, policy_identity=policy_identity, actor=actor, daily_cap=daily_cap,
    )
    session.commit()
    return result


def start(session: Session, world: RLWorld, svc=None, **kwargs) -> cdr.RLVerdictStart:
    result = cdr.start_rl_verdict(svc or service(), session, company_id=world.company_id,
                                  notice_id=world.notice_id, bundle_id=world.bundle_id, **kwargs)
    session.commit()
    return result


def start_code(session: Session, world: RLWorld, **kwargs) -> str:
    with pytest.raises((DeepReviewServiceError, InputVersionError)) as error:
        cdr.start_rl_verdict(service(), session, company_id=world.company_id, notice_id=world.notice_id,
                             bundle_id=kwargs.pop("bundle_id", world.bundle_id), **kwargs)
    session.rollback()
    return error.value.code


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- T2: approve / revoke CLI ------------------------------------------------------


def _cli(monkeypatch, engine, module, *argv: str, capsys) -> tuple[int, dict, str]:
    monkeypatch.setattr(module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(module, "init_db", lambda: None)
    code = module.main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err.strip()


APPROVE_KEYS = {"approval_id", "policy_identity", "policy_sha256", "model_name", "reasoning_effort",
                "cli_version", "daily_cap", "request_id", "created", "errors"}


@needs_rootlab
def test_t2_approve_cli_binds_row_canonical_sha_and_hp00_identity(engine, monkeypatch, capsys) -> None:
    with Session(engine) as session:
        world = build_world(session, monkeypatch)
    code, payload, err = _cli(monkeypatch, engine, approve_cli, "--policy", "analysis-policy-luna-rl-v1",
                              "--actor", "jechoi", "--daily-cap", "2", capsys=capsys)
    assert code == 0 and err == ""
    assert set(payload) == APPROVE_KEYS and payload["created"] is True and payload["errors"] == []
    assert payload["policy_sha256"] == world.policy_sha256
    assert (payload["model_name"], payload["reasoning_effort"], payload["cli_version"]) == ("gpt-6-luna", "high", "0.162.1")
    with Session(engine) as session:
        row = session.get(TransferPolicyApproval, UUID(payload["approval_id"]))
        assert row.policy_version_id == world.policy_id and row.daily_cap == 2 and row.approved_by == "jechoi"
        assert row.scope == {"stages": ["pre_spec"], "purposes": ["deep_review"]}
        assert str(row.request_id) == payload["request_id"] and row.revoked_at is None
    # --request-id replays the same row
    code, replay, _ = _cli(monkeypatch, engine, approve_cli, "--policy", "analysis-policy-luna-rl-v1",
                           "--actor", "jechoi", "--daily-cap", "2", "--request-id", payload["request_id"],
                           capsys=capsys)
    assert code == 0 and replay["created"] is False and replay["approval_id"] == payload["approval_id"]
    # a second active approval of the same sha is refused (exit 2), DB stays at one row
    code, duplicate, err = _cli(monkeypatch, engine, approve_cli, "--policy", "analysis-policy-luna-rl-v1",
                                "--actor", "jechoi", "--daily-cap", "2", capsys=capsys)
    assert code == 2 and duplicate["errors"] == ["active_approval_exists"] and err == "active_approval_exists"
    with Session(engine) as session:
        assert count(session, TransferPolicyApproval) == 1


@needs_rootlab
@pytest.mark.parametrize("case", ["identity", "row_not_rl", "file_mismatch", "model", "unset"])
def test_t2_identity_mismatch_exits_2_without_writes(engine, monkeypatch, capsys, case) -> None:
    with Session(engine) as session:
        build_world(session, monkeypatch)
        hp = import_policy_version(session, HP_LUNA_POLICY_FILE, created_by_name="정책 담당자",
                                   label="analysis-policy-luna-hp-v1")
        session.commit()
        hp_id = hp.id
    policy = "analysis-policy-luna-rl-v1"
    expected = "policy_identity_mismatch"
    if case == "identity":
        policy = "analysis-policy-luna-hp-v1"
    elif case == "row_not_rl":
        configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(hp_id))
    elif case == "file_mismatch":
        monkeypatch.setenv("BIDOPS_RL_ANALYSIS_POLICY_PATH", str(HP_LUNA_POLICY_FILE))
        get_settings.cache_clear()
    elif case == "model":
        monkeypatch.setattr(transfer_policy, "MODEL", "gpt-other")
    else:
        configure(monkeypatch)
        expected = "analysis_policy_unavailable"
    code, payload, err = _cli(monkeypatch, engine, approve_cli, "--policy", policy, "--actor", "jechoi",
                              "--daily-cap", "2", capsys=capsys)
    assert code == 2 and payload["errors"] == [expected] and err == expected
    assert payload["approval_id"] is None
    with Session(engine) as session:
        assert count(session, TransferPolicyApproval) == 0


@needs_rootlab
def test_t2_cap_range_dry_run_and_revoke_once(engine, monkeypatch, capsys) -> None:
    with Session(engine) as session:
        build_world(session, monkeypatch)
    for cap in ("0", "51"):
        code, payload, _ = _cli(monkeypatch, engine, approve_cli, "--policy", "analysis-policy-luna-rl-v1",
                                "--actor", "jechoi", "--daily-cap", cap, capsys=capsys)
        assert code == 2 and payload["errors"] == ["invalid_request"]
    code, dry, _ = _cli(monkeypatch, engine, approve_cli, "--policy", "analysis-policy-luna-rl-v1",
                        "--actor", "jechoi", "--daily-cap", "2", "--dry-run", capsys=capsys)
    assert code == 0 and dry["approval_id"] is None and dry["created"] is False
    with Session(engine) as session:
        assert count(session, TransferPolicyApproval) == 0
    code, approved, _ = _cli(monkeypatch, engine, approve_cli, "--policy", "analysis-policy-luna-rl-v1",
                             "--actor", "jechoi", "--daily-cap", "2", capsys=capsys)
    assert code == 0
    code, revoked, _ = _cli(monkeypatch, engine, revoke_cli, "--approval-id", approved["approval_id"],
                            "--actor", "jechoi", "--reason", "시운전 종료", capsys=capsys)
    assert code == 0 and revoked["revoked_by"] == "jechoi" and revoked["errors"] == []
    code, again, err = _cli(monkeypatch, engine, revoke_cli, "--approval-id", approved["approval_id"],
                            "--actor", "jechoi", "--reason", "두 번째", capsys=capsys)
    assert code == 2 and again["errors"] == ["already_revoked"] and err == "already_revoked"
    code, missing, _ = _cli(monkeypatch, engine, revoke_cli, "--approval-id", str(uuid4()),
                            "--actor", "jechoi", "--reason", "없음", capsys=capsys)
    assert code == 2 and missing["errors"] == ["not_found"]
    with Session(engine) as session:
        row = session.get(TransferPolicyApproval, UUID(approved["approval_id"]))
        assert row.revoked_at is not None and row.revoke_reason == "시운전 종료"
        assert transfer_policy.active_approval(session) is None
    # after revocation a new approval may be issued (the partial UNIQUE covers active rows only)
    code, renewed, _ = _cli(monkeypatch, engine, approve_cli, "--policy", "analysis-policy-luna-rl-v1",
                            "--actor", "jechoi", "--daily-cap", "2", capsys=capsys)
    assert code == 0 and renewed["created"] is True and renewed["approval_id"] != approved["approval_id"]


@needs_rootlab
def test_t2_partial_unique_rejects_two_active_rows_of_one_sha(world) -> None:
    session, w = world
    approve(session)
    session.add(TransferPolicyApproval(
        id=uuid4(), policy_identity="analysis-policy-luna-rl-v1", policy_version_id=w.policy_id,
        policy_sha256=w.policy_sha256, model_name="gpt-6-luna", reasoning_effort="high", cli_version="0.162.1",
        scope={"stages": ["pre_spec"], "purposes": ["deep_review"]}, daily_cap=1, approved_by="jechoi",
        request_id=uuid4(),
    ))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# --- T3: gate order and automatic preview/approval ----------------------------------


@needs_rootlab
def test_t3_card_v1_starts_without_any_overview_run_and_freezes_null_overview(world) -> None:
    session, w = world
    assert count(session, PrespecOverviewRun) == 0
    approval = approve(session)
    result = start(session, w)
    assert result.new_review is True
    preview = session.get(DeepReviewPreview, result.preview_id)
    frozen = preview.input_snapshot
    assert frozen["schema_version"] == "bidops.company-analysis-input.v2"
    assert frozen["overview_run_id"] is None and frozen["overview_sha256"] is None
    assert preview.provenance_jsonb["overview_run_id"] is None
    assert frozen["card_analysis"]["selector"]["version"] == "card-sections-v1"
    kinds = {unit["kind"] for unit in frozen["card_analysis"]["units"]}
    assert kinds == {"card", "segment"}
    assert frozen["card_analysis"]["missing_sections"] == []
    row = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == result.attempt_id))
    assert row.claimed_name == "system:transfer-policy"
    assert row.request_id == uuid5(UUID(approval["approval_id"]), preview.input_sha256)
    audits = session.scalars(select(AuditEvent).where(AuditEvent.claimed_name == "system:transfer-policy")).all()
    by_action = {audit.action: audit for audit in audits}
    assert {"deep_review.auto_create", "deep_review.external_transfer_approved"} <= set(by_action)
    assert "deep_review.create" not in {audit.action for audit in session.scalars(select(AuditEvent)).all()}
    assert all(audit.actor_kind == "system" for audit in audits)
    creation = by_action["deep_review.auto_create"].safe_metadata
    assert creation["input_sha256"] == preview.input_sha256 and creation["grade_source"] == "company_sw_business"
    assert "analysis.transfer.sent" not in by_action  # only the worker writes it, after claim
    attempt = session.get(DeepReviewAttempt, result.attempt_id)
    assert attempt.status == "queued" and session.get(WorkJob, attempt.work_job_id).status == "queued"
    review = session.get(DeepReview, result.review_id)
    assert review.company_id == w.company_id and review.policy_version_id == w.policy_id
    assert cdr.is_company_review_current(session, review) is True


@needs_rootlab
@pytest.mark.parametrize("case,expected", [
    ("no_approval", "policy_not_approved"),
    ("other_sha", "policy_not_approved"),
    ("scope", "policy_not_approved"),
    ("revoked", "policy_not_approved"),
    ("rl_disabled", "not_found"),
    ("reference_off", "reference_mode_required"),
    ("luna_off", "luna_disabled"),
])
def test_t3_gate_failures_create_nothing(world, monkeypatch, case, expected) -> None:
    session, w = world
    if case not in {"no_approval", "other_sha", "scope"}:
        result = approve(session)
    if case in {"other_sha", "scope"}:
        session.add(TransferPolicyApproval(
            id=uuid4(), policy_identity="analysis-policy-luna-rl-v1", policy_version_id=w.policy_id,
            policy_sha256=("0" * 64) if case == "other_sha" else w.policy_sha256, model_name="gpt-6-luna",
            reasoning_effort="high", cli_version="0.162.1",
            scope={"stages": ["pre_spec"], "purposes": ["deep_review"]} if case == "other_sha"
            else {"stages": ["bid_notice"], "purposes": ["deep_review"]},
            daily_cap=10, approved_by="jechoi", request_id=uuid4(),
        ))
        session.commit()
    if case == "revoked":
        transfer_policy.revoke_transfer_policy(session, approval_id=UUID(result["approval_id"]),
                                               actor="jechoi", reason="중지")
        session.commit()
    if case == "rl_disabled":
        monkeypatch.setenv("BIDOPS_RL_ANALYSIS_ENABLED", "false")
    if case == "reference_off":
        monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "false")
    if case == "luna_off":
        monkeypatch.setenv("BIDOPS_LUNA_DEEP_REVIEW_ENABLED", "false")
    get_settings.cache_clear()
    before = count(session, AuditEvent)
    assert start_code(session, w) == expected
    assert count(session, DeepReviewPreview) == 0
    assert count(session, DeepReviewApproval) == 0
    assert count(session, DeepReview) == 0
    assert count(session, WorkJob) == 0
    assert count(session, AuditEvent) == before


@needs_rootlab
def test_t3_sw_not_y_is_403_effective_grade_ineligible(engine, monkeypatch) -> None:
    with Session(engine) as session:
        w = build_world(session, monkeypatch, sw="N")
        approve(session)
        with pytest.raises(DeepReviewServiceError) as error:
            cdr.start_rl_verdict(service(), session, company_id=w.company_id, notice_id=w.notice_id,
                                 bundle_id=w.bundle_id)
        session.rollback()
        assert (error.value.code, error.value.status_code) == ("effective_grade_ineligible", 403)
        assert count(session, DeepReviewPreview) == 0 and count(session, WorkJob) == 0


@needs_rootlab
def test_t3_daily_cap_is_checked_before_the_existing_gates(world) -> None:
    session, w = world
    approve(session, daily_cap=1)
    first = start(session, w)
    # B17: a queued attempt has not transmitted, so today_used stays 0, but the
    # creation gate reserves it (in flight) -- the cap still holds before any send.
    assert transfer_policy.today_used(session) == 0
    # the active attempt would be active_attempt_exists; the cap answers first
    assert start_code(session, w) == "daily_cap_reached"
    assert count(session, DeepReviewApproval) == 1
    assert session.get(DeepReviewAttempt, first.attempt_id).status == "queued"


@needs_rootlab
def test_t3_same_lineage_reverdict_reuses_the_review_and_existing_codes(world) -> None:
    session, w = world
    approve(session)
    first = start(session, w)
    assert start_code(session, w) == "active_attempt_exists"
    attempt = session.get(DeepReviewAttempt, first.attempt_id)
    review = session.get(DeepReview, first.review_id)
    job = session.get(WorkJob, attempt.work_job_id)
    attempt.status, review.status, job.status = "failed", "failed", "failed"
    session.commit()
    second = start(session, w)
    assert second.review_id == first.review_id and second.new_review is False
    assert session.get(DeepReviewAttempt, first.attempt_id).status == "superseded"
    new_attempt = session.get(DeepReviewAttempt, second.attempt_id)
    assert new_attempt.sequence == 2 and new_attempt.status == "queued"
    preview = session.get(DeepReviewPreview, second.preview_id)
    assert preview.input_snapshot["target_review_id"] == str(first.review_id)
    assert count(session, DeepReview) == 1


@needs_rootlab
def test_t3_bundle_not_ready_uses_the_existing_code(world) -> None:
    session, w = world
    approve(session)
    from app.deep_review.models import DocumentBundle

    session.get(DocumentBundle, w.bundle_id).status = "superseded"
    session.commit()
    assert start_code(session, w, bundle_id=None) == "bundle_not_ready"  # no ready bundle to pick
    assert start_code(session, w) == "bundle_not_ready"  # the given bundle is not ready
    assert count(session, DeepReviewPreview) == 0


@needs_rootlab
def test_t3_card_review_currentness_has_no_overview_and_tracks_sw_and_bundle(world) -> None:
    session, w = world
    approve(session)
    result = start(session, w)
    review = session.get(DeepReview, result.review_id)
    assert cdr.is_company_review_current(session, review) is True
    notice = session.get(Notice, w.notice_id)
    notice.qualification_flags_json = {"sw_business_status": "N"}
    session.commit()
    assert cdr.is_company_review_current(session, review) is False


def test_t3_narrative_v2_still_requires_a_completed_overview(sqlite_engine_demo, monkeypatch) -> None:
    from tests.app.test_company_deep_review_binding import deep_world, preview as demo_preview
    from tests.app.test_company_deep_review_binding import service as demo_service

    with Session(sqlite_engine_demo) as session:
        world = deep_world(session, monkeypatch)
        session.execute(update(PrespecOverviewRun).where(PrespecOverviewRun.notice_id == world.notice_id)
                        .values(status="failed"))
        session.commit()
        with pytest.raises(DeepReviewServiceError) as error:
            demo_preview(session, demo_service(), world)
        assert error.value.code == "overview_not_completed"
        assert count(session, DeepReviewPreview) == 0


@pytest.fixture
def sqlite_engine_demo():
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


# --- T10: transfer audit right after the claim ---------------------------------------


def _claim(session: Session, svc: DeepReviewService):
    claim = svc.claim_next_job(session, "worker-rl-1")
    assert claim is not None
    return claim


@needs_rootlab
def test_t10_transfer_sent_is_written_once_after_claim_and_before_the_first_call(world, monkeypatch) -> None:
    session, w = world
    approval = approve(session)
    started = start(session, w)
    svc = service()
    seen: list[dict] = []

    def runner(service_obj, runner_session, claim, *, frozen, policy, approval):
        # Before any (fake) call the audit is already committed and visible.
        rows = runner_session.scalars(select(AuditEvent).where(AuditEvent.action == "analysis.transfer.sent")).all()
        seen.append({"audits": len(rows), "units": len(frozen["card_analysis"]["units"]),
                     "approval": str(approval.id), "policy": policy["policy_identity"]})

    monkeypatch.setattr(DeepReviewService, "_card_pipeline", lambda self: runner)
    claim = _claim(session, svc)
    assert claim.attempt_id == started.attempt_id
    svc.run_claim(session, claim)
    assert seen == [{"audits": 1, "units": seen[0]["units"], "approval": approval["approval_id"],
                     "policy": "analysis-policy-luna-rl-v1"}]
    audits = session.scalars(select(AuditEvent).where(AuditEvent.action == "analysis.transfer.sent")).all()
    assert len(audits) == 1
    audit = audits[0]
    preview = session.get(DeepReviewPreview, started.preview_id)
    card = preview.input_snapshot["card_analysis"]
    assert audit.actor_kind == "system" and audit.claimed_name == "system:transfer-policy"
    assert (audit.aggregate_type, audit.aggregate_id) == ("deep_review_attempt", str(started.attempt_id))
    assert set(audit.safe_metadata) == transfer_policy.TRANSFER_SENT_KEYS
    assert audit.safe_metadata == {
        "approval_id": approval["approval_id"], "policy_sha256": w.policy_sha256,
        "input_sha256": preview.input_sha256, "unit_count": len(card["units"]),
        "planned_call_count": len(card["batches"]) + 4, "notice_id": w.notice_id,
        "attempt_id": str(started.attempt_id),
    }
    metadata_text = json.dumps(audit.safe_metadata, ensure_ascii=False)
    for forbidden in ("token", "BBB0", "게시판", "추정가격", "대구", "prompt", "auth"):
        assert forbidden not in metadata_text
    # one per attempt: recording again is a no-op
    assert transfer_policy.record_transfer_sent(
        session, approval=session.get(TransferPolicyApproval, UUID(approval["approval_id"])),
        attempt_id=started.attempt_id, notice_id=w.notice_id, input_sha256=preview.input_sha256,
        unit_count=1, planned_call_count=5,
    ) is False


@needs_rootlab
def test_t10_unconnected_runner_fails_closed_without_audit(world, monkeypatch) -> None:
    session, w = world
    approve(session)
    started = start(session, w)
    # STEP-005 connected the runner; the ``None`` seam still fails closed before the audit.
    monkeypatch.setattr(DeepReviewService, "_card_pipeline", lambda self: None)
    svc = service()
    with pytest.raises(DeepReviewServiceError) as error:
        svc.run_claim(session, _claim(session, svc))
    assert error.value.code == "company_policy_invalid"
    assert session.get(DeepReviewAttempt, started.attempt_id).status == "failed"
    assert count_action(session, "analysis.transfer.sent") == 0


@needs_rootlab
def test_t10_revoked_approval_fails_closed_at_the_worker_before_any_call(world, monkeypatch) -> None:
    session, w = world
    approval = approve(session)
    started = start(session, w)
    transfer_policy.revoke_transfer_policy(session, approval_id=UUID(approval["approval_id"]),
                                           actor="jechoi", reason="중지")
    session.commit()
    called: list[int] = []
    monkeypatch.setattr(DeepReviewService, "_card_pipeline", lambda self: lambda *a, **k: called.append(1))
    svc = service()
    with pytest.raises(DeepReviewServiceError) as error:
        svc.run_claim(session, _claim(session, svc))
    assert error.value.code == "policy_not_approved" and called == []
    assert session.get(DeepReviewAttempt, started.attempt_id).status == "failed"
    assert count_action(session, "analysis.transfer.sent") == 0


@needs_rootlab
def test_t10_worker_claims_real_company_jobs_only_with_rl_enabled(world, monkeypatch) -> None:
    session, w = world
    approve(session)
    start(session, w)
    monkeypatch.setenv("BIDOPS_RL_ANALYSIS_ENABLED", "false")
    get_settings.cache_clear()
    assert service().claim_next_job(session, "worker-rl-1") is None
    monkeypatch.setenv("BIDOPS_RL_ANALYSIS_ENABLED", "true")
    get_settings.cache_clear()
    assert service().claim_next_job(session, "worker-rl-1") is not None


def count_action(session: Session, action: str) -> int:
    return int(session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)) or 0)
