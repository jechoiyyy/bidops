import type { ReactNode } from "react";

interface PanelProps {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, action, children, className = "" }: PanelProps) {
  return (
    <section className={`panel ${className}`.trim()}>
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
