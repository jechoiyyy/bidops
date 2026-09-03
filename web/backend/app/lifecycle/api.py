"""lifecycle이 다른 모듈에 공개하는 함수 (명세 §6.3).

screening·deep_review는 lifecycle 모델을 ORM으로 **읽고 join해도 된다**(§4). 그러나
lifecycle 테이블에 **쓰기와 잠금**은 여기 있는 함수로만 한다. 그래야 회차·공고·
사업기회·첨부 메타의 잠금 순서와 불변 조건이 한 곳에 남는다.

폴더 이주(T7) 전이므로 구현은 아직 `app.models`·`app.ingest.loader`·`app.services`를
가리킨다. 대상 파일들이 lifecycle 폴더로 옮겨지면 import 경로만 바뀐다.
"""

from __future__ import annotations

from collections.abc import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingest.loader import IngestResult, ingest_run
from ..models import AgencyPortal, Attachment, Notice, OrderPlan, Opportunity, Run

__all__ = [
    "ATTACHMENT_ORIGINS",
    "IngestResult",
    "delete_manual_attachment",
    "get_notice",
    "get_run",
    "ingest_run",
    "list_agency_portals",
    "list_attachments_for_notice",
    "list_order_plans_for_run",
    "lock_notice",
    "lock_opportunity",
    "match_agency_portal",
    "register_attachment",
    "register_manual_attachment",
]


# --- 읽기 편의 ---------------------------------------------------------------


def get_notice(session: Session, notice_id: int) -> Notice | None:
    """공고 하나. 잠그지 않는다."""

    return session.get(Notice, notice_id)


def get_run(session: Session, run_id: str) -> Run | None:
    """회차 하나. 잠그지 않는다."""

    return session.get(Run, run_id)


def list_order_plans_for_run(session: Session, run_id: str) -> Sequence[OrderPlan]:
    """회차에 속한 발주계획. 선별이 회차 범위를 읽을 때 쓴다."""

    return tuple(
        session.scalars(
            select(OrderPlan).join(OrderPlan.observations).where(
                OrderPlan.observations.any(run_id=run_id)
            ).distinct()
        )
    )


def list_agency_portals(session: Session, *, enabled_only: bool = False) -> Sequence[AgencyPortal]:
    """등록된 발주처 포털.

    `enabled_only`는 꺼진 포털을 제외한다. 첨부 취득 경로를 만들 때는 반드시
    켜서 부른다 — 꺼진 포털로 검색 주소를 만들면 안 된다.
    """

    query = select(AgencyPortal).order_by(AgencyPortal.id.asc())
    if enabled_only:
        query = query.where(AgencyPortal.enabled.is_(True))
    return tuple(session.scalars(query))


def match_agency_portal(session: Session, agency: str | None) -> AgencyPortal | None:
    """발주처 문자열에 가장 구체적으로 맞는 **켜진** 포털.

    `agency_pattern`이 발주처 이름에 부분 일치하는 것 중 pattern이 가장 긴 것을
    고르고, 길이가 같으면 먼저 등록된 것(작은 id)을 고른다. 첨부 취득이 검색
    주소를 만들 때 이 판정을 쓴다.
    """

    if not agency or not agency.strip():
        return None
    agency_value = agency.casefold()
    matches = [
        portal
        for portal in list_agency_portals(session, enabled_only=True)
        if portal.agency_pattern.strip()
        and portal.agency_pattern.strip().casefold() in agency_value
    ]
    return max(matches, key=lambda portal: (len(portal.agency_pattern), -portal.id), default=None)


def list_attachments_for_notice(session: Session, notice_id: int) -> Sequence[Attachment]:
    """공고의 첨부 메타. 취득 순서를 고정하려고 id로 정렬한다."""

    return tuple(
        session.scalars(
            select(Attachment).where(Attachment.notice_pk == notice_id).order_by(Attachment.id)
        )
    )


# --- 잠금 -------------------------------------------------------------------


def lock_notice(session: Session, notice_id: int) -> Notice | None:
    """공고를 잠근다.

    심층 검토는 notice → 최신 bundle → document 순서로 잠근다(§9). 이 함수가 그
    첫 단계이며, 순서를 뒤집지 않으려면 호출부가 이것을 먼저 불러야 한다.
    """

    return session.scalar(select(Notice).where(Notice.id == notice_id).with_for_update())


def lock_opportunity(session: Session, opportunity_id: int) -> Opportunity | None:
    """사업기회를 잠근다. 병합 여부 판단은 호출부가 한다."""

    return session.scalar(
        select(Opportunity).where(Opportunity.id == opportunity_id).with_for_update()
    )


# --- 첨부 메타 쓰기 ----------------------------------------------------------


ATTACHMENT_ORIGINS = ("manual", "g2b")


def register_manual_attachment(
    session: Session,
    notice: Notice,
    *,
    name: str,
    file_ext: str,
    size_bytes: int,
    stored_path: str,
) -> Attachment:
    """사람이 화면에서 올린 첨부의 메타를 기록한다.

    회차 적재가 수집한 첨부 메타와 같은 테이블이므로 lifecycle이 소유한다.
    파일 저장·검사는 호출한 모듈이 하고, 여기서는 행만 만든다. `origin`은
    `manual`로 고정한다 — 나라장터 제공 첨부와 섞이면 삭제 권한 판단이 깨진다.

    문서 준비가 취득한 자산을 기록할 때는 출처 메타가 함께 필요하므로
    `register_attachment`를 쓴다.
    """

    attachment = Attachment(
        name=name,
        url=None,
        origin="manual",
        file_ext=file_ext,
        size_bytes=size_bytes,
        stored_path=stored_path,
        extract_status="pending",
    )
    notice.attachments.append(attachment)
    return attachment


def register_attachment(
    session: Session,
    *,
    notice_id: int,
    name: str,
    file_ext: str,
    size_bytes: int,
    origin: str,
    source_url: str | None = None,
    source_system: str | None = None,
    source_attachment_key: str | None = None,
) -> Attachment:
    """취득한 첨부의 메타를 출처와 함께 기록한다.

    문서 준비가 자산을 확보한 뒤 부른다. `source_system`·`source_attachment_key`
    는 `notice_id`와 함께 부분 unique index를 이루므로 같은 자산을 두 번 기록하지
    않게 하는 열쇠다 — 호출부가 값을 갖고 있으면 반드시 넘긴다.

    `origin`을 `manual`·`g2b`로 제한하는 이유는 삭제 권한 판단이 그 값에
    기대기 때문이다(나라장터 제공 첨부는 지울 수 없다).
    """

    if origin not in ATTACHMENT_ORIGINS:
        raise ValueError(f"첨부 출처는 {ATTACHMENT_ORIGINS} 중 하나여야 한다: {origin!r}")
    attachment = Attachment(
        notice_id=notice_id,
        name=name,
        source_url=source_url,
        origin=origin,
        file_ext=file_ext,
        size_bytes=size_bytes,
        source_system=source_system,
        source_attachment_key=source_attachment_key,
    )
    session.add(attachment)
    return attachment


def delete_manual_attachment(session: Session, attachment: Attachment) -> None:
    """수동 업로드 첨부의 메타를 지운다.

    나라장터 제공 첨부는 지울 수 없다. 저장 파일 제거는 호출한 모듈이 이 함수를
    부르기 전에 한다.
    """

    if attachment.origin != "manual":
        raise ValueError("나라장터 제공 첨부는 삭제할 수 없다")
    session.delete(attachment)


# --- 회차 적재 --------------------------------------------------------------
# `ingest_run`은 `..ingest.loader`에서 그대로 재공개한다(위 import). 선별 worker가
# 회차를 적재할 때 lifecycle 공개 이름으로 부른다.
