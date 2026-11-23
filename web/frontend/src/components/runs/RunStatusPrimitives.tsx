import type { ReactNode } from "react";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { SideFacts } from "../common/Facts";
import { StatusMark, type Mark, type MarkTone } from "../common/Marks";

export function Caption({ children, as = "p" }: { children: ReactNode; as?: "p" | "span" }) {
  return (
    <Text className="rs-caption" as={as} type="supporting" color="secondary">
      {children}
    </Text>
  );
}

export function StatusToken({ label, tone = "neutral", description }: { label: string; tone?: MarkTone; description?: string }) {
  return <StatusMark mark={{ label, tone }} description={description} />;
}

export function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rs-section">
      <div className="rs-section-head">
        <Heading level={3}>{title}</Heading>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Facts({ items }: { items: Array<[string, ReactNode]> }) {
  return <SideFacts items={items.map(([label, value]) => ({ label, value }))} />;
}

export function DialogFacts({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <dl className="rs-facts">
      {items.map(([term, value]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 맥락 주석. 항상 켜져 있던 경계 패널을 대신해 관련 내용 옆에 놓는다. */
export function Note({
  title,
  tone = "neutral",
  action,
  children,
  role,
}: {
  title: string;
  tone?: "neutral" | "warning" | "error";
  action?: ReactNode;
  children?: ReactNode;
  role?: "note" | "alert" | "status";
}) {
  const toneClass = tone === "warning" ? " is-warning" : tone === "error" ? " is-error" : "";
  return (
    <div className={`rs-note${toneClass}`} role={role ?? (tone === "error" ? "alert" : "note")}>
      <div className="rs-note-copy">
        <strong>{title}</strong>
        {children ? <Caption>{children}</Caption> : null}
      </div>
      {action}
    </div>
  );
}

export function DetailHeader({
  eyebrow,
  title,
  status,
  statusDescription,
  children,
}: {
  eyebrow: ReactNode;
  title: string;
  status?: Mark;
  statusDescription?: string;
  children?: ReactNode;
}) {
  return (
    <header className="rs-detail-head">
      <div className="rs-row rs-spread">
        <Caption as="span">{eyebrow}</Caption>
        {status ? <StatusMark mark={status} description={statusDescription} /> : null}
      </div>
      <Heading level={2}>{title}</Heading>
      {children}
    </header>
  );
}

export function DataTable({
  caption,
  headings,
  rows,
}: {
  caption: string;
  headings: string[];
  rows: Array<{ id: string; cells: ReactNode[] }>;
}) {
  return (
    <div className="rs-table-scroll">
      <table className="rs-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>{headings.map((heading) => <th key={heading} scope="col">{heading}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>{row.cells.map((cell, index) => <td key={`${row.id}-${headings[index] ?? index}`}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
