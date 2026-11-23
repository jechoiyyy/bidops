import type { ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { DialogHeader } from "@astryxdesign/core/Dialog";
import { Dialog } from "../common/WorkspaceDialog";
import { Heading } from "@astryxdesign/core/Heading";
import { Table, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Tab } from "@astryxdesign/core/TabList";
import { Text } from "@astryxdesign/core/Text";
import { AdminListHeader, AdminRecordTable, type AdminRecord } from "../common/AdminRecordTable";
import { SideFacts } from "../common/Facts";
import { StatusMark, type Mark, type MarkTone } from "../common/Marks";
import { DetailTabs as WorkbenchDetailTabs } from "../common/ReviewPrimitives";
import { AlertCircle, LoaderCircle, Search } from "lucide-react";

export function Small({ children, className }: { children: ReactNode; className?: string }) {
  return <Text as="span" className={`crit-small${className ? ` ${className}` : ""}`} color="secondary">{children}</Text>;
}

/**
 * 64자 digest가 들어 있는 식별자를 요약 줄에서 줄여 적는다.
 *
 * `company-profile.sha256:<64hex>`를 통째로 한 줄에 넣으면 요약 줄이 두 줄로
 * 접히면서 목록·상세의 높이를 먹는다. **값을 바꾸지는 않는다** — 앞뒤를 남겨
 * 서로 다른 사본을 구별할 수 있게 하고, 전문은 사본 정보 창과 `title` 속성에
 * 그대로 둔다.
 */
export function shortIdentifier(value: string): string {
  return value.length <= 34 ? value : `${value.slice(0, 26)}…${value.slice(-6)}`;
}

export function StatusToken({ label, tone = "neutral" }: { label: string; tone?: MarkTone }) {
  return <StatusMark mark={{ label, tone }} />;
}

export function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="crit-section">
      <div className="crit-section-head">
        <Heading level={3}>{title}</Heading>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Facts({ items }: { items: [string, ReactNode][] }) {
  return <SideFacts items={items.map(([label, value]) => ({ label, value }))} />;
}

export function DialogFacts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="crit-facts">
      {items.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}
    </dl>
  );
}

export function Note({ title, children, tone = "neutral", action, role }: {
  title: string;
  children?: ReactNode;
  tone?: "neutral" | "warning" | "error";
  action?: ReactNode;
  role?: "note" | "alert" | "status";
}) {
  return (
    <div className="crit-note" data-tone={tone} role={role ?? "note"}>
      <div className="crit-note-copy">
        <Text weight="semibold">{title}</Text>
        {children ? <Small>{children}</Small> : null}
      </div>
      {action}
    </div>
  );
}

export function StatLine({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="crit-stat-line">
      {items.map(([term, value]) => (
        <div key={term}>
          <Small>{term}</Small>
          <Text as="span" className="crit-stat-value">{value}</Text>
        </div>
      ))}
    </div>
  );
}

export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="crit-disclosure">
      <summary>{summary}</summary>
      <div className="crit-disclosure-body">{children}</div>
    </details>
  );
}

export function Queue({ title, count, items, selectedId, onSelect, footer, tools, emptyText, identifierWidth }: {
  title: string;
  /** 목록 머리의 건수. 조회 실패·미확인은 `null`로 넘겨 0건으로 접지 않는다. */
  count: number | null;
  items: AdminRecord<string>[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  footer: ReactNode;
  tools?: ReactNode;
  emptyText: string;
  identifierWidth?: number;
}) {
  return (
    <section aria-label={title} className="review-split-list">
      <AdminListHeader
        title={title}
        count={count === null ? "건수 미확인" : `${count.toLocaleString("ko-KR")}건`}
        toolsClassName="crit-queue-tools"
      >
        {tools}
      </AdminListHeader>
      <AdminRecordTable
        label={title}
        identifierWidth={identifierWidth}
        onSelect={onSelect}
        rows={items}
        selectedId={selectedId}
        state={{ kind: "empty", message: { title: emptyText } }}
      />
      <footer className="workbench-admin-list-foot crit-pane-foot"><Small>{footer}</Small></footer>
    </section>
  );
}

export function DetailHeader({ eyebrow, title, status, children }: {
  eyebrow: ReactNode;
  title: string;
  status?: Mark;
  children?: ReactNode;
}) {
  return (
    <header className="crit-detail-head">
      <div className="crit-detail-eyebrow-row">
        <Small>{eyebrow}</Small>
        {status ? <StatusMark mark={status} /> : null}
      </div>
      <Heading level={2}>{title}</Heading>
      {children}
    </header>
  );
}

export function DetailTabs({ id, value, onChange, items }: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  items: [string, string][];
}) {
  return (
    <WorkbenchDetailTabs onChange={onChange} value={value}>
      {items.map(([tabValue, label]) => <Tab key={tabValue} label={label} panelId={`${id}-${tabValue}`} value={tabValue} />)}
    </WorkbenchDetailTabs>
  );
}

/** 표 한 벌. 머리글과 셀만 받는다 — 셀의 의미는 부르는 쪽이 정한다. */
export function DataTable({ headings, rows, caption, firstColumnWeight = 0.8 }: {
  headings: string[];
  rows: ReactNode[][];
  caption?: string;
  firstColumnWeight?: number;
}) {
  interface Row extends Record<string, unknown> { id: number; cells: ReactNode[] }
  const columns: TableColumn<Row>[] = headings.map((header, index) => ({
    key: `col${index}`,
    header,
    width: proportional(index === 0 ? firstColumnWeight : 1),
    renderCell: (row: Row) => row.cells[index],
  }));
  return (
    <Table
      aria-label={caption}
      columns={columns}
      data={rows.map((cells, id) => ({ id, cells }))}
      density="compact"
      dividers="rows"
      idKey="id"
      verticalAlign="top"
    />
  );
}

export function StateView({ kind, title, description, action }: {
  kind: "loading" | "error" | "empty";
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="crit-state" role={kind === "error" ? "alert" : "status"}>
      {kind === "loading" ? <LoaderCircle aria-hidden="true" /> : kind === "error" ? <AlertCircle aria-hidden="true" /> : <Search aria-hidden="true" />}
      <Heading level={2}>{title}</Heading>
      <Text as="p" className="crit-state-body">{description}</Text>
      {action}
    </div>
  );
}

/**
 * 축약하지 않은 폼과 확인 절차가 사는 자리.
 *
 * 시안이 줄여 그린 폼도 기존 계약의 전체 양식으로 들어간다. 대화상자를 닫는 것은
 * 취소이며, 저장·평가·활성화는 각 폼의 확인 단추만 수행한다.
 */
export function CriteriaDialog({ open, title, onClose, children, width = 620 }: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  width?: number;
}) {
  return (
    <Dialog isOpen={open} maxHeight="90dvh" onOpenChange={(next) => { if (!next) onClose(); }} padding={6} purpose="form" width={width}>
      <div className="crit-dialog" data-astryx-theme="bidops">
        <DialogHeader onOpenChange={(next) => { if (!next) onClose(); }} title={title} />
        {children}
      </div>
    </Dialog>
  );
}

export function DialogActions({ children }: { children: ReactNode }) {
  return <div className="crit-dialog-actions">{children}</div>;
}

export function CancelButton({ onClick, label = "취소", isDisabled = false }: { onClick: () => void; label?: string; isDisabled?: boolean }) {
  return <Button isDisabled={isDisabled} label={label} onClick={onClick} size="sm" />;
}
