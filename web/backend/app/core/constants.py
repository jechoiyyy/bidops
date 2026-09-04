"""Canonical judgment vocabulary from the workflow contract.

등급과 준비 상태 문자열은 `skills/references/workflow-contract.md` 가 정하는
값이다. 여러 라우터가 각자 목록을 들고 있으면 계약이 바뀔 때 한 곳을 놓치기
쉬우므로, 정렬 순서를 포함해 이 모듈 하나만 참조한다.
"""

from __future__ import annotations

from typing import Literal

GRADE_ORDER: list[str] = ["우선 검토", "검토 권장", "관찰 대상", "제외"]

READINESS_ORDER: list[str] = [
    "확인 완료",
    "부분 확인 필요",
    "참여 불가 확인",
    "해당 없음",
]

GRADE_RANK: dict[str, int] = {value: index for index, value in enumerate(GRADE_ORDER)}


# 사전규격 개요 검토 상태 (docs/design/PLAN.md 3단계).
#
# 값을 만드는 것은 deep_review의 개요 검토지만, lifecycle의 사전규격 목록이
# 같은 리터럴로 상태를 투영하고 집계한다(`PreSpecListItem.overview_review_status`,
# `PreSpecOverviewStatusCount.status`). 두 모듈이 각자 사본을 들면 계약이
# 갈라지고 lifecycle → deep_review 역방향 import가 생기므로, 명세 §4의
# "상수·검증기가 필요하면 core로 옮긴다"에 따라 여기 한 벌만 둔다.
# 구성원과 문자열은 바뀌지 않는다. 행이 없는 공고(개요 검토 미시작)는 이
# 리터럴의 값이 아니라 `None`으로 남는 열한 번째 구간이다.
PreSpecOverviewReviewStatus = Literal[
    "awaiting_document",
    "awaiting_structure",
    "preparing",
    "awaiting_model",
    "queued",
    "running",
    "needs_human_review",
    "completed",
    "failed",
    "cancelled",
]
