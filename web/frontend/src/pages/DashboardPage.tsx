import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { ActionStrip, type ActionItem } from "../components/dashboard/ActionStrip";
import { GradeDistribution } from "../components/dashboard/GradeDistribution";
import { KpiCard } from "../components/dashboard/KpiCard";
import { PipelineFunnel } from "../components/dashboard/PipelineFunnel";
import { ValidationGauges } from "../components/dashboard/ValidationGauges";
import { DeadlineTable } from "../components/dashboard/DeadlineTable";
import { VerificationRequests } from "../components/dashboard/VerificationRequests";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import type { DeadlineNotice, RunStatsResponse, ValidationMetric } from "../lib/types";
import "../styles/dashboard-relaxed.css";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "대시보드 데이터를 확인할 수 없습니다.";
}

function priorityStatus(metric: ValidationMetric | undefined): string | undefined {
  if (!metric || metric.percentage === null || typeof metric.threshold !== "object" || metric.threshold === null) return undefined;
  if (!("min" in metric.threshold) || !("max" in metric.threshold)) return undefined;
  const range = metric.threshold as { min: unknown; max: unknown };
  if (typeof range.min !== "number" || typeof range.max !== "number") return undefined;
  if (metric.value !== null && metric.value > range.max) return "임계 초과";
  if (metric.value !== null && metric.value < range.min) return "임계 미달";
  return undefined;
}

const CRITICAL_DAYS = 3;

/** 회차 산출물이 이미 "임박"으로 좁혀 준 목록에서 마감이 `referenceAt` 기준
 * CRITICAL_DAYS일 이내인 항목 수를 센다. 하한이 없으므로 서버가 창을 좁혀 준
 * 목록에만 쓸 수 있다 — 누적 목록에 그대로 적용하면 이미 지난 마감까지
 * 임박으로 센다. `referenceAt`이 없으면 임박 여부도 계산하지 않고 0을
 * 반환한다. 현재 시각으로 대체하면 같은 회차가 조회 시점에 따라 다른 작업
 * 목록으로 보일 수 있다(회차 산출물은 생성 시점에 동결된 스냅숏이다). */
function criticalDeadlineCount(notices: DeadlineNotice[], referenceAt: string | null): number {
  if (!referenceAt) return 0;
  const referenceMs = new Date(referenceAt).getTime();
  if (Number.isNaN(referenceMs)) return 0;
  return notices.filter((notice) => {
    const deadlineMs = new Date(notice.deadline_at ?? "").getTime();
    if (Number.isNaN(deadlineMs)) return false;
    return Math.ceil((deadlineMs - referenceMs) / 86_400_000) <= CRITICAL_DAYS;
  }).length;
}

/**
 * 회차 통계로 계산하는 항목들. "우선 검토"는 결정 3(공고 1차 판정, 검토
 * 대기열)으로 가는 유일한 통로이므로 건수가 0이어도(또는 회차를 아직
 * 고르지 않았어도) 이 스트립에서 계속 이동 가능해야 한다 — PLAN.md 3단계
 * 게이트 "할 일 스트립에서 네 결정 화면 각각으로 이동 가능". 마감 임박·
 * 검증 요청은 네 결정에 속하지 않는 보조 항목이라 값이 있을 때만 보탠다.
 */
function runScopedActionItems(stats: RunStatsResponse | undefined, runId: string | null): ActionItem[] {
  if (!runId || !stats) {
    // 공고 1차 판정은 읽기 전용 이력이다(ADR-0045 결정 3). 처리할 일이 아니라
    // 회차 자료를 확인하는 자리이므로 제목이 "판정 대기"가 아니다.
    return [{
      key: "priority",
      count: null,
      title: "공고 1차 판정 이력 확인",
      description: "회차를 선택하면 우선 검토 건수를 확인합니다 · 읽기 전용",
      to: "/queue",
    }];
  }
  const search = `run=${encodeURIComponent(runId)}`;
  const criticalCount = criticalDeadlineCount(stats.imminent_deadlines, stats.generated_at);
  const blockingCount = stats.verification_requests.reduce((sum, request) => sum + request.count, 0);
  const items: ActionItem[] = [
    {
      key: "priority",
      count: stats.priority_review_count,
      title: "우선 검토로 판정된 공고 확인",
      description: "회차 판정 이력을 등급순으로 열기 · 읽기 전용",
      to: `/queue?${search}&grade=${encodeURIComponent("우선 검토")}`,
    },
  ];
  if (criticalCount > 0) {
    items.push({
      key: "deadline",
      count: criticalCount,
      title: `마감이 ${CRITICAL_DAYS}일 이내다`,
      description: "회차 판정 이력을 마감 임박순으로 열기 · 읽기 전용",
      to: `/queue?${search}&sort=deadline`,
      tone: "alert",
    });
  }
  if (blockingCount > 0) {
    items.push({
      key: "verification",
      count: blockingCount,
      title: "담당자가 확정해야 할 차단 항목이 있다",
      description: "회사 프로필에서 기준 확정하기",
      to: `/profile?${search}`,
    });
  }
  return items;
}

interface QueryState {
  status: "pending" | "error" | "success";
  count: number | null;
}

/**
 * 네 결정으로 가는 항목 (PLAN 단계 E 작업 7, ADR-0045).
 *
 * 결정 1 발주계획 추적 결정 · 결정 2 사전규격 심층 검토 승인 · 예외 조치(연결·
 * 실패) · 결정 4 최종 입찰 Go/No-Go. 넷 다 누적 추적이라 회차 선택과 무관하다
 * (docs/design/PRD.md §2.1).
 *
 * ADR-0045 결정 3으로 공고 1차 판정이 읽기 전용 이력이 됐으므로, 넷째 자리를
 * 차지하던 "공고 1차 판정 대기"를 **예외 조치**로 바꿨다. 사람이 손대야 하는
 * 것은 회차 표본 전수가 아니라 근거 없음·검증 실패·연결 불확실이다.
 *
 * 건수를 확인할 수 없는 항목은 `null`(확인 불가)로 두고 이동 경로만 남긴다.
 * 0으로 바꾸지 않는다 — 0은 확인된 값이고 null은 확인하지 못한 상태다.
 */
function cumulativeActionItems(orderPlanReview: QueryState): ActionItem[] {
  return [
    {
      key: "c2-review",
      count: orderPlanReview.status === "success" ? orderPlanReview.count : null,
      loading: orderPlanReview.status === "pending",
      title: "발주계획 추적 결정이 필요하다",
      description: orderPlanReview.status === "error"
        ? "건수를 확인할 수 없습니다 · 발주계획에서 직접 확인하기"
        : "Qwen 신호가 검토 대상(relevant·uncertain)인 발주계획 열기 · 추적 미결정 건수는 아닙니다",
      to: "/order-plans",
    },
    {
      // 심층 검토 승인 대기 건수는 서버가 세지 않는다. `GET /api/pre-specs`는
      // 개요 검토 상태 집계(`overview_status_counts`)만 주고 심층 검토 실행
      // 승인 여부를 담지 않는다. 근사값으로 채우지 않고 이동 경로만 남긴다.
      key: "pre-spec-deep-review",
      count: null,
      title: "사전규격 심층 검토 승인이 필요할 수 있다",
      description: "건수 확인 불가 · 사전규격을 마감 임박순으로 열기",
      to: "/pre-specs?sort=deadline",
    },
    {
      // 예외 조치(근거 없음·검증 실패·연결 불확실)는 저장된 상태가 아니라 파생
      // 조건이라 서버가 세지 못한다(docs/tracking/findings.md). 사업 추적의
      // `조치 필요` 구역이 받은 페이지에서 그 조건을 나누므로, 대시보드는
      // 건수를 만들지 않고 그 구역으로 보낸다.
      key: "tracking-exception",
      count: null,
      title: "예외 조치가 남아 있을 수 있다",
      description: "건수 확인 불가 · 사업 추적의 조치 필요 구역 열기 (연결 불확실·검증 실패·근거 없음)",
      to: `/opportunities?section=${encodeURIComponent("조치 필요")}`,
      tone: "alert",
    },
    {
      // 서버에 "Go/No-Go 결정 대기 사업기회" 집계 endpoint가 없다(GoNoGoPage.tsx
      // 머리 주석 참조). 클라이언트에서 재현하려면 계속 추적 사업기회마다
      // bid-delta workspace를 조회하는 N+1이 필요한데, 대시보드에서 그 N+1을
      // 반복하지 않는다(web/backend/AGENTS.md·CLAUDE.md 게이트). 그래서 건수는
      // 항상 null(확인 불가)이고, 이동 경로만 항상 제공한다 — 0이나 다른
      // 근사값으로 채우지 않는다.
      key: "go-no-go",
      count: null,
      title: "최종 Go/No-Go 결정이 필요할 수 있다",
      description: "건수 확인 불가 · 결정 대기 사업기회 목록에서 직접 확인하기",
      to: "/go-no-go",
    },
  ];
}

export function DashboardPage() {
  const [searchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const statsQuery = useQuery({
    queryKey: ["run-stats", runId],
    queryFn: () => api.getRunStats(runId as string),
    enabled: Boolean(runId),
    staleTime: 30_000,
  });
  const validationQuery = useQuery({
    queryKey: ["validation-metrics", runId],
    queryFn: () => api.getValidationMetrics(runId as string),
    enabled: Boolean(runId),
    staleTime: 30_000,
  });

  // 누적 추적 항목 셋(결정 1·2·4)은 회차 선택과 무관하다. 건수를 실제로
  // 조회할 수 있는 것은 C-2 하나뿐이며, 두 건만 부르는 집계 조회다
  // (limit=1로 total만 읽는다). 행마다 반복 조회하는 N+1이 아니다.
  // 사전규격 마감·Go/No-Go는 서버 집계가 없어 조회하지 않는다 —
  // cumulativeActionItems의 각 주석과 docs/tracking/findings.md 참조.
  const orderPlanReviewQuery = useQuery({
    queryKey: ["dashboard-action", "order-plan-review-candidates"],
    queryFn: async ({ signal }) => {
      const [relevant, uncertain] = await Promise.all([
        api.getOrderPlans({ qwen_relevance: "relevant", limit: 1 }, { signal }),
        api.getOrderPlans({ qwen_relevance: "uncertain", limit: 1 }, { signal }),
      ]);
      return relevant.total + uncertain.total;
    },
    staleTime: 60_000,
  });

  const actionItems: ActionItem[] = [
    ...runScopedActionItems(statsQuery.data, runId),
    ...cumulativeActionItems({
      status: orderPlanReviewQuery.status,
      count: orderPlanReviewQuery.data ?? null,
    }),
  ];

  if (!runId) {
    return (
      <div className="dashboard-page">
        <ActionStrip items={actionItems} />
        <EmptyState title="선택된 회차가 없습니다." description="상단의 실행 회차 선택기에서 회차를 선택하면 회차 지표를 확인합니다. 위 항목은 회차와 무관하게 항상 확인할 수 있습니다." />
      </div>
    );
  }

  if (statsQuery.isLoading || validationQuery.isLoading) {
    return (
      <div className="dashboard-page">
        <ActionStrip items={actionItems} />
        <div className="dashboard-loading" role="status" aria-live="polite">선택한 회차의 대시보드 데이터를 불러오는 중입니다.</div>
      </div>
    );
  }

  if (statsQuery.error || validationQuery.error) {
    return (
      <div className="dashboard-page">
        <ActionStrip items={actionItems} />
        <EmptyState
          title="대시보드 데이터를 불러오지 못했습니다."
          description={errorMessage(statsQuery.error ?? validationQuery.error)}
          action={{ label: "다시 시도", onClick: () => { void statsQuery.refetch(); void validationQuery.refetch(); } }}
        />
      </div>
    );
  }

  const stats = statsQuery.data;
  const validation = validationQuery.data;
  if (!stats || !validation) {
    return (
      <div className="dashboard-page">
        <ActionStrip items={actionItems} />
        <EmptyState title="대시보드 데이터 없음" description="선택한 회차에 표시할 응답이 없습니다." />
      </div>
    );
  }

  const discriminativePower = validation.metrics.find((metric) => metric.key === "discriminative_power");
  // 수집 통계는 collected-notices.json 이 있어야 나온다. 없으면 비율도 계산하지 않는다.
  const candidateRatio =
    stats.collected_count !== null && stats.candidate_count !== null && stats.collected_count > 0
      ? (stats.candidate_count / stats.collected_count) * 100
      : null;
  const priorityDescription = discriminativePower
    ? `분석 표본 ${formatNumber(discriminativePower.basis.denominator)}건의 ${percentageText(discriminativePower.percentage)}`
    : "분석 표본 분모 확인 불가";

  return (
    <div className="dashboard-page">
      <ActionStrip items={actionItems} />

      <section className="dashboard-kpi-grid" aria-label="회차 주요 지표">
        <KpiCard
          label="수집 건수"
          value={<><span>{countText(stats.collected_count)}</span>{stats.collected_count !== null ? <span className="dashboard-kpi-unit">건</span> : null}</>}
          description={stats.collected_count === null ? "collected-notices.json이 없어 수집 건수를 알 수 없습니다." : "수집 산출물 기준 · 용역 본공고"}
        />
        <KpiCard
          label="후보 풀"
          value={<><span>{countText(stats.candidate_count)}</span>{stats.candidate_count !== null ? <span className="dashboard-kpi-unit">건</span> : null}</>}
          description={<><span>전체 수집의 </span><span className="mono tabular-nums">{percentageText(candidateRatio)}</span></>}
        />
        <KpiCard
          accent
          to={`/queue?run=${encodeURIComponent(runId)}&grade=${encodeURIComponent("우선 검토")}`}
          label="우선 검토"
          value={<><span>{formatNumber(stats.priority_review_count)}</span><span className="dashboard-kpi-unit">건</span></>}
          description={priorityDescription}
          status={priorityStatus(discriminativePower)}
        />
        <KpiCard
          label="1차 필터 누락"
          value={<><span>{formatNumber(stats.audit_missed_count)}</span><span className="dashboard-kpi-fraction"> / 표본 미확인</span></>}
          description="감사 표본 분모를 확인할 수 없어 누락률을 계산하지 않습니다."
        />
      </section>

      <div className="dashboard-primary-grid">
        <PipelineFunnel funnel={stats.funnel}>
          <GradeDistribution distribution={stats.grade_distribution} embedded runId={runId} />
        </PipelineFunnel>
        <ValidationGauges metrics={validation.metrics} />
      </div>

      <div className="dashboard-secondary-grid">
        <DeadlineTable notices={stats.imminent_deadlines} referenceAt={stats.generated_at} runId={runId} timezone={stats.timezone} />
        <VerificationRequests requests={stats.verification_requests} runId={runId} />
      </div>
    </div>
  );
}

function countText(value: number | null): string {
  return value === null ? "값 없음" : formatNumber(value);
}

function percentageText(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "비율 계산 불가";
  return `${value.toFixed(1)}%`;
}
