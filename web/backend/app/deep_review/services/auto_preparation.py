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

심층 검토는 여기서 만들지 않는다. SW사업대상=Y 자동 시작 규칙(명세 §6.4)은 다른
작업의 몫이며, 이 모듈은 그 결과를 `auto_preparation_status`로 **읽기만** 한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

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
    PreSpecOverviewReview,
)
from ..schemas.document_bundles import ConfirmRequest
from .effective_grade import EffectiveGrade, effective_grades

#: 시스템 actor의 표식 (명세 §6.2). 인증이 아니라 감사 표식이다.
AUTO_ACTOR_NAME = "auto-preparation"
AUTO_ACTOR_KIND = "system"

#: 자동 준비를 연 사유. 감사 이벤트의 `trigger`로 남는다.
AUTO_TRIGGER = "priority_grade"

#: 자동 확정만 남기는 감사 이벤트 (명세 §8).
AUTO_CONFIRM_ACTION = "document_bundle.auto_confirm"

#: 취득 행의 종결 상태 (명세 §6.2 "자동 묶음").
TERMINAL_FETCH_STATUSES = frozenset({"완료", "차단", "실패"})

#: 개요 검토가 아직 돌고 있다고 보는 상태.
_OVERVIEW_RUNNING_STATUSES = frozenset(
    {"awaiting_structure", "preparing", "awaiting_model", "queued", "running"}
)
#: 개요 검토가 끝났다고 보는 상태. 자동 시작 여부와 무관하게 사람이 누를 수 있다.
_OVERVIEW_SETTLED_STATUSES = frozenset(
    {"completed", "needs_human_review", "failed", "cancelled"}
)

# --- `auto_preparation_reason` 안전 코드 (§8: nullable 안전 코드) -------------
REASON_GRADE_NOT_PRIORITY = "grade_not_priority"
REASON_AWAITING_FETCH = "awaiting_fetch"
REASON_NO_READY_DOCUMENT = "no_ready_document"
REASON_BLOCKING_ISSUES = "bundle_has_blocking_issues"
REASON_BUNDLE_UNCHANGED = "bundle_unchanged"
REASON_HUMAN_DRAFT = "human_bundle_draft"


@dataclass(frozen=True)
class AutoPreparationOutcome:
    """공고 한 건에 대해 자동 준비가 실제로 한 일."""

    notice_id: int
    bundle_id: UUID | None = None
    created: bool = False
    confirmed: bool = False
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
    grade: EffectiveGrade,
    *,
    service: Any,
    run_id: str | None,
    review_id: int | None,
) -> AutoPreparationOutcome:
    """이미 `우선 검토`로 확인된 공고 하나를 실제로 준비한다.

    사전규격 여부와 등급은 호출부가 **batch로 한 번에** 걸러 두었다. 회차 하나가
    사전규격 약 2,000건이므로 여기서 공고당 다시 묻지 않는다.
    """

    # 촉발 식별자 (명세 §6.2). 호출부가 알려 준 회차·리뷰가 있으면 그것이고,
    # 없으면 **이 등급을 만든 것**이 촉발이다 — 등급 변경 hook은 확장점 서명상
    # 식별자를 받지 않으므로 그 경우 리뷰의 회차·리뷰 id가 남는다. 둘 다 없으면
    # `None`으로 남기고 다른 값으로 채우지 않는다.
    trigger = _trigger_metadata(
        run_id if run_id is not None else grade.run_id,
        review_id if review_id is not None else grade.review_id,
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
        # 아무것도 하지 않는다 (명세 §6.2 재수집 규칙).
        return AutoPreparationOutcome(
            notice_id=notice_id, bundle_id=confirmed.id, reason=REASON_BUNDLE_UNCHANGED
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
    return AutoPreparationOutcome(
        notice_id=notice_id, bundle_id=view.id, created=created, confirmed=True
    )


def maybe_auto_prepare(
    session: Session,
    notice_ids: Sequence[int],
    *,
    run_id: str | None = None,
    review_id: int | None = None,
    root: Path | None = None,
    service: Any = None,
) -> list[AutoPreparationOutcome]:
    """대상 공고마다 자동 묶음 생성·확정 조건을 검사하고 만족하면 실행한다.

    **선별과 등급은 batch로 한 번에 푼다.** 회차 적재 hook은 그 회차의 사전규격
    전부(관측 규모로 3일 약 1,200건, 1주 약 2,000건)를 한 번에 넘긴다. 공고당
    등급을 묻거나 공고당 savepoint를 열면 회차 적재 transaction 하나에 수천 번의
    왕복과 수천 개의 하위 transaction이 쌓인다 — PostgreSQL은 한 transaction의
    subtransaction이 대략 64개를 넘어서면 눈에 띄게 나빠진다. 그래서 실제로 할 일이
    있는 공고(사전규격이고 effective grade가 `우선 검토`)가 하나도 없으면 작업
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
    except Exception:
        # 등급을 아예 풀지 못하면(선별 모듈 부재 등) 자동 준비는 이번에 아무것도
        # 하지 않는다. 예외는 호출자에게 오르지 않는다.
        return [
            AutoPreparationOutcome(notice_id=notice_id, reason="processing_failed")
            for notice_id in ids
        ]

    pre_spec = set(pre_spec_ids)
    candidates: list[tuple[int, EffectiveGrade]] = []
    for notice_id in ids:
        if notice_id not in pre_spec:
            outcomes[notice_id] = AutoPreparationOutcome(notice_id=notice_id)
            continue
        grade = grades.get(notice_id)
        if grade is None or not grade.is_priority:
            outcomes[notice_id] = AutoPreparationOutcome(
                notice_id=notice_id, reason=REASON_GRADE_NOT_PRIORITY
            )
            continue
        candidates.append((notice_id, grade))

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
                        )
                    except Exception:
                        # 예외 본문은 여기서 버린다. 다음 촉발에서 다시 시도된다.
                        work.rollback()
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
) -> tuple[str, str | None]:
    """(`auto_preparation_status`, `auto_preparation_reason`)를 정한다.

    `bundles`는 revision 내림차순의 `(revision, status, issues_snapshot, created_by)`다.
    등급이 내려가도 이미 만들어진 것을 되돌리지 않으므로, 실제로 존재하는
    산출물을 먼저 보고 등급은 마지막에 본다.
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
        if overview_status in _OVERVIEW_SETTLED_STATUSES:
            return "deep_review_ready_for_click", None
        return "bundle_ready", None
    if grade is None or not grade.is_priority:
        return "not_applicable", REASON_GRADE_NOT_PRIORITY
    if has_pending_fetch:
        return "waiting_attachments", REASON_AWAITING_FETCH
    return "waiting_attachments", REASON_NO_READY_DOCUMENT


def auto_preparation_fields(
    session: Session, notice_ids: Sequence[int]
) -> Mapping[int, Mapping[str, Any]]:
    """사전규격 응답의 등급·자동 준비 필드 (명세 §8).

    공고 수와 무관하게 **상수 회 조회**다. 명세 §8이 이 자리에 N+1을 금지한다.
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}

    kinds = {
        int(notice_id): source_type
        for notice_id, source_type in session.execute(
            select(Notice.id, Notice.source_type).where(Notice.id.in_(ids))
        ).all()
    }
    grades = effective_grades(session, ids)

    pending_by_notice: set[int] = set()
    for notice_id, status in session.execute(
        select(Attachment.notice_id, AttachmentFetch.status)
        .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
        .where(Attachment.notice_id.in_(ids), Attachment.retired_at.is_(None))
    ).all():
        if status not in TERMINAL_FETCH_STATUSES:
            pending_by_notice.add(int(notice_id))

    bundles_by_notice: dict[int, list[tuple[int, str, Any, str | None]]] = {}
    for notice_id, revision, status, issues, created_by in session.execute(
        select(
            DocumentBundle.notice_id,
            DocumentBundle.revision,
            DocumentBundle.status,
            DocumentBundle.issues_snapshot,
            DocumentBundle.created_by_name,
        )
        .where(DocumentBundle.notice_id.in_(ids))
        .order_by(DocumentBundle.notice_id.asc(), DocumentBundle.revision.desc())
    ).all():
        bundles_by_notice.setdefault(int(notice_id), []).append(
            (int(revision), str(status), issues, created_by)
        )

    overview_by_notice = {
        int(notice_id): status
        for notice_id, status in session.execute(
            select(PreSpecOverviewReview.notice_id, PreSpecOverviewReview.status).where(
                PreSpecOverviewReview.notice_id.in_(ids)
            )
        ).all()
    }

    deep_review_by_notice: dict[int, UUID] = {}
    for notice_id, deep_review_id in session.execute(
        select(DeepReview.notice_id, DeepReview.id)
        .where(DeepReview.notice_id.in_(ids))
        .order_by(DeepReview.notice_id.asc(), DeepReview.created_at.desc())
    ).all():
        deep_review_by_notice.setdefault(int(notice_id), deep_review_id)

    fields: dict[int, Mapping[str, Any]] = {}
    for notice_id in ids:
        grade = grades.get(notice_id)
        deep_review_id = deep_review_by_notice.get(notice_id)
        status, reason = _status_for(
            is_pre_spec=kinds.get(notice_id) == "pre_spec",
            grade=grade,
            deep_review_id=deep_review_id,
            bundles=bundles_by_notice.get(notice_id, ()),
            overview_status=overview_by_notice.get(notice_id),
            has_pending_fetch=notice_id in pending_by_notice,
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
    "REASON_AWAITING_FETCH",
    "REASON_BLOCKING_ISSUES",
    "REASON_BUNDLE_UNCHANGED",
    "REASON_GRADE_NOT_PRIORITY",
    "REASON_HUMAN_DRAFT",
    "REASON_NO_READY_DOCUMENT",
    "AUTO_ACTOR_NAME",
    "AUTO_CONFIRM_ACTION",
    "AUTO_TRIGGER",
    "AutoPreparationOutcome",
    "TERMINAL_FETCH_STATUSES",
    "auto_preparation_fields",
    "document_fingerprint",
    "maybe_auto_prepare",
]
