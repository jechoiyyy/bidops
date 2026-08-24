import type { ReactNode } from "react";

export interface FactItem {
  label: string;
  value: ReactNode;
}

interface FactsProps {
  items: FactItem[];
  className?: string;
  fallback?: string;
}

function normalizeValue(value: ReactNode, fallback: string): ReactNode {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "boolean") return value ? "예" : "아니오";
  return value;
}

export function Facts({ items, className = "", fallback = "값 없음" }: FactsProps) {
  return (
    <dl className={`facts ${className}`.trim()}>
      {items.map((item) => (
        <div className="fact-row" key={item.label}>
          <dt>{item.label}</dt>
          <dd>{normalizeValue(item.value, fallback)}</dd>
        </div>
      ))}
    </dl>
  );
}
