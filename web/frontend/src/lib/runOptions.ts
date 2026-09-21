import type { RunSummary } from "./types";
import { formatDateTime, formatRunRange } from "./format";

/**
 * 수집 회차 선택기의 옵션 조립 — **순수 함수만** 둔다(명세 §2.1).
 *
 * 실무 화면(발주계획·사전규격)과 운영 화면(`/runs`·상단바)이 같은 회차를 서로 다른
 * 말로 부르던 것을 한곳에서 만든다. 날짜 포맷터는 새로 만들지 않고 `lib/format.ts`의
 * `formatRunRange`·`formatDateTime`을 그대로 재사용한다 — 같은 회차가 화면마다
 * 다른 모양으로 보이지 않게 하는 것이 이 파일의 목적이기 때문이다.
 */

export interface SourceRunOption {
  value: string;
  label: string;
  description?: string;
}

/**
 * 옵션 설명을 누가 읽는가.
 *
 * - `practitioner`: 같은 기간을 다시 수집한 회차를 구분할 수 있게 **생성 시각**을 적는다.
 *   회차 식별자 원문은 적지 않는다(M1 승인 2026-09-21). 식별자가 필요한 사람은 URL과
 *   `목록 기준` 다이얼로그, 운영 화면에서 전문을 그대로 읽는다 — 줄여서 적지는 않는다.
 * - `ops`: 회차 식별자 원문. 운영 화면은 이 값으로 실행·산출물을 찾아간다.
 */
export type SourceRunAudience = "practitioner" | "ops";

export interface BuildSourceRunOptionsInput {
  /** `/api/runs`가 준 회차. 화면이 자기 kind로 이미 걸러 넘긴다. */
  runs: readonly RunSummary[];
  /**
   * 회차 목록에는 없지만 화면이 아는 회차(발주계획의 C-2 실행이 가리키는 `source_run_id`).
   * 수집 metadata가 없으므로 **날짜를 지어내지 않는다.**
   */
  extraRunIds?: readonly string[];
  /** URL에 걸려 있는 회차. 목록에 없어도 조용히 다른 회차로 바꾸지 않는다. */
  selectedRunId?: string | null;
  /** 회차 목록 조회가 실패했는가. 목록에 없는 이유를 가르는 데만 쓴다. */
  isError?: boolean;
  audience?: SourceRunAudience;
}

/** `2026-09-19 ~ 2026-09-20 수집`. 수집 기간이 없으면 생성 시각으로 적는다. */
export function runOptionLabel(run: RunSummary): string {
  if (run.window_from && run.window_to) {
    return `${formatRunRange(run.run_id, run.window_from, run.window_to)} 수집`;
  }
  return `${formatDateTime(run.generated_at)} 수집분`;
}

/**
 * 회차 옵션을 만든다. 누적 옵션(`모든 수집 회차`)은 여기 없다 — 그 문구와 빈 값
 * 계약은 화면 컴포넌트(`SourceRunFilter`)가 소유한다.
 *
 * 순서는 화면이 넘긴 `runs` 순서(보통 생성 시각 내림차순)이고, 목록에 없는 회차는
 * 그 뒤에 붙는다. 같은 회차가 여러 출처에 있어도 한 번만 나온다.
 */
export function buildSourceRunOptions({
  runs,
  extraRunIds = [],
  selectedRunId = null,
  isError = false,
  audience = "practitioner",
}: BuildSourceRunOptionsInput): SourceRunOption[] {
  const byId = new Map(runs.map((run) => [run.run_id, run] as const));
  const ordered: string[] = [];
  const seen = new Set<string>();
  const push = (runId: string | null | undefined) => {
    const id = runId?.trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    ordered.push(id);
  };
  runs.forEach((run) => push(run.run_id));
  extraRunIds.forEach(push);
  push(selectedRunId);

  return ordered.map((runId) => {
    const run = byId.get(runId);
    if (run) {
      return {
        value: runId,
        label: runOptionLabel(run),
        description: audience === "ops" ? runId : `${formatDateTime(run.generated_at)} 생성`,
      };
    }
    // 고른 회차가 목록에 없다. **다른 회차로 바꾸지 않고** 왜 이름을 모르는지만 적는다.
    if (runId === selectedRunId?.trim()) {
      return {
        value: runId,
        label: "선택한 회차 (목록에 없음)",
        description: isError ? "회차 목록 조회 실패" : "목록에서 확인할 수 없음",
      };
    }
    // 실행에만 있는 회차. 수집 기간도 생성 시각도 모르므로 날짜를 지어내지 않는다.
    return {
      value: runId,
      label: "수집 정보 없는 회차",
      description: audience === "ops" ? runId : "수집 기록을 확인할 수 없음",
    };
  });
}
