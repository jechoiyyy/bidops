import type { BadgeVariant } from "../components/common/Badge";
import type { PreSpecDisplayAssessment } from "./types";

// 등급 문자열은 `skills/references/workflow-contract.md` 가 정의한 네 값이다.
// 배지 변형과의 대응을 한곳에 두어, 계약이 바뀔 때 고칠 자리를 하나로 만든다.
export const GRADE_ORDER = ["우선 검토", "검토 권장", "관찰 대상", "제외"] as const;

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

/** 등급순 정렬에서 그룹 머리글을 만들 때 쓰는 순위. 계약에 없는 값은 맨 뒤로 보낸다. */
export function gradeRank(grade: string | null): number {
  if (!grade) return GRADE_ORDER.length;
  const index = GRADE_ORDER.indexOf(grade as (typeof GRADE_ORDER)[number]);
  return index === -1 ? GRADE_ORDER.length : index;
}

/** 등급이 없는 상태의 고정 라벨. 다섯 번째 등급이 아니라 "아직 판정하지
 * 않음"이므로 등급 ramp가 아닌 무채색으로 따로 둔다(design/PRD.md §4). */
const GRADE_NONE_LABEL = "판정 없음";

export function gradeLabel(grade: string | null): string {
  return grade && grade.trim() ? grade : GRADE_NONE_LABEL;
}

export function displayAssessmentSemanticLabel(value: PreSpecDisplayAssessment): string | null {
  if (value.semantic_status === "passed") return "선택 의미검증 통과";
  if (value.semantic_status === "failed") return "선택 의미검증 실패";
  if (value.semantic_status === "not_run") return "선택 의미검증 미실행";
  return null;
}
