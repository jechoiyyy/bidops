import type { OrderPlanScreeningExecutionSummary, RunSummary } from "./types";

/**
 * 발주계획 일일 실행의 사실 한 줄(설계고도화안 A-5, 2026-11-18).
 *
 * "어제 일일 실행이 돌았는가"를 기존 GET 두 개(`/api/runs`, `/api/order-plan-screening/executions`)
 * 에서 그대로 읽는다. 새 집계를 서버에 만들지 않고, 판정·건수를 다시 계산하지 않는다.
 *
 * - 일일 실행 회차는 `scripts/run-daily-lifecycle.sh --track order-plans`가 만드는 디렉터리
 *   `lifecycle-<기준일 YYYYMMDD>-plans`(재수집은 `-retry<N>`)의 회차다. 회차 기본키는
 *   `<디렉터리>--<generated_at>Z`다(CLAUDE.md). 수동 워크플로 회차(`order-plans-…`)는 일일
 *   실행이 아니므로 세지 않는다.
 * - 그 회차의 C-2 실행은 같은 `source_run_id`의 **운영(`operational`) 실행 중 가장 최근**이다.
 *   측정 전용 실행(`gate_measurement`)은 일일 실행이 아니다.
 * - 화면은 스케줄이 있다고 말하지 않는다. 스위치는 일일 스크립트의 실행을 허용할 뿐이고 cron이
 *   있는지는 이 화면이 알 수 없다.
 */
const DAILY_PLAN_RUN = /^lifecycle-(\d{4})(\d{2})(\d{2})-plans(?:-retry\d+)?(?:--|$)/;

export interface DailyPlanRun {
  run: RunSummary;
  /** 디렉터리 이름의 기준일(`YYYY-MM-DD`). 수집 대상 하루이며 실행일이 아니다. */
  basisDate: string;
}

export function dailyPlanRunBasisDate(runId: string): string | null {
  const match = DAILY_PLAN_RUN.exec(runId);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : null;
}

/** 가장 최근에 수집된(`generated_at`) 일일 발주계획 회차. 없으면 `null`이다. */
export function latestDailyPlanRun(runs: readonly RunSummary[]): DailyPlanRun | null {
  let latest: DailyPlanRun | null = null;
  for (const run of runs) {
    const basisDate = dailyPlanRunBasisDate(run.run_id);
    if (basisDate === null) continue;
    if (!latest || run.generated_at.localeCompare(latest.run.generated_at) > 0) latest = { run, basisDate };
  }
  return latest;
}

/** 같은 회차의 운영 실행 중 가장 최근(대기 시각) 하나. 측정 전용 실행은 제외한다. */
export function latestOperationalExecution(
  executions: readonly OrderPlanScreeningExecutionSummary[],
  sourceRunId: string,
): OrderPlanScreeningExecutionSummary | null {
  let latest: OrderPlanScreeningExecutionSummary | null = null;
  for (const execution of executions) {
    if (execution.source_run_id !== sourceRunId || execution.purpose !== "operational") continue;
    if (!latest || execution.queued_at.localeCompare(latest.queued_at) > 0) latest = execution;
  }
  return latest;
}

const KST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });

/** 시각의 한국 시간 날짜(`YYYY-MM-DD`). 읽을 수 없는 값이면 `null`이다. */
export function kstDate(value: string | number): string | null {
  const time = typeof value === "number" ? value : Date.parse(value);
  return Number.isFinite(time) ? KST_DATE.format(new Date(time)) : null;
}

function dayIndex(isoDate: string): number {
  return Date.UTC(Number(isoDate.slice(0, 4)), Number(isoDate.slice(5, 7)) - 1, Number(isoDate.slice(8, 10))) / 86_400_000;
}

/** 두 한국 시간 날짜 사이의 일수(`to - from`). */
export function daysBetween(fromIsoDate: string, toIsoDate: string): number {
  return dayIndex(toIsoDate) - dayIndex(fromIsoDate);
}

/** 이 상태만 일일 실행이 끝까지 돈 것으로 본다. 나머지(대기·실행 중·실패·중단)는 주의다. */
const DONE_STATUSES = new Set(["성공", "부분 성공"]);

export type DailyRunProblem = "no_daily_run" | "stale" | "no_execution" | "execution_not_done";

export interface DailyRunStatus {
  latest: DailyPlanRun | null;
  /** 수집 시각의 한국 시간 날짜. */
  collectedDate: string | null;
  /** 오늘(한국 시간)까지 지난 일수. 수집 날짜를 읽을 수 없으면 `null`이다. */
  daysSince: number | null;
  execution: OrderPlanScreeningExecutionSummary | null;
  /**
   * 모델 판정이 없어 사람이 봐야 하는 건수. 실행 계약의 `human_review_count`가
   * `관련 + 불확실 + 무판정(1차 실패·거부, 모델 실패·거부·미확인)`이므로 그 차이다
   * (`web/backend/app/screening/c2_contracts.py`). 실행이 없으면 `null`이다.
   */
  noJudgmentCount: number | null;
  problems: DailyRunProblem[];
}

export function dailyRunStatus(
  runs: readonly RunSummary[],
  executions: readonly OrderPlanScreeningExecutionSummary[],
  now: number,
): DailyRunStatus {
  const latest = latestDailyPlanRun(runs);
  if (!latest) {
    return { latest: null, collectedDate: null, daysSince: null, execution: null, noJudgmentCount: null, problems: ["no_daily_run"] };
  }
  const collectedDate = kstDate(latest.run.generated_at);
  const today = kstDate(now);
  const daysSince = collectedDate && today ? daysBetween(collectedDate, today) : null;
  const execution = latestOperationalExecution(executions, latest.run.run_id);
  const problems: DailyRunProblem[] = [];
  if (daysSince === null || daysSince > 1) problems.push("stale");
  if (!execution) problems.push("no_execution");
  else if (!DONE_STATUSES.has(execution.status)) problems.push("execution_not_done");
  const counts = execution?.counts;
  const noJudgmentCount = counts
    ? Math.max(0, counts.human_review_count - counts.stage2_relevant_count - counts.stage2_uncertain_count)
    : null;
  return { latest, collectedDate, daysSince, execution, noJudgmentCount, problems };
}
