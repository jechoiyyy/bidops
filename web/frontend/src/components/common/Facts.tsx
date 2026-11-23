import type { ReactNode } from "react";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";

interface FactItem {
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

export function SideFacts(props: FactsProps) {
  return <WorkbenchFacts {...props} columns="single" />;
}

export function GridFacts({ columns, ...props }: FactsProps & { columns: 2 | 3 }) {
  return <WorkbenchFacts {...props} columns={columns} />;
}

function WorkbenchFacts({ items, className = "", fallback = "값 없음", columns }: FactsProps & { columns: "single" | 2 | 3 }) {
  return (
    <div className={`workbench-facts ${className}`.trim()}>
      <MetadataList columns={columns} label={columns === "single" ? { position: "start", width: 108 } : { position: "top" }}>
        {items.map((item) => (
          <MetadataListItem key={item.label} label={item.label}>
            {normalizeValue(item.value, fallback)}
          </MetadataListItem>
        ))}
      </MetadataList>
    </div>
  );
}
