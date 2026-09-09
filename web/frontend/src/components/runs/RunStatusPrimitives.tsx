import type { ReactNode } from "react";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";

/**
 * 실행 상태 화면(수집 실행·첨부 확보·상시 운영·산출물 감사 로그)이 공유하는
 * 표시 조각. 승인된 시안 `source/shared.tsx`의 Small·Status·Notice·Facts·
 * Section·Queue·DetailHeader·Footer·DataTable를 이 저장소의 규칙에 맞춰 옮긴
 * 것이다. 값은 만들지 않고 받은 것만 그린다.
 *
 * 이 화면 안에서만 쓰며 `components/common`에 올리지 않는다. 다른 화면이 같은
 * 이름을 쓰면 그때 공용으로 승격할지 판단한다(파일 소유 경계).
 */

/** 12px 보조 문구. 이보다 작은 글자는 두지 않는다(`styles/typography.css`). */
export function Caption({ children, as = "p" }: { children: ReactNode; as?: "p" | "span" }) {
  return (
    <Text className="rs-caption" as={as} type="supporting" color="secondary">
      {children}
    </Text>
  );
}

/** 상태 표식의 의미색.
 *
 * 성공·실패 의미색은 **종결된 처리 상태에만** 붙인다. 참조 실행·품질 미측정·
 * mock 참조 같은 비측정 표식과 "미확인"에는 붙이지 않는다(ADR-0050,
 * IMPLEMENTATION-CONTRACT §상태와 행동). */
const TONE_RED = ["실패", "미달", "차단", "거절"];
const TONE_ORANGE = ["부분 성공", "확인 필요", "중단됨", "중단", "건너뜀", "중지 요청"];
const TONE_GREEN = ["성공", "통과", "완료"];

export function StatusToken({ label, description }: { label: string; description?: string }) {
  const color = TONE_RED.includes(label)
    ? "red"
    : TONE_ORANGE.includes(label)
      ? "orange"
      : TONE_GREEN.includes(label)
        ? "green"
        : "gray";
  return <Token size="sm" label={label} color={color} description={description} />;
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

export interface RecordItem {
  id: string;
  title: string;
  subtitle: ReactNode;
  meta?: ReactNode;
  status?: string;
  statusDescription?: string;
}

/** 목록 행. 제목 15px semibold · 보조 14px · 캡션 12px (시안 고정 기준). */
export function ListRecord({
  item,
  selected,
  onSelect,
}: {
  item: RecordItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button className="rs-record" type="button" aria-pressed={selected} onClick={onSelect}>
      <span className="rs-row rs-spread">
        <Text className="rs-record-title" as="span" weight="semibold">{item.title}</Text>
        {item.status ? <StatusToken label={item.status} description={item.statusDescription} /> : null}
      </span>
      <Text className="rs-record-subtitle" as="span">{item.subtitle}</Text>
      {item.meta ? <Caption as="span">{item.meta}</Caption> : null}
    </button>
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
  status?: string;
  statusDescription?: string;
  children?: ReactNode;
}) {
  return (
    <header className="rs-detail-head">
      <div className="rs-row rs-spread">
        <Caption as="span">{eyebrow}</Caption>
        {status ? <StatusToken label={status} description={statusDescription} /> : null}
      </div>
      <Heading level={2}>{title}</Heading>
      {children}
    </header>
  );
}

/** 상세 바닥의 고정 액션. 본문 스크롤과 분리된다. */
export function DetailFooter({ note, children }: { note: ReactNode; children?: ReactNode }) {
  return (
    <footer className="rs-detail-foot">
      <Caption>{note}</Caption>
      {children ? <div className="rs-detail-actions">{children}</div> : null}
    </footer>
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
