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

export function Badge({ variant, label, className = "", ...props }: BadgeProps) {
  const text = label && label.trim() ? label : defaultLabels[variant];
  return (
    <span className={`badge badge-${variant} ${className}`.trim()} {...props}>
      {text}
    </span>
  );
}
