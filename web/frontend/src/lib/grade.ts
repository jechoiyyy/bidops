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

const GRADE_RAIL: Record<string, string> = {
  "우선 검토": "rail-grade-1",
  "검토 권장": "rail-grade-2",
  "관찰 대상": "rail-grade-3",
  제외: "rail-grade-4",
};

/** 목록 행의 좌측 레일 색을 등급에 맞춘다. 등급 배지를 행에서 뺀 자리를 대신한다. */
export function gradeRailClass(grade: string | null): string {
  if (!grade) return "rail-grade-none";
  return GRADE_RAIL[grade] ?? "rail-grade-none";
}

/** 등급순 정렬에서 그룹 머리글을 만들 때 쓰는 순위. 계약에 없는 값은 맨 뒤로 보낸다. */
export function gradeRank(grade: string | null): number {
  if (!grade) return GRADE_ORDER.length;
  const index = GRADE_ORDER.indexOf(grade as (typeof GRADE_ORDER)[number]);
  return index === -1 ? GRADE_ORDER.length : index;
}
