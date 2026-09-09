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

# v4 current 상태는 목록·상세·자동 준비가 같은 개요 상태 열을 사용한다.
# v4에만 있는 `stale`은 검증된 권고가 없다는 뜻으로 사람 확인에 두고, 그 밖의
# 실행 상태는 목록 계약의 같은 리터럴을 유지한다. 알 수 없는 상태도 fail closed
# 로 사람 확인에 둔다.
PRESPEC_V4_STATUS_TO_OVERVIEW_STATUS: dict[str, str] = {
    "queued": "running",
    "running": "running",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "needs_human_review": "needs_human_review",
    "stale": "needs_human_review",
}


def prespec_overview_status_from_v4(status: str | None) -> str:
    return PRESPEC_V4_STATUS_TO_OVERVIEW_STATUS.get(status or "", "needs_human_review")


# 형식 밖 첨부(`unsupported_extension`)로 종결된 취득 행이 남기는
# `attachment.extract_status` (명세 §6.2).
#
# 값을 쓰는 것은 deep_review의 취득 worker이고 읽는 것은 문서 묶음 issue 계산이다.
# 두 곳이 각자 문자열을 들면 "확정을 막지 않는 값"이라는 계약이 조용히 갈라지므로
# 여기 한 벌만 둔다. 접두사가 `provider_`로 시작하지만 **차단 issue가 아니다** —
# 묶음 issue 계산이 다른 `provider_*`보다 먼저 이 값을 본다.
UNSUPPORTED_ATTACHMENT_EXTRACT_STATUS = "provider_unsupported_excluded"

#: 위 첨부가 묶음에 남기는 비차단 issue 코드 (명세 §5).
UNSUPPORTED_ATTACHMENT_ISSUE_CODE = "unsupported_attachment_excluded"


# 사전규격 자동 준비 상태 (명세 §5·§6.2).
#
# 값을 만드는 것은 deep_review의 자동 준비지만 lifecycle의 사전규격 응답이 같은
# 리터럴을 싣는다. 개요 검토 상태와 같은 이유로 core에 한 벌만 둔다.
# `not_applicable`은 "자동 준비 대상이 아니다"이며 "알 수 없다"가 아니다 —
# 제공자가 없는 배포에서도 자동 준비는 실제로 일어나지 않으므로 같은 값이다.
PreSpecAutoPreparationStatus = Literal[
    "not_applicable",
    "waiting_attachments",
    "bundle_draft",
    "bundle_ready",
    "overview_running",
    "deep_review_started",
    "deep_review_ready_for_click",
    "blocked",
]

#: 사전규격 응답의 `grade`가 어디서 왔는가 (명세 §8).
#: 사람 정정 등급이 있으면 `human_review`, 없고 판정만 있으면
#: `screening_judgment`, 둘 다 없으면 `None`(등급도 `None`)이다.
PreSpecGradeSource = Literal["screening_judgment", "human_review"]


# 심층 검토를 만든 감사 action (명세 §6.4·§8).
#
# 사람 클릭은 `deep_review.create`, SW사업대상=Y 자동 시작은
# `deep_review.auto_create`이고 **둘은 같은 safe_metadata 모양**을 남긴다.
# "이 검토의 생성 감사"를 찾는 자리는 두 값을 모두 봐야 한다 — 한쪽만 보면
# 자동 생성된 검토는 실행 시점에 고정 입력 snapshot을 찾지 못해 만들어지기만
# 하고 절대 실행되지 않는다.
#
# 서비스·router와 **의존성 없는 agent projection**이 같이 쓴다. projection은
# 서비스를 import하지 않는 것이 그 모듈의 계약이므로, 명세 §4의 "상수·검증기가
# 필요하면 core로 옮긴다"에 따라 여기 한 벌만 둔다.
DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND: dict[str, str] = {
    "human": "deep_review.create",
    "system": "deep_review.auto_create",
}

#: 위 표의 값들. "누가 만들었든 이 검토의 생성 감사"를 찾을 때 쓴다.
DEEP_REVIEW_CREATION_ACTIONS: tuple[str, ...] = tuple(
    DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND.values()
)
