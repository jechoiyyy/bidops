import { useId } from "react";
import { Link } from "react-router-dom";
import type { ApiErrorDescription } from "../../lib/apiErrors";

export interface EmptyStateAction {
  label: string;
  to?: string;
  onClick?: () => void;
}

interface EmptyStateProps {
  title: string;
  description?: string;
  compact?: boolean;
  action?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  tone?: "neutral" | "warning" | "error";
  className?: string;
  /**
   * `lib/apiErrors.describeApiError`의 결과. 주면 원인 한 줄과 다음 행동 한 줄을
   * 화면 맥락 제목 아래에 함께 적는다. 서버 raw message는 여기에 들어오지 않고,
   * 안전한 코드만 표식으로 남는다(docs/security.md).
   */
  problem?: ApiErrorDescription;
}

function ActionControl({ action, variant }: { action: EmptyStateAction; variant: "primary" | "secondary" }) {
  const className = `empty-state-action empty-state-action-${variant}`;
  if (action.to) return <Link className={className} to={action.to}>{action.label}</Link>;
  return <button className={className} type="button" onClick={action.onClick}>{action.label}</button>;
}

export function EmptyState({
  title,
  description,
  compact = false,
  action,
  secondaryAction,
  tone = "neutral",
  className = "",
  problem,
}: EmptyStateProps) {
  const generatedId = useId();
  const titleId = `empty-state-title-${generatedId}`;
  const descriptionId = description ? `empty-state-description-${generatedId}` : undefined;
  return (
    <div
      className={`empty-state empty-state-${tone} ${compact ? "empty-state-compact" : ""} ${className}`.trim()}
      role={tone === "error" ? "alert" : undefined}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <div className="empty-state-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <path d="M8 9h8M8 13h5M8 17h3" />
        </svg>
      </div>
      <strong id={titleId}>{title}</strong>
      {description ? <p id={descriptionId}>{description}</p> : null}
      {problem ? (
        <p className="empty-state-problem">
          {problem.title} {problem.detail}
          {problem.code ? <span className="empty-state-problem-code"> · 오류 코드 {problem.code}</span> : null}
        </p>
      ) : null}
      {action || secondaryAction ? (
        <div className="empty-state-actions">
          {action ? <ActionControl action={action} variant="primary" /> : null}
          {secondaryAction ? <ActionControl action={secondaryAction} variant="secondary" /> : null}
        </div>
      ) : null}
    </div>
  );
}
