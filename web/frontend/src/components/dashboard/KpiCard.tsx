import type { ReactNode } from "react";
import { Link } from "react-router-dom";

interface KpiCardProps {
  label: string;
  value: ReactNode;
  description: ReactNode;
  status?: ReactNode;
  accent?: boolean;
  /** 지정하면 카드 전체가 해당 목록으로 가는 링크가 된다. */
  to?: string;
}

export function KpiCard({ label, value, description, status, accent = false, to }: KpiCardProps) {
  const className = `dashboard-kpi ${accent ? "is-accent" : ""} ${to ? "is-linked" : ""}`.replace(/\s+/g, " ").trim();
  const body = (
    <>
      {to ? (
        <svg className="dashboard-kpi-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
          <path d="M5 12h13M13 6l6 6-6 6" />
        </svg>
      ) : null}
      <div className="dashboard-kpi-label">{label}</div>
      <div className="dashboard-kpi-value mono tabular-nums">{value}</div>
      <div className="dashboard-kpi-description">
        {description}
        {status ? <span className="dashboard-kpi-status">{status}</span> : null}
      </div>
    </>
  );

  if (to) {
    return <Link className={className} to={to} aria-label={label}>{body}</Link>;
  }
  return <section className={className} aria-label={label}>{body}</section>;
}
