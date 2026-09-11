"""사전규격 개요 run의 enqueue·실행·투영 (MVP 계약, 2026-09-11).

한 곳에 모아 둔 이유는 개요가 **한 테이블·한 슬롯**이기 때문이다. 자동 준비가
enqueue를 부르고, 합성 analysis worker의 개요 슬롯이 `run_once`를 부르며, 목록·
상세·회사 핏이 `current_runs`로 "이 공고의 현재 개요"를 묻는다. 세 경로가 같은
상태 규칙을 두 벌 만들지 않도록 여기 한 벌만 둔다.

경계 규칙:

- 모델 호출은 `ModelClient.for_purpose("overview", ...)` 하나뿐이고 transport는
  주입 seam(`client_factory`)으로만 갈아 끼운다. 원응답 본문은 DB에 넣지 않고
  암호화 저장소 참조(`raw_response_refs`)만 남긴다.
- 결정적 검사·의미 검토·구성은 `prespec_overview_claim_validation`이 소유한다.
  여기서 같은 규칙을 다시 쓰지 않는다.
- 실패는 안정 코드로만 남긴다. 예외 본문·프롬프트·경로·object key는 run에도
  응답에도 담지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.model_client import (
    APPROVED_GENERATION,
    ModelClient,
    ModelEndpointError,
    ModelIdentityError,
    ModelInvocationError,
    PromptTooLargeError,
    strip_leading_thinking,
    structured_request_capacity,
)
from ...core.models import AuditEvent
from ...core.object_store import EncryptedModelResponseStore, ObjectStoreError, object_store
from ..models import (
    ContentObject,
    ContentObjectLocation,
    DocumentBundle,
    DocumentBundleItem,
    DocumentVersion,
    PrespecOverviewRun,
    PrespecV4PdfSnapshot,
    WorkJob,
)
from .effective_grade import PRIORITY_GRADE, effective_grades
from .model_retry import VALIDATION_RETRY_SEED, build_correction
from .model_response_storage import store_raw_model_response
from .overview_range import (
    V4OpsError,
    V4PreparationError,
    select_v4_input_range,
    select_v4_page_span,
)
from .pdf_snapshot import (
    choose_rfp_document,
    prepare_v4_pdf_snapshot,
    read_snapshot_page_text,
    read_snapshot_section_candidates,
    safe_snapshot,
)
from .prespec_overview_claim_policy import (
    CLAIMS_STAGE,
    FORMAT_RETRY_CODES,
    LIMITS,
    SEMANTIC_STAGE,
    build_claims_prompt,
    build_claims_stage_input,
    canonical_sha256,
    load_claims_policy,
)
from .prespec_overview_claim_validation import (
    ClaimDraftError,
    SemanticResponseError,
    apply_semantic_review,
    build_input_limitations,
    compose_page_overview,
    draft_failure_checks,
    parse_claims_draft,
    validate_claims_deterministically,
    verify_composed_page_overview,
)

#: 사람이 쪽 범위를 확정했을 때 남기는 감사 action.
RANGE_CONFIRMATION_ACTION = "prespec_overview.range_confirmation"
#: WorkJob 계약 (contracts.md "사전규격 개요 검토 (MVP)").
OVERVIEW_JOB_TYPE = "prespec_overview"
OVERVIEW_AGGREGATE_TYPE = "prespec_overview_run"
#: queued·running은 공고당 하나뿐이다 (부분 유니크 `uq_prespec_overview_run_active`).
ACTIVE_STATUSES = ("queued", "running")
#: 종결 상태. 없는 것(`None`)을 종결로 승격시키지 않는다.
SETTLED_STATUSES = ("completed", "needs_human_review", "failed", "cancelled")
#: 개요 입력 PDF 준비 option. 옛 v4 ops CLI가 쓰던 값 그대로다.
SNAPSHOT_OPTIONS: Mapping[str, Any] = {
    "prepare_pdf": True,
    "ocr": False,
    "timeout_seconds": 300,
    "max_output_bytes": 64 * 1024 * 1024,
    "max_pdf_objects": 10000,
}
#: 모델 응답 자체의 문제라 같은 입력을 한 번 더 보낼 가치가 있는 호출 실패.
_RETRYABLE_INVOCATION_CODES = frozenset({"malformed_json", "truncated_json"})
#: 초안 파싱 실패 중 사람 검토로 보내는 사실 계열 코드.
_FACTUAL_DRAFT_CODES = frozenset({
    "fact_structure_missing", "fact_schema_invalid", "output_limit_exceeded", "duplicate_json_key",
})


class OverviewEnqueueError(ValueError):
    """enqueue 인자 자체가 틀렸다. 자격 미충족은 예외가 아니라 ``None``이다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OverviewRequestError(ValueError):
    """사람 요청 경계의 안정 실패 코드. 라우터는 이 코드만 상태로 옮긴다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OverviewRunResult:
    """한 poll이 개요 슬롯에서 한 일. 원문·응답·경로는 담지 않는다."""

    claimed: bool
    attempt_id: UUID | None = None
    status: str = "idle"
    reason_code: str | None = None
    expired_leases: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


# --- 읽기 투영 ---------------------------------------------------------------


def current_runs(
    session: Session, notice_ids: Sequence[int]
) -> dict[int, PrespecOverviewRun | None]:
    """공고별 `created_at` 최신 run. 없는 공고는 ``None``이다.

    조회는 공고 수와 무관하게 한 번이다 (명세 §8의 N+1 금지).
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}
    latest: dict[int, PrespecOverviewRun] = {}
    for row in session.scalars(
        select(PrespecOverviewRun)
        .where(PrespecOverviewRun.notice_id.in_(ids))
        .order_by(
            PrespecOverviewRun.notice_id.asc(),
            PrespecOverviewRun.created_at.desc(),
            PrespecOverviewRun.id.desc(),
        )
    ).all():
        latest.setdefault(int(row.notice_id), row)
    return {notice_id: latest.get(notice_id) for notice_id in ids}


def overview_status_for(run: PrespecOverviewRun | None) -> str | None:
    """run 상태를 목록 계약의 개요 상태로 그대로 옮긴다.

    run이 없으면 ``None``이다. 없는 것을 실행 중이나 실패로 승격시키지 않는다.
    """

    return str(run.status) if run is not None else None


def completed_result(run: PrespecOverviewRun | None) -> Mapping[str, Any] | None:
    """완료된 run의 `result_json`. 그 밖의 상태에서는 ``None``이다."""

    if run is None or run.status != "completed":
        return None
    result = run.result_json
    return result if isinstance(result, Mapping) else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _evidence_view(rows: Any) -> list[dict[str, Any]]:
    """근거를 계약이 정한 `{page, quote}`로만 줄인다.

    저장된 근거에는 char offset·page hash가 함께 있지만 화면 계약이 아니다.
    """

    result: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return result
    for row in rows:
        if isinstance(row, Mapping) and isinstance(row.get("page"), int) and isinstance(row.get("quote"), str):
            result.append({"page": int(row["page"]), "quote": str(row["quote"])})
    return result


_RESULT_SECTIONS = ("business_overview", "main_tasks", "budget_and_period", "important_conditions")


def _result_view(result: Any) -> dict[str, Any] | None:
    """완료된 `result_json`을 REST 계약 모양으로 옮긴다."""

    if not isinstance(result, Mapping):
        return None
    view: dict[str, Any] = {}
    for section in _RESULT_SECTIONS:
        rows = result.get(section)
        view[section] = [
            {
                "claim_id": str(row.get("claim_id")),
                "text": str(row.get("text")),
                "evidence": _evidence_view(row.get("evidence")),
            }
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, Mapping)
        ]
    view["reviewer_analysis"] = [
        {
            "id": str(row.get("id")),
            "text": str(row.get("text")),
            "supporting_claim_ids": _string_list(row.get("supporting_claim_ids")),
        }
        for row in (result.get("reviewer_analysis") or [])
        if isinstance(row, Mapping)
    ]
    view["unknowns"] = _string_list(result.get("unknowns"))
    view["input_limitations"] = _string_list(result.get("input_limitations"))
    return view


def _failed_claims(checks: Any) -> list[dict[str, Any]]:
    """사람이 봐야 할 주장만 검사 결과에서 계산한다.

    실패 목록을 따로 저장하지 않는다 — 저장하면 검사 결과와 갈릴 수 있다.
    """

    if not isinstance(checks, Mapping):
        return []
    rows = checks.get("checks")
    result: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        deterministic = row.get("deterministic") if isinstance(row.get("deterministic"), Mapping) else {}
        semantic = row.get("semantic") if isinstance(row.get("semantic"), Mapping) else {}
        codes = [
            *_string_list(deterministic.get("reason_codes")),
            *(
                _string_list(semantic.get("reason_codes"))
                if semantic.get("status") in {"contradicted", "insufficient"}
                else []
            ),
        ]
        if deterministic.get("status") == "passed" and semantic.get("status") not in {"contradicted", "insufficient"}:
            continue
        result.append({
            "claim_id": str(row.get("claim_id")),
            "section": str(row.get("section")),
            "text": str(row.get("text")),
            "reason_codes": sorted(set(codes)),
            "evidence": _evidence_view(deterministic.get("verified_evidence")),
        })
    return result


def run_view(run: PrespecOverviewRun) -> dict[str, Any]:
    """한 run의 REST 응답. 모델 원문·원응답 참조·내부 경로는 담지 않는다."""

    return {
        "id": str(run.id),
        "status": str(run.status),
        "range_source": str(run.range_source),
        "page_start": run.page_start,
        "page_end": run.page_end,
        "range_reason_codes": _string_list(run.range_reason_codes),
        "reason_codes": _string_list(run.reason_codes),
        "warnings": _string_list(run.warnings_json),
        "result": _result_view(run.result_json) if run.status == "completed" else None,
        "failed_claims": _failed_claims(run.checks_json) if run.status == "needs_human_review" else [],
        "model_name": run.model_name,
        "model_revision": run.model_revision,
        "call_count": int(run.call_count),
        "actor_name": run.actor_name,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
    }


OVERVIEW_ENVELOPE_SCHEMA = "bidops.prespec-overview.v1"


def overview_envelope(session: Session, notice_id: int) -> dict[str, Any]:
    """공고 한 건의 현재 개요와 이력 (`bidops.prespec-overview.v1`)."""

    history = session.scalars(
        select(PrespecOverviewRun)
        .where(PrespecOverviewRun.notice_id == int(notice_id))
        .order_by(PrespecOverviewRun.created_at.desc(), PrespecOverviewRun.id.desc())
    ).all()
    rows = [run_view(run) for run in history]
    return {
        "schema": OVERVIEW_ENVELOPE_SCHEMA,
        "notice_id": int(notice_id),
        "current": rows[0] if rows else None,
        "history": rows,
    }


# --- enqueue -----------------------------------------------------------------


def active_run(session: Session, notice_id: int) -> PrespecOverviewRun | None:
    """공고의 queued·running run. 없으면 ``None``이다."""

    return session.scalars(
        select(PrespecOverviewRun)
        .where(
            PrespecOverviewRun.notice_id == int(notice_id),
            PrespecOverviewRun.status.in_(ACTIVE_STATUSES),
        )
        .order_by(PrespecOverviewRun.created_at.asc(), PrespecOverviewRun.id.asc())
        .limit(1)
    ).first()


def ready_bundle_document(session: Session, notice_id: int) -> DocumentVersion | None:
    """가장 최근 `ready` 묶음에서 고른 제안요청서. 없으면 ``None``이다."""

    bundle = session.scalars(
        select(DocumentBundle)
        .where(DocumentBundle.notice_id == int(notice_id), DocumentBundle.status == "ready")
        .order_by(DocumentBundle.revision.desc())
        .limit(1)
    ).first()
    if bundle is None:
        return None
    documents = session.scalars(
        select(DocumentVersion)
        .join(DocumentBundleItem, DocumentBundleItem.document_version_id == DocumentVersion.id)
        .where(
            DocumentBundleItem.bundle_id == bundle.id,
            DocumentVersion.is_current.is_(True),
            DocumentVersion.safety_status == "safe",
            DocumentVersion.needs_human_review.is_(False),
        )
    ).all()
    return choose_rfp_document(documents).document


def enqueue_overview_run(
    session: Session,
    notice_id: int,
    *,
    range_source: str = "auto",
    page_start: int | None = None,
    page_end: int | None = None,
    actor_name: str | None = None,
    settings: Any | None = None,
) -> PrespecOverviewRun | None:
    """개요 run 하나를 대기열에 넣는다. 조건 미충족은 예외가 아니라 ``None``이다.

    조건은 네 가지다 — 플래그 on(사람이 범위를 확정한 경우는 플래그와 무관),
    활성 run 없음, effective grade `우선 검토`, `ready` 묶음에 제안요청서 문서.
    부분 유니크 인덱스가 최종 방어이고 여기서는 사전 조회로 조용히 물러난다.
    """

    settings = settings or get_settings()
    if range_source not in {"auto", "human"}:
        raise OverviewEnqueueError("range_source_invalid")
    if range_source == "human":
        if (
            isinstance(page_start, bool) or isinstance(page_end, bool)
            or not isinstance(page_start, int) or not isinstance(page_end, int)
            or page_start < 1 or page_end < page_start
        ):
            raise OverviewEnqueueError("range_invalid")
    elif page_start is not None or page_end is not None:
        raise OverviewEnqueueError("range_invalid")
    if range_source != "human" and not settings.prespec_overview_enabled:
        return None
    if active_run(session, notice_id) is not None:
        return None
    grade = effective_grades(session, [int(notice_id)]).get(int(notice_id))
    if grade is None or grade.grade != PRIORITY_GRADE:
        return None
    document = ready_bundle_document(session, notice_id)
    if document is None:
        return None
    policy = load_claims_policy(settings.prespec_overview_policy_path)
    run_id = uuid4()
    job = WorkJob(
        id=uuid4(),
        job_type=OVERVIEW_JOB_TYPE,
        aggregate_type=OVERVIEW_AGGREGATE_TYPE,
        aggregate_id=run_id,
        status="queued",
    )
    session.add(job)
    session.flush()
    run = PrespecOverviewRun(
        id=run_id,
        notice_id=int(notice_id),
        document_version_id=document.id,
        snapshot_id=None,
        work_job_id=job.id,
        status="queued",
        range_source=range_source,
        page_start=page_start,
        page_end=page_end,
        range_reason_codes=[],
        policy_digest=policy.digest,
        model_name=str(policy.document["model_name"]),
        model_revision=None,
        warnings_json=[],
        reason_codes=[],
        call_count=0,
        raw_response_refs=[],
        actor_name=actor_name,
    )
    session.add(run)
    session.flush()
    return run


def cancel_queued_runs(session: Session, reason: str = "overview_disabled", *, clock: Callable[[], datetime] | None = None) -> int:
    """플래그가 꺼졌을 때 대기 중인 run과 job을 닫는다.

    이미 `running`인 run은 건드리지 않는다 — 진행 중인 실행을 중간에 잘라
    반쪽 결과를 남기지 않는다는 뜻이다.
    """

    now = (clock or _now)()
    cancelled = 0
    for run in session.scalars(
        select(PrespecOverviewRun).where(PrespecOverviewRun.status == "queued")
    ).all():
        run.status = "cancelled"
        run.reason_codes = [reason]
        run.completed_at = now
        job = session.get(WorkJob, run.work_job_id)
        if job is not None and job.status in ACTIVE_STATUSES:
            job.status = "cancelled"
            job.last_error_code = reason
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
        cancelled += 1
    return cancelled


# --- 실행 --------------------------------------------------------------------


class _RunFailure(Exception):
    """실행 단계가 run을 닫아야 할 때 쓰는 내부 신호. 코드만 갖는다."""

    def __init__(self, status: str, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


class _IdentityUnavailable(Exception):
    """모델 신원을 확인할 수 없다. run은 건드리지 않고 다음 poll에 다시 본다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _expire_leases(session: Session, clock: Callable[[], datetime]) -> int:
    """lease가 지난 `running` run을 `failed/lease_expired`로 닫는다."""

    now = clock()
    expired = 0
    rows = session.execute(
        select(PrespecOverviewRun, WorkJob)
        .join(WorkJob, WorkJob.id == PrespecOverviewRun.work_job_id)
        .where(
            PrespecOverviewRun.status == "running",
            WorkJob.lease_expires_at.is_not(None),
            WorkJob.lease_expires_at < now,
        )
    ).all()
    for run, job in rows:
        run.status = "failed"
        run.reason_codes = [*_string_list(run.reason_codes), "lease_expired"]
        run.completed_at = now
        job.status = "failed"
        job.last_error_code = "lease_expired"
        job.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        expired += 1
    if expired:
        session.commit()
    return expired


def _claim_next(session: Session, worker_id: str, clock: Callable[[], datetime]) -> UUID | None:
    """가장 오래된 queued run 하나를 WorkJob lease로 잡는다."""

    now = clock()
    if session.in_transaction():
        session.commit()
    row = session.execute(
        select(PrespecOverviewRun, WorkJob)
        .join(WorkJob, WorkJob.id == PrespecOverviewRun.work_job_id)
        .where(PrespecOverviewRun.status == "queued", WorkJob.status == "queued")
        .order_by(PrespecOverviewRun.created_at.asc(), PrespecOverviewRun.id.asc())
        .with_for_update(skip_locked=True, of=WorkJob)
        .limit(1)
    ).first()
    if row is None:
        session.commit()
        return None
    run, job = row
    job.status = "running"
    job.lease_owner = worker_id
    job.lease_fence = int(job.lease_fence) + 1
    job.lease_expires_at = now + timedelta(seconds=LIMITS["lease_seconds"])
    job.attempt_count = int(job.attempt_count) + 1
    run.status = "running"
    run.started_at = now
    session.commit()
    return run.id


def _release(session: Session, run: PrespecOverviewRun, job: WorkJob | None) -> None:
    """claim을 되돌린다. 실행하지 않은 것을 실패로 적지 않는다."""

    run.status = "queued"
    run.started_at = None
    if job is not None:
        job.status = "queued"
        job.lease_owner = None
        job.lease_expires_at = None


def _source_location(session: Session, document: DocumentVersion) -> ContentObjectLocation:
    """이 문서 원본의 검증된 `source` 위치 하나.

    같은 bytes를 두 공고가 첨부로 갖고 있으면 한 content object에 위치가 둘
    이상 생긴다. 원본의 정체는 **hash**이고 읽기 경계가 그 hash를 다시 확인하므로
    위치가 여럿인 것은 모호함이 아니다. 가장 오래된 것을 고정해서 고르면 같은
    문서가 늘 같은 위치에 묶여 스냅샷 재사용 identity도 흔들리지 않는다.
    """

    location = session.scalars(
        select(ContentObjectLocation)
        .where(
            ContentObjectLocation.content_object_id == document.content_object_id,
            ContentObjectLocation.namespace_key == "source",
            ContentObjectLocation.status == "verified",
            ContentObjectLocation.purged_at.is_(None),
        )
        .order_by(ContentObjectLocation.created_at.asc(), ContentObjectLocation.id.asc())
        .limit(1)
    ).first()
    if location is None:
        raise V4PreparationError("source_location_missing")
    return location


class _ReplayConverter:
    """이미 만들어진 변환 결과 하나를 그대로 돌려주는 어댑터.

    준비 경계는 renderer·font binding을 **변환 전에** 요구하지만, MVP에는
    배포가 선언하는 binding 원본이 없다. 그래서 변환을 한 번만 돌리고 그
    산출물이 낸 provenance를 binding으로 묶은 뒤 같은 결과를 준비 경계에
    다시 넘긴다. 문서 하나에 변환은 여전히 한 번이다.
    """

    def __init__(self, processed: Any, clamav_checker: Any) -> None:
        self._processed = processed
        self.clamav_checker = clamav_checker
        self.calls = 0

    def process(self, _content: bytes, _media_type: str | None, _options: Any) -> Any:
        self.calls += 1
        return self._processed


def _worker_bindings(metadata: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """변환기가 낸 provenance를 준비 경계가 받는 binding 모양으로 옮긴다."""

    if metadata.get("renderer") == "source-pdf":
        return (
            {"source_pdf": True, "processor_provenance": metadata.get("processor_provenance")},
            {"source_pdf": True, "font_provenance": None},
        )
    renderer = metadata.get("renderer_provenance")
    font = metadata.get("font_provenance")
    if not isinstance(renderer, Mapping) or not isinstance(font, Mapping):
        raise V4PreparationError("renderer_binding_invalid")
    return dict(renderer), dict(font)


def prepare_run_snapshot(
    session: Session,
    document: DocumentVersion,
    *,
    store: Any,
    converter: Any,
    settings: Any,
) -> PrespecV4PdfSnapshot:
    """개요 입력이 쓸 PDF·쪽 텍스트 스냅샷을 얻는다.

    같은 원본으로 이미 동결한 스냅샷이 있으면 재변환하지 않는다. 없으면 변환을
    한 번 돌리고 그 산출물을 그대로 준비 경계에 넘겨 동결한다.
    """

    source = session.get(ContentObject, document.content_object_id)
    if source is None:
        raise V4PreparationError("source_content_missing")
    existing = session.scalars(
        select(PrespecV4PdfSnapshot)
        .where(
            PrespecV4PdfSnapshot.document_version_id == document.id,
            PrespecV4PdfSnapshot.source_sha256 == source.sha256,
        )
        .order_by(PrespecV4PdfSnapshot.created_at.desc(), PrespecV4PdfSnapshot.id.desc())
        .limit(1)
    ).first()
    if existing is not None:
        return safe_snapshot(session, existing)
    location = _source_location(session, document)
    from .pdf_snapshot import _read_verified_artifact

    source_bytes = _read_verified_artifact(store, location, source, max_bytes=source.size_bytes)
    options = dict(SNAPSHOT_OPTIONS)
    try:
        processed = converter.process(source_bytes, source.detected_mime, options)
    except V4PreparationError:
        raise
    except Exception as error:
        code = getattr(error, "code", None)
        raise V4PreparationError(f"pdf_preparation_failed:{code}" if isinstance(code, str) else "pdf_preparation_failed") from error
    metadata = processed.pdf_metadata if hasattr(processed, "pdf_metadata") else None
    if not isinstance(metadata, Mapping):
        raise V4PreparationError("pdf_metadata_invalid")
    renderer, font = _worker_bindings(metadata)
    from ..document_mcp.safety import ProcessorOptions

    config = {"options": vars(ProcessorOptions.from_mapping(options))}
    return prepare_v4_pdf_snapshot(
        session,
        document_version_id=document.id,
        source_location_id=location.id,
        source_bytes=source_bytes,
        media_type=source.detected_mime,
        converter=_ReplayConverter(processed, getattr(converter, "clamav_checker", None)),
        store=store,
        options=options,
        renderer=renderer,
        font=font,
        config=config,
        scanner=getattr(converter, "clamav_checker", None),
    )


def _fallback_pages(pages: Sequence[Mapping[str, Any]]) -> int:
    """1쪽부터 상한을 넘지 않는 마지막 쪽. 상한 안에 한 쪽도 없으면 0이다."""

    total = 0
    last = 0
    for index, page in enumerate(pages, 1):
        if index > LIMITS["max_pages"]:
            break
        text = str(page.get("text") or "")
        if total + len(text) > LIMITS["max_page_text_chars"]:
            break
        total += len(text)
        last = index
    return last


def _locator(page: int, kind: str) -> dict[str, Any]:
    return {"kind": kind, "page": int(page)}


def _select_range(
    session: Session,
    run: PrespecOverviewRun,
    snapshot: PrespecV4PdfSnapshot,
    document: DocumentVersion,
    *,
    store: Any,
) -> tuple[Any, list[str]]:
    """동결 입력 범위 하나를 정한다. (선택, 사유 코드)를 돌려준다."""

    payload_source = read_snapshot_page_text(session, store, snapshot)
    pages = payload_source.get("pages")
    if not isinstance(pages, list) or not pages:
        raise _RunFailure("failed", "manifest_invalid")
    payload = {
        "document_version_id": str(document.id),
        "source_sha256": snapshot.source_sha256,
        "pages": pages,
        "blocks": payload_source.get("blocks", []),
    }
    if run.range_source == "human":
        selection = select_v4_page_span(
            payload,
            int(run.page_start),
            int(run.page_end),
            start_locator=_locator(run.page_start, "page"),
            end_locator=_locator(run.page_end, "page"),
        )
        return selection, []
    candidates = read_snapshot_section_candidates(session, store, snapshot)
    selection = select_v4_input_range(
        payload,
        candidates_complete=not bool(candidates and candidates.get("candidates_truncated")),
    )
    if selection.status == "ready":
        return selection, []
    last = _fallback_pages(pages)
    if last < 1:
        raise _RunFailure("failed", "manifest_invalid")
    fallback = select_v4_page_span(
        payload, 1, last,
        start_locator=_locator(1, "page"),
        end_locator=_locator(last, "page"),
    )
    reasons = [code for code in (selection.reason_code,) if code]
    return fallback, [*reasons, "range_fallback_head"]


def _stage_pages(selection: Any) -> dict[int, str]:
    return {
        int(page["number"]): str(page["text"])
        for page in selection.manifest.get("pages", [])
    }


def _binding_digest(run: PrespecOverviewRun, policy: Any) -> str:
    return canonical_sha256({
        "model_name": run.model_name,
        "model_revision": run.model_revision,
        "policy_digest": policy.digest,
    })


class _Caller:
    """호출 상한·원응답 저장·call_count를 한 곳에서 지키는 호출 seam."""

    def __init__(self, session: Session, run: PrespecOverviewRun, client: Any, policy: Any, *, settings: Any, clock: Callable[[], datetime]) -> None:
        self.session = session
        self.run = run
        self.client = client
        self.policy = policy
        self.settings = settings
        self.clock = clock
        self._store: Any | None = None

    def _record(self, stage: str, raw: bytes | None) -> None:
        if raw is None:
            return
        if self._store is None:
            self._store = EncryptedModelResponseStore(self.settings)
        try:
            digest = store_raw_model_response(self.session, raw, store=self._store, clock=self.clock)
        except (ObjectStoreError, ValueError, TypeError) as error:
            raise _RunFailure("failed", "response_store_unavailable") from error
        refs = list(self.run.raw_response_refs or [])
        refs.append({"stage": stage, "sha256": digest})
        self.run.raw_response_refs = refs

    def invoke(self, stage: str, ledger_stage: str, input_slice: Mapping[str, Any], *, correction: str | None = None, seed: int | None = None) -> tuple[Any, bytes]:
        if int(self.run.call_count) >= LIMITS["max_calls"]:
            raise _RunFailure("failed", "call_budget_exhausted")
        contract = self.policy.structured_output_contract(stage)
        stage_policy = self.policy.stage_policy(stage)
        try:
            prompt = build_claims_prompt(self.policy, stage, dict(input_slice))
        except PromptTooLargeError as error:
            raise _RunFailure("failed", "input_capacity_exceeded") from error
        try:
            capacity = structured_request_capacity(
                model=self.run.model_name,
                prompt=prompt,
                contract=contract,
                api_dialect=str(getattr(self.client, "api_dialect", "vllm")),
                max_model_len=getattr(self.client, "model_context_tokens", None),
                policy_context_ceiling=LIMITS["max_model_context_tokens"],
                max_tokens=APPROVED_GENERATION["max_completion_tokens"],
                chat_template_reserve_tokens=LIMITS["chat_template_reserve_tokens"],
                timeout_seconds=LIMITS["timeout_seconds"],
                seed=int(APPROVED_GENERATION["seed"] if seed is None else seed),
                correction=correction,
            )
        except ModelInvocationError as error:
            raise _RunFailure("failed", "input_capacity_exceeded") from error
        if capacity.context_unverified:
            self.run.warnings_json = sorted({*_string_list(self.run.warnings_json), "context_unverified"})
        self.run.call_count = int(self.run.call_count) + 1
        try:
            response = self.client.invoke(
                stage, input_slice, stage_policy,
                seed=seed, correction=correction, output_contract=contract,
                prompt_max_chars=LIMITS["max_prompt_chars"],
            )
        except ModelInvocationError as error:
            self._record(ledger_stage, error.raw_response)
            raise
        raw = bytes(response.raw_response)
        self._record(ledger_stage, raw)
        return response, raw


def _draft_text(raw: bytes) -> str:
    text, _thinking = strip_leading_thinking(raw.decode("utf-8", "strict"))
    return text


def _run_draft(caller: _Caller, stage_input: Mapping[str, Any], run: PrespecOverviewRun, policy: Any) -> Any:
    """초안 한 번, 형식 오류면 한 번 더. 사실 실패는 사람 검토로 보낸다."""

    codes: list[str] = []
    raw: bytes | None = None
    for attempt in range(2):
        correction = build_correction(codes) if attempt else None
        seed = VALIDATION_RETRY_SEED if attempt else None
        try:
            _response, raw = caller.invoke(CLAIMS_STAGE, "draft", stage_input, correction=correction, seed=seed)
            return parse_claims_draft(_draft_text(raw))
        except ModelInvocationError as error:
            code = str(getattr(error, "code", "") or "provider_error")
            if code not in _RETRYABLE_INVOCATION_CODES or attempt:
                raise _RunFailure(
                    "failed",
                    "draft_format_retry_exhausted" if code in _RETRYABLE_INVOCATION_CODES else code,
                ) from error
            codes = [code]
        except UnicodeError as error:
            if attempt:
                raise _RunFailure("failed", "draft_format_retry_exhausted") from error
            codes = ["json_invalid"]
        except ClaimDraftError as error:
            if error.code in _FACTUAL_DRAFT_CODES:
                caller.run.draft_json = None
                caller.run.checks_json = draft_failure_checks(
                    _draft_text(raw) if raw is not None else "",
                    error,
                    attempt_id=run.id,
                    input_sha256=str(run.input_sha256),
                    policy_digest=policy.digest,
                    binding_digest=_binding_digest(run, policy),
                ).model_dump(mode="json")
                raise _RunFailure("needs_human_review", error.code) from error
            if attempt or error.code not in FORMAT_RETRY_CODES:
                raise _RunFailure("failed", "draft_format_retry_exhausted") from error
            codes = [error.code]
    raise _RunFailure("failed", "draft_format_retry_exhausted")


def _execute(
    session: Session,
    run: PrespecOverviewRun,
    *,
    settings: Any,
    client_factory: Callable[[Any], Any] | None,
    clock: Callable[[], datetime],
    converter: Any | None,
    store: Any | None,
) -> None:
    """claim된 run 하나를 끝까지 실행하고 그 상태를 run에 적는다."""

    policy = load_claims_policy(settings.prespec_overview_policy_path)
    document = session.get(DocumentVersion, run.document_version_id)
    if document is None:
        raise _RunFailure("failed", "runner_failed")
    if store is None:
        store = object_store(namespaces=("source", "structure"), read_namespaces=("source", "structure"))
    if converter is None:
        from ...core.clamav import ClamAVScanner
        from .document_converter import ScratchDocumentProcessor

        scanner = ClamAVScanner(settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds)
        converter = ScratchDocumentProcessor(wait_seconds=310, clamav_checker=scanner.scan)

    # --- prepare -------------------------------------------------------------
    snapshot = session.get(PrespecV4PdfSnapshot, run.snapshot_id) if run.snapshot_id else None
    if snapshot is None:
        try:
            snapshot = prepare_run_snapshot(session, document, store=store, converter=converter, settings=settings)
        except (V4PreparationError, V4OpsError, ObjectStoreError) as error:
            code = str(getattr(error, "code", "") or "pdf_preparation_failed")
            raise _RunFailure(
                "failed",
                code if code.startswith("pdf_preparation_failed") else f"pdf_preparation_failed:{code}",
            ) from error
        run.snapshot_id = snapshot.id

    # --- range ---------------------------------------------------------------
    try:
        selection, range_codes = _select_range(session, run, snapshot, document, store=store)
    except (V4PreparationError, V4OpsError, ObjectStoreError) as error:
        code = str(getattr(error, "code", "") or "manifest_invalid")
        raise _RunFailure("failed", "manifest_invalid" if code == "page_range_invalid" else code) from error
    pages = _stage_pages(selection)
    if not pages or not any(text.strip() for text in pages.values()):
        raise _RunFailure("failed", "manifest_invalid")
    run.page_start = min(pages)
    run.page_end = max(pages)
    run.input_sha256 = selection.input_sha256
    run.range_reason_codes = range_codes
    if range_codes:
        run.range_source = "fallback"

    # --- model client ---------------------------------------------------------
    try:
        client = (
            client_factory(policy) if client_factory is not None
            else ModelClient.for_purpose(
                "overview",
                model=str(policy.document["model_name"]),
                output_contract=policy.structured_output_contract(CLAIMS_STAGE),
                settings=settings,
            )
        )
        identity = client.verify_identity()
    except (ModelEndpointError, ModelIdentityError) as error:
        raise _IdentityUnavailable(str(getattr(error, "code", "") or "identity_unavailable")) from error
    run.model_revision = str(getattr(identity, "revision", "") or "") or None
    caller = _Caller(session, run, client, policy, settings=settings, clock=clock)

    # --- draft ---------------------------------------------------------------
    try:
        stage_input = build_claims_stage_input(pages)
    except ValueError as error:
        raise _RunFailure("failed", "input_capacity_exceeded") from error
    draft = _run_draft(caller, stage_input, run, policy)
    run.draft_json = draft.model_dump(mode="json")

    # --- deterministic --------------------------------------------------------
    try:
        checks = validate_claims_deterministically(
            draft, pages,
            attempt_id=run.id,
            input_sha256=str(run.input_sha256),
            policy_digest=policy.digest,
            binding_digest=_binding_digest(run, policy),
        )
    except ClaimDraftError as error:
        raise _RunFailure("failed", "draft_format_retry_exhausted") from error
    except ValueError as error:
        if str(error) == "input_limit_exceeded":
            raise _RunFailure("failed", "input_capacity_exceeded") from error
        raise _RunFailure("failed", "runner_failed") from error
    run.checks_json = checks.model_dump(mode="json")
    run.warnings_json = sorted({*_string_list(run.warnings_json), *checks.warnings})
    if checks.reason_codes or any(row.deterministic.status != "passed" for row in checks.checks) or not checks.checks:
        raise _RunFailure("needs_human_review", "deterministic_check_failed")

    # --- semantic -------------------------------------------------------------
    try:
        semantic_input = build_claims_stage_input(pages, draft=draft, checks=checks)
    except ValueError as error:
        raise _RunFailure("failed", "input_capacity_exceeded") from error
    try:
        _response, raw = caller.invoke(SEMANTIC_STAGE, "semantic", semantic_input)
    except ModelInvocationError as error:
        raise _RunFailure("failed", str(getattr(error, "code", "") or "semantic_response_invalid")) from error
    try:
        checks = apply_semantic_review(draft, checks, _draft_text(raw))
    except SemanticResponseError as error:
        raise _RunFailure("failed", "semantic_response_invalid") from error
    except (UnicodeError, ValueError) as error:
        raise _RunFailure("failed", "semantic_response_invalid") from error
    run.checks_json = checks.model_dump(mode="json")
    run.warnings_json = sorted({*_string_list(run.warnings_json), *checks.warnings})
    if checks.overall != "passed":
        raise _RunFailure("needs_human_review", "semantic_review_failed")

    # --- compose --------------------------------------------------------------
    try:
        payload = compose_page_overview(
            draft, checks,
            verification_id=run.id,
            input_limitations=build_input_limitations(
                sorted(pages), pdf_page_count=int(snapshot.pdf_page_count),
            ),
        )
        if not verify_composed_page_overview(payload, draft, checks):
            raise ValueError("verification_not_passed")
    except ValueError as error:
        raise _RunFailure("needs_human_review", "composition_not_verified") from error
    run.result_json = payload.model_dump(mode="json")


def _finish(session: Session, run: PrespecOverviewRun, status: str, codes: Sequence[str], clock: Callable[[], datetime]) -> None:
    run.status = status
    if codes:
        run.reason_codes = [*_string_list(run.reason_codes), *codes]
    run.completed_at = clock()
    job = session.get(WorkJob, run.work_job_id)
    if job is not None:
        # 사람 검토로 보내는 것은 job의 실패가 아니다. job은 자기 일을 끝냈다.
        job.status = "failed" if status == "failed" else "completed"
        job.last_error_code = codes[0] if codes else None
        job.completed_at = run.completed_at
        job.lease_owner = None
        job.lease_expires_at = None


def run_once(
    session: Session,
    worker_id: str | None = None,
    *,
    settings: Any | None = None,
    client_factory: Callable[[Any], Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    converter: Any | None = None,
    store: Any | None = None,
) -> OverviewRunResult:
    """개요 슬롯의 한 poll. 최대 하나의 run을 claim하고 끝까지 실행한다."""

    settings = settings or get_settings()
    clock = clock or _now
    worker_id = worker_id or "analysis-worker"
    expired = _expire_leases(session, clock)
    if not settings.prespec_overview_enabled:
        cancelled = cancel_queued_runs(session, clock=clock)
        session.commit()
        return OverviewRunResult(
            False, status="idle",
            reason_code="overview_disabled" if cancelled else None,
            expired_leases=expired,
        )
    run_id = _claim_next(session, worker_id, clock)
    if run_id is None:
        return OverviewRunResult(False, status="idle", expired_leases=expired)
    run = session.get(PrespecOverviewRun, run_id)
    if run is None:  # pragma: no cover - claim은 방금 이 행을 읽었다
        return OverviewRunResult(False, status="idle", expired_leases=expired)
    try:
        _execute(
            session, run,
            settings=settings, client_factory=client_factory, clock=clock,
            converter=converter, store=store,
        )
    except _IdentityUnavailable as error:
        _release(session, run, session.get(WorkJob, run.work_job_id))
        session.commit()
        return OverviewRunResult(False, attempt_id=run_id, status="idle", reason_code=error.code, expired_leases=expired)
    except _RunFailure as failure:
        _finish(session, run, failure.status, [failure.code], clock)
        session.commit()
        return OverviewRunResult(True, attempt_id=run_id, status=failure.status, reason_code=failure.code, expired_leases=expired)
    except Exception as error:  # noqa: BLE001 - 코드만 남기고 본문은 버린다
        session.rollback()
        run = session.get(PrespecOverviewRun, run_id)
        code = str(getattr(error, "code", "") or "runner_failed")
        if run is not None:
            _finish(session, run, "failed", [code if code.replace("_", "").isalnum() else "runner_failed"], clock)
            session.commit()
        return OverviewRunResult(True, attempt_id=run_id, status="failed", reason_code="runner_failed", expired_leases=expired)
    _finish(session, run, "completed", [], clock)
    session.commit()
    from .auto_preparation import maybe_auto_start_deep_review

    maybe_auto_start_deep_review(session, int(run.notice_id))
    return OverviewRunResult(True, attempt_id=run_id, status="completed", expired_leases=expired)


# --- 사람 요청 경계 (REST가 부르는 것) ---------------------------------------


def latest_snapshot(session: Session, document_version_id: UUID) -> PrespecV4PdfSnapshot | None:
    """문서의 가장 최근 동결 스냅샷. 없으면 ``None``이다."""

    return session.scalars(
        select(PrespecV4PdfSnapshot)
        .where(PrespecV4PdfSnapshot.document_version_id == document_version_id)
        .order_by(PrespecV4PdfSnapshot.created_at.desc(), PrespecV4PdfSnapshot.id.desc())
        .limit(1)
    ).first()


def confirm_range(
    session: Session,
    notice_id: int,
    *,
    page_start: int,
    page_end: int,
    actor_name: str,
    note: str | None = None,
    settings: Any | None = None,
) -> PrespecOverviewRun:
    """사람이 확정한 쪽 범위로 개요 run 하나를 넣고 감사 이벤트를 남긴다.

    **자동 enqueue 플래그와 무관하다.** 사람이 명시적으로 고른 범위는 언제나 한
    건을 실행할 수 있어야 한다. 범위 확정은 실행 승인이 아니라 개요 run의 입력
    범위를 정하는 것이며 담당자 이름은 감사 표식이다.
    """

    if page_end < page_start:
        raise OverviewRequestError("range_invalid")
    if active_run(session, notice_id) is not None:
        raise OverviewRequestError("run_active")
    document = ready_bundle_document(session, notice_id)
    if document is None:
        raise OverviewRequestError("not_found")
    # 준비된 스냅샷이 있으면 그 현재성을 본다. 아직 없어도 문서 자체가
    # current·safe면 허용한다 — 준비는 run이 한다.
    snapshot = latest_snapshot(session, document.id)
    if snapshot is not None:
        try:
            safe_snapshot(session, snapshot)
        except V4OpsError as error:
            raise OverviewRequestError(str(getattr(error, "code", "") or "document_not_current_safe")) from error
    elif not document.is_current or document.safety_status != "safe" or document.needs_human_review:
        raise OverviewRequestError("document_not_current_safe")
    try:
        run = enqueue_overview_run(
            session, notice_id, range_source="human",
            page_start=page_start, page_end=page_end,
            actor_name=actor_name, settings=settings,
        )
    except OverviewEnqueueError as error:
        raise OverviewRequestError(error.code) from error
    if run is None:
        raise OverviewRequestError("not_found")
    session.add(
        AuditEvent(
            actor_kind="human",
            claimed_name=actor_name,
            action=RANGE_CONFIRMATION_ACTION,
            aggregate_type=OVERVIEW_AGGREGATE_TYPE,
            aggregate_id=str(run.id),
            safe_metadata={
                "notice_id": int(notice_id),
                "page_start": int(page_start),
                "page_end": int(page_end),
                "has_note": note is not None,
            },
        )
    )
    return run


def run_snapshot_pdf(
    session: Session, notice_id: int, run_id: UUID, *, store: Any | None = None
) -> bytes:
    """이 run이 실제로 읽은 고정 스냅샷 PDF bytes.

    다른 공고의 run이나 준비 전 run은 `not_found`이고, 문서·원본이 지금 current·
    safe가 아니면 `document_not_current_safe`다. 읽기는 저장된 version·hash를
    다시 확인하는 경계를 그대로 지난다.
    """

    run = session.get(PrespecOverviewRun, run_id)
    if run is None or int(run.notice_id) != int(notice_id) or run.snapshot_id is None:
        raise OverviewRequestError("not_found")
    snapshot = session.get(PrespecV4PdfSnapshot, run.snapshot_id)
    if snapshot is None:
        raise OverviewRequestError("not_found")
    try:
        safe_snapshot(session, snapshot)
    except V4OpsError as error:
        raise OverviewRequestError("document_not_current_safe") from error
    content = session.get(ContentObject, snapshot.pdf_content_object_id)
    location = session.get(ContentObjectLocation, snapshot.pdf_location_id)
    if content is None or location is None:
        raise OverviewRequestError("pdf_unavailable")
    from .pdf_snapshot import _read_verified_artifact

    try:
        if store is None:
            store = object_store(namespaces=("source",), read_namespaces=("source",))
        return _read_verified_artifact(
            store, location, content,
            max_bytes=content.size_bytes, expected_mime="application/pdf",
        )
    except (V4PreparationError, ObjectStoreError, OSError, ValueError) as error:
        raise OverviewRequestError("pdf_unavailable") from error


__all__ = [
    "ACTIVE_STATUSES",
    "OVERVIEW_AGGREGATE_TYPE",
    "OVERVIEW_ENVELOPE_SCHEMA",
    "OVERVIEW_JOB_TYPE",
    "RANGE_CONFIRMATION_ACTION",
    "SETTLED_STATUSES",
    "OverviewEnqueueError",
    "OverviewRequestError",
    "OverviewRunResult",
    "active_run",
    "cancel_queued_runs",
    "completed_result",
    "confirm_range",
    "current_runs",
    "enqueue_overview_run",
    "overview_envelope",
    "overview_status_for",
    "latest_snapshot",
    "prepare_run_snapshot",
    "ready_bundle_document",
    "run_once",
    "run_snapshot_pdf",
    "run_view",
]
