"""트랙별 일일 수집 기준일 상태를 기존 회차·적재 경고 행에서 판정한다 (읽기 전용).

화면 헤더의 "수집 완료 · N월 N일 기준"이 서버 판정을 그대로 옮기도록, 대시보드 `일일 수집`
줄이 화면에서 하던 기준일 계산을 여기로 모은다. 새 테이블·migration 없이 `run`과
`ingest_warning` 두 테이블만 읽고 파이프라인 내부 구현을 import하지 않는다.

규칙(계약 `docs/contracts/lifecycle-rest.md` "일일 수집 기준일 상태"):

- 일일 회차는 `scripts/run-daily-lifecycle.sh`가 만드는 디렉터리 `lifecycle-<YYYYMMDD>-plans`·
  `lifecycle-<YYYYMMDD>-notices`(재수집은 `-retry<N>`)의 회차뿐이다. 회차 id는
  `<디렉터리>--<generated_at>Z`다. 수동·참조 실행(`order-plans-…`·`*-vllm-reference-*`·
  `gate-gold-*` 등)과 C-2 측정 전용 실행은 운영 수집이 아니므로 세지 않는다. 같은 디렉터리를
  다시 적재해 `superseded`가 된 행도 세지 않는다.
- 기준일은 한국 시간 전일(ADR-0061)이다. 다만 아침 수집 전 공백을 경고로 만들지 않도록, 전일
  회차가 아직 없고 한국 시간 정오 전이면 그저께를 판정한다(2026-11-18 G2 규칙 그대로).
- 판정 기준일의 회차가 없으면 `missing`(수집 실패·중단은 회차 행을 남기지 않는다). 있으면 늦게
  적재한 회차 하나를 보고, 적재 경고가 1건이라도 있으면 `incomplete`, 0건이면 `complete`다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.models import utc_now
from ..models import IngestWarning, Run
from ..schemas.daily_collection import (
    SCHEMA_VERSION,
    DailyCollectionReason,
    DailyCollectionState,
    DailyCollectionStatusResponse,
    DailyCollectionTrack,
    DailyCollectionTrackStatus,
)

KST = ZoneInfo("Asia/Seoul")
#: 이 시각(한국 시간) 전에는 전일 회차가 아직 없어도 그저께를 판정한다.
MORNING_GRACE_HOUR = 12

_DAILY_RUN_PATTERNS: dict[DailyCollectionTrack, re.Pattern[str]] = {
    "order-plans": re.compile(r"^lifecycle-(\d{4})(\d{2})(\d{2})-plans(?:-retry\d+)?--"),
    "notices": re.compile(r"^lifecycle-(\d{4})(\d{2})(\d{2})-notices(?:-retry\d+)?--"),
}
TRACKS: tuple[DailyCollectionTrack, ...] = ("order-plans", "notices")


@dataclass(frozen=True)
class DailyRun:
    run_id: str
    basis_date: date
    generated_at: datetime


def daily_run_basis_date(run_id: str, track: DailyCollectionTrack) -> date | None:
    """일일 회차 id의 기준일. 일일 회차가 아니거나 날짜가 아니면 `None`."""

    match = _DAILY_RUN_PATTERNS[track].match(run_id)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _daily_runs(session: Session) -> dict[DailyCollectionTrack, list[DailyRun]]:
    rows = session.execute(
        select(Run.id, Run.generated_at, Run.status).where(Run.id.like("lifecycle-%"))
    ).all()
    result: dict[DailyCollectionTrack, list[DailyRun]] = {track: [] for track in TRACKS}
    for run_id, generated_at, status in rows:
        if status == "superseded":
            continue
        for track in TRACKS:
            basis = daily_run_basis_date(run_id, track)
            if basis is not None:
                result[track].append(DailyRun(run_id=run_id, basis_date=basis, generated_at=_aware(generated_at)))
    return result


def target_basis_date(now: datetime, has_run_on: set[date]) -> date:
    """판정할 기준일. 전일이 기본이고, 정오 전에 전일 회차가 없으면 그저께다."""

    local = _aware(now).astimezone(KST)
    yesterday = local.date() - timedelta(days=1)
    if yesterday in has_run_on or local.hour >= MORNING_GRACE_HOUR:
        return yesterday
    return yesterday - timedelta(days=1)


def _warning_counts(session: Session, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    rows = session.execute(
        select(IngestWarning.run_id, func.count(IngestWarning.id))
        .where(IngestWarning.run_id.in_(run_ids))
        .group_by(IngestWarning.run_id)
    ).all()
    return {run_id: int(count) for run_id, count in rows}


def _track_status(
    track: DailyCollectionTrack,
    runs: list[DailyRun],
    now: datetime,
    warnings: dict[str, int],
) -> DailyCollectionTrackStatus:
    basis = target_basis_date(now, {run.basis_date for run in runs})
    latest_basis = max((run.basis_date for run in runs), default=None)
    candidates = [run for run in runs if run.basis_date == basis]
    if not candidates:
        return DailyCollectionTrackStatus(
            track=track,
            basis_date=basis,
            state="missing",
            reasons=["no_run"],
            run_id=None,
            collected_at=None,
            warning_count=None,
            latest_basis_date=latest_basis,
        )
    chosen = max(candidates, key=lambda run: (run.generated_at, run.run_id))
    warning_count = warnings.get(chosen.run_id, 0)
    reasons: list[DailyCollectionReason] = ["ingest_warnings"] if warning_count > 0 else []
    state: DailyCollectionState = "incomplete" if reasons else "complete"
    return DailyCollectionTrackStatus(
        track=track,
        basis_date=basis,
        state=state,
        reasons=reasons,
        run_id=chosen.run_id,
        collected_at=chosen.generated_at,
        warning_count=warning_count,
        latest_basis_date=latest_basis,
    )


def daily_collection_status(session: Session, now: datetime | None = None) -> DailyCollectionStatusResponse:
    moment = _aware(now or utc_now())
    runs = _daily_runs(session)
    run_ids = [run.run_id for track in TRACKS for run in runs[track]]
    warnings = _warning_counts(session, run_ids)
    return DailyCollectionStatusResponse(
        schema_version=SCHEMA_VERSION,
        generated_at=moment,
        timezone="Asia/Seoul",
        today=moment.astimezone(KST).date(),
        tracks=[_track_status(track, runs[track], moment, warnings) for track in TRACKS],
    )
