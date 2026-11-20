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
const DAILY_RUN = {
  plans: /^lifecycle-(\d{4})(\d{2})(\d{2})-plans(?:-retry\d+)?(?:--|$)/,
  notices: /^lifecycle-(\d{4})(\d{2})(\d{2})-notices(?:-retry\d+)?(?:--|$)/,
} as const;
/** 일일 수집 트랙(`scripts/run-daily-lifecycle.sh --track`). 공고 트랙은 사전규격·입찰공고를 함께 모은다. */
export type DailyTrack = keyof typeof DAILY_RUN;

export interface DailyPlanRun {
  run: RunSummary;
  /** 디렉터리 이름의 기준일(`YYYY-MM-DD`). 수집 대상 하루이며 실행일이 아니다. */
  basisDate: string;
}

export function dailyRunBasisDate(runId: string, track: DailyTrack): string | null {
  const match = DAILY_RUN[track].exec(runId);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : null;
}

export function dailyPlanRunBasisDate(runId: string): string | null {
  return dailyRunBasisDate(runId, "plans");
}

/**
 * **기준일이 가장 늦은** 일일 회차(같은 기준일이면 늦게 수집한 재수집 회차). 이 줄은
 * "가장 최근 기준일이 처리됐는가"에 답한다 — 지난 날을 메우는(catch-up) 수집이 나중에 돌아도
 * 어제 기준일의 결과를 가리지 않는다(2026-11-18 운영 관측). 없으면 `null`이다.
 */
export function latestDailyRun(runs: readonly RunSummary[], track: DailyTrack): DailyPlanRun | null {
  let latest: DailyPlanRun | null = null;
  for (const run of runs) {
    const basisDate = dailyRunBasisDate(run.run_id, track);
    if (basisDate === null) continue;
    const later = !latest
      || basisDate > latest.basisDate
      || (basisDate === latest.basisDate && run.generated_at.localeCompare(latest.run.generated_at) > 0);
    if (later) latest = { run, basisDate };
  }
  return latest;
}

export function latestDailyPlanRun(runs: readonly RunSummary[]): DailyPlanRun | null {
  return latestDailyRun(runs, "plans");
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

const KST_HOUR = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", hour: "2-digit", hourCycle: "h23" });

/**
 * 최근 기준일이 늦었는가(2026-11-18 G2). 일정을 가정하지 않는 규칙이다: 한국 시간 **정오가 지나면**
 * 최근 기준일이 (오늘 − 1) 이상이어야 하고, **정오 전에는** (오늘 − 2) 이상이면 된다 — 자정과 아침
 * 수집 사이에 어제 기준일이 아직 없다는 이유로 경고하지 않기 위해서다. 오늘 기준일은 아직 수집 전일
 * 수 있다. 오늘을 읽을 수 없으면 늦은 것으로 본다.
 */
export function isBasisStale(basisDate: string, now: number): boolean {
  const today = kstDate(now);
  if (!today) return true;
  const beforeNoon = Number(KST_HOUR.format(new Date(now))) < 12;
  return daysBetween(basisDate, today) > (beforeNoon ? 2 : 1);
}

/** 기준일 규칙을 사람 말로(줄의 보조 글). 일정이 있다고 말하지 않는다. */
export const BASIS_RULE_TEXT = "정오가 지나면 어제 기준일, 정오 전에는 그저께 기준일까지 수집돼 있어야 정상으로 봐요. 오늘 기준일은 아직 수집 전일 수 있어요.";

function dayIndex(isoDate: string): number {
  return Date.UTC(Number(isoDate.slice(0, 4)), Number(isoDate.slice(5, 7)) - 1, Number(isoDate.slice(8, 10))) / 86_400_000;
}

/** 두 한국 시간 날짜 사이의 일수(`to - from`). */
export function daysBetween(fromIsoDate: string, toIsoDate: string): number {
  return dayIndex(toIsoDate) - dayIndex(fromIsoDate);
}

/** 이 상태만 일일 실행이 끝까지 돈 것으로 본다. */
const DONE_STATUSES = new Set(["성공", "부분 성공"]);
/** 아직 끝나지 않은 상태. 문제가 아니라 진행 중이다. */
const IN_PROGRESS_STATUSES = new Set(["대기", "실행 중", "중지 요청"]);
/** 진행 중이 이보다 오래면 주의다. 서버의 `대기` 최대 체류 시간(설계고도화안 A-1)과 같은 4시간이다. */
export const IN_PROGRESS_LIMIT_MS = 4 * 60 * 60 * 1000;

export type DailyRunProblem = "no_daily_run" | "stale" | "no_execution" | "execution_not_done" | "in_progress_too_long";
export type DailyRunState = "ok" | "in_progress" | "warning";

export interface DailyRunStatus {
  latest: DailyPlanRun | null;
  /** 수집 시각의 한국 시간 날짜. */
  collectedDate: string | null;
  /** 수집일부터 오늘(한국 시간)까지 지난 일수. 읽을 수 없으면 `null`이다. */
  daysSince: number | null;
  /** 기준일부터 오늘까지 지난 일수. 일일 실행은 전일 기준이라 평상시 1이다. */
  basisLag: number | null;
  execution: OrderPlanScreeningExecutionSummary | null;
  /** 진행 중인 실행이 대기에 들어간 뒤 지난 시간(ms). 진행 중이 아니면 `null`이다. */
  inProgressMs: number | null;
  /**
   * 모델 판정이 없어 사람이 봐야 하는 건수. 실행 계약의 `human_review_count`가
   * `관련 + 불확실 + 무판정(1차 실패·거부, 모델 실패·거부·미확인)`이므로 그 차이다
   * (`web/backend/app/screening/c2_contracts.py`). 실행이 없거나 진행 중이면 `null`이다.
   */
  noJudgmentCount: number | null;
  problems: DailyRunProblem[];
  state: DailyRunState;
}

/**
 * 실행 집계의 무판정 몫(`human_review_count − 관련 − 불확실`). 화면 문구 `모델 미판정 n건`의 n이며
 * 1차 선별 `순위 밖`은 들지 않는다(그 건은 `human_review_count`에 없다).
 */
export function noJudgmentCountOf(counts: Pick<OrderPlanScreeningExecutionSummary["counts"], "human_review_count" | "stage2_relevant_count" | "stage2_uncertain_count">): number {
  return Math.max(0, counts.human_review_count - counts.stage2_relevant_count - counts.stage2_uncertain_count);
}

/** 수집 건수(`counts.collection.total`)가 0으로 확인된 회차. 모르면 비어 있다고 보지 않는다. */
function isEmptyRun(run: RunSummary): boolean {
  return run.counts.collection?.total === 0;
}

export function dailyRunStatus(
  runs: readonly RunSummary[],
  executions: readonly OrderPlanScreeningExecutionSummary[],
  now: number,
): DailyRunStatus {
  const latest = latestDailyPlanRun(runs);
  if (!latest) {
    return {
      latest: null, collectedDate: null, daysSince: null, basisLag: null, execution: null, inProgressMs: null,
      noJudgmentCount: null, problems: ["no_daily_run"], state: "warning",
    };
  }
  const collectedDate = kstDate(latest.run.generated_at);
  const today = kstDate(now);
  const daysSince = collectedDate && today ? daysBetween(collectedDate, today) : null;
  const basisLag = today ? daysBetween(latest.basisDate, today) : null;
  const execution = latestOperationalExecution(executions, latest.run.run_id);
  const problems: DailyRunProblem[] = [];
  if (isBasisStale(latest.basisDate, now)) problems.push("stale");
  let inProgressMs: number | null = null;
  if (!execution) {
    if (!isEmptyRun(latest.run)) problems.push("no_execution");
  } else if (IN_PROGRESS_STATUSES.has(execution.status)) {
    const since = Date.parse(execution.queued_at);
    inProgressMs = Number.isFinite(since) ? Math.max(0, now - since) : null;
    if (inProgressMs === null || inProgressMs > IN_PROGRESS_LIMIT_MS) problems.push("in_progress_too_long");
  } else if (!DONE_STATUSES.has(execution.status)) {
    problems.push("execution_not_done");
  }
  const counts = execution && DONE_STATUSES.has(execution.status) ? execution.counts : null;
  const noJudgmentCount = counts ? noJudgmentCountOf(counts) : null;
  const state: DailyRunState = problems.length > 0 ? "warning" : inProgressMs !== null ? "in_progress" : "ok";
  return { latest, collectedDate, daysSince, basisLag, execution, inProgressMs, noJudgmentCount, problems, state };
}

/** 공고 트랙(사전규격·입찰공고) 일일 수집의 사실. 목록에 있으면 적재된 회차다. */
export interface DailyNoticeStatus {
  latest: DailyPlanRun | null;
  collectedDate: string | null;
  daysSince: number | null;
  /** 그 회차의 적재 경고 수. 조회하지 않았거나 실패했으면 `null`이다. */
  warningCount: number | null;
  problems: Array<"no_daily_run" | "stale">;
  state: "ok" | "warning";
}

export function dailyNoticeStatus(runs: readonly RunSummary[], warningCount: number | null, now: number): DailyNoticeStatus {
  const latest = latestDailyRun(runs, "notices");
  if (!latest) return { latest: null, collectedDate: null, daysSince: null, warningCount: null, problems: ["no_daily_run"], state: "warning" };
  const collectedDate = kstDate(latest.run.generated_at);
  const today = kstDate(now);
  const daysSince = collectedDate && today ? daysBetween(collectedDate, today) : null;
  const problems: DailyNoticeStatus["problems"] = isBasisStale(latest.basisDate, now) ? ["stale"] : [];
  return { latest, collectedDate, daysSince, warningCount, problems, state: problems.length ? "warning" : "ok" };
}
