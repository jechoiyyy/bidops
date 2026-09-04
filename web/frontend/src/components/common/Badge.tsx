import type { HTMLAttributes } from "react";

export type BadgeVariant =
  | "grade-1"
  | "grade-2"
  | "grade-3"
  | "grade-4"
  | "readiness"
  | "focus"
  | "alert"
  | "neutral"
  | "evidence-confirmed"
  | "evidence-inferred"
  | "evidence-unknown";

const defaultLabels: Record<BadgeVariant, string> = {
  "grade-1": "우선 검토",
  "grade-2": "검토 권장",
  "grade-3": "관찰 대상",
  "grade-4": "제외",
  readiness: "준비 상태 미확인",
  focus: "역량 축 미확인",
  alert: "확인 필요",
  neutral: "상태 미확인",
  "evidence-confirmed": "confirmed",
  "evidence-inferred": "inferred",
  "evidence-unknown": "unknown",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant: BadgeVariant;
  label?: string | null;
}

/** 등급 4단은 심각도가 아니라 우선순위 순서다. 색은 grade-ramp.css 의
 * `--bo-grade-*` 농도 한 벌만 쓰고, 인접 단의 대비가 1.9~2.1 이라 색만으로는
 * 구분되지 않으므로 라벨을 지울 수 없게 여기서 기본값을 채운다(ADR-0048 §3). */
const GRADE_LEVELS: Partial<Record<BadgeVariant, number>> = {
  "grade-1": 1,
  "grade-2": 2,
  "grade-3": 3,
  "grade-4": 4,
};

export function Badge({ variant, label, className = "", ...props }: BadgeProps) {
  const text = label && label.trim() ? label : defaultLabels[variant];
  const gradeLevel = GRADE_LEVELS[variant];
  return (
    <span
      className={`badge badge-${variant} ${className}`.trim()}
      data-grade-level={gradeLevel}
      data-review-primitive={gradeLevel === undefined ? undefined : "grade"}
      {...props}
    >
      {text}
    </span>
  );
}
