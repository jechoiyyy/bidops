import type { BadgeVariant } from "../components/common/Badge";
import type { PreSpecDisplayAssessment, PreSpecGradeSource } from "./types";

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

/** 등급이 없는 상태의 고정 라벨. 다섯 번째 등급이 아니라 "아직 판정하지
 * 않음"이므로 등급 ramp가 아닌 무채색으로 따로 둔다(design/PRD.md §4). */
export const GRADE_NONE_LABEL = "판정 없음";

export function gradeLabel(grade: string | null): string {
  return grade && grade.trim() ? grade : GRADE_NONE_LABEL;
}

/** 등급 출처(`grade_source`)의 표시 이름. 등급이 없으면 출처도 없다. */
export function gradeSourceLabel(source: PreSpecGradeSource | null): string {
  if (source === "screening_judgment") return "판정";
  if (source === "human_review") return "정정";
  return "없음";
}

export function displayAssessmentLabel(value: PreSpecDisplayAssessment): string {
  if (value.status === "held") return "판단 보류";
  return gradeLabel(value.grade);
}

export function displayAssessmentSourceLabel(value: PreSpecDisplayAssessment): string {
  if (value.source === "human_review") return "사람 정정";
  if (value.source === "preliminary_assessment") return "개요 예비 판단";
  if (value.source === "screening_judgment") return "기존 선별 판정";
  return "판정 없음";
}

export function displayAssessmentSemanticLabel(value: PreSpecDisplayAssessment): string | null {
  if (value.semantic_status === "passed") return "선택 의미검증 통과";
  if (value.semantic_status === "failed") return "선택 의미검증 실패";
  if (value.semantic_status === "not_run") return "선택 의미검증 미실행";
  return null;
}
