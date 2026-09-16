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

import logging
import re
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
from .effective_grade import effective_grades, overview_eligible
from .model_retry import VALIDATION_RETRY_SEED, build_correction
from .model_response_storage import store_raw_model_response
from .overview_range import (
    V4OpsError,
    V4PreparationError,
    _pages_from_indices,
    select_v4_input_range,
    select_v4_page_span,
)
from .pdf_snapshot import (
    choose_rfp_document,
    prepare_v4_pdf_snapshot,
    read_snapshot_page_text,
    read_snapshot_section_candidates,
    safe_snapshot,
    snapshot_has_section_candidates,
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
    drop_failed_claims,
    merge_semantic_checks,
    parse_claims_draft,
    validate_claims_deterministically,
    verify_composed_page_overview,
)

#: 사람이 쪽 범위를 확정했을 때 남기는 감사 action.
RANGE_CONFIRMATION_ACTION = "prespec_overview.range_confirmation"
#: claim 상한을 이미 쓴 run을 claim하지 않고 닫을 때 남기는 감사 action.
ATTEMPTS_EXHAUSTED_ACTION = "prespec_overview.attempts_exhausted"
#: 운영자가 활성 run을 손으로 닫을 때 남기는 감사 action.
OPERATOR_CLOSE_ACTION = "prespec_overview.operator_close"
#: 종결 사유 코드 (contracts.md "사전규격 개요 검토 (MVP)").
ATTEMPTS_EXHAUSTED_REASON = "attempts_exhausted"
IDENTITY_UNAVAILABLE_REASON = "identity_unavailable"
OPERATOR_CLOSE_REASON = "operator_close"
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
    #: 모델 신원 확인이 막혔을 때 그 실패 자체. worker가 재확인 backoff를
    #: 계산하려면 코드뿐 아니라 재시도 분류(`retryable`)가 필요하고, 그 분류는
    #: 응답 본문을 담지 않으려고 예외 객체가 out-of-band로 들고 있다. 확인이
    #: 막히지 않았으면 ``None``이다.
    identity_error: ModelEndpointError | ModelIdentityError | None = None


logger = logging.getLogger(__name__)

#: 로그로 나가도 되는 안정 코드 모양. 이 밖의 값(경로·DSN·본문이 섞인 문자열)은
#: 코드가 아니라고 보고 버린다.
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _safe_code(value: Any) -> str | None:
    return value if isinstance(value, str) and _SAFE_CODE.match(value) else None


def _failure_chain(error: BaseException, depth: int = 4) -> list[str]:
    """예외 클래스명과 안정 코드만 최대 `depth`단까지. 본문은 담지 않는다."""

    chain: list[str] = []
    cause: BaseException | None = error
    seen: set[int] = set()
    while cause is not None and len(chain) < depth and id(cause) not in seen:
        seen.add(id(cause))
        code = _safe_code(getattr(cause, "code", None))
        chain.append(f"{type(cause).__name__}:{code}" if code else type(cause).__name__)
        cause = cause.__cause__ or cause.__context__
    return chain


def _log_run_failure(run_id: UUID, notice_id: int | None, error: BaseException, code: str) -> None:
    """실패한 run 하나의 진단 표식. 본문·SQL·경로·원문은 남기지 않는다.

    운영에서 MinIO 자격 누락·ClamAV 연결·scratch 볼륨 누락이 모두 한 단어로만
    보였다. 예외 클래스와 `__cause__` 체인이 있어야 컨테이너 재현 없이 갈린다.
    """

    logger.warning(
        "prespec overview run failed",
        extra={"bidops": {
            "event": "prespec_overview.run_failed",
            "run_id": str(run_id),
            "notice_id": int(notice_id) if notice_id is not None else None,
            "reason_code": code,
            "error_chain": _failure_chain(error),
        }},
    )


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


def _verified_evidence_view(rows: Any) -> list[dict[str, Any]]:
    """검증된 근거를 `{page, quote, start_char, end_char}`로 줄인다.

    `page_text_sha256`은 내부 결속 값이라 응답에 담지 않는다.
    """

    result: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("page"), int):
            continue
        if not isinstance(row.get("quote"), str):
            continue
        result.append({
            "page": int(row["page"]),
            "quote": str(row["quote"]),
            "start_char": int(row["start_char"]) if isinstance(row.get("start_char"), int) else 0,
            "end_char": int(row["end_char"]) if isinstance(row.get("end_char"), int) else 0,
        })
    return result


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


def _verification_status(checks: Any) -> str | None:
    """검사 결과 한 벌의 공개 상태. 검사가 없으면 ``None``이다.

    판정은 `_failed_claims`와 같은 한 벌을 쓴다 — 사람이 볼 주장이 남아 있거나
    draft 전체 사유 코드가 있으면 `needs_human_review`다.
    """

    if not isinstance(checks, Mapping) or not isinstance(checks.get("checks"), list):
        return None
    if _failed_claims(checks) or _string_list(checks.get("reason_codes")):
        return "needs_human_review"
    return "passed"


def _draft_claim_texts(draft: Any) -> dict[str, tuple[str, str]]:
    """초안 주장의 `(section, text)`. 검사 행에 없는 값을 채울 때만 쓴다."""

    rows = draft.get("claims") if isinstance(draft, Mapping) else None
    result: dict[str, tuple[str, str]] = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping) and isinstance(row.get("id"), str):
            result[str(row["id"])] = (str(row.get("section") or ""), str(row.get("text") or ""))
    return result


def verification_view(run: PrespecOverviewRun | None) -> dict[str, Any] | None:
    """현재 run의 주장별 검증 기록. 검사 결과가 없으면 ``None``이다."""

    if run is None:
        return None
    checks = run.checks_json
    status = _verification_status(checks)
    if status is None:
        return None
    drafted = _draft_claim_texts(run.draft_json)
    claims: list[dict[str, Any]] = []
    for row in checks.get("checks") or []:
        if not isinstance(row, Mapping):
            continue
        claim_id = str(row.get("claim_id"))
        section, text = drafted.get(claim_id, ("", ""))
        deterministic = row.get("deterministic") if isinstance(row.get("deterministic"), Mapping) else {}
        semantic = row.get("semantic") if isinstance(row.get("semantic"), Mapping) else {}
        claims.append({
            "claim_id": claim_id,
            "section": str(row.get("section") or section),
            "text": str(row.get("text") or text),
            "deterministic": {
                "status": str(deterministic.get("status") or "failed"),
                "reason_codes": _string_list(deterministic.get("reason_codes")),
            },
            "semantic": {
                "status": str(semantic.get("status") or "not_run"),
                "reason_codes": _string_list(semantic.get("reason_codes")),
            },
            "verified_evidence": _verified_evidence_view(deterministic.get("verified_evidence")),
        })
    return {
        "verification_id": str(run.id),
        "status": status,
        "reason_codes": _string_list(checks.get("reason_codes")),
        "claims": claims,
    }


def _reviewed_pages(run: PrespecOverviewRun) -> list[int]:
    if run.page_start is None or run.page_end is None or int(run.page_end) < int(run.page_start):
        return []
    return list(range(int(run.page_start), int(run.page_end) + 1))


def run_view(
    run: PrespecOverviewRun,
    *,
    snapshot: PrespecV4PdfSnapshot | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """한 run의 REST 응답. 모델 원문·원응답 참조·내부 경로는 담지 않는다.

    `snapshot`·`prompt_version`은 호출자가 한 번에 모아 온 파생 값이다. 주지
    않으면 그 필드는 ``None``으로 남는다 — 여기서 다시 조회하지 않는다
    (공고당 run 수만큼 질의가 늘어나는 것을 막는다).
    """

    completed = run.status == "completed"
    reason_codes = _string_list(run.reason_codes)
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
        # 완료한 run도 결정적 검사에서 빠진 주장을 계속 보여준다.
        "failed_claims": _failed_claims(run.checks_json) if run.status in {"completed", "needs_human_review"} else [],
        "model_name": run.model_name,
        "model_revision": run.model_revision,
        "call_count": int(run.call_count),
        "actor_name": run.actor_name,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        # --- 화면이 쓰는 파생 값. 저장 값을 옮긴 것이며 새 판정이 아니다. ---
        "result_id": str(run.id) if completed else None,
        "prompt_version": prompt_version,
        "verification_status": _verification_status(run.checks_json),
        "document_version_id": str(run.document_version_id) if run.document_version_id else None,
        "source_sha256": snapshot.source_sha256 if snapshot is not None else None,
        "pdf_sha256": snapshot.pdf_sha256 if snapshot is not None else None,
        "pdf_page_count": int(snapshot.pdf_page_count) if snapshot is not None else None,
        "reviewed_pages": _reviewed_pages(run),
        "payload_sha256": canonical_sha256(run.result_json) if isinstance(run.result_json, Mapping) else None,
        # 참조 실행 표식이다. 측정된 품질이 아니며 승격시키지 않는다.
        "quality_status": (
            "mock_reference" if str(run.model_name or "").startswith("mock") else "unmeasured_reference"
        ),
        "validation_status": "passed" if completed else "failed",
        "validation_errors": reason_codes,
        "evidence_check_status": "passed" if completed else "failed",
        "evidence_check_errors": reason_codes,
    }


OVERVIEW_ENVELOPE_SCHEMA = "bidops.prespec-overview.v1"


#: 후보를 읽지 못했을 때 남기는 안전 코드 (화면이 쪽 입력으로 넘어간다).
CANDIDATES_UNAVAILABLE = "section_candidates_unavailable"
#: 후보가 일부만 있을 때의 안전 코드. 절 선택 대신 쪽 입력만 허용한다.
CANDIDATES_INCOMPLETE = "section_candidates_incomplete"

_CANDIDATE_READ_ERRORS = (V4OpsError, V4PreparationError, ObjectStoreError, OSError, ValueError, KeyError)


def _structure_store(store: Any | None) -> Any:
    if store is not None:
        return store
    return object_store(namespaces=("structure",), read_namespaces=("structure",))


def read_range_candidates(
    session: Session, snapshot: PrespecV4PdfSnapshot | None, *, store: Any | None = None
) -> Mapping[str, Any] | None:
    """스냅샷의 절 후보. 없거나 읽을 수 없으면 ``None``이다.

    후보는 읽기 보조일 뿐이라 읽기 실패가 개요 조회를 막지 않는다. 실패는
    `candidate_status=unavailable`로 나가고 사람은 쪽 범위를 직접 넣는다.
    """

    if not snapshot_has_section_candidates(snapshot):
        return None
    try:
        candidates = read_snapshot_section_candidates(session, _structure_store(store), snapshot)
    except _CANDIDATE_READ_ERRORS:
        return None
    return candidates if isinstance(candidates, Mapping) else None


def _candidate_rows(candidates: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    rows = list(candidates.get("sections") or []) if candidates else []
    return [
        {
            "index": int(row["index"]),
            "title": str(row.get("title") or ""),
            "page": int(row["page"]),
            "char_count": int(row.get("char_count") or 0),
        }
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("index"), int) and isinstance(row.get("page"), int)
    ]


def _range_status(latest: PrespecOverviewRun | None) -> str:
    """범위 확인 칸의 상태. 사람 확정이 있으면 그것이 이긴다."""

    if latest is None:
        return "pending"
    if str(latest.range_source) == "human":
        return "human_confirmed"
    if str(latest.range_source) == "fallback" or str(latest.status) in {
        "needs_human_review", "failed", "cancelled",
    }:
        return "pending"
    return "ready"


def _confirmation_view(runs: Sequence[PrespecOverviewRun]) -> dict[str, Any] | None:
    """가장 최근 사람 확정 기록. `note` 본문은 저장하지 않으므로 항상 ``None``이다."""

    for run in runs:
        if str(run.range_source) == "human" and run.page_start is not None and run.page_end is not None:
            return {
                "page_start": int(run.page_start),
                "page_end": int(run.page_end),
                "actor_name": run.actor_name,
                "note": None,
                "created_at": _iso(run.created_at),
            }
    return None


def range_review_view(
    session: Session,
    notice_id: int,
    runs: Sequence[PrespecOverviewRun],
    *,
    store: Any | None = None,
) -> dict[str, Any] | None:
    """개요 입력 범위 확인 칸. ready 묶음의 동결 스냅샷이 없으면 ``None``이다."""

    document = ready_bundle_document(session, notice_id)
    if document is None:
        return None
    snapshot = latest_snapshot(session, document.id)
    if snapshot is None:
        return None
    candidates = read_range_candidates(session, snapshot, store=store)
    rows = _candidate_rows(candidates)
    if candidates is None:
        candidate_status, warning = "unavailable", CANDIDATES_UNAVAILABLE
    elif bool(candidates.get("candidates_truncated")):
        candidate_status, warning = "partial", CANDIDATES_INCOMPLETE
    else:
        candidate_status, warning = "complete", None
    latest = runs[0] if runs else None
    selected = (
        [int(latest.page_start), int(latest.page_end)]
        if latest is not None and latest.page_start is not None and latest.page_end is not None
        else None
    )
    can_confirm = active_run(session, notice_id) is None
    if can_confirm:
        try:
            safe_snapshot(session, snapshot)
        except V4OpsError:
            can_confirm = False
    run_reasons = _string_list(latest.range_reason_codes) if latest is not None else []
    total = candidates.get("section_count") if candidates else None
    return {
        "target_id": str(latest.id) if latest is not None else None,
        "status": _range_status(latest),
        "document_version_id": str(snapshot.document_version_id),
        "pdf_page_count": int(snapshot.pdf_page_count),
        "mode": str(candidates.get("mode")) if candidates and candidates.get("mode") else None,
        "candidate_status": candidate_status,
        "candidate_count_total": int(total) if isinstance(total, int) else None,
        "candidate_count_returned": len(rows),
        "candidates": rows,
        "selected_pages": selected,
        "warning_codes": [warning] if warning else [],
        "reason_code": run_reasons[0] if run_reasons else warning,
        "can_confirm": can_confirm,
        # 범위 보조 실행은 MVP에 없다. 없는 것을 있는 것처럼 만들지 않는다.
        "assisted": None,
        "confirmation": _confirmation_view(runs),
    }


def _prompt_version(settings: Any | None = None) -> str | None:
    """정책 문서의 `prompt_version`. 정책을 읽을 수 없으면 ``None``이다."""

    try:
        resolved = settings or get_settings()
        return str(load_claims_policy(resolved.prespec_overview_policy_path).document["prompt_version"])
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def overview_envelope(session: Session, notice_id: int, *, store: Any | None = None) -> dict[str, Any]:
    """공고 한 건의 현재 개요와 이력 (`bidops.prespec-overview.v1`)."""

    history = session.scalars(
        select(PrespecOverviewRun)
        .where(PrespecOverviewRun.notice_id == int(notice_id))
        .order_by(PrespecOverviewRun.created_at.desc(), PrespecOverviewRun.id.desc())
    ).all()
    snapshot_ids = {run.snapshot_id for run in history if run.snapshot_id is not None}
    snapshots = {
        row.id: row
        for row in (
            session.scalars(
                select(PrespecV4PdfSnapshot).where(PrespecV4PdfSnapshot.id.in_(snapshot_ids))
            ).all()
            if snapshot_ids
            else []
        )
    }
    prompt_version = _prompt_version()
    rows = [
        run_view(run, snapshot=snapshots.get(run.snapshot_id), prompt_version=prompt_version)
        for run in history
    ]
    return {
        "schema": OVERVIEW_ENVELOPE_SCHEMA,
        "notice_id": int(notice_id),
        "current": rows[0] if rows else None,
        "history": rows,
        "range_review": range_review_view(session, notice_id, history, store=store),
        "verification": verification_view(history[0] if history else None),
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
    활성 run 없음, `overview_eligible`이 연 자격, `ready` 묶음에 제안요청서 문서.
    자격은 effective grade `우선 검토`이고, 플래그가 켜져 있으면 `SW사업대상=Y`
    사전규격도 포함한다(MVP 완화). 부분 유니크 인덱스가 최종 방어이고 여기서는
    사전 조회로 조용히 물러난다.
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
    grades = effective_grades(session, [int(notice_id)])
    if int(notice_id) not in overview_eligible(
        session, [int(notice_id)], settings=settings, grades=grades
    ):
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
    """모델 신원을 확인할 수 없다. 남은 시도가 있으면 다음 poll에 다시 본다.

    `source`는 client가 낸 실패 그대로다(코드와 재시도 분류만 들어 있다).
    worker의 재확인 backoff가 "일시 장애"와 "설정을 고쳐야 낫는 실패"를
    가르는 기준이므로 코드 문자열만 옮기면 그 구분이 사라진다.
    """

    def __init__(self, code: str, source: ModelEndpointError | ModelIdentityError) -> None:
        self.code = code
        self.source = source
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


def _close_exhausted(session: Session, run: PrespecOverviewRun, job: WorkJob, now: datetime) -> None:
    """claim 상한을 다 쓴 queued run 하나를 잡지 않고 닫는다.

    상한을 claim **전에** 보는 이유는 claim이 곧 시도 하나이기 때문이다.
    잡은 뒤에 보면 이미 counter를 올린 상태라 같은 run이 한 바퀴 더 돈다.
    """

    run.status = "failed"
    run.reason_codes = [*_string_list(run.reason_codes), ATTEMPTS_EXHAUSTED_REASON]
    run.completed_at = now
    job.status = "failed"
    job.last_error_code = ATTEMPTS_EXHAUSTED_REASON
    job.completed_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    session.add(AuditEvent(
        actor_kind="system",
        claimed_name=None,
        action=ATTEMPTS_EXHAUSTED_ACTION,
        aggregate_type=OVERVIEW_AGGREGATE_TYPE,
        aggregate_id=str(run.id),
        safe_metadata={
            "run_id": str(run.id),
            "job_id": str(job.id),
            "notice_id": int(run.notice_id),
            "attempt_count": int(job.attempt_count),
            "max_attempts": int(job.max_attempts),
            "reason_code": ATTEMPTS_EXHAUSTED_REASON,
        },
    ))


def _claim_next(session: Session, worker_id: str, clock: Callable[[], datetime]) -> UUID | None:
    """가장 오래된 queued run 하나를 WorkJob lease로 잡는다.

    상한(`work_job.max_attempts`)을 다 쓴 후보는 잡지 않고 닫은 뒤 다음
    후보로 넘어간다. 닫은 만큼 후보가 줄어들므로 이 순회는 끝난다.
    """

    now = clock()
    if session.in_transaction():
        session.commit()
    while True:
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
        if int(job.attempt_count) >= int(job.max_attempts):
            _close_exhausted(session, run, job, now)
            session.commit()
            continue
        job.status = "running"
        job.lease_owner = worker_id
        job.lease_fence = int(job.lease_fence) + 1
        job.lease_expires_at = now + timedelta(seconds=LIMITS["lease_seconds"])
        job.attempt_count = int(job.attempt_count) + 1
        run.status = "running"
        run.started_at = now
        session.commit()
        return run.id


def _release(
    session: Session, run: PrespecOverviewRun, job: WorkJob | None, *, restore_attempt: bool = True
) -> None:
    """claim을 되돌린다. 실행하지 않은 것을 실패로 적지 않는다.

    `restore_attempt`가 참이면 claim이 올린 `attempt_count`도 함께 되돌린다 —
    일을 하지 않고 돌려놓는 것이므로 시도를 쓴 것이 아니다. 모델 신원 확인이
    막혀 돌려놓을 때만 거짓이다. 그 경우는 **시도를 쓴 것**으로 세야 상한이
    의미를 갖고, 세지 않으면 같은 run을 무한히 재점유한다(운영에서 205회).
    """

    run.status = "queued"
    run.started_at = None
    if job is not None:
        job.status = "queued"
        job.lease_owner = None
        job.lease_expires_at = None
        if restore_attempt:
            job.attempt_count = max(int(job.attempt_count) - 1, 0)


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


#: 자동 선택이 이 아래면 개요를 만들 만한 입력이 아니다. 목차 한 쪽이나
#: 표제만 남은 한 쪽을 그대로 동결해 주장 0개로 끝나는 실행을 막는다
#: (2026-09-11 운영 첫 실행: 공고 805가 목차 쪽 한 장으로 선택됐다).
MIN_AUTO_RANGE_PAGES = 2
MIN_AUTO_RANGE_CHARS = 1500


def _fallback_pages(pages: Sequence[Mapping[str, Any]], first: int = 1) -> int:
    """`first` 쪽부터 상한을 넘지 않는 마지막 쪽. 한 쪽도 못 담으면 0이다."""

    total = 0
    last = 0
    for index, page in enumerate(pages, 1):
        if index < first:
            continue
        if index - first + 1 > LIMITS["max_pages"]:
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
    reasons = [code for code in (selection.reason_code,) if code]
    if selection.status == "ready":
        numbers = selection.page_numbers
        chars = sum(len(str(item.get("text") or "")) for item in selection.manifest.get("pages", []))
        if len(numbers) > LIMITS["max_pages"] or chars > LIMITS["max_page_text_chars"]:
            # 상한을 넘은 자동 선택은 통째로 버리지 않는다. 시작 쪽은 맞았으니
            # 상한 안에 드는 마지막 쪽까지만 잘라 쓰고 잘렸다고 남긴다.
            clipped_last = _fallback_pages(pages, numbers[0])
            if clipped_last >= numbers[0]:
                return select_v4_page_span(
                    payload, numbers[0], clipped_last,
                    start_locator=_locator(numbers[0], "page"),
                    end_locator=_locator(clipped_last, "page"),
                ), ["range_clipped_to_limit"]
        elif len(numbers) >= MIN_AUTO_RANGE_PAGES and chars >= MIN_AUTO_RANGE_CHARS:
            return selection, []
        else:
            reasons = ["range_too_small"]
    last = _fallback_pages(pages)
    if last < 1:
        raise _RunFailure("failed", "manifest_invalid")
    fallback = select_v4_page_span(
        payload, 1, last,
        start_locator=_locator(1, "page"),
        end_locator=_locator(last, "page"),
    )
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

    def _record(
        self,
        stage: str,
        raw: bytes | None,
        *,
        prompt_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """원응답 하나를 저장하고 그 호출의 계측값을 ref에 함께 남긴다.

        토큰 수와 지연은 provider가 낸 사실이며 새 판정이 아니다. 실패 호출은
        usage를 받지 못하므로 `null`로 남긴다 — 0으로 적으면 "측정했는데 0"이
        되어 미측정과 섞인다.
        """

        if raw is None:
            return
        if self._store is None:
            self._store = EncryptedModelResponseStore(self.settings)
        try:
            digest = store_raw_model_response(self.session, raw, store=self._store, clock=self.clock)
        except (ObjectStoreError, ValueError, TypeError) as error:
            raise _RunFailure("failed", "response_store_unavailable") from error
        refs = list(self.run.raw_response_refs or [])
        refs.append({
            "stage": stage,
            "sha256": digest,
            "prompt_tokens": int(prompt_tokens) if isinstance(prompt_tokens, int) else None,
            "output_tokens": int(output_tokens) if isinstance(output_tokens, int) else None,
            "latency_ms": int(latency_ms) if isinstance(latency_ms, int) else None,
        })
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
            # 실패 호출은 usage를 내지 않는다. 세 값은 `null`로 남는다.
            self._record(ledger_stage, error.raw_response)
            raise
        raw = bytes(response.raw_response)
        self._record(
            ledger_stage, raw,
            prompt_tokens=getattr(response, "prompt_tokens", None),
            output_tokens=getattr(response, "output_tokens", None),
            latency_ms=getattr(response, "latency_ms", None),
        )
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
        store = object_store(namespaces=("source", "structure"))
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
    # 상한 clip은 자동 선택의 결과를 그대로 줄인 것이므로 `auto`로 남는다.
    if "range_fallback_head" in range_codes:
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
        raise _IdentityUnavailable(
            str(getattr(error, "code", "") or IDENTITY_UNAVAILABLE_REASON), error
        ) from error
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
    # 섹션 배정 쏠림은 경고다. 주장이 한 개도 없을 때만 별도 사유로 닫는다.
    if not checks.checks:
        raise _RunFailure("needs_human_review", "claims_empty")
    if checks.reason_codes:
        raise _RunFailure("needs_human_review", "deterministic_check_failed")
    # 실패한 주장은 결과에서 빼고 나머지로 계속 간다. 통과가 절반 미만이면 그
    # 초안을 개요로 볼 수 없으므로 예전처럼 사람 검토로 보낸다 (2026-09-11).
    full_checks = checks
    subset = drop_failed_claims(draft, checks)
    if not subset.checks.checks or len(subset.checks.checks) * 2 < len(full_checks.checks):
        raise _RunFailure("needs_human_review", "deterministic_check_failed")
    draft, checks = subset.draft, subset.checks
    run.warnings_json = sorted({
        *_string_list(run.warnings_json),
        *(["claims_dropped"] if subset.dropped_claim_ids else []),
        *(["analysis_dropped"] if subset.dropped_analysis_ids else []),
    })

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
    stored = merge_semantic_checks(full_checks, checks) if subset.dropped_claim_ids else checks
    run.checks_json = stored.model_dump(mode="json")
    # 반박·근거부족으로 본 unknown은 그 항목만 빠지고 run은 계속 간다.
    run.warnings_json = sorted({
        *_string_list(run.warnings_json), *stored.warnings,
        *(f"unknown_{row.status}" for row in checks.unknown_checks
          if row.status in {"contradicted", "insufficient"}),
    })
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
        job = session.get(WorkJob, run.work_job_id)
        # 모델이 죽어 있으면 상한까지만 다시 잡고 그 뒤에는 닫는다. 돌려놓기만
        # 하면 대기열이 이 run 하나로 막힌다.
        if job is not None and int(job.attempt_count) >= int(job.max_attempts):
            _log_run_failure(run_id, run.notice_id, error, IDENTITY_UNAVAILABLE_REASON)
            _finish(session, run, "failed", [IDENTITY_UNAVAILABLE_REASON], clock)
            session.commit()
            return OverviewRunResult(
                True, attempt_id=run_id, status="failed",
                reason_code=IDENTITY_UNAVAILABLE_REASON,
                expired_leases=expired, identity_error=error.source,
            )
        _release(session, run, job, restore_attempt=False)
        session.commit()
        return OverviewRunResult(
            False, attempt_id=run_id, status="idle", reason_code=error.code,
            expired_leases=expired, identity_error=error.source,
        )
    except _RunFailure as failure:
        if failure.status == "failed":
            _log_run_failure(run_id, run.notice_id, failure, failure.code)
        _finish(session, run, failure.status, [failure.code], clock)
        session.commit()
        return OverviewRunResult(True, attempt_id=run_id, status=failure.status, reason_code=failure.code, expired_leases=expired)
    except Exception as error:  # noqa: BLE001 - 코드만 남기고 본문은 버린다
        session.rollback()
        run = session.get(PrespecOverviewRun, run_id)
        code = str(getattr(error, "code", "") or "runner_failed")
        code = code if code.replace("_", "").isalnum() else "runner_failed"
        _log_run_failure(run_id, run.notice_id if run is not None else None, error, code)
        if run is not None:
            _finish(session, run, "failed", [code], clock)
            session.commit()
        return OverviewRunResult(True, attempt_id=run_id, status="failed", reason_code="runner_failed", expired_leases=expired)
    _finish(session, run, "completed", [], clock)
    session.commit()
    from .auto_preparation import maybe_auto_start_deep_review

    maybe_auto_start_deep_review(session, int(run.notice_id))
    return OverviewRunResult(True, attempt_id=run_id, status="completed", expired_leases=expired)


# --- 사람 요청 경계 (REST와 운영 CLI가 부르는 것) ----------------------------


def close_run(
    session: Session,
    run_id: UUID,
    *,
    actor_name: str,
    reason: str = OPERATOR_CLOSE_REASON,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """운영자가 활성 run 하나를 닫는다 (`close-overview-run`).

    `queued`는 `cancelled`, `running`은 `failed`다 — 실행 중이던 것을 취소로
    적으면 반쪽 결과가 남았을 수 있다는 사실이 사라진다. 이미 종결된 run은
    `run_not_active`로 거절하고 아무것도 바꾸지 않는다(종결은 불변이다).
    커밋은 호출자가 한다.
    """

    if not isinstance(actor_name, str) or not actor_name.strip():
        raise OverviewRequestError("actor_name_invalid")
    now = (clock or _now)()
    run = session.get(PrespecOverviewRun, run_id)
    if run is None or run.status not in ACTIVE_STATUSES:
        raise OverviewRequestError("run_not_active")
    status = "cancelled" if run.status == "queued" else "failed"
    run.status = status
    run.reason_codes = [*_string_list(run.reason_codes), reason]
    run.completed_at = now
    job = session.get(WorkJob, run.work_job_id)
    if job is not None and job.status in ACTIVE_STATUSES:
        job.status = status
        job.last_error_code = reason
        job.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
    session.add(AuditEvent(
        actor_kind="human",
        claimed_name=actor_name.strip(),
        action=OPERATOR_CLOSE_ACTION,
        aggregate_type=OVERVIEW_AGGREGATE_TYPE,
        aggregate_id=str(run.id),
        safe_metadata={
            "run_id": str(run.id),
            "job_id": str(run.work_job_id),
            "notice_id": int(run.notice_id),
            "status": status,
            "reason_code": reason,
        },
    ))
    return {
        "status": status,
        "run_id": str(run.id),
        "notice_id": int(run.notice_id),
        "reason": reason,
    }


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
    page_start: int | None = None,
    page_end: int | None = None,
    candidate_indices: Sequence[int] | None = None,
    actor_name: str,
    note: str | None = None,
    settings: Any | None = None,
    store: Any | None = None,
) -> PrespecOverviewRun:
    """사람이 확정한 쪽 범위로 개요 run 하나를 넣고 감사 이벤트를 남긴다.

    **자동 enqueue 플래그와 무관하다.** 사람이 명시적으로 고른 범위는 언제나 한
    건을 실행할 수 있어야 한다. 범위 확정은 실행 승인이 아니라 개요 run의 입력
    범위를 정하는 것이며 담당자 이름은 감사 표식이다.
    """

    indices: tuple[int, int] | None = None
    if candidate_indices is not None:
        values = [int(value) for value in candidate_indices]
        if len(values) != 2 or values[0] < 0 or values[1] < values[0]:
            raise OverviewRequestError("range_invalid")
        indices = (values[0], values[1])
    elif page_start is None or page_end is None or page_end < page_start:
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
    if indices is not None:
        # 절 후보로 고른 범위는 여기서 쪽으로 바꾼다. 화면이 쪽을 계산하지
        # 않는다 — 끝 쪽 규칙(다음 절 시작 쪽)은 서버 한 곳에만 둔다.
        candidates = read_range_candidates(session, snapshot, store=store)
        if candidates is None or not (candidates.get("sections") or []):
            raise OverviewRequestError("candidate_range_unavailable")
        try:
            page_start, page_end = _pages_from_indices(
                candidates, indices[0], indices[1], int(snapshot.pdf_page_count)
            )
        except V4OpsError as error:
            code = str(getattr(error, "code", "") or "range_invalid")
            raise OverviewRequestError(
                code if code == "candidate_range_incomplete" else "range_invalid"
            ) from error
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
                "candidate_indices": list(indices) if indices is not None else None,
                "has_note": note is not None,
            },
        )
    )
    return run


def _snapshot_pdf_bytes(
    session: Session, snapshot: PrespecV4PdfSnapshot, store: Any | None = None
) -> bytes:
    """동결 스냅샷의 PDF bytes. 저장된 version·hash를 다시 확인하고 읽는다."""

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


def snapshot_pdf(session: Session, notice_id: int, *, store: Any | None = None) -> bytes:
    """공고의 현재 RFP 문서에서 가장 최근 동결 스냅샷 PDF bytes.

    run이 아직 없어도 사람이 쪽 범위를 고르려면 같은 PDF를 봐야 한다. 경계는
    run PDF와 같다 — 문서·원본이 지금 current·safe가 아니면 열지 않는다.
    """

    document = ready_bundle_document(session, notice_id)
    if document is None:
        raise OverviewRequestError("not_found")
    snapshot = latest_snapshot(session, document.id)
    if snapshot is None:
        raise OverviewRequestError("not_found")
    try:
        safe_snapshot(session, snapshot)
    except V4OpsError as error:
        raise OverviewRequestError("document_not_current_safe") from error
    return _snapshot_pdf_bytes(session, snapshot, store)


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
    return _snapshot_pdf_bytes(session, snapshot, store)


__all__ = [
    "ACTIVE_STATUSES",
    "CANDIDATES_INCOMPLETE",
    "CANDIDATES_UNAVAILABLE",
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
    "range_review_view",
    "read_range_candidates",
    "ready_bundle_document",
    "run_once",
    "run_snapshot_pdf",
    "run_view",
    "snapshot_pdf",
    "verification_view",
]
