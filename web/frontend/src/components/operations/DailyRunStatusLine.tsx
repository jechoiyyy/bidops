import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { StatusBadge } from "../common/StatusBadge";
import { api } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { dailyRunStatus, type DailyRunStatus } from "../../lib/orderPlanDaily";

/**
 * "어제 일일 실행이 돌았는가"에 답하는 한 줄(설계고도화안 A-5, 2026-11-18).
 *
 * 대시보드와 발주계획 판정 기준(정책) 화면이 같은 줄을 쓴다. 판정·건수는 서버 값 그대로이며
 * (`lib/orderPlanDaily.ts`) 이 줄은 **스케줄이 있다고 말하지 않는다** — 마지막으로 실제로
 * 돈 사실만 적는다. 마지막 실행이 1일보다 오래됐거나 C-2 실행이 성공·부분 성공이 아니면
 * `확인 필요` 상태다. 조회 실패는 "돌았다"로 읽지 않는다.
 */
export function useDailyRunStatus() {
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const latestRunId = useMemo(() => {
    const status = dailyRunStatus(runsQuery.data?.items ?? [], [], Date.now());
    return status.latest?.run.run_id ?? null;
  }, [runsQuery.data]);
  const executionsQuery = useQuery({
    queryKey: ["order-plan-c2", "executions", "daily-run", latestRunId],
    queryFn: ({ signal }) => api.getOrderPlanScreeningExecutions({ source_run_id: latestRunId, limit: 50 }, { signal }),
    enabled: latestRunId !== null,
    staleTime: 30_000,
  });
  const now = useMemo(() => Date.now(), []);
  const status = useMemo(
    () => dailyRunStatus(runsQuery.data?.items ?? [], executionsQuery.data?.items ?? [], now),
    [executionsQuery.data, now, runsQuery.data],
  );
  const isPending = runsQuery.isPending || (latestRunId !== null && executionsQuery.isPending);
  const isError = runsQuery.isError || executionsQuery.isError;
  const refetch = () => { void runsQuery.refetch(); if (latestRunId !== null) void executionsQuery.refetch(); };
  return { status, isPending, isError, refetch };
}

function shortDate(isoDate: string): string {
  return `${Number(isoDate.slice(5, 7))}월 ${Number(isoDate.slice(8, 10))}일`;
}

function agoLabel(days: number | null): string {
  if (days === null) return "경과일 미확인";
  if (days <= 0) return "오늘";
  return `${formatNumber(days)}일 전`;
}

/** 진행 시간 표기. 분 단위로 내리고 1시간이 넘으면 시간·분이다. */
function elapsedLabel(ms: number | null): string {
  if (ms === null) return "경과 시간 미확인";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes}분째`;
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분째`;
}

/** 줄을 이루는 사실 조각. 순서: 기준일 → 수집일·경과일 → C-2 상태 → 사람 검토 건수. */
function factParts(status: DailyRunStatus): string[] {
  if (!status.latest) return ["일일 발주계획 수집 기록이 없습니다"];
  const parts = [
    `최근 기준일 ${status.latest.basisDate.slice(5)}`,
    status.collectedDate
      ? `수집 ${shortDate(status.collectedDate)} · ${agoLabel(status.daysSince)}`
      : "수집 날짜 미확인",
  ];
  const execution = status.execution;
  if (!execution) {
    parts.push(status.problems.includes("no_execution") ? "C-2 실행 없음" : "C-2 실행 없음 · 수집 0건");
    return parts;
  }
  // 대기·실행 중·중지 요청은 진행 중이다. 건수는 끝난 뒤에만 적는다.
  if (["대기", "실행 중", "중지 요청"].includes(execution.status)) {
    parts.push(`C-2 ${execution.status} · ${elapsedLabel(status.inProgressMs)}`);
    return parts;
  }
  parts.push(`C-2 ${execution.status}`);
  if (status.noJudgmentCount === null) return parts;
  const counts = execution.counts;
  const breakdown = [`관련 ${formatNumber(counts.stage2_relevant_count)}`, `불확실 ${formatNumber(counts.stage2_uncertain_count)}`];
  if (status.noJudgmentCount > 0) breakdown.push(`모델 판정 없음 ${formatNumber(status.noJudgmentCount)}`);
  parts.push(`사람 검토 ${formatNumber(counts.human_review_count)}건 (${breakdown.join(" · ")})`);
  return parts;
}

function problemSentence(status: DailyRunStatus): string | null {
  const { problems } = status;
  if (problems.includes("no_daily_run")) return "일일 스크립트가 아직 발주계획을 수집한 적이 없습니다.";
  const sentences: string[] = [];
  if (problems.includes("stale")) sentences.push("최근 기준일이 어제보다 오래됐습니다. 일일 스크립트가 돌지 않았을 수 있습니다.");
  if (problems.includes("no_execution")) sentences.push("이 회차에는 C-2 운영 실행이 없습니다.");
  if (problems.includes("in_progress_too_long")) sentences.push("오래 진행 중 — 실행 상태 확인.");
  if (problems.includes("execution_not_done")) sentences.push("C-2 실행이 성공·부분 성공으로 끝나지 않았습니다.");
  return sentences.length ? sentences.join(" ") : null;
}

const STATE_BADGE = {
  ok: { label: "정상", tone: "neutral" },
  in_progress: { label: "진행 중", tone: "neutral" },
  warning: { label: "확인 필요", tone: "warning" },
} as const;

export function DailyRunStatusLine({ className = "", showLink = true }: { className?: string; showLink?: boolean }) {
  const { status, isPending, isError, refetch } = useDailyRunStatus();
  if (isPending) {
    return <p className={`daily-run-line ${className}`.trim()} data-testid="daily-run-status" role="status">발주계획 일일 실행 · 기록을 확인하는 중입니다.</p>;
  }
  if (isError) {
    return (
      <div className={`daily-run-line is-warning ${className}`.trim()} data-testid="daily-run-status" data-state="error" role="status">
        <StatusBadge label="확인 불가" tone="warning" />
        <span>발주계획 일일 실행 기록을 불러오지 못했습니다. 돌았다고 가정하지 않습니다.</span>
        <Button label="다시 조회" onClick={refetch} size="sm" variant="ghost" />
      </div>
    );
  }
  const problem = problemSentence(status);
  const badge = STATE_BADGE[status.state];
  return (
    <div
      className={`daily-run-line${status.state === "warning" ? " is-warning" : ""} ${className}`.trim()}
      data-state={status.state}
      data-testid="daily-run-status"
      role="status"
    >
      <StatusBadge label={badge.label} tone={badge.tone} />
      <span className="daily-run-facts">
        <span className="daily-run-title">발주계획 일일 실행</span>
        {factParts(status).map((part) => <span className="daily-run-fact" key={part}>{part}</span>)}
      </span>
      {problem ? <span className="daily-run-problem">{problem}</span> : null}
      {showLink ? <Link className="daily-run-link" to="/runs">회차 기록 →</Link> : null}
    </div>
  );
}
