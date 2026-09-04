"""lifecycle이 다른 모듈에 공개하는 함수 (명세 §6.3).

screening·deep_review는 lifecycle 모델을 ORM으로 **읽고 join해도 된다**(§4). 그러나
lifecycle 테이블에 **쓰기와 잠금**은 여기 있는 함수로만 한다. 그래야 회차·공고·
사업기회·첨부 메타의 잠금 순서와 불변 조건이 한 곳에 남는다.

T7 3단계가 lifecycle 소유 파일을 모두 `app/lifecycle/`로 들여왔으므로 구현은
같은 패키지 안(`.models`·`.ingest.loader`)을 가리킨다.
"""

from __future__ import annotations

from collections.abc import Sequence
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.run_id import ensure_aware as _ensure_aware
from .ingest.loader import IngestResult, _load_order_plans, ingest_run
from .models import (
    AgencyPortal,
    Attachment,
    IngestWarning,
    Notice,
    NoticeObservation,
    Opportunity,
    OrderPlan,
    Run,
)

__all__ = [
    "ATTACHMENT_ORIGINS",
    "IngestResult",
    "attachment_download_url",
    "delete_manual_attachment",
    "delete_run",
    "get_notice",
    "get_run",
    "ingest_run",
    "list_agency_portals",
    "list_attachments_for_notice",
    "list_order_plans_for_run",
    "seed_default_portals",
    "lock_active_attachments",
    "lock_attachment",
    "load_order_plan_artifact",
    "lock_notice",
    "lock_opportunity",
    "match_agency_portal",
    "mirror_notice_observation",
    "record_ingest_warning",
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


# --- 기관 포털 시드 ---------------------------------------------------------

# MVP 대상 3개 기관의 시드 데이터. 검색 주소는 담당자가 실제 주소로 교체하는
# 것을 전제로 한 자리표시자이며, 확인 전에는 화면에서 미확인 상태로 안내한다.
PORTAL_SEED_NOTE = "검색 주소는 자리표시자입니다. 실제 조달시스템 주소를 확인하여 수정한 뒤 사용하십시오."


def seed_default_portals(session: Session) -> None:
    """기관 포털 표가 완전히 비어 있을 때만 MVP 시드를 넣는다.

    `agency_portal`은 lifecycle 소유이므로 이 쓰기도 lifecycle 안에 있다(§4).
    앱 startup은 seed를 하지 않는다(§9) — 담당자가 명시적으로 부를 때만 돈다.
    """

    if session.scalar(select(AgencyPortal.id).limit(1)) is not None:
        return
    session.add_all(
        [
            AgencyPortal(
                agency_pattern="한국수자원공사",
                system_name="한국수자원공사 전자조달시스템",
                search_url_template="https://ebid.kwater.or.kr/search?bidNo={bid_no}&title={title}",
                note=PORTAL_SEED_NOTE,
            ),
            AgencyPortal(
                agency_pattern="한국도로공사",
                system_name="한국도로공사 전자조달시스템",
                search_url_template="https://ebid.ex.co.kr/search?bidNo={bid_no}&title={title}",
                note=PORTAL_SEED_NOTE,
            ),
            AgencyPortal(
                agency_pattern="한국토지주택공사",
                system_name="한국토지주택공사 전자조달",
                search_url_template="https://ebid.lh.or.kr/search?bidNo={bid_no}&title={title}",
                note=PORTAL_SEED_NOTE,
            ),
        ]
    )
    session.commit()


# --- 잠금 -------------------------------------------------------------------


def lock_notice(session: Session, notice_id: int) -> Notice | None:
    """공고를 잠근다.

    심층 검토는 notice → 최신 bundle → document 순서로 잠근다(§9). 이 함수가 그
    첫 단계이며, 순서를 뒤집지 않으려면 호출부가 이것을 먼저 불러야 한다.
    """

    return session.scalar(select(Notice).where(Notice.id == notice_id).with_for_update())


def lock_attachment(
    session: Session, attachment_id: int, *, populate_existing: bool = False
) -> Attachment | None:
    """첨부 메타 행을 잠근다.

    `populate_existing`은 같은 session이 이미 들고 있는 인스턴스를 잠금과 함께 다시
    읽어야 할 때 켠다(문서 준비가 취득 상태를 바꾼 직후처럼). 끄면 identity map의
    값을 그대로 쓴다 — 호출부의 기존 동작을 그대로 옮기려고 둔 선택지다.
    """

    statement = select(Attachment).where(Attachment.id == attachment_id)
    if populate_existing:
        statement = statement.execution_options(populate_existing=True)
    return session.scalar(statement.with_for_update())


def lock_active_attachments(session: Session, notice_id: int) -> Sequence[Attachment]:
    """공고의 은퇴하지 않은 첨부 메타를 id 순서로 한꺼번에 잠근다.

    문서 준비가 공고 단위 은퇴 울타리를 세울 때 쓴다. join 잠금이 아니라 행을
    명시적으로 나열해 잠그는 것이 원래 동작이며, 그래야 잠금 대상이
    PostgreSQL과 이후 첨부 writer 양쪽에 결정적으로 보인다.
    """

    return session.scalars(
        select(Attachment)
        .where(Attachment.notice_id == notice_id, Attachment.retired_at.is_(None))
        .order_by(Attachment.id.asc())
        .with_for_update()
    ).all()


def lock_opportunity(session: Session, opportunity_id: int) -> Opportunity | None:
    """사업기회를 잠근다. 병합 여부 판단은 호출부가 한다."""

    return session.scalar(
        select(Opportunity).where(Opportunity.id == opportunity_id).with_for_update()
    )


# --- 회차 쓰기 ---------------------------------------------------------------


def delete_run(session: Session, run_id: str) -> None:
    """회차 행을 지운다. commit은 호출부가 한다.

    선별이 공고 산출물 발행에 실패해 자기가 만든 회차를 되돌릴 때 쓴다. 그
    한 자리 때문에 lifecycle 테이블 삭제를 모듈 밖에서 직접 하게 두지 않는다
    (§4: lifecycle 테이블 쓰기는 lifecycle 공개 함수로만).

    행이 없으면 아무 일도 하지 않는다 — 호출부가 재시도 안에서 부르므로 두 번째
    호출이 실패하면 안 된다.
    """

    session.execute(delete(Run).where(Run.id == run_id))


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


# --- 회차 적재 부수 쓰기 ------------------------------------------------------
# 회차 경고·발주계획·공고 관측은 lifecycle 테이블이다. 회차 적재 hook을 등록한
# 모듈이 같은 transaction 안에서 이 세 가지를 남겨야 하므로, 그 쓰기를 여기서만
# 열어 준다(§4: lifecycle 테이블 쓰기는 lifecycle 공개 함수로만).


def record_ingest_warning(
    session: Session,
    *,
    run_id: str,
    level: str,
    code: str,
    message: str,
    context: dict | None = None,
) -> IngestWarning:
    """회차 경고 한 줄. 적재 순서가 곧 응답의 순서이므로 즉시 기록한다."""

    warning = IngestWarning(
        run_id=run_id,
        level=level,
        code=code,
        message=message,
        context_json=context,
    )
    session.add(warning)
    return warning


def load_order_plan_artifact(
    session: Session,
    *,
    run_id: str,
    raw: dict,
    timezone_name: str,
    source_file: str,
) -> int:
    """발주계획 산출물을 회차에 적재한다.

    C-2 선별 결과 적재는 자기 모집단이 그 회차의 발주계획 전체와 같은지 확인해야
    하므로 같은 transaction에서 이 함수를 부른다. 적재 규칙과 경고는 lifecycle의
    회차 적재와 완전히 같다.
    """

    return _load_order_plans(session, run_id, raw, timezone_name, source_file)


def mirror_notice_observation(
    session: Session,
    *,
    notice_id: int,
    from_run_id: str,
    to_run_id: str,
) -> NoticeObservation | None:
    """이미 있는 관측의 불변 snapshot을 다른 회차로 복제한다.

    파생 회차로 발행된 판정은 자기 source 회차의 관측을 참조한다. 그 후보가
    과거 표본 밖이면 source 회차 관측이 아직 없을 수 있으므로, 동결 입력이
    가리키는 회차에 같은 snapshot을 세운 뒤에야 revision을 붙일 수 있다.
    이미 있으면 아무것도 하지 않는다.
    """

    if from_run_id == to_run_id:
        return None
    existing = session.scalar(
        select(NoticeObservation).where(
            NoticeObservation.notice_id == notice_id,
            NoticeObservation.run_id == to_run_id,
        )
    )
    if existing is not None:
        return existing
    target_run = session.get(Run, to_run_id)
    source_observation = session.scalar(
        select(NoticeObservation).where(
            NoticeObservation.notice_id == notice_id,
            NoticeObservation.run_id == from_run_id,
        )
    )
    if target_run is None or source_observation is None:
        raise ValueError("verified v3 source observation cannot be materialized")
    observation = NoticeObservation(
        notice_id=notice_id,
        run_id=to_run_id,
        observed_at=_ensure_aware(target_run.generated_at, target_run.timezone),
        changed_fields_json=[],
        snapshot_schema_version=source_observation.snapshot_schema_version,
        snapshot_jsonb=source_observation.snapshot_jsonb,
        source_sha256=source_observation.source_sha256,
    )
    session.add(observation)
    session.flush()
    return observation

# --- 회차 적재 --------------------------------------------------------------
# `ingest_run`은 `..ingest.loader`에서 그대로 재공개한다(위 import). 선별 worker가
# 회차를 적재할 때 lifecycle 공개 이름으로 부른다.


def attachment_download_url(attachment: Attachment) -> str | None:
    """Return an internal download URL when a stored file exists.

    첨부 메타는 lifecycle 소유이고 다운로드 경로 문자열도 그 계약의 일부다
    (명세 §5.2). deep_review의 첨부 화면도 같은 문자열을 쓰므로 여기 한 벌만
    둔다. 순수 문자열 생성이며 저장소에 닿지 않는다.
    """

    if attachment.stored_path:
        return f"/api/attachments/{attachment.id}/download"
    return attachment.url
