interface EmptyStateProps {
  title: string;
  description?: string;
  compact?: boolean;
}

export function EmptyState({ title, description, compact = false }: EmptyStateProps) {
  return (
    <div className={`empty-state ${compact ? "empty-state-compact" : ""}`.trim()}>
      <div className="empty-state-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <path d="M8 9h8M8 13h5M8 17h3" />
        </svg>
      </div>
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
    </div>
  );
}
