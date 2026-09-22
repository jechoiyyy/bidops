import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Text } from "@astryxdesign/core/Text";
import { ArrowRight } from "lucide-react";
import type {
  BidDeltaDecisionQueueItem,
  BidDeltaDecisionQueueResponse,
  OpportunityListResponse,
  OrderPlanListItem,
  OrderPlanListResponse,
  PreSpecListItem,
  PreSpecListResponse,
} from "../../lib/types";
import { formatPrice } from "../../lib/format";
import { EmptyState } from "../common/EmptyState";
import { SkeletonPanel } from "../common/Skeleton";
import { budgetValue, plannedTiming, qwenRowLabel } from "../order-plans/orderPlanFormat";
import { primaryTitle } from "../opportunities/trackingFlow";
import { DashboardPanel, LinkButton, Small, Tag } from "./DashboardPrimitives";
import { WORK_PANEL_LIMIT, imminentDeadline, queueDeadlineLabel } from "./dashboardData";

/**
 * 회차 없이 완결되는 누적 업무 패널들(시안 M6 승인 2026-09-22, ADR-0067).
 *
 * 지키는 것:
 * - **건수와 목록은 서로 다른 요청이다.** 건수는 `/api/workload`의 키 하나가 내고
 *   목록은 짝지은 목록 API 한 번이 낸다. 화면은 건수를 목록 길이로 덮지 않고,
 *   목록이 비었다고 건수를 0으로 고치지 않는다(ADR-0067 결정 1·7).
 * - 패널 하나의 조회 실패가 다른 패널을 막지 않는다. 실패는 그 패널 안에서만 알린다.
 * - 서버가 주지 않은 값(대표 마감 등)을 지어내지 않는다.
 */

/** 사업 추적 화면의 `전체` 구역 값. 기본 구역(`조치 필요`)이 목록을 더 좁히지 않게 건다. */
const ALL_SECTION = "전체";

export interface WorkPanelState {
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
}

export function WorkPanel({
  title, caption, to, linkLabel, state, rows, emptyTitle, errorTitle, footBasis, footCount, className = "",
}: {
  title: string;
  caption?: ReactNode;
  to: string;
  linkLabel: string;
  state: WorkPanelState;
  rows: ReactNode[];
  emptyTitle: string;
  errorTitle: string;
  /** 바닥 왼쪽: 이 목록의 범위와 기준. */
  footBasis: ReactNode;
  /** 바닥 오른쪽: `/api/workload`가 낸 건수 문구. 목록 길이가 아니다. */
  footCount: ReactNode;
  className?: string;
}) {
  let body: ReactNode;
  if (state.isError) {
    body = <EmptyState compact tone="error" title={errorTitle} action={{ label: "다시 시도", onClick: state.onRetry }} />;
  } else if (state.isPending) {
    body = <SkeletonPanel withTitle={false} lines={3} label={`${title} 목록을 불러오는 중`} className="dash-work-skeleton" />;
  } else if (!rows.length) {
    body = <EmptyState compact title={emptyTitle} />;
  } else {
    body = <ul className="dash-work-list">{rows}</ul>;
  }
  return <DashboardPanel title={title} caption={caption} className={`dash-work-panel ${className}`.trim()}
    action={<LinkButton label={linkLabel} to={to} icon={<ArrowRight aria-hidden="true" />} />}
    footer={<><Small>{footBasis}</Small><Small>{footCount}</Small></>}>
    {body}
  </DashboardPanel>;
}

/** 업무 패널의 행 하나. 다섯 패널이 모두 이 모양을 쓴다(보류 재검토 포함, S1). */
export function WorkRow({ to, title, meta, end }: { to: string; title: string; meta: string; end: ReactNode }) {
  return <li className="dash-work-item"><Link className="dash-work-row" to={to}>
    <div className="dash-cell-stack"><Text className="dash-work-title" weight="semibold">{title}</Text><Small>{meta}</Small></div>
    <div className="dash-work-end">{end}</div>
  </Link></li>;
}

export function DueText({ text, urgent }: { text: string; urgent: boolean }) {
  return <Text className={urgent ? "dash-work-due dash-work-due-urgent" : "dash-work-due"}>{text}</Text>;
}

/**
 * 마감 임박 추적 건. 서버가 대표 마감을 고르지 않으므로 행의 마감 종류·D-day는
 * `links[]`에서 화면이 고른다(`imminentDeadline`).
 */
export function DeadlineImminentPanel({ data, state, footBasis, footCount, now, windowDays }: {
  data: OpportunityListResponse | undefined; state: WorkPanelState;
  footBasis: ReactNode; footCount: ReactNode; now: number;
  /** 목록 호출과 링크가 함께 쓰는 창(일). 둘이 갈라지지 않게 한 값을 받는다. */
  windowDays: number;
}) {
  const rows = (data?.items ?? []).slice(0, WORK_PANEL_LIMIT).map((item) => {
    const due = imminentDeadline(item, now);
    return <WorkRow key={item.id} to={`/opportunities/${item.id}`} title={primaryTitle(item)}
      meta={`${due ? due.kind : "마감 종류 미확인"} · ${item.tracking_status}`}
      end={<DueText text={due ? `D-${due.days}` : "마감 미확인"} urgent={due?.urgent ?? false} />} />;
  });
  // 링크는 패널의 목록 호출과 **같은 조건**을 사업 추적 화면에 그대로 넘긴다(S1).
  // 구역은 `전체`로 연다 — 그 화면의 기본 구역(`조치 필요`)이 걸리면 다른 집합이 된다.
  const to = `/opportunities?section=${ALL_SECTION}&deadline_within_days=${windowDays}&sort=deadline`;
  return <WorkPanel title="마감 임박 추적 건" to={to} linkLabel="사업 추적" state={state} rows={rows}
    emptyTitle="7일 이내 마감인 추적 건이 없습니다" errorTitle="마감 임박 추적 건을 불러오지 못했습니다"
    footBasis={footBasis} footCount={footCount} />;
}

/** 최종 결정 대기. 대기열과 같은 값·같은 마감 표기를 쓴다(F3). */
export function FinalDecisionPanel({ data, state, footBasis, footCount, now }: {
  data: BidDeltaDecisionQueueResponse | undefined; state: WorkPanelState;
  footBasis: ReactNode; footCount: ReactNode; now: number;
}) {
  const rows = (data?.items ?? []).slice(0, WORK_PANEL_LIMIT).map((item: BidDeltaDecisionQueueItem) => {
    const deadline = queueDeadlineLabel(item.deadline_at, now);
    // `formatPrice`의 null 표기가 이미 "추정가격"을 품으므로 값이 있을 때만 부른다.
    const price = item.estimated_price === null ? "미제공" : formatPrice(Number(item.estimated_price));
    return <WorkRow key={item.opportunity_id} to={`/go-no-go?selected=${item.opportunity_id}`}
      title={item.title?.trim() || "제목 미확인"}
      meta={`${item.agency?.trim() || "발주기관 미확인"} · 추정가격 ${price}`}
      end={<DueText text={deadline.text} urgent={deadline.urgent} />} />;
  });
  return <WorkPanel title="최종 결정 대기" to="/go-no-go" linkLabel="최종 Go/No-Go" state={state} rows={rows}
    emptyTitle="최종 결정을 기다리는 사업이 없습니다" errorTitle="최종 결정 대기 목록을 불러오지 못했습니다"
    footBasis={footBasis} footCount={footCount} />;
}

/** 사람 확인 필요 행 하나. 개요 실패·개요 사람 확인·공고별 확인 항목을 섞지 않고 표식으로 나눈다. */
interface OverviewRow { kind: "overview_failed" | "overview_attention"; item: PreSpecListItem }
interface BlockingRow { kind: "blocking"; id: number; title: string; count: number }
type HumanCheckRow = OverviewRow | BlockingRow;

function preSpecDeadlineValue(item: PreSpecListItem): number {
  const parsed = item.deadline_at === null ? Number.NaN : Date.parse(item.deadline_at);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

/**
 * 사람 확인 필요.
 *
 * 출처가 둘이고 세는 단위도 다르다 — 개요 검토는 **사전규격 공고**, 확인 항목은
 * **사업기회**다(ADR-0067 결정 5). 그래서 합계(`human_check_required`)는 서버가 주고,
 * 화면은 바닥에 하위 건수 둘을 따로 적는다.
 */
export function HumanCheckPanel({ failed, attention, blocking, state, footBasis, footCount }: {
  failed: PreSpecListResponse | undefined;
  attention: PreSpecListResponse | undefined;
  blocking: OpportunityListResponse | undefined;
  state: WorkPanelState; footBasis: ReactNode; footCount: ReactNode;
}) {
  // 두 개요 상태는 서로 배타적이라 합쳐도 중복되지 않는다. 마감순으로 섞고 마감
  // 미제공은 맨 뒤에 둔다(목록 API의 `sort=deadline`과 같은 방향).
  const overview: OverviewRow[] = [
    ...(failed?.items ?? []).map((item): OverviewRow => ({ kind: "overview_failed", item })),
    ...(attention?.items ?? []).map((item): OverviewRow => ({ kind: "overview_attention", item })),
  ].sort((left, right) => preSpecDeadlineValue(left.item) - preSpecDeadlineValue(right.item));
  const blockingRows: BlockingRow[] = (blocking?.items ?? []).map((item) => ({
    kind: "blocking", id: item.id, title: primaryTitle(item), count: item.open_blocking_item_count,
  }));
  const merged: HumanCheckRow[] = [...overview, ...blockingRows];
  const rows = merged.slice(0, WORK_PANEL_LIMIT).map((row) => row.kind === "blocking"
    ? <WorkRow key={`opportunity-${row.id}`} to={`/opportunities/${row.id}`} title={row.title}
      meta={`공고별 확인 항목 ${row.count}건`} end={<Tag label="확인" tone="warning" />} />
    : <WorkRow key={`pre-spec-${row.kind}-${row.item.notice_pk}`} to={`/pre-specs/${row.item.notice_pk}`}
      title={row.item.title?.trim() || "제목 미확인"}
      meta={row.kind === "overview_failed" ? "개요 검토 실패" : "개요 검토 · 사람 확인 필요"}
      end={<Tag label={row.kind === "overview_failed" ? "실패" : "확인"} tone={row.kind === "overview_failed" ? "error" : "warning"} />} />);
  return <WorkPanel title="사람 확인 필요" caption="확인 항목은 추적 상태와 무관하게 셉니다." to="/pre-specs?workspace=all&sw_only=false&overview_view=attention"
    linkLabel="사전규격" state={state} rows={rows}
    emptyTitle="사람이 확인할 개요 검토와 확인 항목이 없습니다" errorTitle="사람 확인 필요 목록을 불러오지 못했습니다"
    footBasis={footBasis} footCount={footCount} />;
}

/**
 * 새 우선 검토 발주계획. `모델 판단 관련`은 `qwen_relevance=relevant` 한 값이라
 * 발주계획 타일의 `검토 후보`(`relevant,uncertain`)와 다른 집합이다(spec §7.3).
 */
export function NewPriorityOrderPlanPanel({ data, state, footBasis, footCount, newSince }: {
  data: OrderPlanListResponse | undefined; state: WorkPanelState; footBasis: ReactNode; footCount: ReactNode;
  /** 목록 호출과 링크가 함께 쓰는 `first_observed_from`(`YYYY-MM-DD`). */
  newSince: string;
}) {
  const rows = (data?.items ?? []).slice(0, WORK_PANEL_LIMIT).map((item: OrderPlanListItem) => <WorkRow
    key={item.order_plan_pk} to={`/order-plans?selected=${item.order_plan_pk}`}
    title={item.title?.trim() || "사업명 미확인"}
    meta={`${item.agency_name?.trim() || "기관 미확인"} · ${budgetValue(item.budget_amount)} · ${plannedTiming(item.planned_order_year, item.planned_order_month)}`}
    end={<Tag label={qwenRowLabel(item)} />} />);
  // 링크에 `first_observed_from`까지 넘겨야 목록 화면이 패널과 같은 창을 연다(S1).
  const to = `/order-plans?qwen=relevant&tracking=미선택&first_observed_from=${newSince}`;
  return <WorkPanel title="새 우선 검토 발주계획" to={to} linkLabel="발주계획"
    state={state} rows={rows} className="dash-work-wide"
    emptyTitle="새로 관측된 우선 검토 발주계획이 없습니다" errorTitle="새 우선 검토 발주계획을 불러오지 못했습니다"
    footBasis={footBasis} footCount={footCount} />;
}
