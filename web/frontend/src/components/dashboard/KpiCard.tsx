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
      <div className="dashboard-kpi-label">{label}</div>
      <div className="dashboard-kpi-value mono tabular-nums">{value}</div>
      <div className="dashboard-kpi-description">
        {description}
        {status ? <span className="dashboard-kpi-status">{status}</span> : null}
      </div>
    </>
  );

  if (to) {
    return <Link className={className} to={to}>{body}</Link>;
  }
  return <section className={className} aria-label={label}>{body}</section>;
}
