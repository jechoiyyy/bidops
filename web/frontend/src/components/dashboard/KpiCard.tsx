import type { ReactNode } from "react";

interface KpiCardProps {
  label: string;
  value: ReactNode;
  description: ReactNode;
  status?: ReactNode;
  accent?: boolean;
}

export function KpiCard({ label, value, description, status, accent = false }: KpiCardProps) {
  return (
    <section className={`dashboard-kpi ${accent ? "is-accent" : ""}`.trim()} aria-label={label}>
      <div className="dashboard-kpi-label">{label}</div>
      <div className="dashboard-kpi-value mono tabular-nums">{value}</div>
      <div className="dashboard-kpi-description">
        {description}
        {status ? <span className="dashboard-kpi-status">{status}</span> : null}
      </div>
    </section>
  );
}
