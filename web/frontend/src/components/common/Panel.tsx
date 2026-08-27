import type { ReactNode } from "react";

export type PanelTone = "secondary" | "selected" | "warning" | "error";

interface PanelProps {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  tone?: PanelTone;
}

export function Panel({ title, action, children, className = "", tone }: PanelProps) {
  const toneClass = tone ? `panel-tone-${tone}` : "";
  return (
    <section className={`panel ${toneClass} ${className}`.trim()}>
      {title || action ? (
        <div className="panel-header">
          {title ? <h3>{title}</h3> : <span />}
          {action}
        </div>
      ) : null}
      <div className="panel-body">{children}</div>
    </section>
  );
}
