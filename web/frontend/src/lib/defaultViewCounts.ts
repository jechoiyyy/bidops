import { api } from "./api";
import type { BidDeltaDecisionQueueItem, OpportunityListResponse, PreSpecListQuery, PreSpecListResponse } from "./types";

/**
 * 대시보드 타일·사이드바 건수가 **링크한 목록의 기본 보기와 같은 정의**로 세도록 한 곳에 둔다
 * (설계고도화안 A-6·C-1, 2026-11-18). 건수는 그 목록이 쓰는 API의 `total`이며 화면이
 * 목록을 다시 세지 않는다. 같은 query key를 써서 대시보드와 사이드바가 한 번만 부른다.
 */

/**
 * 발주계획 목록의 기본 보기 `관련`(모델 판단 `relevant` AND 추적 `미선택`, 누적 모드)과
 * 옆 탭 `불확실`(모델 판단 `uncertain` AND 추적 `미선택`). 목록 화면의 프리셋과 같은 두 축이다
 * (`pages/OrderPlansPage.tsx` `PRESETS`).
 */
export function orderPlanViewTotalQuery(relevance: "relevant" | "uncertain") {
  return {
    queryKey: ["order-plans", "default-view-total", relevance] as const,
    queryFn: async ({ signal }: { signal: AbortSignal }) =>
      (await api.getOrderPlans({ qwen_relevance: relevance, tracking_status: "미선택", limit: 1 }, { signal })).total,
    staleTime: 60_000,
  };
}

/**
 * 사전규격 목록이 주소 없이 열렸을 때 보내는 질의(`pages/PreSpecsPage.tsx` `listQuery`의 기본값):
 * `검토할 항목` 업무 보기, 마감 `마감 전·미확인`, SW사업대상만, 개요 상태 전체, 검토 제외 전체.
 */
export const PRE_SPEC_DEFAULT_VIEW_QUERY: PreSpecListQuery = {
  workspace: "actionable",
  deadline_scope: "current",
  sw_only: true,
  overview_view: "all",
  review_exclusion: "all",
  sort: "deadline",
};

/**
 * 캐시에는 목록 응답 그대로를 둔다. 사전규격 화면은 추적 저장 뒤 `["pre-specs"]` 아래 모든 캐시를
 * 목록 응답으로 보고 고쳐 쓰므로(`setQueriesData`), 숫자만 두면 그 갱신이 깨진다. 건수는 `select`로 읽는다.
 */
export const PRE_SPEC_PAGE_SIZE = 200;

export function preSpecPageOptions(params: PreSpecListQuery, normalizedSearch: string) {
  const key = Object.fromEntries(Object.entries({ ...params, q: normalizedSearch }).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  ));
  return {
    queryKey: ["pre-specs", key] as const,
    queryFn: ({ signal }: { signal: AbortSignal }) => api.getPreSpecs(params, { signal }),
  };
}

export function preSpecDefaultViewTotalQuery() {
  return {
    ...preSpecPageOptions({ ...PRE_SPEC_DEFAULT_VIEW_QUERY, limit: PRE_SPEC_PAGE_SIZE, offset: 0 }, ""),
    select: (response: PreSpecListResponse) => response.total,
    staleTime: 60_000,
  };
}

/**
 * 사전규격 `확인 필요` 보기(2026-11-19): 기본 보기와 같은 축에서 업무 보기만 `needs_check`다.
 * `/pre-specs?workspace=needs_check`가 열릴 때 목록 화면이 보내는 질의와 같다(마감 `마감 전·미확인`).
 * 서버 workload `pre_spec_needs_check`와 같은 값이다.
 */
export const PRE_SPEC_NEEDS_CHECK_QUERY: PreSpecListQuery = {
  ...PRE_SPEC_DEFAULT_VIEW_QUERY,
  workspace: "needs_check",
};

export function preSpecNeedsCheckTotalQuery() {
  return {
    queryKey: ["pre-specs", "needs-check-total"] as const,
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      api.getPreSpecs({ ...PRE_SPEC_NEEDS_CHECK_QUERY, limit: 1, offset: 0 }, { signal }),
    select: (response: PreSpecListResponse) => response.total,
    staleTime: 60_000,
  };
}

/**
 * 사전규격 `최근 수집` 보기에 첫 관측일 하한을 건 질의(대시보드 `새로 볼 것`, 설계고도화안 C-8).
 * `/pre-specs?workspace=recent&observed_from=<YYYY-MM-DD>`가 열릴 때 목록 화면이 보내는 것과 같은 축이다 —
 * 마감 구간은 `검토할 항목` 밖에서는 `current`, SW사업대상만, 개요 상태 전체, 검토 제외 전체, 상한 없음.
 */
export function preSpecRecentQuery(observedFrom: string): PreSpecListQuery {
  return {
    workspace: "recent",
    deadline_scope: "current",
    sw_only: true,
    overview_view: "all",
    review_exclusion: "all",
    observed_from: observedFrom,
    sort: "observed",
  };
}

export function preSpecRecentTotalQuery(observedFrom: string) {
  return {
    queryKey: ["pre-specs", "recent-total", observedFrom] as const,
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      api.getPreSpecs({ ...preSpecRecentQuery(observedFrom), limit: 1, offset: 0 }, { signal }),
    select: (response: PreSpecListResponse) => response.total,
    staleTime: 60_000,
  };
}

/**
 * 사업 추적의 기본 구역 `조치 필요`(목록 화면이 주소 없이 열 때의 질의). `total`이 구역 건수이고
 * `action_reason_counts`가 사유 칩의 건수다 — 사유 칩(`reason=hold_overdue` 등)을 누르면 그 건수의
 * 목록이 열린다. 캐시는 목록 응답 그대로 둔다(`["opportunities"]` 무효화 대상).
 */
export function opportunityActionRequiredQuery() {
  return {
    queryKey: ["opportunities", "action-required-total"] as const,
    queryFn: ({ signal }: { signal: AbortSignal }): Promise<OpportunityListResponse> =>
      api.getOpportunities({ section: "조치 필요", sort: "created_at", limit: 1, offset: 0 }, { signal }),
    staleTime: 60_000,
  };
}

/**
 * 최종 Go/No-Go 목록의 기본 보기 `검토 대상`.
 *
 * 미결정만 남기면 **오래된 Go 결정**이 목록에서 사라진다. 새 차수로 현재성이
 * `stale`이 된 결정과 현재성 `unknown`은 담당자가 다시 봐야 하는 것이지 끝난 것이
 * 아니다. 결정이 없어도 입찰공고가 연결되지 않은 사업은 결정할 공고가 없으므로
 * 검토 대상에 올리지 않고 전체 보기에 남긴다.
 */
export function isGoNoGoReviewTarget(item: BidDeltaDecisionQueueItem): boolean {
  if (!item.latest_final_decision) return item.bid_notice_external_id !== null;
  return item.decision_currentness !== "current";
}

/** Go/No-Go 목록이 한 번에 받는 범위(서버 상한 500). 넘치면 받은 범위 기준이다. */
export const GO_NO_GO_PAGE_SIZE = 500;

export function goNoGoReviewTotalQuery() {
  return {
    queryKey: ["bid-delta-decision-queue", "default-view-total"] as const,
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const response = await api.getBidDeltaDecisionQueue({ status: "all", limit: GO_NO_GO_PAGE_SIZE, offset: 0 }, { signal });
      return {
        count: response.items.filter(isGoNoGoReviewTarget).length,
        /** 받은 범위가 전체인지. 아니면 건수는 받은 범위 기준이다(목록 화면과 같은 규칙). */
        complete: response.items.length >= response.total,
      };
    },
    staleTime: 60_000,
  };
}
