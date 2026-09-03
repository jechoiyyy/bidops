"""Canonical judgment vocabulary from the workflow contract.

등급과 준비 상태 문자열은 `skills/references/workflow-contract.md` 가 정하는
값이다. 여러 라우터가 각자 목록을 들고 있으면 계약이 바뀔 때 한 곳을 놓치기
쉬우므로, 정렬 순서를 포함해 이 모듈 하나만 참조한다.
"""

from __future__ import annotations

GRADE_ORDER: list[str] = ["우선 검토", "검토 권장", "관찰 대상", "제외"]

READINESS_ORDER: list[str] = [
    "확인 완료",
    "부분 확인 필요",
    "참여 불가 확인",
    "해당 없음",
]

GRADE_RANK: dict[str, int] = {value: index for index, value in enumerate(GRADE_ORDER)}
