import type { ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Heading } from "@astryxdesign/core/Heading";
import { Table, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { AlertCircle, LoaderCircle, Search } from "lucide-react";

/**
 * 판정 기준 화면 네 탭이 함께 쓰는 조각.
 *
 * 승인된 시안(`design-previews/bidops-criteria-runstatus-erp-20260907/source/shared.tsx`)의
 * 구조·정보 순서를 그대로 옮기고 이름만 이 저장소 규칙으로 바꿨다. 값은 넣지 않고
 * 표시만 한다 — 어떤 상태를 무슨 말로 부를지는 각 탭이 API 응답에서 정한다.
 */

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

/**
 * 상태 표식.
 *
 * 성공·실패 의미색은 서버가 실제로 통과/미달을 말한 값에만 붙인다. 미측정·보류·
 * 계산 불가·미확인·참조 실행은 성공도 실패도 아니므로 중립색으로 두고
 * (`web/frontend/AGENTS.md` "상태 표현"), 색이 아니라 글자가 상태를 말한다.
 */
// 승인 시안 `shared.tsx`의 `Status`와 같은 배정이다. 프로필의 `확정`·`추정`은
// 판정의 성공·실패가 아니라 자료의 확인 단계이므로 의미색을 붙이지 않는다 —
// 초록 `확정`은 "게이트를 통과했다"로 잘못 읽힌다.
const POSITIVE = new Set(["통과", "성공", "측정 통과"]);
const NEGATIVE = new Set(["실패", "미달"]);
const CAUTION = new Set(["부분 성공", "확인 필요"]);

export function StatusToken({ label, size = "sm" }: { label: string; size?: "sm" | "md" }) {
  const color = POSITIVE.has(label) ? "green" : NEGATIVE.has(label) ? "red" : CAUTION.has(label) ? "orange" : "gray";
  return <Token color={color} label={label} size={size} />;
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

export interface QueueItem extends Record<string, unknown> {
  id: string;
  title: string;
  subtitle?: ReactNode;
  meta?: ReactNode;
  status?: string;
}

export function Queue({ title, count, items, selectedId, onSelect, footer, tools, emptyText }: {
  title: string;
  /** 목록 머리의 건수. 조회 실패·미확인은 `null`로 넘겨 0건으로 접지 않는다. */
  count: number | null;
  items: QueueItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  footer: ReactNode;
  tools?: ReactNode;
  emptyText: string;
}) {
  const columns: TableColumn<QueueItem>[] = [{
    key: "record",
    header: title,
    width: proportional(1),
    renderCell: (item) => (
      <button aria-pressed={selectedId === item.id} className="crit-record" onClick={() => onSelect(item.id)} type="button">
        <span className="crit-record-line">
          <Text as="span" className="crit-record-title">{item.title}</Text>
          {item.status ? <StatusToken label={item.status} /> : null}
        </span>
        {item.subtitle ? <Text as="span" className="crit-record-subtitle">{item.subtitle}</Text> : null}
        {item.meta ? <Small>{item.meta}</Small> : null}
      </button>
    ),
  }];
  return (
    <section aria-label={title} className="crit-queue">
      <header className="crit-pane-head">
        <Text weight="semibold">{title}</Text>
        <Small>{count === null ? "건수 미확인" : `${count.toLocaleString("ko-KR")}건`}</Small>
      </header>
      {tools ? <div className="crit-queue-tools">{tools}</div> : null}
      <div className="crit-queue-scroll">
        {items.length > 0 ? (
          <Table columns={columns} data={items} density="compact" dividers="rows" hasHover idKey="id" verticalAlign="top" />
        ) : (
          <div className="crit-empty-inline">
            <Search aria-hidden="true" />
            <Text as="p">{emptyText}</Text>
          </div>
        )}
      </div>
      <footer className="crit-pane-foot"><Small>{footer}</Small></footer>
    </section>
  );
}

export function DetailHeader({ eyebrow, title, status, children }: {
  eyebrow: ReactNode;
  title: string;
  status?: string;
  children?: ReactNode;
}) {
  return (
    <header className="crit-detail-head">
      <div className="crit-detail-eyebrow-row">
        <Small>{eyebrow}</Small>
        {status ? <StatusToken label={status} /> : null}
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
    <div className="crit-detail-tabs">
      <TabList hasDivider onChange={onChange} role="tablist" size="md" value={value}>
        {items.map(([tabValue, label]) => <Tab key={tabValue} label={label} panelId={`${id}-${tabValue}`} value={tabValue} />)}
      </TabList>
    </div>
  );
}

export function DetailFooter({ note, children }: { note: ReactNode; children?: ReactNode }) {
  return (
    <footer className="crit-detail-foot">
      <span className="crit-detail-foot-note"><Small>{note}</Small></span>
      {children ? <div className="crit-detail-foot-actions">{children}</div> : null}
    </footer>
  );
}

/** 표 한 벌. 머리글과 셀만 받는다 — 셀의 의미는 부르는 쪽이 정한다. */
export function DataTable({ headings, rows, caption }: { headings: string[]; rows: ReactNode[][]; caption?: string }) {
  interface Row extends Record<string, unknown> { id: number; cells: ReactNode[] }
  const columns: TableColumn<Row>[] = headings.map((header, index) => ({
    key: `col${index}`,
    header,
    width: proportional(index === 0 ? 0.8 : 1),
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
