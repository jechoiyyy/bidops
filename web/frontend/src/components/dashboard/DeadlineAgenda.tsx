import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import type { BidDeltaDecisionQueueResponse, OpportunityListResponse } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { EmptyState } from "../common/EmptyState";
import { SkeletonPanel } from "../common/Skeleton";
import { Small, Tag } from "./DashboardPrimitives";
import { DEADLINE_IMMINENT_DAYS } from "./dashboardData";
import { buildAgenda, mergeAgendaSources, type AgendaItem, type ChainStep } from "./agendaModel";

/** 펼치지 않았을 때 보이는 행 수. 가까운 마감부터 채우고, 나머지 날은 건수와 `보기` 버튼만 남는다. */
export const AGENDA_ROW_BUDGET = 5;
/** 전체가 이 수 이하이면 접지 않고 모두 보인다. */
export const AGENDA_SHOW_ALL_MAX = 8;

export interface AgendaSource<Data> {
  data: Data | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
}

function Chain({ steps }: { steps: ChainStep[] }) {
  if (!steps.length) return <Small className="dash-agenda-chain-empty">단계 미확인</Small>;
  return <ol className="dash-agenda-chain" aria-label="단계 진행">
    {steps.map(step => <li className="dash-agenda-step" data-state={step.state} key={step.key}>
      {step.label}
      {step.state === "linked" ? <><span aria-hidden="true"> ✓</span><span className="visually-hidden"> 연결됨</span></> : null}
      {step.state === "current" ? <span className="visually-hidden"> 지금 단계</span> : null}
      {step.state === "absent" ? <span className="visually-hidden"> 아직 없음</span> : null}
    </li>)}
  </ol>;
}

/** 한 날의 행이 모두 같은 마감 종류면 그 종류. 날짜 칸에 한 번만 적고 행에서는 뺀다. */
function sharedKind(items: AgendaItem[]): string | null {
  const kinds = new Set(items.map(item => item.deadlineKind));
  return kinds.size === 1 ? items[0].deadlineKind : null;
}

function AgendaRow({ item, now, showKind = true }: { item: AgendaItem; now: number; showKind?: boolean }) {
  const passed = item.deadlineAt !== null && Date.parse(item.deadlineAt) < now;
  return <li className="dash-agenda-item" data-kind={item.kind}>
    <div className="dash-agenda-main">
      <Link className="dash-agenda-title" to={item.to} title={item.title}>{item.title}</Link>
      <Small>{`${item.agency} · ${item.amount}`}</Small>
    </div>
    <Chain steps={item.chain} />
    <div className="dash-agenda-time">
      <strong>{item.time ?? "시각 미확인"}</strong>
      {passed ? <Small>{`${item.deadlineKind} 지남`}</Small> : showKind ? <Small>{item.deadlineKind}</Small> : null}
    </div>
    <div className="dash-agenda-status">
      <Tag label={item.status} tone={item.statusTone} />
      {item.statusNote ? <Small className="dash-agenda-note">{item.statusNote}</Small> : null}
    </div>
  </li>;
}

/**
 * 추적 중인 사업의 마감 일정. 마감 임박 추적 건과 최종 Go/No-Go 대기를 한 일정으로 합치고
 * (같은 사업은 한 행), 가까운 마감부터 `AGENDA_ROW_BUDGET`행만 펼친다. 한 목록이 실패해도
 * 다른 목록의 행은 보인다.
 */
export function DeadlineAgenda({ tracking, final, now }: {
  tracking: AgendaSource<OpportunityListResponse>;
  final: AgendaSource<BidDeltaDecisionQueueResponse>;
  now: number;
}) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (key: string) => setExpanded(current => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const trackingData = tracking.isPending || tracking.isError ? [] : tracking.data?.items ?? [];
  const finalData = final.isPending || final.isError ? [] : final.data?.items ?? [];
  const merged = mergeAgendaSources(trackingData, finalData, now, DEADLINE_IMMINENT_DAYS);
  const entries = buildAgenda(merged.items, now);
  const settled = !tracking.isPending && !final.isPending && !tracking.isError && !final.isError;

  const notes: { key: string; text: string; retry?: () => void; alert?: boolean; link?: { to: string; label: string } }[] = [];
  for (const [key, name, source] of [["tracking", "마감 임박 추적 건", tracking], ["final", "최종 결정 대기", final]] as const) {
    if (source.isError) notes.push({ key, text: `${name} 목록을 불러오지 못했어요.`, retry: source.onRetry, alert: true });
    else if (source.isPending) notes.push({ key, text: `${name} 목록을 불러오는 중이에요.` });
  }
  if (!tracking.isPending && !tracking.isError && (tracking.data?.total ?? 0) > trackingData.length) {
    notes.push({
      key: "tracking-more",
      text: `마감 임박 추적 건 ${formatNumber(tracking.data?.total)}건 중 마감이 가까운 ${formatNumber(trackingData.length)}건을 받았어요.`,
      link: { to: `/opportunities?section=전체&deadline_within_days=${DEADLINE_IMMINENT_DAYS}&sort=deadline`, label: "사업기회에서 모두 보기" },
    });
  }
  if (!final.isPending && !final.isError && (merged.finalPast > 0 || merged.finalOutside > 0)) {
    const parts = [
      merged.finalPast > 0 ? `마감 지남 ${formatNumber(merged.finalPast)}건` : null,
      merged.finalOutside > 0 ? `${DEADLINE_IMMINENT_DAYS}일 밖·마감 미제공 ${formatNumber(merged.finalOutside)}건` : null,
    ].filter(Boolean).join(" · ");
    const unread = (final.data?.total ?? 0) > finalData.length ? ` (대기열 ${formatNumber(final.data?.total)}건 중 ${formatNumber(finalData.length)}건 기준)` : "";
    notes.push({ key: "final-outside", text: `일정 밖 최종 결정 대기: ${parts}${unread}`, link: { to: "/go-no-go", label: "최종 Go/No-Go에서 보기" } });
  }

  let body;
  if (entries.length === 0 && settled) {
    body = <EmptyState compact title="이번 주 마감인 추적 사업이 없어요" description={`${DEADLINE_IMMINENT_DAYS}일 이내 마감 추적 건과 최종 결정 대기가 비어 있어요.`} />;
  } else if (entries.length === 0 && (tracking.isPending || final.isPending) && !tracking.isError && !final.isError) {
    body = <SkeletonPanel withTitle={false} lines={4} label="마감 일정을 불러오는 중" />;
  } else {
    let budget = merged.items.length <= AGENDA_SHOW_ALL_MAX ? merged.items.length : AGENDA_ROW_BUDGET;
    body = <ol className="dash-agenda" aria-label="마감 일정">
      {entries.map(entry => {
        if (entry.type === "gap") return <li className="dash-agenda-day is-gap" data-entry="gap" key={entry.key}>
          <div className="dash-agenda-rail"><strong>{entry.label}</strong></div>
          <Small className="dash-agenda-gap-text">마감 없음</Small>
        </li>;
        const open = expanded.has(entry.key);
        const visible = open ? entry.items.length : Math.min(entry.items.length, Math.max(budget, 0));
        budget -= visible;
        const hidden = entry.items.length - visible;
        const count = <Small className="dash-agenda-count">{`${formatNumber(entry.items.length)}건`}</Small>;
        const kind = entry.type === "day" ? sharedKind(entry.items) : null;
        const rail = entry.type === "day"
          ? <div className="dash-agenda-rail">
            <span className="dash-agenda-date"><strong>{entry.date}</strong><Small>{entry.weekday}</Small></span>
            <span className="dash-agenda-meta">
              <span className={entry.urgent ? "dash-agenda-due is-urgent" : "dash-agenda-due"}>{entry.due}</span>
              {count}
            </span>
            {kind ? <Small className="dash-agenda-kind">{kind}</Small> : null}
          </div>
          : <div className="dash-agenda-rail"><span className="dash-agenda-date"><strong>마감 미확인</strong></span><span className="dash-agenda-meta">{count}</span></div>;
        return <li className={visible === 0 ? "dash-agenda-day is-folded" : "dash-agenda-day"} data-entry={entry.type} key={entry.key}>
          {rail}
          <ul className="dash-agenda-items">
            {entry.items.slice(0, visible).map(item => <AgendaRow item={item} now={now} showKind={kind === null} key={item.key} />)}
            {hidden > 0 || open ? <li className="dash-agenda-more">
              <Button size="sm" variant="ghost" onClick={() => toggle(entry.key)}
                label={open ? "접기" : visible === 0 ? `${formatNumber(hidden)}건 보기` : `${formatNumber(hidden)}건 더 보기`} />
            </li> : null}
          </ul>
        </li>;
      })}
    </ol>;
  }

  return <div className="dash-agenda-body">
    {body}
    {notes.map(note => <div className="dash-agenda-status-line" data-source={note.key} key={note.key} role={note.alert ? "alert" : "status"}>
      <span>{note.text}</span>
      {note.link ? <Link to={note.link.to}>{note.link.label}</Link> : null}
      {note.retry ? <Button label="다시 시도" onClick={note.retry} size="sm" variant="ghost" /> : null}
    </div>)}
  </div>;
}
