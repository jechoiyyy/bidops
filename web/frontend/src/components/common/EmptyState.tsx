import { Link } from "react-router-dom";

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
}

function ActionControl({ action, variant }: { action: EmptyStateAction; variant: "primary" | "secondary" }) {
  const className = `empty-state-action empty-state-action-${variant}`;
  if (action.to) return <Link className={className} to={action.to}>{action.label}</Link>;
  return <button className={className} type="button" onClick={action.onClick}>{action.label}</button>;
}

export function EmptyState({ title, description, compact = false, action, secondaryAction, tone = "neutral" }: EmptyStateProps) {
  return (
    <div className={`empty-state empty-state-${tone} ${compact ? "empty-state-compact" : ""}`.trim()}>
      <div className="empty-state-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <path d="M8 9h8M8 13h5M8 17h3" />
        </svg>
      </div>
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action || secondaryAction ? (
        <div className="empty-state-actions">
          {action ? <ActionControl action={action} variant="primary" /> : null}
          {secondaryAction ? <ActionControl action={secondaryAction} variant="secondary" /> : null}
        </div>
      ) : null}
    </div>
  );
}
