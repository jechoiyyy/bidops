import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Activity, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { stageLabel } from "../lib/briefing";
import type { WorkloadKey } from "../lib/types";
import { formatNumber } from "../lib/format";
import { DECISION_AXIS_LABEL, ORDER_PLAN_REVIEW_TIER_LABEL, PRE_SPEC_TERM, TERM_SENSE } from "../lib/glossary";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { DailyCollectionStatus } from "../components/operations/DailyRunStatusLine";
import { CollectionStatus } from "../components/dashboard/CollectionStatus";
import {
  opportunityActionRequiredQuery, orderPlanViewTotalQuery, preSpecDefaultViewTotalQuery,
  preSpecNeedsCheckTotalQuery, preSpecRecentTotalQuery,
} from "../lib/defaultViewCounts";
import { CountStrip, DashboardBlock, DashboardPanel, LinkButton, Small, type DashCount } from "../components/dashboard/DashboardPrimitives";
import { HoldReviewPanel } from "../components/dashboard/HoldReviewPanel";
import {
  HumanCheckPanel, NewPriorityOrderPlanPanel, TodayDecisionTable, WorkRow,
} from "../components/dashboard/WorkPanels";
import {
  DEADLINE_IMMINENT_DAYS, HOLD_REVIEW_LIMIT, HOLD_REVIEW_LIST_PATH, WORK_PANEL_LIMIT, previousKstDate, snapshotTime,
} from "../components/dashboard/dashboardData";
import "../styles/dashboard-erp.css";

// 서버가 정한 안전 코드다. 문장이 있는 코드만 옮기고 모르는 코드는 그대로 보여 준다.
const WORKLOAD_UNAVAILABLE_REASON: Record<string, string> = {
  provider_absent: "집계 모듈 없음",
  no_completed_execution: "완료된 선별 실행 없음",
  sub_count_unavailable: "하위 건수 미확인",
};

/** 업무 대기열과 원본 목록으로 연결하는 실무자 시작 화면이다. */
export function DashboardPage() {
  return <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}><DashboardWorkspace /></InternationalizationProvider>;
}

function DashboardWorkspace() {
  // D-day와 `새로`의 창은 한 번 잡은 기준 시각으로 센다. 매 렌더의 `Date.now()`를
  // query key에 넣으면 조회가 멈추지 않는다.
  const now = useMemo(() => Date.now(), []);
  const newSince = useMemo(() => previousKstDate(now), [now]);

  // 누적 업무 건수는 서버가 한 번에 준다. 브라우저에서 목록을 다시 세지 않는다.
  const workloadQuery = useQuery({ queryKey: ["workload"], queryFn: ({ signal }) => api.getWorkload({ signal }), staleTime: 60_000 });
  const collectionQuery = useQuery({
    queryKey: ["daily-collection-status"],
    queryFn: ({ signal }) => api.getDailyCollectionStatus({ signal }),
    staleTime: 30_000,
  });
  const deadlineQuery = useQuery({
    queryKey: ["opportunities", "dashboard-deadline"],
    queryFn: ({ signal }) => api.getOpportunities({ deadline_within_days: DEADLINE_IMMINENT_DAYS, sort: "deadline", limit: WORK_PANEL_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  const decisionQuery = useQuery({
    queryKey: ["bid-delta-decision-queue", "dashboard"],
    queryFn: ({ signal }) => api.getBidDeltaDecisionQueue({ status: "pending", limit: WORK_PANEL_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  // 개요 두 상태(`failed`·`needs_human_review`)는 서로 배타적이라 두 번 받아 합친다.
  // 제공자와 같은 모집단이 되도록 `sw_only=false`와 나머지 기본값(`workspace=all`·
  // `deadline_scope=all`·`review_exclusion=all`)을 그대로 쓴다(spec §7.1).
  const overviewFailedQuery = useQuery({
    queryKey: ["pre-specs", "dashboard-overview", "failed"],
    queryFn: ({ signal }) => api.getPreSpecs({ sw_only: false, overview_view: "failed", sort: "deadline", limit: WORK_PANEL_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  const overviewAttentionQuery = useQuery({
    queryKey: ["pre-specs", "dashboard-overview", "attention"],
    queryFn: ({ signal }) => api.getPreSpecs({ sw_only: false, overview_view: "attention", sort: "deadline", limit: WORK_PANEL_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  const blockingQuery = useQuery({
    queryKey: ["opportunities", "dashboard-blocking"],
    queryFn: ({ signal }) => api.getOpportunities({ reason: "blocking_item", limit: WORK_PANEL_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  // 보류 재검토도 회차와 무관하다. 기한 지남·임박 선별과 정렬은 서버가 한다(spec §8).
  const holdReviewQuery = useQuery({
    queryKey: ["opportunities", "dashboard-hold-review"],
    queryFn: ({ signal }) => api.getOpportunities({ hold_review: "attention", sort: "hold_review_due_at", limit: HOLD_REVIEW_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  const newPlanQuery = useQuery({
    queryKey: ["order-plans", "dashboard-new-priority", newSince],
    queryFn: ({ signal }) => api.getOrderPlans({ qwen_relevance: "relevant", tracking_status: "미선택", first_observed_from: newSince, limit: WORK_PANEL_LIMIT }, { signal }),
    staleTime: 60_000,
  });

  // 건수 띠의 건수는 **링크한 목록의 기본 보기**와 같은 정의다(설계고도화안 C-1·A-6·C-8).
  // 목록 API의 `total`(또는 같은 판정 함수)을 쓰며 화면이 다른 정의로 다시 세지 않는다.
  const relevantPlanQuery = useQuery(orderPlanViewTotalQuery("relevant"));
  const uncertainPlanQuery = useQuery(orderPlanViewTotalQuery("uncertain"));
  const preSpecViewQuery = useQuery(preSpecDefaultViewTotalQuery());
  const preSpecNeedsCheckQuery = useQuery(preSpecNeedsCheckTotalQuery());
  const actionRequiredQuery = useQuery(opportunityActionRequiredQuery());
  const recentPreSpecQuery = useQuery(preSpecRecentTotalQuery(newSince));

  const workloadItem = (key: WorkloadKey) => (workloadQuery.isSuccess
    ? workloadQuery.data.items.find(entry => entry.key === key)
    : undefined);
  // 건수를 못 받으면 0으로 채우지 않고 미확인으로 두며, 서버가 준 사유를 함께 남긴다.
  const workloadNote = (key: WorkloadKey, label: string, suffix = " · 누적") => {
    if (workloadQuery.isPending) return `${label} 확인 중`;
    const item = workloadItem(key);
    if (!item) return `${label} 건수 미확인`;
    if (item.count === null) return `${label} 건수 미확인 · ${item.unavailable_reason === null ? "사유 없음" : WORKLOAD_UNAVAILABLE_REASON[item.unavailable_reason] ?? item.unavailable_reason}`;
    return `${label} ${formatNumber(item.count)}건${suffix}`;
  };
  /** 문장 안에 끼우는 건수 하나. 단위 없이 숫자만 적고 없으면 `미확인`이다. */
  const workloadValue = (key: WorkloadKey) => {
    if (workloadQuery.isPending) return "확인 중";
    const item = workloadItem(key);
    return !item || item.count === null ? "미확인" : formatNumber(item.count);
  };
  const workloadBasis = snapshotTime(workloadQuery.data?.generated_at, "Asia/Seoul");

  const briefingQuery = useQuery({
    queryKey: ["briefing", "latest"],
    queryFn: ({ signal }) => api.getLatestBriefing({ signal }),
    staleTime: 60_000,
    retry: false,
  });
  const briefing = briefingQuery.isSuccess ? briefingQuery.data : null;
  const briefingChanges = briefing?.tracked_changes.slice(0, 2) ?? [];
  const briefingPreview = briefing
    ? [...briefing.items.slice(0, WORK_PANEL_LIMIT - briefingChanges.length), ...briefingChanges]
    : [];

  const allQueries = [
    briefingQuery, collectionQuery,
    workloadQuery, deadlineQuery, decisionQuery, overviewFailedQuery, overviewAttentionQuery, blockingQuery,
    holdReviewQuery, newPlanQuery, relevantPlanQuery, uncertainPlanQuery, preSpecViewQuery, preSpecNeedsCheckQuery,
    actionRequiredQuery, recentPreSpecQuery,
  ];
  const refresh = () => { for (const query of allQueries) void query.refetch(); };
  const isRefreshing = allQueries.some((query) => query.isFetching);

  /** 목록 total 한 개. 못 받으면 0이 아니라 `미확인`이다. */
  const countText = (state: { isPending: boolean; isError: boolean }, value: number | undefined) =>
    (state.isPending ? "확인 중" : state.isError || value === undefined ? "미확인" : `${formatNumber(value)}건`);
  const listCount = (query: { isPending: boolean; isError: boolean; data?: number }) => countText(query, query.data);

  const goNoGoNote = `검토 대상 ${countText(decisionQuery, decisionQuery.data?.total)}`;
  const actionData = actionRequiredQuery.data;
  const actionCount: DashCount = { key: "action-required", label: "사업기회 조치 필요", value: countText(actionRequiredQuery, actionData?.total), basis: "새 연결·후보·확인 항목·보류 기한", to: "/opportunities" };

  const finalCount: DashCount = {
    key: "go-no-go",
    label: DECISION_AXIS_LABEL.goNoGo,
    value: countText(decisionQuery, decisionQuery.data?.total),
    basis: "미결정·재검토·공고 확인 필요",
    to: "/go-no-go",
  };
  const deadlinePath = `/opportunities?section=전체&deadline_within_days=${DEADLINE_IMMINENT_DAYS}&sort=deadline`;
  const deadlineCount: DashCount = {
    key: "deadline", label: "마감 임박 추적 건", value: countText(deadlineQuery, deadlineQuery.data?.total),
    basis: `${DEADLINE_IMMINENT_DAYS}일 이내`, to: deadlinePath,
  };
  const orderPlanCount: DashCount = { key: "order-plan-relevant", label: `${ORDER_PLAN_REVIEW_TIER_LABEL.relevant} 발주계획`, value: listCount(relevantPlanQuery), basis: "추적 결정 대기 · 모델 관련", to: "/order-plans" };
  const preSpecCount: DashCount = { key: "pre-spec-actionable", label: `사전규격 ${PRE_SPEC_TERM.actionable}`, value: listCount(preSpecViewQuery), basis: `${PRE_SPEC_TERM.reviewOverview}·추적 결정 · 마감 전·미확인`, to: "/pre-specs" };
  const holdCount: DashCount = { key: "hold-overdue", label: "보류 재검토", value: countText(actionRequiredQuery, actionData?.action_reason_counts?.hold_overdue), basis: "기한 지남 · 14일", to: HOLD_REVIEW_LIST_PATH };
  // 확인할 것: 실패·사람 확인·마감 임박.
  const checkCounts: DashCount[] = [
    // 사전규격 확인 필요(2026-11-19): 개요 실패·취소, 문서 준비 중단. 기본 보기와 같은 마감 구간이다.
    // 옛 `개요 실패`(누적) 칸을 대신한다 — 누적 실패 건수는 아래 사람 확인 패널 바닥이 그대로 적는다.
    { key: "pre-spec-needs-check", label: `사전규격 ${PRE_SPEC_TERM.needsCheck}`, value: listCount(preSpecNeedsCheckQuery), basis: "개요 실패·취소 · 문서 준비 중단 · 마감 전·미확인", to: "/pre-specs?workspace=needs_check" },
    { key: "overview-attention", label: "개요 사람 확인", value: countText(overviewAttentionQuery, overviewAttentionQuery.data?.total), basis: "사전규격 · 누적", to: "/pre-specs?workspace=all&sw_only=false&overview_view=attention" },
    { key: "blocking", label: "확인 항목 미답변", value: countText(actionRequiredQuery, actionData?.action_reason_counts?.blocking_item), basis: "조치 필요 사업", to: "/opportunities?section=조치 필요&reason=blocking_item" },
    { key: "order-plan-uncertain", label: `${ORDER_PLAN_REVIEW_TIER_LABEL.uncertain} 발주계획`, value: listCount(uncertainPlanQuery), basis: `모델 ${TERM_SENSE.modelUncertain} · 추적 미선택`, to: "/order-plans?qwen=uncertain&tracking=미선택" },
  ];
  // 새로 볼 것: 전일(KST) 이후 처음 수집된 것.
  const newCounts: DashCount[] = [
    { key: "new-order-plan", label: "새 관련 발주계획", value: countText(newPlanQuery, newPlanQuery.data?.total), basis: `${newSince.slice(5)} 이후 첫 수집 · 추적 미선택`, to: `/order-plans?qwen=relevant&tracking=미선택&first_observed_from=${newSince}` },
    { key: "new-pre-spec", label: "새 사전규격", value: listCount(recentPreSpecQuery), basis: `${newSince.slice(5)} 이후 관측 · SW사업대상`, to: `/pre-specs?workspace=recent&observed_from=${newSince}` },
  ];

  // 한 출처라도 실패하면 이 패널의 목록이 완전하다고 말할 수 없으므로 패널째 실패로 적는다.
  const humanCheckState = {
    isPending: overviewFailedQuery.isPending || overviewAttentionQuery.isPending || blockingQuery.isPending,
    isError: overviewFailedQuery.isError || overviewAttentionQuery.isError || blockingQuery.isError,
    onRetry: () => { void overviewFailedQuery.refetch(); void overviewAttentionQuery.refetch(); void blockingQuery.refetch(); },
  };

  return <section className="dash-page" aria-label="오늘 할 일" data-astryx-theme="bidops">
    <PageHeaderActions><div className="dash-header-actions">
      <Button label="새로고침" size="sm" variant="ghost" icon={<RefreshCw aria-hidden="true" />} isDisabled={isRefreshing} onClick={refresh} />
      <LinkButton label="실행 상태" to="/run-status" icon={<Activity aria-hidden="true" />} secondary />
    </div></PageHeaderActions>
    <DashboardBlock id="today" title="오늘 검토할 업무">
      <CountStrip label="오늘 검토할 업무 건수" items={[deadlineCount, finalCount, actionCount, orderPlanCount, preSpecCount]} />
    </DashboardBlock>
    <DashboardBlock id="decide" title="오늘 결정할 것" caption="마감순" actions={<>
      <LinkButton label="사업기회" to={deadlinePath} />
      <LinkButton label="최종 Go/No-Go" to="/go-no-go" />
    </>}>
      <TodayDecisionTable now={now}
        tracking={{
          data: deadlineQuery.data, isPending: deadlineQuery.isPending, isError: deadlineQuery.isError,
          onRetry: () => { void deadlineQuery.refetch(); },
        }}
        final={{
          data: decisionQuery.data, isPending: decisionQuery.isPending, isError: decisionQuery.isError,
          onRetry: () => { void decisionQuery.refetch(); },
        }}
      />
      <footer className="dash-decision-scope"><Small>
        {`추적 중·보류 사업 중 ${DEADLINE_IMMINENT_DAYS}일 이내 · ${workloadBasis} 기준 · `}
        {workloadNote("tracking_deadline_imminent", "마감 임박", "")}
        {` · 최종 Go/No-Go ${goNoGoNote} · 입찰 마감순`}
      </Small></footer>
    </DashboardBlock>
    {/* 발주계획·공고 두 트랙의 일일 수집과 실행 기록. */}
    <DailyCollectionStatus collectionStatus={<CollectionStatus data={collectionQuery.data} failed={collectionQuery.isError} />} />

    <DashboardBlock id="check" title="확인할 것">
      <CountStrip label="확인할 것 건수" items={[holdCount, ...checkCounts]} />
      <div className="dash-work-grid">
        <HumanCheckPanel failed={overviewFailedQuery.data} attention={overviewAttentionQuery.data} blocking={blockingQuery.data}
          state={humanCheckState}
          footBasis={`개요 실패·확인 필요 ${workloadValue("overview_human_review")} · 공고별 확인 항목 ${workloadValue("blocking_items_open")}`}
          footCount={workloadNote("human_check_required", "사람 확인 필요", "")} />
        {(!holdReviewQuery.isSuccess || holdReviewQuery.data.total > 0) && <HoldReviewPanel data={holdReviewQuery.data} isPending={holdReviewQuery.isPending} isError={holdReviewQuery.isError}
          onRetry={() => { void holdReviewQuery.refetch(); }} overdueNote={workloadNote("tracking_hold_review_due", "기한 지남", "")} now={now} />}

      </div>
    </DashboardBlock>

    {briefing ? (
      <DashboardBlock id="briefing" title="오늘의 브리핑" caption={briefing.briefing_date}>
        <DashboardPanel
          action={<LinkButton label="브리핑과 반응 이력 열기" to="/briefing" />}
          title="추천과 추적 변화"
        >
          {briefing.status === "collection_incomplete" ? <p>수집이 완료되지 않은 상태에서 만든 브리핑이에요.</p> : null}
          {briefingPreview.length > 0 ? (
            <ul className="dash-work-list">
              {briefingPreview.map((item) => (
                <WorkRow
                  end={item.kind === "tracked_change" ? "추적 변화" : item.reaction ?? "반응 대기"}
                  key={item.item_id}
                  meta={[stageLabel(item.stage), item.agency].filter(Boolean).join(" · ")}
                  title={item.title}
                  to={`/briefing?date=${briefing.briefing_date}&selected=${encodeURIComponent(item.item_id)}`}
                />
              ))}
            </ul>
          ) : <p>추천이나 추적 변화가 없어요.</p>}
        </DashboardPanel>
      </DashboardBlock>
    ) : null}

    <DashboardBlock id="new" title="새로 볼 것" caption={`${newSince.slice(5)} 이후 처음 수집된 것이에요.`}>
      <CountStrip label="새로 볼 것 건수" items={newCounts} />
      <div className="dash-work-grid">
        <NewPriorityOrderPlanPanel data={newPlanQuery.data} newSince={newSince}
          state={{ isPending: newPlanQuery.isPending, isError: newPlanQuery.isError, onRetry: () => { void newPlanQuery.refetch(); } }}
          footBasis="전일 수집 이후 처음 관측"
          footCount={workloadNote("order_plan_new_priority", "추적 미선택", ` 중 상위 ${WORK_PANEL_LIMIT}건`)} />
      </div>
    </DashboardBlock>
  </section>;
}
