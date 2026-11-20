"""일일 수집 기준일 상태의 읽기 전용 REST 계약 (2026-11-20, ADR-0076 후속).

화면 헤더의 "수집 완료 · N월 N일 기준"을 사실대로 그리기 위한 응답이다. 판정은 서버가 하고
화면은 옮겨 적기만 한다(`docs/contracts/lifecycle-rest.md` "일일 수집 기준일 상태").
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from ...core.schema_base import AwareDateTime, RuntimeContractModel

SCHEMA_VERSION = "bidops.daily-collection-status.v1"

#: `scripts/run-daily-lifecycle.sh --track`의 두 트랙. 응답은 이 순서로 둘 다 싣는다.
DailyCollectionTrack = Literal["order-plans", "notices"]

#: 닫힌 상태 어휘. `complete`만 "수집 완료"로 읽는다.
#: - `complete`: 판정 기준일의 일일 회차가 적재돼 있고 적재 경고가 0건이다.
#: - `incomplete`: 판정 기준일의 일일 회차는 있으나 적재 경고가 있다(부분 산출물).
#: - `missing`: 판정 기준일의 일일 회차 기록이 없다. 수집 실패·중단은 회차 행을 남기지 않으므로 여기다.
DailyCollectionState = Literal["complete", "incomplete", "missing"]

#: `complete`가 아닌 이유. 비어 있으면 `complete`다.
DailyCollectionReason = Literal["no_run", "ingest_warnings"]


class DailyCollectionTrackStatus(RuntimeContractModel):
    track: DailyCollectionTrack
    #: 이 상태가 말하는 기준일(수집 대상 하루, 한국 시간). 실행일이 아니다.
    basis_date: date
    state: DailyCollectionState
    reasons: list[DailyCollectionReason]
    #: 판정에 쓴 회차의 정규 id(`<디렉터리>--<generated_at>Z`). 기록이 없으면 `null`.
    run_id: str | None
    #: 그 회차의 수집(적재 스냅숏) 시각. 기록이 없으면 `null`.
    collected_at: AwareDateTime | None
    #: 그 회차의 적재 경고 수. 회차가 없으면 `null`(0과 구분한다).
    warning_count: int | None = Field(ge=0)
    #: 이 트랙에서 기록이 있는 가장 늦은 기준일. 하나도 없으면 `null`.
    latest_basis_date: date | None


class DailyCollectionStatusResponse(RuntimeContractModel):
    schema_version: Literal["bidops.daily-collection-status.v1"]
    generated_at: AwareDateTime
    timezone: Literal["Asia/Seoul"]
    #: 판정 시각의 한국 시간 날짜.
    today: date
    tracks: list[DailyCollectionTrackStatus]
