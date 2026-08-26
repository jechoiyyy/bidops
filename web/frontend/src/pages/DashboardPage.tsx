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

function sampleCountFromDistribution(distribution: { count: number }[]): number {
  return distribution.reduce((sum, item) => sum + item.count, 0);
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

function criticalDeadlineCount(notices: DeadlineNotice[], referenceAt: string | null): number {
  const referenceMs = referenceAt ? new Date(referenceAt).getTime() : Date.now();
  return notices.filter((notice) => {
    const deadlineMs = new Date(notice.deadline_at ?? "").getTime();
    if (Number.isNaN(deadlineMs)) return false;
    return Math.ceil((deadlineMs - referenceMs) / 86_400_000) <= CRITICAL_DAYS;
  }).length;
}

/**
 * 회차 통계만으로 계산할 수 있는 세 가지 할 일을 뽑는다.
 * 건수가 0이면 할 일이 아니므로 항목 자체를 내보내지 않는다.
 */
function actionItems(stats: RunStatsResponse, runId: string): ActionItem[] {
  const search = `run=${encodeURIComponent(runId)}`;
  const criticalCount = criticalDeadlineCount(stats.imminent_deadlines, stats.generated_at);
  const blockingCount = stats.verification_requests.reduce((sum, request) => sum + request.count, 0);
  const items: ActionItem[] = [];

  if (stats.priority_review_count > 0) {
    items.push({
      key: "priority",
      count: stats.priority_review_count,
      title: "우선 검토로 판정된 공고가 있다",
      description: "대기열을 등급순으로 열기",
      to: `/queue?${search}&grade=${encodeURIComponent("우선 검토")}`,
    });
  }
  if (criticalCount > 0) {
    items.push({
      key: "deadline",
      count: criticalCount,
      title: `마감이 ${CRITICAL_DAYS}일 이내다`,
      description: "대기열을 마감 임박순으로 열기",
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

function countText(value: number | null): string {
  return value === null ? "값 없음" : formatNumber(value);
}

function percentageText(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "비율 계산 불가";
  return `${value.toFixed(1)}%`;
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

  if (!runId) {
    return <EmptyState title="선택된 회차가 없습니다." description="상단의 실행 회차 선택기에서 회차를 선택하십시오." />;
  }

  if (statsQuery.isLoading || validationQuery.isLoading) {
    return <div className="dashboard-loading" role="status" aria-live="polite">선택한 회차의 대시보드 데이터를 불러오는 중입니다.</div>;
  }

  if (statsQuery.error || validationQuery.error) {
    return (
      <EmptyState
        title="대시보드 데이터를 불러오지 못했습니다."
        description={errorMessage(statsQuery.error ?? validationQuery.error)}
        action={{ label: "다시 시도", onClick: () => { void statsQuery.refetch(); void validationQuery.refetch(); } }}
      />
    );
  }

  const stats = statsQuery.data;
  const validation = validationQuery.data;
  if (!stats || !validation) {
    return <EmptyState title="대시보드 데이터 없음" description="선택한 회차에 표시할 응답이 없습니다." />;
  }

  const discriminativePower = validation.metrics.find((metric) => metric.key === "discriminative_power");
  const analysisSampleCount = sampleCountFromDistribution(stats.grade_distribution);
  const auditSampleCount = Math.max(stats.sample_count - analysisSampleCount, 0);
  // 수집 통계는 collected-notices.json 이 있어야 나온다. 없으면 비율도 계산하지 않는다.
  const candidateRatio =
    stats.collected_count !== null && stats.candidate_count !== null && stats.collected_count > 0
      ? (stats.candidate_count / stats.collected_count) * 100
      : null;
  const auditPoolCount =
    stats.collected_count !== null && stats.candidate_count !== null
      ? Math.max(stats.collected_count - stats.candidate_count, 0)
      : null;
  const priorityDescription = discriminativePower
    ? `분석 표본 ${formatNumber(discriminativePower.basis.denominator)}건의 ${percentageText(discriminativePower.percentage)}`
    : `분석 표본 ${formatNumber(analysisSampleCount)}건 기준`;

  return (
    <div className="dashboard-page">
      <ActionStrip items={actionItems(stats, runId)} />

      <section className="dashboard-kpi-grid" aria-label="회차 주요 지표">
        <KpiCard
          label="수집 건수"
          value={<><span>{countText(stats.collected_count)}</span>{stats.collected_count !== null ? <span className="dashboard-kpi-unit">건</span> : null}</>}
          description={stats.collected_count === null ? "collected-notices.json이 없어 수집 건수를 알 수 없습니다." : "수집 산출물 기준 · 용역 본공고"}
        />
        <KpiCard
          label="후보 풀"
          value={<><span>{countText(stats.candidate_count)}</span>{stats.candidate_count !== null ? <span className="dashboard-kpi-unit">건</span> : null}</>}
          description={<><span>전체 수집의 </span><span className="mono tabular-nums">{percentageText(candidateRatio)}</span><span> · 감사 풀 </span><span className="mono tabular-nums">{countText(auditPoolCount)}</span>{auditPoolCount !== null ? <span>건</span> : null}</>}
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
          value={<><span>{formatNumber(stats.audit_missed_count)}</span><span className="dashboard-kpi-fraction"> / {formatNumber(auditSampleCount)}건</span></>}
          description={auditSampleCount === 0 ? "감사 표본 0건 기준 · 누락도 0건" : "감사 표본에서 비제외 판정 건수"}
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
        <VerificationRequests requests={stats.verification_requests} />
      </div>
    </div>
  );
}
