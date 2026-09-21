"""`우선 검토` 사전규격의 자동 문서 준비 (명세 §6.2).

취득 행이 모두 종결되고 safe·구조 준비 문서가 하나 이상 있으면, 그 문서 집합에
대한 묶음을 시스템이 만들고 확정한다. 사람 경로와 **같은 함수**(`create_bundle`
·`confirm`)를 부르므로 확정 fence(최신 document version·clean scan·불변 structure
snapshot·blocking issue)는 그대로다. 조건이 깨지면 확정하지 않고 `draft`로 둔다.

세 가지 불변식이 이 모듈의 성격을 정한다.

* **아무것도 취소하지 않는다.** 등급이 내려가도 이미 만들어진 fetch 행·문서·묶음
  ·심층 검토는 그대로 있다. 자동 준비는 새로 만들기만 한다.
* **재수집은 새 revision이다.** current 문서 집합(첨부별 current document의
  content sha256 집합)이 마지막 확정 묶음과 같으면 아무것도 하지 않는다. 다르면
  새 revision을 만들어 확정하고 이전 묶음·검토·의견은 그대로 남는다.
* **호출자의 transaction을 커밋하지 않는다.** `create_bundle`·`confirm`은 스스로
  commit하므로, 이미 transaction을 연 호출자(회차 적재 hook, 리뷰 저장 hook)
  안에서는 그 연결에 savepoint를 잡은 별도 session으로 돈다. 그 session의 commit은
  savepoint를 놓을 뿐 바깥 transaction을 끝내지 않는다.

SW사업대상=Y 자동 심층 검토 시작(명세 §6.4)도 이 모듈이 갖는다. 조건 검사는
`maybe_auto_start_deep_review`이고, 생성은 사람 경로와 **같은 함수**
(`DeepReviewService.create_review`)를 시스템 actor로 부른다. 자동 시작은
사업기회 추적 상태를 바꾸지 않으며 최종 입찰 Go/No-Go도 아니다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError
from ...core.models import AuditEvent
from ...lifecycle.models import Attachment, Notice
from ..models import (
    AttachmentFetch,
    ContentObject,
    DeepReview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
)
from ..schemas.document_bundles import ConfirmRequest
from .effective_grade import (
    EffectiveGrade,
    effective_grades,
    overview_eligible,
    sw_business_object as _sw_business_object,
)
from .input_versions import InputVersionError, active_version_ids, resolve_active_versions
from ...core.config import get_settings

logger = logging.getLogger(__name__)

#: 시스템 actor의 표식 (명세 §6.2). 인증이 아니라 감사 표식이다.
AUTO_ACTOR_NAME = "auto-preparation"
AUTO_ACTOR_KIND = "system"

#: 자동 준비를 연 사유. 감사 이벤트의 `trigger`로 남는다.
AUTO_TRIGGER = "priority_grade"

#: 자동 확정만 남기는 감사 이벤트 (명세 §8).
AUTO_CONFIRM_ACTION = "document_bundle.auto_confirm"

#: 취득 행의 종결 상태 (명세 §6.2 "자동 묶음").
TERMINAL_FETCH_STATUSES = frozenset({"완료", "차단", "실패"})

#: 종결됐지만 문서를 남기지 못한 취득 상태. 재시도가 남아 있지 않다.
_FAILED_FETCH_STATUSES = frozenset({"차단", "실패"})

#: 개요 run이 아직 돌고 있다고 보는 상태.
_OVERVIEW_RUNNING_STATUSES = frozenset({"queued", "running"})
#: 개요 run이 끝났다고 보는 상태. 자동 시작 여부와 무관하게 사람이 누를 수 있다.
_OVERVIEW_SETTLED_STATUSES = frozenset(
    {"completed", "needs_human_review", "failed", "cancelled"}
)

# --- `auto_preparation_reason` 안전 코드 (§8: nullable 안전 코드) -------------
REASON_GRADE_NOT_PRIORITY = "grade_not_priority"
REASON_AWAITING_FETCH = "awaiting_fetch"
REASON_NO_READY_DOCUMENT = "no_ready_document"
#: 취득 행이 모두 종결됐는데 그중 `차단`·`실패`가 있고 준비된 문서가 하나도
#: 없다. "기다리는 중"이 아니라 사람이 손대야 끝나는 상태다.
REASON_ATTACHMENTS_FAILED = "attachments_failed"
REASON_BLOCKING_ISSUES = "bundle_has_blocking_issues"
REASON_BUNDLE_UNCHANGED = "bundle_unchanged"
REASON_HUMAN_DRAFT = "human_bundle_draft"

# --- SW사업대상=Y 자동 심층 검토 시작 (명세 §6.4) ----------------------------

#: 자동 시작이 남기는 감사 이벤트 (명세 §8). 실제 기록은 사람 경로와 같은
#: `DeepReviewService.create_review`가 하고, safe_metadata 모양도 같다 —
#: `quality_status`가 이 action에서도 계산돼야 하기 때문이다.
AUTO_DEEP_REVIEW_ACTION = "deep_review.auto_create"

#: 자동 시작 사유 코드. 안전한 코드만 남기고 예외 본문·경로·비밀값은 넣지 않는다.
REASON_NOT_SW_BUSINESS = "not_sw_business"
REASON_BUNDLE_NOT_AUTO_READY = "bundle_not_auto_ready"
REASON_OVERVIEW_NOT_COMPLETED = "overview_not_completed"
#: 묶음이 ready가 된 뒤 개요 run을 넣지 못했다는 비차단 경고 (§6.3).
WARNING_OVERVIEW_ENQUEUE_FAILED = "overview_enqueue_failed"
REASON_DEEP_REVIEW_EXISTS = "deep_review_exists"
#: active profile/policy 설정이 없거나 §6.5 조건이 맞지 않는다. 생성 경로가
#: 내는 code와 같은 값이라 화면이 두 경로를 같은 이름으로 설명한다.
REASON_SERVICE_UNAVAILABLE = "service_unavailable"
REASON_PROCESSING_FAILED = "processing_failed"


@dataclass(frozen=True)
class AutoPreparationOutcome:
    """공고 한 건에 대해 자동 준비가 실제로 한 일."""

    notice_id: int
    bundle_id: UUID | None = None
    created: bool = False
    confirmed: bool = False
    reason: str | None = None
    #: 준비 자체는 끝났지만 파생 작업이 실패했다는 비차단 표시. 지금은 개요
    #: enqueue 실패(`overview_enqueue_failed`) 한 가지뿐이며 확정을 되돌리지
    #: 않는다.
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoDeepReviewOutcome:
    """공고 한 건에 대해 §6.4의 자동 시작이 실제로 한 일."""

    notice_id: int
    bundle_id: UUID | None = None
    deep_review_id: UUID | None = None
    created: bool = False
    reason: str | None = None


@contextmanager
def _work_session(session: Session):
    """묶음 생성·확정을 돌릴 session.

    호출자가 이미 transaction을 열었으면 그 **연결**에 savepoint를 잡은 별도
    session을 준다. `create_bundle`·`confirm`의 commit은 savepoint를 놓을 뿐이라
    회차 적재나 리뷰 저장을 앞당겨 커밋하지 않는다. transaction이 없으면
    (취득 worker처럼 자기 session을 소유한 호출자) 그 session을 그대로 쓴다.
    """

    if session.in_transaction():
        # 바깥 session의 미flush 변경을 먼저 연결에 내보낸다. 두 session이 같은
        # transaction을 공유하므로 flush한 행은 곧바로 보인다.
        session.flush()
        nested = Session(
            bind=session.connection(), join_transaction_mode="create_savepoint"
        )
        try:
            yield nested
        finally:
            nested.close()
    else:
        yield session


def _active_attachment_ids(session: Session, notice_id: int) -> list[int]:
    return [
        int(value)
        for value in session.scalars(
            select(Attachment.id)
            .where(Attachment.notice_id == notice_id, Attachment.retired_at.is_(None))
            .order_by(Attachment.id.asc())
        ).all()
    ]


def _current_documents(session: Session, attachment_ids: Sequence[int]) -> list[DocumentVersion]:
    if not attachment_ids:
        return []
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.attachment_id.in_(list(attachment_ids)),
                DocumentVersion.is_current.is_(True),
            )
            .order_by(DocumentVersion.attachment_id.asc(), DocumentVersion.id.asc())
        ).all()
    )


def document_fingerprint(session: Session, documents: Iterable[DocumentVersion]) -> tuple[str, ...]:
    """첨부별 current document의 content sha256 집합 (명세 §6.2 재수집 규칙).

    같은 bytes가 다시 들어와도 값이 같으므로 재적재가 새 묶음을 만들지 않는다.
    순서는 의미가 없으므로 정렬해서 비교한다.
    """

    ids = [document.content_object_id for document in documents]
    if not ids:
        return ()
    rows = session.execute(
        select(ContentObject.id, ContentObject.sha256).where(ContentObject.id.in_(ids))
    ).all()
    by_id = {content_id: sha for content_id, sha in rows}
    return tuple(sorted(by_id[value] for value in ids if value in by_id))


def _bundle_fingerprint(session: Session, bundle_id: UUID) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(value)
            for value in session.scalars(
                select(DocumentBundleItem.content_sha256).where(
                    DocumentBundleItem.bundle_id == bundle_id
                )
            ).all()
        )
    )


def _ready_documents(session: Session, documents: Sequence[DocumentVersion]) -> list[DocumentVersion]:
    """safe이고 구조가 준비된 current document만 남긴다."""

    safe = [document for document in documents if document.safety_status == "safe"]
    if not safe:
        return []
    ready_ids = {
        value
        for value in session.scalars(
            select(DocumentStructure.document_version_id).where(
                DocumentStructure.document_version_id.in_([row.id for row in safe]),
                DocumentStructure.validation_status == "ready",
            )
        ).all()
    }
    return [document for document in safe if document.id in ready_ids]


def _latest_bundles(session: Session, notice_id: int) -> list[DocumentBundle]:
    return list(
        session.scalars(
            select(DocumentBundle)
            .where(DocumentBundle.notice_id == notice_id)
            .order_by(DocumentBundle.revision.desc())
        ).all()
    )


def _trigger_metadata(run_id: str | None, review_id: int | None) -> dict[str, Any]:
    """감사 metadata. 안전한 식별자와 사유 코드만 담는다 (§10)."""

    return {
        "trigger": AUTO_TRIGGER,
        "trigger_run_id": run_id,
        "trigger_review_id": review_id,
    }


def _prepare_one(
    session: Session,
    notice_id: int,
    grade: EffectiveGrade | None,
    *,
    service: Any,
    run_id: str | None,
    review_id: int | None,
    deep_review_service: Any = None,
) -> AutoPreparationOutcome:
    """이미 자격이 확인된 공고 하나를 실제로 준비한다.

    사전규격 여부와 자격은 호출부가 **batch로 한 번에** 걸러 두었다. 회차 하나가
    사전규격 약 2,000건이므로 여기서 공고당 다시 묻지 않는다.

    `grade`는 ``None``일 수 있다. MVP 완화(`overview_eligible`)로 판정도 정정도
    없는 `SW사업대상=Y` 사전규격이 자격을 얻기 때문이며, 그때 촉발 식별자는
    등급에서 오지 않고 호출부가 준 값만 남는다 — 없는 것을 채우지 않는다.
    """

    # 촉발 식별자 (명세 §6.2). 호출부가 알려 준 회차·리뷰가 있으면 그것이고,
    # 없으면 **이 등급을 만든 것**이 촉발이다 — 등급 변경 hook은 확장점 서명상
    # 식별자를 받지 않으므로 그 경우 리뷰의 회차·리뷰 id가 남는다. 둘 다 없으면
    # `None`으로 남기고 다른 값으로 채우지 않는다.
    trigger = _trigger_metadata(
        run_id if run_id is not None else (grade.run_id if grade is not None else None),
        review_id if review_id is not None else (grade.review_id if grade is not None else None),
    )

    attachment_ids = _active_attachment_ids(session, notice_id)
    if attachment_ids:
        statuses = [
            str(value)
            for value in session.scalars(
                select(AttachmentFetch.status).where(
                    AttachmentFetch.attachment_id.in_(attachment_ids)
                )
            ).all()
        ]
        if any(status not in TERMINAL_FETCH_STATUSES for status in statuses):
            return AutoPreparationOutcome(notice_id=notice_id, reason=REASON_AWAITING_FETCH)

    documents = _current_documents(session, attachment_ids)
    if not _ready_documents(session, documents):
        return AutoPreparationOutcome(notice_id=notice_id, reason=REASON_NO_READY_DOCUMENT)

    fingerprint = document_fingerprint(session, documents)
    bundles = _latest_bundles(session, notice_id)
    confirmed = next(
        (bundle for bundle in bundles if bundle.status in {"ready", "superseded"}), None
    )
    if confirmed is not None and _bundle_fingerprint(session, confirmed.id) == fingerprint:
        # 같은 사전규격이 뒤 회차에서 다시 `우선 검토`여도 문서 집합이 같으면
        # 새 묶음은 만들지 않는다 (명세 §6.2 재수집 규칙). 다만 §6.4의 자동
        # 시작은 이 촉발(회차 적재·등급 변경)에서 다시 판단한다 — 지난번
        # fail closed의 재시도가 일어나는 자리가 여기다.
        #
        # 재판단 전에 읽기만 한 savepoint를 놓는다. 확정 경로가 `confirm`의
        # commit 뒤에 자동 시작을 부르는 것과 같은 이유다 — 이 함수가 끝나며
        # 작업 session이 닫힐 때 자동 시작이 만든 것까지 되돌아가면 안 된다.
        session.commit()
        warnings = _enqueue_overview(session, notice_id)
        maybe_auto_start_deep_review(session, notice_id, service=deep_review_service)
        return AutoPreparationOutcome(
            notice_id=notice_id, bundle_id=confirmed.id, reason=REASON_BUNDLE_UNCHANGED,
            warnings=warnings,
        )

    latest = bundles[0] if bundles else None
    created = False
    if latest is not None and latest.status == "draft":
        if latest.created_by_name != AUTO_ACTOR_NAME:
            # 사람이 편집 중인 draft는 시스템이 확정하지 않는다 (명세 §6.2:
            # 차단된 묶음은 "사람이 ... 확정한다").
            return AutoPreparationOutcome(
                notice_id=notice_id, bundle_id=latest.id, reason=REASON_HUMAN_DRAFT
            )
        bundle_id, bundle_version = latest.id, latest.version
    else:
        try:
            view = service.create_bundle(
                session,
                notice_id,
                AUTO_ACTOR_NAME,
                actor_kind=AUTO_ACTOR_KIND,
                trigger_metadata=trigger,
            )
        except BundleServiceError as error:
            return AutoPreparationOutcome(notice_id=notice_id, reason=error.code)
        bundle_id, bundle_version = view.id, view.version
        created = True

    # 확정 범위는 "확인 시점의 모든 current document"다. 자동 경로도 사람 경로와
    # 같은 요구를 그대로 통과해야 하므로 safe·구조 준비 여부로 거르지 않는다.
    current = _current_documents(session, _active_attachment_ids(session, notice_id))
    request = ConfirmRequest(
        request_id=uuid4(),
        version=bundle_version,
        confirmed_documents=[
            {"document_version_id": document.id, "version": document.version}
            for document in current
        ],
    )
    try:
        view = service.confirm(
            session,
            bundle_id,
            request,
            AUTO_ACTOR_NAME,
            actor_kind=AUTO_ACTOR_KIND,
            trigger_metadata=trigger,
        )
    except BundleServiceError as error:
        # 확정 fence가 막으면 묶음은 `draft`로 남고 blocking issue가 보인다.
        # 사람이 첨부를 제외하거나 수동 업로드한 뒤 확정한다 (명세 §6.2).
        return AutoPreparationOutcome(
            notice_id=notice_id, bundle_id=bundle_id, created=created, reason=error.code
        )

    session.add(
        AuditEvent(
            actor_kind=AUTO_ACTOR_KIND,
            claimed_name=AUTO_ACTOR_NAME,
            action=AUTO_CONFIRM_ACTION,
            aggregate_type="document_bundle",
            aggregate_id=str(view.id),
            safe_metadata={
                "notice_id": notice_id,
                "revision": view.revision,
                "version": view.version,
                "document_count": len(view.documents),
                **trigger,
            },
        )
    )
    session.commit()
    # 묶음이 방금 `ready`가 됐다. 개요 run을 넣고, 개요가 이미 완료돼 있으면
    # 여기서 심층 검토가 시작된다 (명세 §6.3·§6.4). 실패는 안전한 코드로만
    # 남고 위의 확정을 되돌리지 않는다.
    warnings = _enqueue_overview(session, notice_id)
    maybe_auto_start_deep_review(session, notice_id, service=deep_review_service)
    return AutoPreparationOutcome(
        notice_id=notice_id, bundle_id=view.id, created=created, confirmed=True,
        warnings=warnings,
    )


# --- SW사업대상=Y 자동 심층 검토 시작 (명세 §6.4) ----------------------------


def _enqueue_overview(session: Session, notice_id: int) -> tuple[str, ...]:
    """묶음이 `ready`가 된 자리에서 개요 run을 넣는다 (§6.3).

    플래그가 꺼져 있거나 조건이 안 맞으면 ``None``이 돌아오며 그것은 실패가
    아니다. 실패는 안전한 경고 코드 하나로만 남고 방금 끝난 확정을 되돌리지
    않는다 — 자동 준비는 개요보다 앞선 단계이기 때문이다.
    """

    from .overview_runs import enqueue_overview_run

    try:
        enqueue_overview_run(session, notice_id)
        session.commit()
    except Exception:
        session.rollback()
        return (WARNING_OVERVIEW_ENQUEUE_FAILED,)
    return ()


def auto_start_reason(
    *,
    is_sw_business: bool,
    ready_bundle_auto_confirmed: bool,
    overview_status: str | None,
    active_versions_available: bool,
    company_fit_reason: str | None = None,
) -> str | None:
    """§6.4의 자동 시작을 막은 사유 코드. ``None``이면 막은 것이 없다.

    **이 순서가 규칙 자체다.** 쓰기 경로(`_auto_start_scope`)와 읽기 경로
    (`auto_preparation_fields`)가 같은 함수를 부르므로 화면이 말하는 사유와
    실제로 시작하지 않은 이유가 갈리지 않는다.
    """

    if not is_sw_business:
        # SW=N은 언제나 사람 클릭이다.
        return REASON_NOT_SW_BUSINESS
    if not ready_bundle_auto_confirmed:
        # "자동 확정된 묶음이 `ready`"가 조건이다. 사람이 확정한 묶음은 사람이
        # 심층 검토도 누른다.
        return REASON_BUNDLE_NOT_AUTO_READY
    if overview_status != "completed":
        # 대기·실행·사람 검토·실패·취소, 그리고 run이 아예 없는 경우까지
        # 모두 자동 시작하지 않는다.
        return REASON_OVERVIEW_NOT_COMPLETED
    if not active_versions_available:
        # active profile/policy 설정이 없거나 §6.5 조건이 맞지 않는다.
        return REASON_SERVICE_UNAVAILABLE
    if company_fit_reason is not None:
        return company_fit_reason
    return None


def _auto_start_scope(
    session: Session,
    notice_id: int,
    *,
    require_company_fit: bool = True,
    runs: Mapping[int, Any] | None = None,
) -> tuple[UUID | None, str | None]:
    """§6.4의 조건을 검사해 (묶음 id, 사유 코드)를 돌려준다.

    사유가 ``None``이면 자동 시작해도 되는 상태다. 조건이 하나라도 어긋나면
    사람 클릭으로 남는다. 앞 조건이 이미 막았으면 뒤 조건은 **조회하지 않고**
    통과 값으로 둔다 — 판단은 `auto_start_reason`이 순서대로 하므로 결과가
    같고, SW=N 사전규격 한 건에 조회 하나만 쓴다.

    active profile/policy는 여기서 보지 않는다. 그 fail closed는 생성 직전에
    보고, 읽기 경로는 `auto_preparation_fields`가 따로 판단한다.
    """

    notice = session.get(Notice, notice_id)
    if notice is None or notice.source_type != "pre_spec":
        # 사전규격이 아니면 이 규칙의 대상이 아니다. 사유도 남기지 않는다.
        return None, None

    is_sw_business = _sw_business_object(notice.qualification_flags_json)
    bundle = (
        session.scalars(
            select(DocumentBundle)
            .where(DocumentBundle.notice_id == notice_id, DocumentBundle.status == "ready")
            .order_by(DocumentBundle.revision.desc())
            .limit(1)
        ).first()
        if is_sw_business
        else None
    )
    ready_bundle_auto_confirmed = (
        bundle is not None and bundle.confirmed_by_name == AUTO_ACTOR_NAME
    )
    from .company_fit import gate_reasons
    from .overview_runs import automation_overview_status, current_runs

    run_map = (
        dict(runs)
        if runs is not None
        else (current_runs(session, [notice_id]) if ready_bundle_auto_confirmed else {notice_id: None})
    )
    overview_status = automation_overview_status(run_map.get(notice_id))
    fit_reason = (
        gate_reasons(session, [notice_id], runs=run_map)[notice_id]
        if require_company_fit
        else None
    )
    reason = auto_start_reason(
        is_sw_business=is_sw_business,
        ready_bundle_auto_confirmed=ready_bundle_auto_confirmed,
        overview_status=overview_status,
        # active 설정은 이 함수의 판단 대상이 아니다.
        active_versions_available=True,
        company_fit_reason=fit_reason,
    )
    return (bundle.id if bundle is not None else None), reason


def _auto_request_id(
    notice_id: int, bundle_id: UUID, profile_id: UUID, policy_id: UUID
) -> UUID:
    """불변 입력 묶음에서 유도한 결정적 request id.

    같은 (공고, 묶음, active profile, active policy)를 다시 촉발해도 값이 같으므로
    생성 경로의 idempotency 검사가 재생으로 처리한다. 무작위 값을 쓰면 같은
    입력에 다른 요청이 쌓인다.
    """

    return uuid5(
        NAMESPACE_URL,
        f"bidops.deep-review.auto-create:{notice_id}:{bundle_id}:{profile_id}:{policy_id}",
    )


def maybe_auto_start_deep_review(
    session: Session,
    notice_id: int,
    *,
    service: Any = None,
) -> AutoDeepReviewOutcome:
    """§6.4의 조건이 모두 성립하면 심층 검토를 시스템 actor로 만든다.

    **아무것도 되돌리지 않는다.** 촉발한 개요 완료나 묶음 확정은 이 함수의
    성패와 무관하게 그대로 남는다 — 호출자가 transaction을 열어 두었으면
    savepoint session에서 돌기 때문이다.

    **추적 상태를 바꾸지 않는다.** 사업기회는 `미선택` 그대로이고, 자동 시작은
    적합성 등급·참여 준비 상태·추적 선택·최종 Go/No-Go 중 어느 것도 대신하지
    않는다.

    실패는 예외로 오르지 않고 안전한 사유 코드로만 남는다. active profile/policy
    설정이 없거나 §6.5 조건이 맞지 않으면 fail closed하고, 재시도는 다음 촉발
    시점(회차 적재·등급 변경·개요 완료)에만 한다.
    """

    notice_id = int(notice_id)
    try:
        with _work_session(session) as work:
            from ...lifecycle import lock_notice
            lock_notice(work, notice_id)
            bundle_id, reason = _auto_start_scope(work, notice_id, require_company_fit=False)
            if reason is not None or bundle_id is None:
                return AutoDeepReviewOutcome(
                    notice_id=notice_id, bundle_id=bundle_id, reason=reason
                )

            try:
                profile_id, policy_id = active_version_ids()
            except InputVersionError as error:
                # active ID가 없으면 만들지 않는다. 사유는 안정 code뿐이다.
                return AutoDeepReviewOutcome(
                    notice_id=notice_id, bundle_id=bundle_id, reason=error.code
                )

            existing = work.scalar(
                select(DeepReview.id)
                .where(
                    DeepReview.notice_id == notice_id,
                    DeepReview.bundle_id == bundle_id,
                    DeepReview.profile_version_id == profile_id,
                    DeepReview.policy_version_id == policy_id,
                )
                .limit(1)
            )
            if existing is not None:
                # 같은 불변 입력에는 두 번 만들지 않는다 (명세 §6.4).
                return AutoDeepReviewOutcome(
                    notice_id=notice_id,
                    bundle_id=bundle_id,
                    deep_review_id=existing,
                    reason=REASON_DEEP_REVIEW_EXISTS,
                )

            from .company_fit import gate_reasons
            fit_reason = gate_reasons(work, [notice_id])[notice_id]
            if fit_reason is not None:
                return AutoDeepReviewOutcome(notice_id=notice_id, bundle_id=bundle_id, reason=fit_reason)

            if service is None:
                # 지연 import: 모듈 최상위에서 들면 서비스와 서로를 부르는
                # 방향이 겹친다. 실제로 만들 일이 있을 때만 만든다.
                from .deep_reviews import DeepReviewService

                service = DeepReviewService()

            try:
                response = service.create_review(
                    work,
                    notice_id,
                    bundle_id,
                    AUTO_ACTOR_NAME,
                    _auto_request_id(notice_id, bundle_id, profile_id, policy_id),
                    actor_kind=AUTO_ACTOR_KIND,
                )
            except Exception as error:
                # 예외 본문·경로는 버린다. 서비스가 붙인 안정 code만 남긴다.
                work.rollback()
                code = getattr(error, "code", None)
                return AutoDeepReviewOutcome(
                    notice_id=notice_id,
                    bundle_id=bundle_id,
                    reason=code if isinstance(code, str) and code else REASON_PROCESSING_FAILED,
                )

            created_id = None
            if isinstance(response, Mapping):
                try:
                    created_id = UUID(str(response.get("id")))
                except (TypeError, ValueError):
                    created_id = None
            return AutoDeepReviewOutcome(
                notice_id=notice_id,
                bundle_id=bundle_id,
                deep_review_id=created_id,
                created=True,
            )
    except Exception:
        # savepoint session을 세우지 못하는 경우까지 포함해 자동 시작의 실패가
        # 촉발한 쪽으로 오르지 않게 한다.
        return AutoDeepReviewOutcome(notice_id=notice_id, reason=REASON_PROCESSING_FAILED)


def maybe_auto_prepare(
    session: Session,
    notice_ids: Sequence[int],
    *,
    run_id: str | None = None,
    review_id: int | None = None,
    root: Path | None = None,
    service: Any = None,
    deep_review_service: Any = None,
) -> list[AutoPreparationOutcome]:
    """대상 공고마다 자동 묶음 생성·확정 조건을 검사하고 만족하면 실행한다.

    **선별과 등급은 batch로 한 번에 푼다.** 회차 적재 hook은 그 회차의 사전규격
    전부(관측 규모로 3일 약 1,200건, 1주 약 2,000건)를 한 번에 넘긴다. 공고당
    등급을 묻거나 공고당 savepoint를 열면 회차 적재 transaction 하나에 수천 번의
    왕복과 수천 개의 하위 transaction이 쌓인다 — PostgreSQL은 한 transaction의
    subtransaction이 대략 64개를 넘어서면 눈에 띄게 나빠진다. 그래서 실제로 할 일이
    있는 공고(사전규격이고 `overview_eligible`이 연 자격)가 하나도 없으면 작업
    session 자체를 열지 않는다. 그 경우 비용은 상수 회 조회뿐이다.

    한 공고의 실패가 다른 공고를 막지 않는다. 어떤 실패도 호출자에게 예외로
    오르지 않으며 사유는 안전 코드로만 남는다 — 자동 준비는 파생 작업이고 그
    실패가 회차 적재나 리뷰 저장을 무효로 만들지 않는다(§6.2).
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return []

    outcomes: dict[int, AutoPreparationOutcome] = {}
    try:
        pre_spec_ids = [
            int(value)
            for value in session.scalars(
                select(Notice.id).where(Notice.id.in_(ids), Notice.source_type == "pre_spec")
            ).all()
        ]
        grades = effective_grades(session, pre_spec_ids) if pre_spec_ids else {}
        # 자격은 등급 하나가 아니다. 개요 플래그가 켜져 있으면 `SW사업대상=Y`
        # 사전규격도 자격을 얻는다 (MVP 완화). 둘 다 아니면 사유는 그대로
        # `grade_not_priority`다.
        eligible = (
            overview_eligible(session, pre_spec_ids, grades=grades)
            if pre_spec_ids
            else frozenset()
        )
    except Exception:
        # 등급을 아예 풀지 못하면(선별 모듈 부재 등) 자동 준비는 이번에 아무것도
        # 하지 않는다. 예외는 호출자에게 오르지 않는다.
        return [
            AutoPreparationOutcome(notice_id=notice_id, reason="processing_failed")
            for notice_id in ids
        ]

    pre_spec = set(pre_spec_ids)
    candidates: list[tuple[int, EffectiveGrade | None]] = []
    for notice_id in ids:
        if notice_id not in pre_spec:
            outcomes[notice_id] = AutoPreparationOutcome(notice_id=notice_id)
            continue
        if notice_id not in eligible:
            outcomes[notice_id] = AutoPreparationOutcome(
                notice_id=notice_id, reason=REASON_GRADE_NOT_PRIORITY
            )
            continue
        candidates.append((notice_id, grades.get(notice_id)))

    if candidates:
        if service is None:
            # 지연 import: `document_bundles`가 이 모듈을 부르는 방향과 겹치지 않게
            # 모듈 최상위가 아니라 여기서 든다. 할 일이 있을 때만 만든다.
            from .document_bundles import DocumentBundleService

            service = DocumentBundleService(root=root)
        try:
            with _work_session(session) as work:
                for notice_id, grade in candidates:
                    try:
                        outcomes[notice_id] = _prepare_one(
                            work,
                            notice_id,
                            grade,
                            service=service,
                            run_id=run_id,
                            review_id=review_id,
                            deep_review_service=deep_review_service,
                        )
                    except Exception as error:
                        # 예외 본문은 여기서 버린다. 다음 촉발에서 다시 시도된다.
                        # 다만 아무 흔적도 없으면 운영에서 `processing_failed`의
                        # 원인을 찾을 수 없으므로, **안전한 식별자만** 남긴다 —
                        # 예외 클래스명, 서비스가 붙인 안정 code, DB sqlstate다.
                        # 메시지 본문·SQL·경로·원문은 남기지 않는다.
                        work.rollback()
                        logger.warning(
                            "auto preparation failed notice_id=%s error=%s code=%s sqlstate=%s",
                            notice_id,
                            type(error).__name__,
                            getattr(error, "code", None),
                            getattr(getattr(error, "orig", None), "sqlstate", None),
                        )
                        outcomes[notice_id] = AutoPreparationOutcome(
                            notice_id=notice_id, reason="processing_failed"
                        )
        except Exception:
            # savepoint session을 세우지 못하는 경우까지 포함해 자동 준비의 실패가
            # 호출자에게 오르지 않게 한다.
            pass

    # 입력 순서를 지킨다. 아직 결과가 없는 공고(작업 session을 세우지 못한 경우)는
    # 안전 코드로 남긴다.
    return [
        outcomes.get(
            notice_id,
            AutoPreparationOutcome(notice_id=notice_id, reason="processing_failed"),
        )
        for notice_id in ids
    ]


# --- 사전규격 응답 필드 (명세 §8) --------------------------------------------


def _status_for(
    *,
    is_pre_spec: bool,
    grade: EffectiveGrade | None,
    deep_review_id: UUID | None,
    bundles: Sequence[tuple[int, str, Any, str | None]],
    overview_status: str | None,
    has_pending_fetch: bool,
    attachments_failed: bool = False,
    has_ready_document: bool = False,
    auto_start_reason_code: str | None = None,
    is_eligible: bool | None = None,
) -> tuple[str, str | None]:
    """(`auto_preparation_status`, `auto_preparation_reason`)를 정한다.

    `bundles`는 revision 내림차순의 `(revision, status, issues_snapshot, created_by, ...)`다.
    등급이 내려가도 이미 만들어진 것을 되돌리지 않으므로, 실제로 존재하는
    산출물을 먼저 보고 등급은 마지막에 본다.

    `auto_start_reason_code`는 §6.4의 자동 시작을 막은 사유이며
    `deep_review_ready_for_click`에서만 나온다 — 사람이 눌러야 하는 이유가
    바로 그 값이기 때문이다. 막은 것이 없으면 ``None``이고, 그 ``None``을
    자리표시자로 채우지 않는다.

    `is_eligible`은 `overview_eligible`이 연 자격이다. 투영과 실제 준비가 같은
    판정을 쓰도록 호출부가 그 helper의 결과를 그대로 넘긴다. ``None``이면 등급만
    보는 기본 규칙(개요 플래그 off와 같은 판정)으로 되돌아간다.

    `attachments_failed`는 "취득 행이 하나 이상 있고 모두 종결됐으며 그중
    `차단`·`실패`가 있다"이고, `has_ready_document`는 safe·구조 준비 문서가
    하나 이상 있다는 뜻이다. 둘이 겹치면 더 기다려도 아무것도 오지 않으므로
    `waiting_attachments`가 아니라 `blocked`다. 아직 진행 중인 취득 행이
    하나라도 있으면(`has_pending_fetch`) 그것이 먼저다.
    """

    if not is_pre_spec:
        return "not_applicable", None
    if deep_review_id is not None:
        return "deep_review_started", None
    latest = bundles[0] if bundles else None
    if latest is not None and latest[1] == "draft":
        blocking = [
            issue
            for issue in (latest[2] if isinstance(latest[2], list) else [])
            if isinstance(issue, Mapping) and issue.get("blocking")
        ]
        if blocking:
            return "blocked", REASON_BLOCKING_ISSUES
        return "bundle_draft", None
    ready = next((row for row in bundles if row[1] == "ready"), None)
    if ready is not None:
        if overview_status in _OVERVIEW_RUNNING_STATUSES:
            return "overview_running", None
        # 개요 run이 아예 없으면(`None`) `bundle_ready`다. 없는 것을 종결로
        # 승격시키면 개요를 한 번도 돌리지 않은 묶음까지 결정 대기로 세게 된다.
        if overview_status in _OVERVIEW_SETTLED_STATUSES:
            return "deep_review_ready_for_click", auto_start_reason_code
        return "bundle_ready", None
    eligible = (
        is_eligible
        if is_eligible is not None
        else (grade is not None and grade.is_priority)
    )
    if not eligible:
        return "not_applicable", REASON_GRADE_NOT_PRIORITY
    if has_pending_fetch:
        return "waiting_attachments", REASON_AWAITING_FETCH
    if attachments_failed and not has_ready_document:
        # 취득이 전부 끝났는데 쓸 문서가 없다. 운영자가 "기다리는 중"으로
        # 읽지 않도록 멈춘 상태로 보여 준다.
        return "blocked", REASON_ATTACHMENTS_FAILED
    return "waiting_attachments", REASON_NO_READY_DOCUMENT


def _resolve_active_versions_ok(session: Session) -> bool:
    """§6.4의 fail closed 조건을 읽는 시점에 다시 판단한다.

    "active 환경변수가 없거나 §6.5 조건이 맞지 않으면"이 조건이고, 생성 경로가
    그것을 확인하는 함수와 **같은 함수**를 쓴다. 실패 사유는 모두 하나의 안전한
    code(`service_unavailable`)이며 예외 본문·경로는 보지 않는다.
    """

    try:
        resolve_active_versions(
            session,
            allow_unmeasured_reference=bool(get_settings().reference_workflow_mode),
        )
    except Exception:
        return False
    return True


def auto_preparation_fields(
    session: Session, notice_ids: Sequence[int]
) -> Mapping[int, Mapping[str, Any]]:
    """사전규격 응답의 등급·자동 준비 필드 (명세 §8).

    공고 수와 무관하게 **상수 회 조회**다. 명세 §8이 이 자리에 N+1을 금지한다.
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}

    kinds: dict[int, str] = {}
    sw_business: dict[int, bool] = {}
    for notice_id, source_type, flags in session.execute(
        select(Notice.id, Notice.source_type, Notice.qualification_flags_json).where(
            Notice.id.in_(ids)
        )
    ).all():
        kinds[int(notice_id)] = source_type
        sw_business[int(notice_id)] = _sw_business_object(flags)
    grades = effective_grades(session, ids)
    # 목록이 말하는 상태와 실제 준비 결과가 갈리지 않도록 자격은 쓰기 경로와
    # **같은 helper**가 판정한다 (MVP 완화 포함).
    eligible_ids = overview_eligible(session, ids, grades=grades)

    # 같은 한 번의 순회로 두 가지를 센다: 아직 끝나지 않은 취득 행이 있는가와,
    # 취득 행이 전부 종결됐는데 그중 `차단`·`실패`가 있는가. 두 번째가 있으면
    # 더 기다려도 문서가 오지 않는다 (아래 `_status_for`의 `blocked`).
    pending_by_notice: set[int] = set()
    failed_notices: set[int] = set()
    for notice_id, status in session.execute(
        select(Attachment.notice_id, AttachmentFetch.status)
        .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
        .where(Attachment.notice_id.in_(ids), Attachment.retired_at.is_(None))
    ).all():
        if status not in TERMINAL_FETCH_STATUSES:
            pending_by_notice.add(int(notice_id))
        elif status in _FAILED_FETCH_STATUSES:
            failed_notices.add(int(notice_id))
    # 취득 행이 없는 공고는 `failed_notices`에 아예 들어오지 않는다 — "행이 하나
    # 이상 있고 전부 종결"이 이 뺄셈으로 그대로 표현된다.
    failed_only_by_notice = failed_notices - pending_by_notice

    # `_ready_documents`와 **같은 조건**을 공고 집합 전체에 한 번 묻는다 (명세
    # §8의 N+1 금지). 위 집합이 비면 물을 일이 없으므로 아예 조회하지 않는다.
    ready_document_notices: set[int] = set()
    if failed_only_by_notice:
        ready_document_notices = {
            int(notice_id)
            for notice_id in session.scalars(
                select(Attachment.notice_id)
                .join(DocumentVersion, DocumentVersion.attachment_id == Attachment.id)
                .join(
                    DocumentStructure,
                    DocumentStructure.document_version_id == DocumentVersion.id,
                )
                .where(
                    Attachment.notice_id.in_(sorted(failed_only_by_notice)),
                    Attachment.retired_at.is_(None),
                    DocumentVersion.is_current.is_(True),
                    DocumentVersion.safety_status == "safe",
                    DocumentStructure.validation_status == "ready",
                )
                .distinct()
            ).all()
        }

    bundles_by_notice: dict[int, list[tuple[int, str, Any, str | None, str | None, UUID]]] = {}
    for notice_id, revision, status, issues, created_by, confirmed_by, bundle_id in session.execute(
        select(
            DocumentBundle.notice_id,
            DocumentBundle.revision,
            DocumentBundle.status,
            DocumentBundle.issues_snapshot,
            DocumentBundle.created_by_name,
            DocumentBundle.confirmed_by_name,
            DocumentBundle.id,
        )
        .where(DocumentBundle.notice_id.in_(ids))
        .order_by(DocumentBundle.notice_id.asc(), DocumentBundle.revision.desc())
    ).all():
        bundles_by_notice.setdefault(int(notice_id), []).append(
            (int(revision), str(status), issues, created_by, confirmed_by, bundle_id)
        )

    deep_review_by_notice: dict[int, UUID] = {}
    for notice_id, deep_review_id in session.execute(
        select(DeepReview.notice_id, DeepReview.id)
        .where(DeepReview.notice_id.in_(ids))
        .order_by(DeepReview.notice_id.asc(), DeepReview.created_at.desc())
    ).all():
        deep_review_by_notice.setdefault(int(notice_id), deep_review_id)

    # §6.4의 자동 시작을 막은 사유를 **읽는 시점에 다시 계산한다**. 새 열을
    # 만들지 않고, 규칙은 쓰기 경로와 같은 `auto_start_reason`이 판단한다.
    ready_bundle_by_notice = {
        notice_id: next((row for row in rows if row[1] == "ready"), None)
        for notice_id, rows in bundles_by_notice.items()
    }

    # active profile/policy는 배포 단위 설정이므로 공고 수와 무관하게 최대 한
    # 번만 본다. 볼 일이 없으면 아예 보지 않는다.
    active_versions: bool | None = None

    def _active_versions_available() -> bool:
        nonlocal active_versions
        if active_versions is None:
            active_versions = _resolve_active_versions_ok(session)
        return active_versions

    fields: dict[int, Mapping[str, Any]] = {}
    from .company_fit import gate_reasons
    from .overview_runs import automation_overview_status, current_runs

    # 공고 수와 무관하게 한 번 읽는 현재 개요 run batch. 목록 전체가 같은
    # 투영을 쓰므로 gate가 다시 읽지 않게 그대로 넘긴다 (명세 §8의 N+1 금지).
    runs = current_runs(session, ids)
    fit_reasons = gate_reasons(session, ids, runs=runs)
    for notice_id in ids:
        grade = grades.get(notice_id)
        deep_review_id = deep_review_by_notice.get(notice_id)
        ready_bundle = ready_bundle_by_notice.get(notice_id)
        auto_start_reason_code = None
        overview_status = automation_overview_status(runs.get(notice_id))
        if kinds.get(notice_id) == "pre_spec" and deep_review_id is None and ready_bundle is not None:
            auto_start_reason_code = auto_start_reason(
                is_sw_business=sw_business.get(notice_id, False),
                ready_bundle_auto_confirmed=ready_bundle[4] == AUTO_ACTOR_NAME,
                overview_status=overview_status,
                active_versions_available=_active_versions_available(),
                company_fit_reason=fit_reasons.get(notice_id),
            )
        status, reason = _status_for(
            is_pre_spec=kinds.get(notice_id) == "pre_spec",
            grade=grade,
            deep_review_id=deep_review_id,
            bundles=bundles_by_notice.get(notice_id, ()),
            overview_status=overview_status,
            has_pending_fetch=notice_id in pending_by_notice,
            attachments_failed=notice_id in failed_only_by_notice,
            has_ready_document=notice_id in ready_document_notices,
            auto_start_reason_code=auto_start_reason_code,
            is_eligible=notice_id in eligible_ids,
        )
        fields[notice_id] = {
            # 판정도 정정도 없으면 `None`이다. 0이나 특정 등급으로 접지 않는다.
            "grade": grade.grade if grade is not None else None,
            "grade_source": grade.source if grade is not None else None,
            "auto_preparation_status": status,
            "auto_preparation_reason": reason,
            "latest_deep_review_id": deep_review_id,
        }
    return fields


__all__ = [
    "AUTO_ACTOR_KIND",
    "AUTO_DEEP_REVIEW_ACTION",
    "REASON_AWAITING_FETCH",
    "REASON_BUNDLE_NOT_AUTO_READY",
    "REASON_DEEP_REVIEW_EXISTS",
    "REASON_SERVICE_UNAVAILABLE",
    "REASON_NOT_SW_BUSINESS",
    "REASON_OVERVIEW_NOT_COMPLETED",
    "REASON_PROCESSING_FAILED",
    "REASON_ATTACHMENTS_FAILED",
    "REASON_BLOCKING_ISSUES",
    "REASON_BUNDLE_UNCHANGED",
    "REASON_GRADE_NOT_PRIORITY",
    "REASON_HUMAN_DRAFT",
    "REASON_NO_READY_DOCUMENT",
    "AUTO_ACTOR_NAME",
    "AUTO_CONFIRM_ACTION",
    "AUTO_TRIGGER",
    "AutoDeepReviewOutcome",
    "AutoPreparationOutcome",
    "TERMINAL_FETCH_STATUSES",
    "WARNING_OVERVIEW_ENQUEUE_FAILED",
    "auto_preparation_fields",
    "auto_start_reason",
    "document_fingerprint",
    "maybe_auto_prepare",
    "maybe_auto_start_deep_review",
]
