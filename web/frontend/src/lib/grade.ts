import type { BadgeVariant } from "../components/common/Badge";

// 등급 문자열은 `skills/references/workflow-contract.md` 가 정의한 네 값이다.
// 배지 변형과의 대응을 한곳에 두어, 계약이 바뀔 때 고칠 자리를 하나로 만든다.
export const GRADE_ORDER = ["우선 검토", "검토 권장", "관찰 대상", "제외"] as const;

export const READINESS_ORDER = [
  "확인 완료",
  "부분 확인 필요",
  "참여 불가 확인",
  "해당 없음",
] as const;

const GRADE_VARIANTS: Record<string, BadgeVariant> = {
  "우선 검토": "grade-1",
  "검토 권장": "grade-2",
  "관찰 대상": "grade-3",
  제외: "grade-4",
};

export function gradeVariant(grade: string | null): BadgeVariant {
  if (!grade) return "neutral";
  return GRADE_VARIANTS[grade] ?? "neutral";
}
