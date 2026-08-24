import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "../components/common/EmptyState";
import { GradeDistribution } from "../components/dashboard/GradeDistribution";
import { KpiCard } from "../components/dashboard/KpiCard";
import { PipelineFunnel } from "../components/dashboard/PipelineFunnel";
import { ValidationGauges } from "../components/dashboard/ValidationGauges";
import { DeadlineTable } from "../components/dashboard/DeadlineTable";
import { VerificationRequests } from "../components/dashboard/VerificationRequests";
import { api } from "../lib/api";
import { formatNumber } from "../lib/format";
import type { ValidationMetric } from "../lib/types";

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
    return <div className="dashboard-loading">선택한 회차의 대시보드 데이터를 불러오는 중입니다.</div>;
  }

  if (statsQuery.error || validationQuery.error) {
    return (
      <EmptyState
        title="대시보드 데이터를 불러오지 못했습니다."
        description={errorMessage(statsQuery.error ?? validationQuery.error)}
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
  const candidateRatio = stats.collected_count > 0 ? (stats.candidate_count / stats.collected_count) * 100 : null;
  const priorityDescription = discriminativePower
    ? `분석 표본 ${formatNumber(discriminativePower.basis.denominator)}건의 ${percentageText(discriminativePower.percentage)}`
    : `분석 표본 ${formatNumber(analysisSampleCount)}건 기준`;

  return (
    <div className="dashboard-page">
      <section className="dashboard-kpi-grid" aria-label="회차 주요 지표">
        <KpiCard
          label="수집 건수"
          value={<><span>{formatNumber(stats.collected_count)}</span><span className="dashboard-kpi-unit">건</span></>}
          description="수집 산출물 기준 · 용역 본공고"
        />
        <KpiCard
          label="후보 풀"
          value={<><span>{formatNumber(stats.candidate_count)}</span><span className="dashboard-kpi-unit">건</span></>}
          description={<><span>전체 수집의 </span><span className="mono tabular-nums">{percentageText(candidateRatio)}</span><span> · 감사 풀 </span><span className="mono tabular-nums">{formatNumber(Math.max(stats.collected_count - stats.candidate_count, 0))}</span><span>건</span></>}
        />
        <KpiCard
          accent
          label="우선 검토"
          value={<><span>{formatNumber(stats.priority_review_count)}</span><span className="dashboard-kpi-unit">건</span></>}
          description={priorityDescription}
          status={priorityStatus(discriminativePower)}
        />
        <KpiCard
          label="1차 필터 누락"
          value={<><span>{formatNumber(stats.audit_missed_count)}</span><span className="dashboard-kpi-fraction"> / {auditSampleCount > 0 ? `${formatNumber(auditSampleCount)}건` : "표본 미확인"}</span></>}
          description="감사 표본에서 비제외 판정 건수"
        />
      </section>

      <div className="dashboard-primary-grid">
        <PipelineFunnel funnel={stats.funnel}>
          <GradeDistribution distribution={stats.grade_distribution} embedded />
        </PipelineFunnel>
        <ValidationGauges metrics={validation.metrics} />
      </div>

      <div className="dashboard-secondary-grid">
        <DeadlineTable notices={stats.imminent_deadlines} referenceAt={stats.generated_at} timezone={stats.timezone} />
        <VerificationRequests requests={stats.verification_requests} />
      </div>
    </div>
  );
}
