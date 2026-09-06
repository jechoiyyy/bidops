import type { HTMLAttributes } from "react";
import { Badge, type BadgeVariant } from "./Badge";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

/** tone은 화면이 쓰던 이름이고 variant는 배지 한 벌의 이름이다. 이 표가 둘을
 * 잇는 전부이며, 여기서 상태를 다시 판정하지 않는다. */
const TONE_VARIANT: Record<StatusTone, BadgeVariant> = {
  neutral: "neutral",
  info: "info",
  success: "success",
  warning: "alert",
  danger: "danger",
};

export interface StatusBadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  label: string;
  tone?: StatusTone;
}

/**
 * 서버가 준 상태 문구를 그대로 표시하는 표현 컴포넌트다.
 * 업무 enum과 tone 매핑은 각 화면이 소유하며 이 컴포넌트는 상태를 재판정하지 않는다.
 *
 * 배지는 `Badge` 한 벌뿐이다. 이 컴포넌트는 tone 이름을 variant로 옮기고
 * `status-badge` 표식만 덧붙인다 — 표식은 화면 CSS의 자리 규칙
 * (`.bid-delta-status-panel > .status-badge` 등)이 읽는 hook이며 색을 정하지
 * 않는다.
 */
export function StatusBadge({ label, tone = "neutral", className = "", ...props }: StatusBadgeProps) {
  return (
    <Badge
      className={`status-badge ${className}`.trim()}
      label={label}
      variant={TONE_VARIANT[tone]}
      {...props}
    />
  );
}
