"""PS-01 사업 범위 카드 lineage 테스트 공용 fixture.

카드는 합성이다(실제 회사 카드는 git 밖 회사 자료다). 개요 run·문서·카드 행을
최소한으로 세우고, 측정 실행기와 같은 모델 입력을 받는 가짜 모델 client를 둔다.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import yaml

from app.core.config import get_settings
from app.core.model_client import ModelIdentity
from app.deep_review.models import (
    ContentObject,
    DocumentVersion,
    PreSpecCompanyFitAttempt,
    PrespecOverviewRun,
    WorkJob,
)
from app.deep_review.services import company_fit as fit
from app.deep_review.services.company_fit_card import load_business_scope_card
from app.lifecycle.models import Notice, Opportunity, OpportunityLink

#: 고정 시계(측정 시점과 같은 2026-11-27 10:30 KST).
NOW = datetime(2026, 11, 27, 1, 30, tzinfo=UTC)
REVISION = "b" * 64

CARD = {
    "schema_version": "bidops.business-scope-card.v1.2",
    "company": {"name": "합성 회사"},
    "basis": "합성 카드",
    "scopes": [
        {"id": "scope:web", "name": "웹 시스템 구축", "summary": "업무 웹 시스템을 구축한다.",
         "includes": ["업무 시스템 구축", "포털 구축"], "boundary": "하드웨어 납품은 제외한다.",
         "keywords": ["시스템", "포털"], "level": "confirmed"},
        {"id": "scope:data", "name": "데이터 분석", "summary": "데이터 분석 플랫폼을 만든다.",
         "includes": ["분석 플랫폼"], "examples": [], "questions": ["범위?"]},
    ],
    "policies": [
        {"id": "policy:no-bid", "kind": "exclude", "summary": "수행하지 않는 사업이다.",
         "items": ["행사 운영"]},
        {"id": "policy:caution", "kind": "caution", "summary": "확인이 필요하다.",
         "rules": ["감리는 확인한다"]},
        {"id": "policy:custom", "kind": "exclude", "summary": "표에 없는 정책이다."},
    ],
    "questions": ["Q8"],
}

#: CARD의 C1 투영 기대값(fit_probe.card_facts 규칙, 키 순서 포함).
EXPECTED_FACTS = [
    {"ref": "scope:web", "fact_key": "웹 시스템 구축", "status": "confirmed",
     "value": {"summary": "업무 웹 시스템을 구축한다.", "includes": ["업무 시스템 구축", "포털 구축"],
               "boundary": "하드웨어 납품은 제외한다.", "keywords": ["시스템", "포털"]}},
    {"ref": "scope:data", "fact_key": "데이터 분석", "status": "confirmed",
     "value": {"summary": "데이터 분석 플랫폼을 만든다.", "includes": ["분석 플랫폼"]}},
    {"ref": "policy:no-bid", "fact_key": "exclude", "status": "confirmed",
     "value": {"summary": "수행하지 않는 사업이다.", "items": ["행사 운영"]}},
    {"ref": "policy:caution", "fact_key": "caution", "status": "confirmed",
     "value": {"summary": "확인이 필요하다.", "rules": ["감리는 확인한다"]}},
    {"ref": "policy:custom", "fact_key": "exclude", "status": "confirmed",
     "value": {"summary": "표에 없는 정책이다."}},
]
EXPECTED_LABELS = {
    "scope:web": "웹 시스템 구축", "scope:data": "데이터 분석",
    "policy:no-bid": "수행하지 않는 사업", "policy:caution": "확인이 필요한 사업",
    "policy:custom": "policy:custom",
}

OVERVIEW_RESULT = {
    "schema_version": "bidops.prespec-overview-claims.v2",
    "business_overview": [{"claim_id": "c1", "text": "업무 시스템을 구축한다.",
                           "evidence": [{"page": 3, "quote": "업무 시스템을 구축한다."}]}],
    "main_tasks": [{"claim_id": "c2", "text": "업무 시스템 구축 과업을 수행한다.",
                    "evidence": [{"page": 3, "quote": "업무 시스템 구축 과업"}]}],
    "budget_and_period": [],
    "input_limitations": ["page_text_only"],
}


def write_card(path: Path, card: Any = None) -> str:
    """카드를 YAML로 쓰고 파일 sha256을 돌려준다."""

    raw = yaml.safe_dump(CARD if card is None else card, allow_unicode=True, sort_keys=False).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def card_env(monkeypatch, tmp_path: Path, *, mode: str = "suggest", card: Any = None,
             mode_row: bool = True) -> Path:
    """카드 lineage가 실효가 되는 설정(모델 binding 포함).

    env 값은 배포 상한이다. 실효에는 최신 모드 행(PS-01 C8)도 `suggest`여야 하므로, 기본으로는
    지금 카드에 묶인 `suggest` 행이 있는 것처럼 둔다. 실제 행의 기록·감사·결속 규칙은
    `tests/deep_review/test_company_fit_mode.py`가 DB로 검사한다. `mode_row=False`면 행이 없다.
    """

    path = tmp_path / "business-scope-card.yaml"
    sha = write_card(path, card)
    for key, value in {
        "BIDOPS_PRESPEC_COMPANY_FIT_ENABLED": "true",
        "BIDOPS_PRESPEC_COMPANY_FIT_MODEL": "test-fit",
        "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
        "BIDOPS_VLLM_OVERVIEW_BASE_URL": "http://127.0.0.1:9/v1",
        "BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS": "127.0.0.1",
        "BIDOPS_VLLM_OVERVIEW_MODEL_REVISION": REVISION,
        "BIDOPS_PRESPEC_COMPANY_FIT_CARD_PATH": str(path),
        "BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256": sha,
        "BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE": mode,
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    from types import SimpleNamespace  # noqa: PLC0415

    from app.deep_review.services import company_fit_mode  # noqa: PLC0415
    from app.deep_review.services.company_fit import PROMPT_VERSION_CARD  # noqa: PLC0415

    if mode_row and mode == "suggest":
        monkeypatch.setattr(company_fit_mode, "latest_row", lambda session: SimpleNamespace(
            mode="suggest", prompt_version=PROMPT_VERSION_CARD, set_by="fixture", set_at=None,
            card_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        ))
    return path


def replace_card(monkeypatch, path: Path, card: Any) -> str:
    sha = write_card(path, card)
    monkeypatch.setenv("BIDOPS_PRESPEC_COMPANY_FIT_CARD_SHA256", sha)
    get_settings.cache_clear()
    return sha


def add_notice(
    session,
    *,
    title: str = "합성 사전규격",
    sw: str | None = "Y",
    deadline: datetime | None = NOW + timedelta(days=5),
    overview: str | None = "completed",
    checks: str = "passed",
) -> Notice:
    """사전규격 공고 하나와 (선택) 개요 run·현재 문서."""

    flags = {"sw_business_status": sw} if sw is not None else {}
    notice = Notice(notice_key=f"card:{uuid4()}", source_type="pre_spec", title=title,
                    deadline_at=deadline, qualification_flags_json=flags)
    session.add(notice)
    session.flush()
    if overview is not None:
        add_overview_run(session, notice, status=overview, checks=checks)
    session.flush()
    return notice


def add_overview_run(session, notice: Notice, *, status: str = "completed", checks: str = "passed",
                     created_at: datetime | None = None) -> PrespecOverviewRun:
    payload = f"card-doc-{notice.id}-{uuid4()}".encode()
    content = ContentObject(id=uuid4(), sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload),
                            detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=1,
                               source_kind="manual", original_filename="제안요청서.pdf", role="제안요청서",
                               is_current=True, safety_status="safe")
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add_all([document, job])
    session.flush()
    completed = status == "completed"
    run = PrespecOverviewRun(
        id=uuid4(), notice_id=notice.id, document_version_id=document.id, work_job_id=job.id,
        status=status, range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="test-overview", warnings_json=[], reason_codes=[], call_count=1,
        raw_response_refs=[], result_json=deepcopy(OVERVIEW_RESULT) if completed else None,
        checks_json={"overall": checks} if completed else None,
        completed_at=NOW if completed else None,
        created_at=created_at or NOW - timedelta(days=1),
    )
    session.add(run)
    session.flush()
    return run


def track(session, notice: Notice, status: str = "계속 추적") -> Opportunity:
    opportunity = Opportunity(first_registered_stage="pre_spec", tracking_status=status,
                              tracking_reason="테스트", tracking_selected_by="테스트 담당자",
                              tracking_selected_at=NOW)
    session.add(opportunity)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity.id, notice_id=notice.id, stage="notice",
                                link_type="official", status="확정", evidence_external_no=f"PRE-{notice.id}"))
    session.flush()
    return opportunity


def card_input(session, notice: Notice, *, judged_by: str = "model", model_name: str = "test-fit",
               model_revision: str = REVISION) -> dict[str, Any]:
    card = load_business_scope_card(get_settings())
    source = fit.overview_inputs(session, [notice.id])[notice.id]
    return fit.frozen_card_input(session, notice.id, source, card, model_name=model_name,
                                 model_revision=model_revision, judged_by=judged_by)


def card_row(inputs: dict[str, Any], *, status: str = "queued", created_at: datetime | None = None,
             result: dict[str, Any] | None = None) -> PreSpecCompanyFitAttempt:
    """카드 lineage attempt 한 행. ``completed``면 결과까지 채운다(SQLite 전용 단축 경로)."""

    row = PreSpecCompanyFitAttempt(
        id=uuid4(), company_id=None, notice_id=inputs["notice_id"],
        document_version_id=UUID(inputs["document_version_id"]),
        overview_run_id=UUID(inputs["overview_id"]), profile_version_id=None, deep_policy_version_id=None,
        card_version=inputs["card_version"], card_sha256=inputs["card_sha256"],
        input_jsonb=inputs, input_sha256=fit.digest(inputs), policy_digest=inputs["policy_digest"],
        model_name=inputs["model_name"], model_revision=inputs["model_revision"],
        quality_status=inputs["quality_status"], status=status, created_at=created_at or datetime.now(UTC),
    )
    if status in {"completed", "failed", "needs_human_review"}:
        row.completed_at = NOW
    if status == "running":
        row.lease_owner, row.lease_expires_at = "test", NOW + timedelta(seconds=600)
    if status == "completed":
        row.result_jsonb = result if result is not None else card_output()
        row.result_sha256 = fit.digest(row.result_jsonb)
    return row


def card_output(decision: str = "matched") -> dict[str, Any]:
    kind = {"matched": "scope_match", "mismatch": "scope_mismatch", "unknown": "information_gap"}[decision]
    company = {"matched": ["scope:web"], "mismatch": ["policy:no-bid"], "unknown": []}[decision]
    return {"schema_version": "bidops.prespec-company-fit-result.v1", "decision": decision,
            "summary": "카드 사업 범위와 대조한 결과입니다.",
            "reasons": [{"kind": kind, "explanation": "공고 과업과 카드 사업 범위를 대조했습니다.",
                         "notice_refs": ["main_tasks:0"], "company_refs": company}],
            "verification_items": ["실제 수행 범위를 확인해 주세요."] if decision == "unknown" else []}


class CardClient:
    """측정 실행기와 같은 입력을 받는지 기록하는 가짜 모델."""

    def __init__(self, result, *, retry_result=None, revision: str = REVISION):
        self.result, self.retry_result, self.revision = result, retry_result, revision
        self.calls = 0
        self.inputs: list[dict[str, Any]] = []
        self.policies: list[dict[str, Any]] = []
        self.seeds: list[Any] = []

    def verify_identity(self):
        return ModelIdentity("test-fit", self.revision)

    def invoke(self, stage, inputs, policy, *, seed=None, correction=None):
        self.calls += 1
        self.inputs.append(inputs)
        self.policies.append(policy)
        self.seeds.append(seed)
        result = self.result if self.calls == 1 or self.retry_result is None else self.retry_result
        return SimpleNamespace(structured_output=result, raw_response=json.dumps(result).encode(),
                               prompt_tokens=300, output_tokens=80, latency_ms=10)


def store_card_attempt(session, inputs: dict[str, Any], *, status: str = "completed",
                       result: dict[str, Any] | None = None,
                       created_at: datetime | None = None) -> PreSpecCompanyFitAttempt:
    """``queued``로 넣고 전이 규칙대로 ``status``까지 옮긴다(PostgreSQL trigger 호환)."""

    row = card_row(inputs, status="queued", created_at=created_at)
    session.add(row)
    session.flush()
    if status == "queued":
        session.commit()
        return row
    if status == "failed":
        row.status, row.error_code, row.completed_at = "failed", "company_fit_execution_failed", NOW
        session.commit()
        return row
    row.status, row.lease_owner, row.lease_expires_at = "running", "test", NOW + timedelta(seconds=600)
    session.flush()
    if status == "completed":
        row.result_jsonb = result if result is not None else card_output()
        row.result_sha256 = fit.digest(row.result_jsonb)
        row.status, row.lease_owner, row.lease_expires_at, row.completed_at = "completed", None, None, NOW
    elif status == "needs_human_review":
        row.status, row.lease_owner, row.lease_expires_at, row.completed_at = (
            "needs_human_review", None, None, NOW)
        row.error_code = "company_fit_validation_failed"
    session.commit()
    return row
