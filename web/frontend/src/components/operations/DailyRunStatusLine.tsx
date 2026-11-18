import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { StatusBadge } from "../common/StatusBadge";
import { api } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { orderPlanReviewTierSummary } from "../../lib/glossary";
import { BASIS_RULE_TEXT, dailyNoticeStatus, dailyRunStatus, latestDailyRun, type DailyNoticeStatus, type DailyRunStatus } from "../../lib/orderPlanDaily";

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

/** 줄을 이루는 사실 조각. 순서: 기준일 → 수집일·경과일 → C-2 상태 → 필수 검토·훑어보기(·모델 미판정) 건수. */
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
  // 필수 검토(관련)와 훑어보기(불확실)를 나눠 적는다(2026-11-18 수정안 3B). 무판정 몫은 0보다 클 때만이다.
  const counts = execution.counts;
  parts.push(orderPlanReviewTierSummary(counts.stage2_relevant_count, counts.stage2_uncertain_count, status.noJudgmentCount, formatNumber));
  return parts;
}

const STALE_SENTENCE = "최근 기준일이 늦었습니다. 일일 스크립트가 돌지 않았을 수 있습니다.";

function problemSentence(status: DailyRunStatus): string | null {
  const { problems } = status;
  if (problems.includes("no_daily_run")) return "일일 스크립트가 아직 발주계획을 수집한 적이 없습니다.";
  const sentences: string[] = [];
  if (problems.includes("stale")) sentences.push(STALE_SENTENCE);
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

/**
 * `embedded`: 대시보드 `일일 수집` 묶음 안의 한 행이다. 테두리 없이 그리고 행 제목은 트랙 이름이다.
 */
export function DailyRunStatusLine({ className = "", showLink = true, embedded = false }: { className?: string; showLink?: boolean; embedded?: boolean }) {
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
      className={`daily-run-line${embedded ? " is-row" : ""}${status.state === "warning" ? " is-warning" : ""} ${className}`.trim()}
      data-state={status.state}
      data-testid="daily-run-status"
      role="status"
      title={BASIS_RULE_TEXT}
    >
      <StatusBadge label={badge.label} tone={badge.tone} />
      <span className="daily-run-facts">
        <span className="daily-run-title">{embedded ? "발주계획" : "발주계획 일일 실행"}</span>
        {factParts(status).map((part) => <span className="daily-run-fact" key={part}>{part}</span>)}
      </span>
      {problem ? <span className="daily-run-problem">{problem}</span> : null}
      {showLink ? <Link className="daily-run-link" to="/runs">회차 기록 →</Link> : null}
    </div>
  );
}

/**
 * 공고 트랙(사전규격·입찰공고) 일일 수집의 한 행(2026-11-18 G1). 기존 GET만 쓴다: `/api/runs`에서
 * 기준일이 가장 늦은 `lifecycle-<기준일>-notices` 회차를 고르고(목록에 있으면 적재된 회차다), 그 회차
 * 하나의 `/api/runs/<id>/warnings` 건수를 붙인다(추가 호출은 그 하나뿐이다).
 */
export function DailyNoticeStatusLine() {
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const latestId = useMemo(() => latestDailyRun(runsQuery.data?.items ?? [], "notices")?.run.run_id ?? null, [runsQuery.data]);
  const warningsQuery = useQuery({
    queryKey: ["run-warnings", latestId],
    queryFn: () => api.getRunWarnings(latestId as string),
    enabled: latestId !== null,
    staleTime: 30_000,
    retry: false,
  });
  const now = useMemo(() => Date.now(), []);
  if (runsQuery.isPending) return <p className="daily-run-line is-row" data-testid="daily-notice-status" role="status">공고 · 기록을 확인하는 중입니다.</p>;
  if (runsQuery.isError) {
    return (
      <div className="daily-run-line is-row is-warning" data-state="error" data-testid="daily-notice-status" role="status">
        <StatusBadge label="확인 불가" tone="warning" />
        <span>공고 일일 수집 기록을 불러오지 못했습니다. 돌았다고 가정하지 않습니다.</span>
      </div>
    );
  }
  const status = dailyNoticeStatus(runsQuery.data.items, warningsQuery.isSuccess ? warningsQuery.data.total : null, now);
  const badge = STATE_BADGE[status.state];
  return (
    <div
      className={`daily-run-line is-row${status.state === "warning" ? " is-warning" : ""}`}
      data-state={status.state}
      data-testid="daily-notice-status"
      role="status"
      title={BASIS_RULE_TEXT}
    >
      <StatusBadge label={badge.label} tone={badge.tone} />
      <span className="daily-run-facts">
        <span className="daily-run-title">공고(사전규격·입찰공고)</span>
        {noticeFactParts(status, warningsQuery.isError).map((part) => <span className="daily-run-fact" key={part}>{part}</span>)}
      </span>
      {status.problems.includes("no_daily_run")
        ? <span className="daily-run-problem">일일 스크립트가 아직 공고를 수집한 적이 없습니다.</span>
        : status.problems.includes("stale") ? <span className="daily-run-problem">{STALE_SENTENCE}</span> : null}
    </div>
  );
}

function noticeFactParts(status: DailyNoticeStatus, warningsFailed: boolean): string[] {
  if (!status.latest) return ["일일 공고 수집 기록이 없습니다"];
  return [
    `최근 기준일 ${status.latest.basisDate.slice(5)}`,
    status.collectedDate ? `적재 ${shortDate(status.collectedDate)} · ${agoLabel(status.daysSince)}` : "적재 날짜 미확인",
    status.warningCount !== null ? `적재 경고 ${formatNumber(status.warningCount)}건` : warningsFailed ? "적재 경고 미확인" : "적재 경고 확인 중",
  ];
}

/** 대시보드의 `일일 수집` 묶음: 발주계획·공고 두 트랙을 한 덩어리 두 행으로 그린다(G1). */
export function DailyCollectionStatus() {
  return (
    <section aria-label="일일 수집" className="daily-collection" data-testid="daily-collection">
      <header className="daily-collection-head">
        <span className="daily-collection-title">일일 수집</span>
        <span className="daily-collection-aux">오늘 기준일은 아직 수집 전일 수 있습니다 · 정오 전에는 그저께 기준일까지를 정상으로 봅니다</span>
        <Link className="daily-run-link" to="/runs">회차 기록 →</Link>
      </header>
      <DailyRunStatusLine embedded showLink={false} />
      <DailyNoticeStatusLine />
    </section>
  );
}
