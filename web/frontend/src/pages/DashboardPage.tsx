import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import type { WorkloadKey } from "../lib/types";
import { PRE_SPEC_TERM } from "../lib/glossary";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { DailyCollectionStatus } from "../components/operations/DailyRunStatusLine";
import { CollectionHealth, CollectionStatus } from "../components/dashboard/CollectionStatus";
import { opportunityActionRequiredQuery, preSpecNeedsCheckTotalQuery, preSpecRecentTotalQuery } from "../lib/defaultViewCounts";
import { DashboardBlock, LinkButton, Small, SummaryCell, type DashCount } from "../components/dashboard/DashboardPrimitives";
import { DeadlineAgenda } from "../components/dashboard/DeadlineAgenda";
import { DEADLINE_IMMINENT_DAYS, HOLD_REVIEW_LIST_PATH, previousKstDate } from "../components/dashboard/dashboardData";
import "../styles/dashboard-erp.css";

/** 마감 일정이 한 번에 받는 마감 임박 추적 건 수. 넘으면 몇 건 중 몇 건인지 적는다. */
const AGENDA_TRACKING_LIMIT = 200;
/** 최종 결정 대기열을 한 번에 받는 수. 일정에 합칠 사업과 일정 밖 건수를 가르는 데 쓴다. */
const AGENDA_FINAL_LIMIT = 200;

/**
 * 오늘 할 일(2026-11-27 시안 C2, `docs/1127_today-simplify/`).
 *
 * 다른 화면에서 이미 보이는 것(사이드바 건수, 목록 상위 몇 건, 실행 상태 세부)은 싣지 않고
 * 요약 줄 · 추적 중인 사업의 마감 일정 · 함께 볼 것 한 줄만 둔다. 건수는 링크한 목록의
 * 기본 보기와 같은 정의다(설계고도화안 C-1·A-6·C-8).
 */
export function DashboardPage() {
  return <InternationalizationProvider locale="ko-KR" messages={{ "ko-KR": koKR }}><DashboardWorkspace /></InternationalizationProvider>;
}

function DashboardWorkspace() {
  // D-day와 `새로`의 창은 한 번 잡은 기준 시각으로 센다. 매 렌더의 `Date.now()`를
  // query key에 넣으면 조회가 멈추지 않는다.
  const now = useMemo(() => Date.now(), []);
  const newSince = useMemo(() => previousKstDate(now), [now]);

  const collectionQuery = useQuery({
    queryKey: ["daily-collection-status"],
    queryFn: ({ signal }) => api.getDailyCollectionStatus({ signal }),
    staleTime: 30_000,
  });
  const deadlineQuery = useQuery({
    queryKey: ["opportunities", "dashboard-deadline", AGENDA_TRACKING_LIMIT],
    queryFn: ({ signal }) => api.getOpportunities({ deadline_within_days: DEADLINE_IMMINENT_DAYS, sort: "deadline", limit: AGENDA_TRACKING_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  const decisionQuery = useQuery({
    queryKey: ["bid-delta-decision-queue", "dashboard", AGENDA_FINAL_LIMIT],
    queryFn: ({ signal }) => api.getBidDeltaDecisionQueue({ status: "pending", limit: AGENDA_FINAL_LIMIT }, { signal }),
    staleTime: 60_000,
  });
  // 개요 사람 확인은 사전규격 목록의 같은 보기와 같은 모집단이다(`sw_only=false`, 나머지 기본값).
  const overviewAttentionQuery = useQuery({
    queryKey: ["pre-specs", "dashboard-overview", "attention", "total"],
    queryFn: ({ signal }) => api.getPreSpecs({ sw_only: false, overview_view: "attention", sort: "deadline", limit: 1 }, { signal }),
    staleTime: 60_000,
  });
  const newPlanQuery = useQuery({
    queryKey: ["order-plans", "dashboard-new-priority", newSince, "total"],
    queryFn: ({ signal }) => api.getOrderPlans({ qwen_relevance: "relevant", tracking_status: "미선택", first_observed_from: newSince, limit: 1 }, { signal }),
    staleTime: 60_000,
  });
  const preSpecNeedsCheckQuery = useQuery(preSpecNeedsCheckTotalQuery());
  const actionRequiredQuery = useQuery(opportunityActionRequiredQuery());
  const recentPreSpecQuery = useQuery(preSpecRecentTotalQuery(newSince));
  const workloadQuery = useQuery({ queryKey: ["workload"], queryFn: ({ signal }) => api.getWorkload({ signal }), staleTime: 60_000 });
  const briefingQuery = useQuery({
    queryKey: ["briefing", "latest"],
    queryFn: ({ signal }) => api.getLatestBriefing({ signal }),
    staleTime: 60_000,
    retry: false,
  });

  const allQueries = [
    collectionQuery, deadlineQuery, decisionQuery, overviewAttentionQuery, newPlanQuery,
    preSpecNeedsCheckQuery, actionRequiredQuery, recentPreSpecQuery, briefingQuery, workloadQuery,
  ];
  const refresh = () => { for (const query of allQueries) void query.refetch(); };
  const isRefreshing = allQueries.some((query) => query.isFetching);

  /** 목록 total 한 개. 못 받으면 0이 아니라 `미확인`이다. */
  const countText = (state: { isPending: boolean; isError: boolean }, value: number | undefined) =>
    (state.isPending ? "확인 중" : state.isError || value === undefined ? "미확인" : `${formatNumber(value)}건`);

  const deadlinePath = `/opportunities?section=전체&deadline_within_days=${DEADLINE_IMMINENT_DAYS}&sort=deadline`;
  const actionData = actionRequiredQuery.data;
  const deadlineCount: DashCount = { key: "deadline", label: "마감 임박 추적 건", value: countText(deadlineQuery, deadlineQuery.data?.total), to: deadlinePath };
  const finalCount: DashCount = { key: "go-no-go", label: "최종 Go/No-Go", value: countText(decisionQuery, decisionQuery.data?.total), to: "/go-no-go" };
  const needsCheckCount: DashCount = {
    key: "pre-spec-needs-check", label: `사전규격 ${PRE_SPEC_TERM.needsCheck}`,
    value: countText(preSpecNeedsCheckQuery, preSpecNeedsCheckQuery.data), to: "/pre-specs?workspace=needs_check",
  };
  const newCounts: DashCount[] = [
    { key: "new-order-plan", label: "발주계획", value: countText(newPlanQuery, newPlanQuery.data?.total), to: `/order-plans?qwen=relevant&tracking=미선택&first_observed_from=${newSince}` },
    { key: "new-pre-spec", label: "사전규격", value: countText(recentPreSpecQuery, recentPreSpecQuery.data), to: `/pre-specs?workspace=recent&observed_from=${newSince}` },
  ];

  // 함께 볼 것: 0건은 링크 대신 한 줄로 모으고, 셀 수 없는 것은 0으로 숨기지 않는다.
  const alsoSee: (DashCount & { count: number | null | undefined })[] = [
    { key: "overview-attention", label: "개요 사람 확인", count: overviewAttentionQuery.data?.total, value: countText(overviewAttentionQuery, overviewAttentionQuery.data?.total), to: "/pre-specs?workspace=all&sw_only=false&overview_view=attention" },
    { key: "action-required", label: "사업기회 조치 필요", count: actionData?.total, value: countText(actionRequiredQuery, actionData?.total), to: "/opportunities" },
    { key: "hold-overdue", label: "보류 재검토", count: actionData?.action_reason_counts?.hold_overdue, value: countText(actionRequiredQuery, actionData?.action_reason_counts?.hold_overdue), to: HOLD_REVIEW_LIST_PATH },
    { key: "blocking", label: "확인 항목 미답변", count: actionData?.action_reason_counts?.blocking_item, value: countText(actionRequiredQuery, actionData?.action_reason_counts?.blocking_item), to: "/opportunities?section=조치 필요&reason=blocking_item" },
  ];
  // RL-11 엔진 분석: 서버가 건수를 줄 때만 보인다(엔진이 꺼져 있으면 항목이 없다).
  const engineTasks: { key: WorkloadKey; label: string }[] = [
    { key: "engine_approval_pending", label: "분석 승인 대기" },
    { key: "engine_result_pending", label: "분석 결과 확인" },
  ];
  for (const { key, label } of engineTasks) {
    const count = workloadQuery.isSuccess ? workloadQuery.data.items.find(entry => entry.key === key)?.count : undefined;
    if (count != null) alsoSee.push({ key, label, count, value: `${formatNumber(count)}건`, to: "/pre-specs?workspace=tracking" });
  }
  const zeroItems = alsoSee.filter(item => item.count === 0);
  const shownItems = alsoSee.filter(item => item.count !== 0);
  const briefing = briefingQuery.isSuccess ? briefingQuery.data : null;

  return <section className="dash-page" aria-label="오늘 할 일" data-astryx-theme="bidops">
    <PageHeaderActions><div className="dash-header-actions">
      <CollectionHealth data={collectionQuery.data} failed={collectionQuery.isError}
        detail={<DailyCollectionStatus collectionStatus={<CollectionStatus data={collectionQuery.data} failed={collectionQuery.isError} />} />} />
      <Button label="새로고침" size="sm" variant="ghost" icon={<RefreshCw aria-hidden="true" />} isDisabled={isRefreshing} onClick={refresh} />
    </div></PageHeaderActions>

    <div className="dash-summary" aria-label="오늘 요약" role="group">
      <SummaryCell id="decide" title="결정할 것" hot main={deadlineCount} basis={`마감 ${DEADLINE_IMMINENT_DAYS}일 이내 추적 건`} extras={[finalCount]} />
      <SummaryCell id="stuck" title="멈춘 것" main={needsCheckCount} basis="사전규격 개요 실패·취소 · 문서 준비 중단" />
      <SummaryCell id="new" title="새로 들어온 것" basis={`관련 발주계획·SW 사전규격 · ${newSince.slice(5)} 이후 첫 수집`} extras={newCounts} />
    </div>

    <DashboardBlock id="agenda" title="추적 중인 사업 · 마감 일정"
      caption={`마감 ${DEADLINE_IMMINENT_DAYS}일 이내 추적 건과 최종 Go/No-Go 대기 · 마감일별`}
      actions={<>
        <LinkButton label="사업기회" to={deadlinePath} secondary />
        <LinkButton label="최종 Go/No-Go" to="/go-no-go" secondary />
      </>}>
      <DeadlineAgenda now={now}
        tracking={{ data: deadlineQuery.data, isPending: deadlineQuery.isPending, isError: deadlineQuery.isError, onRetry: () => { void deadlineQuery.refetch(); } }}
        final={{ data: decisionQuery.data, isPending: decisionQuery.isPending, isError: decisionQuery.isError, onRetry: () => { void decisionQuery.refetch(); } }} />
    </DashboardBlock>

    <nav className="dash-also" aria-label="함께 볼 것">
      <strong className="dash-also-title">함께 볼 것</strong>
      {shownItems.map(item => <Link className="dash-also-link" data-count={item.key} key={item.key} to={item.to}>{`${item.label} ${item.value}`}</Link>)}
      {briefing ? <Link className="dash-also-link" data-count="briefing" to={`/briefing?date=${briefing.briefing_date}`}>{`오늘의 브리핑 ${briefing.briefing_date.slice(5)}`}</Link> : null}
      {zeroItems.length ? <Small className="dash-also-zero">{`${zeroItems.map(item => item.label).join("·")} 0건`}</Small> : null}
    </nav>
  </section>;
}
