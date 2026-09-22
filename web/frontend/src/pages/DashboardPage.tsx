import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { InternationalizationProvider } from "@astryxdesign/core/i18n";
import koKR from "@astryxdesign/core/locales/ko-KR.json";
import { Activity, ArrowUpRight, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import type { WorkloadKey } from "../lib/types";
import { formatNumber } from "../lib/format";
import { PageHeaderActions } from "../components/common/PageHeaderActions";
import { LinkButton, Small } from "../components/dashboard/DashboardPrimitives";
import { HoldReviewPanel } from "../components/dashboard/HoldReviewPanel";
import {
  DeadlineImminentPanel, FinalDecisionPanel, HumanCheckPanel, NewPriorityOrderPlanPanel,
} from "../components/dashboard/WorkPanels";
import {
  DEADLINE_IMMINENT_DAYS, HOLD_REVIEW_LIMIT, WORK_PANEL_LIMIT, previousKstDate, snapshotTime,
} from "../components/dashboard/dashboardData";
import "../styles/dashboard-erp.css";

// 서버가 정한 안전 코드다. 문장이 있는 코드만 옮기고 모르는 코드는 그대로 보여 준다.
const WORKLOAD_UNAVAILABLE_REASON: Record<string, string> = {
  provider_absent: "집계 모듈 없음",
  no_completed_execution: "완료된 선별 실행 없음",
  sub_count_unavailable: "하위 건수 미확인",
};

/**
 * 실무자 대시보드(시안 M6 승인 2026-09-22, ADR-0067).
 *
 * **회차를 고르지 않아도 완결된다.** 회차 선택기와 회차 의존 패널 넷은 빠졌고
 * (`/runs` 회차 상세·회사 프로필로 간다) 남은 다섯 패널은 전부 누적이다.
 * 각 패널은 `/api/workload`의 건수 키 하나와 기존 목록 API 호출 하나를 짝지어 쓰며,
 * **건수를 목록 길이로 덮지 않고 목록이 비었다고 건수를 0으로 고치지 않는다.**
 */
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

  const refresh = () => {
    void workloadQuery.refetch(); void deadlineQuery.refetch(); void decisionQuery.refetch();
    void overviewFailedQuery.refetch(); void overviewAttentionQuery.refetch(); void blockingQuery.refetch();
    void holdReviewQuery.refetch(); void newPlanQuery.refetch();
  };
  const isRefreshing = workloadQuery.isFetching || deadlineQuery.isFetching || decisionQuery.isFetching
    || overviewFailedQuery.isFetching || overviewAttentionQuery.isFetching || blockingQuery.isFetching
    || holdReviewQuery.isFetching || newPlanQuery.isFetching;

  // 한 출처라도 실패하면 이 패널의 목록이 완전하다고 말할 수 없으므로 패널째 실패로 적는다.
  const humanCheckState = {
    isPending: overviewFailedQuery.isPending || overviewAttentionQuery.isPending || blockingQuery.isPending,
    isError: overviewFailedQuery.isError || overviewAttentionQuery.isError || blockingQuery.isError,
    onRetry: () => { void overviewFailedQuery.refetch(); void overviewAttentionQuery.refetch(); void blockingQuery.refetch(); },
  };

  return <section className="dash-page" aria-label="대시보드" data-astryx-theme="bidops">
    <PageHeaderActions><div className="dash-header-actions">
      <Button label="새로고침" size="sm" variant="ghost" icon={<RefreshCw aria-hidden="true" />} isDisabled={isRefreshing} onClick={refresh} />
      <LinkButton label="실행 상태" to="/run-status" icon={<Activity aria-hidden="true" />} secondary />
    </div></PageHeaderActions>
    <nav className="dash-journey-strip" aria-label="업무 바로가기 · 회차와 무관한 누적 업무">
      {[
        ["01", "발주계획", "추적할 후보 선택", `${workloadNote("order_plan_pending", "검토 후보")} · 새로 ${workloadValue("order_plan_new_priority")}`, "/order-plans"],
        ["02", "사전규격", "검토 결과·추적 여부 확인", workloadNote("pre_spec_deep_review_ready", "결정 대기"), "/pre-specs?workspace=all&auto_preparation_status=deep_review_ready_for_click&sw_only=false&sort=deadline"],
        ["03", "사업 추적", "연결·예외 사항 확인", workloadNote("tracking_action_required", "조치 필요"), "/opportunities?section=조치 필요"],
        ["04", "최종 Go/No-Go", "입찰 참여 여부 결정", workloadNote("bid_final_decision_pending", "결정 대기"), "/go-no-go"],
      ].map(([step, title, action, note, to]) => <Link key={step} className="dash-journey-item" to={to}>
        <div className="dash-row dash-spread"><div className="dash-row"><Small>{step}</Small><Text weight="semibold" className="dash-journey-title">{title}</Text></div><ArrowUpRight aria-hidden="true" /></div>
        <Text>{action}</Text><Small>{note}</Small>
      </Link>)}
    </nav>

    <div className="dash-work-grid">
      <DeadlineImminentPanel data={deadlineQuery.data} now={now}
        state={{ isPending: deadlineQuery.isPending, isError: deadlineQuery.isError, onRetry: () => { void deadlineQuery.refetch(); } }}
        footBasis={`추적 중·보류 사업 중 ${DEADLINE_IMMINENT_DAYS}일 이내 · ${workloadBasis} 기준`}
        footCount={workloadNote("tracking_deadline_imminent", "마감 임박", "")} />
      <FinalDecisionPanel data={decisionQuery.data} now={now}
        state={{ isPending: decisionQuery.isPending, isError: decisionQuery.isError, onRetry: () => { void decisionQuery.refetch(); } }}
        footBasis="입찰 마감순" footCount={workloadNote("bid_final_decision_pending", "결정 없음", "")} />
      <HumanCheckPanel failed={overviewFailedQuery.data} attention={overviewAttentionQuery.data} blocking={blockingQuery.data}
        state={humanCheckState}
        footBasis={`개요 실패·확인 필요 ${workloadValue("overview_human_review")} · 공고별 확인 항목 ${workloadValue("blocking_items_open")}`}
        footCount={workloadNote("human_check_required", "사람 확인 필요", "")} />
      <HoldReviewPanel data={holdReviewQuery.data} isPending={holdReviewQuery.isPending} isError={holdReviewQuery.isError}
        onRetry={() => { void holdReviewQuery.refetch(); }} overdueNote={workloadNote("tracking_hold_review_due", "기한 지남", "")} now={now} />
      <NewPriorityOrderPlanPanel data={newPlanQuery.data}
        state={{ isPending: newPlanQuery.isPending, isError: newPlanQuery.isError, onRetry: () => { void newPlanQuery.refetch(); } }}
        footBasis="전일 수집 이후 처음 관측"
        footCount={workloadNote("order_plan_new_priority", "추적 미선택", ` 중 상위 ${WORK_PANEL_LIMIT}건`)} />
    </div>
    <footer className="dash-dashboard-foot"><Small>최종 참여 판단은 최종 Go/No-Go에서 진행합니다.</Small></footer>
  </section>;
}
