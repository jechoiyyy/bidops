import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import type { BidDeltaDecisionQueueResponse, OpportunityListResponse } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { EmptyState } from "../common/EmptyState";
import { SkeletonPanel } from "../common/Skeleton";
import { Small, Tag } from "./DashboardPrimitives";
import { DEADLINE_IMMINENT_DAYS } from "./dashboardData";
import { buildAgenda, finalAgendaItem, trackingAgendaItem, type AgendaItem, type ChainStep } from "./agendaModel";

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

function AgendaRow({ item }: { item: AgendaItem }) {
  return <li className="dash-agenda-item" data-kind={item.kind}>
    <div className="dash-agenda-main">
      <Link className="dash-agenda-title" to={item.to} title={item.title}>{item.title}</Link>
      <Small>{`${item.agency} · ${item.amount}`}</Small>
    </div>
    <Chain steps={item.chain} />
    <div className="dash-agenda-time">
      <strong>{item.time ?? "시각 미확인"}</strong>
      <Small>{item.deadlineKind}</Small>
    </div>
    <div className="dash-agenda-status">
      <Tag label={item.status} tone={item.kind === "final" ? "warning" : "neutral"} />
      {item.statusNote ? <Small className="dash-agenda-note">{item.statusNote}</Small> : null}
    </div>
  </li>;
}

/**
 * 추적 중인 사업의 마감 일정. 마감 임박 추적 건과 최종 Go/No-Go 대기 두 목록을
 * 날짜별로 함께 그린다. 한 목록이 실패해도 다른 목록의 행은 보인다.
 */
export function DeadlineAgenda({ tracking, final, now }: {
  tracking: AgendaSource<OpportunityListResponse>;
  final: AgendaSource<BidDeltaDecisionQueueResponse>;
  now: number;
}) {
  const trackingItems = tracking.isPending || tracking.isError ? [] : (tracking.data?.items ?? []).map(item => trackingAgendaItem(item, now));
  const finalItems = final.isPending || final.isError ? [] : (final.data?.items ?? []).map(finalAgendaItem);
  const entries = buildAgenda([...trackingItems, ...finalItems], now);
  const settled = !tracking.isPending && !final.isPending && !tracking.isError && !final.isError;

  const notes: { key: string; text: string; retry?: () => void; alert?: boolean }[] = [];
  for (const [key, name, source, shown] of [
    ["tracking", "마감 임박 추적 건", tracking, trackingItems.length],
    ["final", "최종 결정 대기", final, finalItems.length],
  ] as const) {
    if (source.isError) notes.push({ key, text: `${name} 목록을 불러오지 못했어요.`, retry: source.onRetry, alert: true });
    else if (source.isPending) notes.push({ key, text: `${name} 목록을 불러오는 중이에요.` });
    else if ((source.data?.total ?? 0) > shown) {
      notes.push({ key, text: `${name} ${formatNumber(source.data?.total)}건 중 ${formatNumber(shown)}건을 보여요.` });
    }
  }

  let body;
  if (entries.length === 0 && settled) {
    body = <EmptyState compact title="이번 주 마감인 추적 사업이 없어요" description={`${DEADLINE_IMMINENT_DAYS}일 이내 마감 추적 건과 최종 결정 대기가 비어 있어요.`} />;
  } else if (entries.length === 0 && (tracking.isPending || final.isPending) && !tracking.isError && !final.isError) {
    body = <SkeletonPanel withTitle={false} lines={4} label="마감 일정을 불러오는 중" />;
  } else {
    body = <ol className="dash-agenda" aria-label="마감 일정">
      {entries.map(entry => {
        if (entry.type === "gap") return <li className="dash-agenda-day is-gap" data-entry="gap" key={entry.key}>
          <div className="dash-agenda-rail"><strong>{entry.label}</strong></div>
          <Small className="dash-agenda-gap-text">마감 없음</Small>
        </li>;
        const rail = entry.type === "day"
          ? <div className="dash-agenda-rail">
            <strong>{entry.date}</strong>
            <Small>{entry.weekday}</Small>
            <span className={entry.urgent ? "dash-agenda-due is-urgent" : "dash-agenda-due"}>{entry.due}</span>
          </div>
          : <div className="dash-agenda-rail"><strong>마감 미확인</strong></div>;
        return <li className="dash-agenda-day" data-entry={entry.type} key={entry.key}>
          {rail}
          <ul className="dash-agenda-items">{entry.items.map(item => <AgendaRow item={item} key={item.key} />)}</ul>
        </li>;
      })}
    </ol>;
  }

  return <div className="dash-agenda-body">
    {body}
    {notes.map(note => <div className="dash-agenda-status-line" data-source={note.key} key={note.key} role={note.alert ? "alert" : "status"}>
      <span>{note.text}</span>
      {note.retry ? <Button label="다시 시도" onClick={note.retry} size="sm" variant="ghost" /> : null}
    </div>)}
  </div>;
}
