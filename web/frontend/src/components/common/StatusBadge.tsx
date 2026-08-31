import type { HTMLAttributes } from "react";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface StatusBadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  label: string;
  tone?: StatusTone;
}

/**
 * 서버가 준 상태 문구를 그대로 표시하는 표현 컴포넌트다.
 * 업무 enum과 tone 매핑은 각 화면이 소유하며 이 컴포넌트는 상태를 재판정하지 않는다.
 */
export function StatusBadge({ label, tone = "neutral", className = "", ...props }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge-${tone} ${className}`.trim()} {...props}>
      {label}
    </span>
  );
}
