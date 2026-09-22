import type { Page } from "@playwright/test";
import type {
  BidDeltaDecisionQueueItem, BidDeltaDecisionQueueResponse, OpportunityLinkView, OpportunityListItem,
  OpportunityListResponse, OrderPlanListItem, OrderPlanListResponse, PreSpecListItem, PreSpecListResponse,
  WorkloadResponse,
} from "../src/lib/types";
import { mockApi } from "./api-mock";

/**
 * 실무자 대시보드(M6·ADR-0067) 고정 응답.
 *
 * 패널마다 **건수 키 하나와 목록 호출 하나**가 짝지어 있다. 이 fixture는 그 둘을
 * 일부러 다른 값으로 준다 — 화면이 건수를 목록 길이로 덮거나 목록에서 다시 세면
 * 바로 드러나게 하기 위해서다(ADR-0067 결정 7).
 */

/** 패널 기준 시각. KST 2026-09-17 12:00이다. 보류 재검토 fixture와 같은 시각을 쓴다. */
export const DASH_NOW = "2026-09-17T03:00:00Z";
export const HOLD_NOW = DASH_NOW;
export const reference = "2026-09-07T08:00:00Z";

const linkBase: OpportunityLinkView = {
  id: 0, stage: "notice", link_type: "official", status: "확정", search_strategy: null, attempted_strategies: [],
  agency_match: null, last_searched_at: null, evidence_external_no: null, evidence_bid_no: null,
  search_target_kind: null, human_decision: null, reviewer_name: null, reviewed_at: null, review_reason: null,
  record_type: "bid_notice", record_id: 0, notice_id: 0, order_plan_id: null, source_type: "bid_notice",
  title: null, agency: null, external_id: null, record_external_id: null,
  budget: null, deadline_at: null, planned_order_year: null, planned_order_month: null,
};

function opportunity(id: number, overrides: Partial<OpportunityListItem>, links: Partial<OpportunityLinkView>[] = []): OpportunityListItem {
  return {
    id, section: "추적 중", pending_candidate_link_count: 0, open_blocking_item_count: 0,
    tracking_status: "계속 추적", tracking_reason: null, tracking_selected_by: null, tracking_selected_at: null,
    recheck_signal: false, recheck_signal_at: null, recheck_signal_link_id: null,
    first_registered_stage: "bid_notice", action_reasons: [], hold_review_due_at: null,
    links: links.map((link, index) => ({ ...linkBase, id: id * 10 + index, record_id: id, notice_id: id, ...link })),
    ...overrides,
  };
}

export function opportunityList(items: OpportunityListItem[], total = items.length): OpportunityListResponse {
  return {
    items, total, limit: 5, offset: 0,
    section_counts: { "조치 필요": 0, "추적 중": 0, "보류": 0, "추적 종료": 0, "신규 입찰공고": 0, "미결정": 0 },
    action_reason_counts: { new_link: 0, candidate_pending: 0, merge_confirmation: 0, blocking_item: 0, hold_overdue: 0 },
  };
}

// ── 마감 임박 추적 건 ──────────────────────────────────────────────────────
// 서버가 이미 `deadline_within_days=7&sort=deadline`으로 걸러 마감순으로 준 3건.
// 종류(입찰 마감·의견등록 마감)는 화면이 `links[]`에서 고른다 — 서버는 대표 마감을
// 고르지 않는다(ADR-0067 결정 4).
export const deadlineItems: OpportunityListItem[] = [
  opportunity(501, { tracking_status: "계속 추적" }, [
    { title: "종료된 지능형 업무 시스템 본공고", agency: "경상남도", source_type: "bid_notice", record_type: "bid_notice", deadline_at: "2026-09-19T00:00:00Z" },
  ]),
  opportunity(502, { tracking_status: "보류", section: "보류" }, [
    { title: "신규 지능형 행정 지원 사전규격", agency: "해솔시청", source_type: "pre_spec", record_type: "pre_spec", deadline_at: "2026-09-21T02:00:00Z" },
  ]),
  opportunity(503, { tracking_status: "계속 추적" }, [
    // 기각된 후보의 마감은 고르지 않는다. 같은 사업의 확정 연결 마감만 쓴다.
    { id: 5039, link_type: "candidate", status: "후보 확인 대기", human_decision: null, title: "후보 연결", deadline_at: "2026-09-17T09:00:00Z" },
    { title: "행정정보 연계시스템 유지관리 공고", agency: "다온구청", source_type: "bid_notice", record_type: "bid_notice", deadline_at: "2026-09-23T05:00:00Z" },
  ]),
];
export const deadlineList = opportunityList(deadlineItems, 7);

// ── 사람 확인 필요 · 공고별 확인 항목 ─────────────────────────────────────
export const blockingItems: OpportunityListItem[] = [
  opportunity(601, {
    section: "조치 필요", open_blocking_item_count: 2, action_reasons: ["blocking_item"], tracking_status: "종료",
  }, [{ title: "지방공기업 업무혁신 및 데이터 연계 체계 고도화", agency: "온빛광역시" }]),
];
export const blockingList = opportunityList(blockingItems, 3);

// ── 최종 결정 대기 ────────────────────────────────────────────────────────
function queueItem(id: number, overrides: Partial<BidDeltaDecisionQueueItem>): BidDeltaDecisionQueueItem {
  return {
    opportunity_id: id, title: null, agency: null, tracking_status: "계속 추적", first_registered_stage: "bid_notice",
    recheck_signal: false, bid_notice_external_id: `BID-${id}`, comparison_count: 0, latest_final_decision: null,
    decision_currentness: "unknown", deadline_at: null, budget: null, estimated_price: null, ...overrides,
  };
}
export const decisionItems: BidDeltaDecisionQueueItem[] = [
  queueItem(701, { title: "종료된 지능형 업무 시스템 본공고", agency: "경상남도", deadline_at: "2026-09-19T00:00:00Z", estimated_price: "940000000" }),
  queueItem(702, { title: "공공기관 업무시스템 개선 검토", agency: "강원특별자치도" }),
];
export const decisionList: BidDeltaDecisionQueueResponse = { items: decisionItems, total: 4, limit: 5, offset: 0 };

// ── 사람 확인 필요 · 개요 검토 ────────────────────────────────────────────
function preSpec(noticePk: number, title: string, deadline: string | null, status: PreSpecListItem["overview_review_status"]): PreSpecListItem {
  return {
    review_exclusion_status: "included", review_exclusion_actor_name: null, review_exclusion_reason: null,
    review_exclusion_changed_at: null, notice_pk: noticePk, pre_spec_no: `PRE-${noticePk}`, title,
    agency: "해솔시청", demand_agency: null, published_at: "2026-09-10T00:00:00Z", deadline_at: deadline,
    budget: null, sw_business_status: "Y", business_division: null, origin: "신규", opportunity_id: null,
    tracking_status: null, kept_by_tracking: false,
    document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
    overview_review_status: status, grade: null, grade_source: null,
    display_assessment: {
      grade: null, status: "none", source: "none", basis_run_id: null, assessed_at: null, quality_status: null,
      reason_codes: [], axes: [], verification_items: [], semantic_status: null, semantic_scope: [], latest_run_status: status,
    },
    auto_preparation_status: "blocked", auto_preparation_reason: null, latest_deep_review_id: null,
    first_observed_at: "2026-09-10T00:00:00Z", last_observed_at: "2026-09-10T00:00:00Z", next_action: "confirm_overview",
  };
}
export function preSpecList(items: PreSpecListItem[], total = items.length): PreSpecListResponse {
  return {
    items, total, limit: 5, offset: 0, overview_status_counts: [],
    workspace_counts: { actionable: total, recent: total, tracking: total, all: total },
    deadline_scope_counts: { current: total, passed: 0 },
  };
}
export const overviewFailedItems = [preSpec(801, "안전한 문서 준비 사전규격", "2026-09-20T00:00:00Z", "failed")];
export const overviewAttentionItems = [preSpec(802, "통합 인증·증명 서비스 사전규격", "2026-09-18T00:00:00Z", "needs_human_review")];

// ── 새 우선 검토 발주계획 ─────────────────────────────────────────────────
function orderPlan(pk: number, title: string, agency: string, budget: number | null, year: string | null, month: string | null): OrderPlanListItem {
  return {
    order_plan_pk: pk, order_plan_unty_no: `PLAN-${pk}`, source_url: null, title, agency_name: agency,
    business_division: null, budget_amount: budget, planned_order_year: year, planned_order_month: month,
    contract_method: null, notice_posted: null, source_run_id: "lifecycle-20260917-plans",
    observed_at: "2026-09-16T22:00:00Z", stage1_status: "selected", stage1_rank: 1, stage1_score: 0.8,
    nearest_capability: null, stage2_status: "success", qwen_relevance: "relevant", qwen_score: 0.9,
    qwen_reason: null, human_feedback: null,
    tracking: { opportunity_id: 9000 + pk, tracking_status: "미선택", tracking_reason: null, tracking_selected_by: null, tracking_selected_at: null },
    execution_id: "exec-dashboard", policy_version: "c2-order-plan-screening-v4", first_observed_at: "2026-09-16T22:00:00Z",
  };
}
export const newPlanItems: OrderPlanListItem[] = [
  orderPlan(901, "행정정보 공동이용 확대 사업 발주계획", "경기도청", 1_240_000_000, "2026", "11"),
  orderPlan(902, "경제금융교육 통합 홈페이지 구축", "예금보험공사", null, "2026", null),
];
export const newPlanList: OrderPlanListResponse = {
  schema_version: "order-plan-list-response.v5", scope: null, producer: "order-plan-review-api",
  consumer: "order-plan-review-client", items: newPlanItems, total: 12, limit: 5, offset: 0,
};

// ── 누적 업무 건수 ────────────────────────────────────────────────────────
// `human_check_required`는 **서버가 낸 합계**다. 하위 둘(2·3)과 일부러 다른 값을 둬
// 화면이 직접 더하지 않는다는 것을 검사한다(ADR-0067 결정 5).
export const dashboardWorkload: WorkloadResponse = {
  generated_at: DASH_NOW,
  items: [
    { key: "order_plan_pending", count: 24, unavailable_reason: null },
    { key: "pre_spec_deep_review_ready", count: 7, unavailable_reason: null },
    { key: "tracking_action_required", count: 3, unavailable_reason: null },
    { key: "tracking_hold_review_due", count: 1, unavailable_reason: null },
    { key: "bid_final_decision_pending", count: 4, unavailable_reason: null },
    { key: "tracking_deadline_imminent", count: 7, unavailable_reason: null },
    { key: "human_check_required", count: 9, unavailable_reason: null },
    { key: "overview_human_review", count: 2, unavailable_reason: null },
    { key: "blocking_items_open", count: 3, unavailable_reason: null },
    { key: "order_plan_new_priority", count: 12, unavailable_reason: null },
  ],
};

/** 키 하나만 바꾼 workload 응답. */
export function workloadWith(key: WorkloadResponse["items"][number]["key"], count: number | null, reason: string | null = null): WorkloadResponse {
  return { ...dashboardWorkload, items: dashboardWorkload.items.map(item => item.key === key ? { ...item, count, unavailable_reason: reason } : item) };
}

// ── 보류 재검토 ───────────────────────────────────────────────────────────
function holdItem(id: number, title: string | null, dueAt: string, overdue: boolean, reason: string | null, selectedBy: string | null): OpportunityListItem {
  return {
    id, section: overdue ? "조치 필요" : "보류", pending_candidate_link_count: 0, open_blocking_item_count: 0,
    tracking_status: "보류", tracking_reason: reason, tracking_selected_by: selectedBy,
    tracking_selected_at: new Date(Date.parse(dueAt) - 14 * 86_400_000).toISOString(),
    recheck_signal: false, recheck_signal_at: null, recheck_signal_link_id: null, first_registered_stage: "pre_spec",
    action_reasons: overdue ? ["hold_overdue"] : [], hold_review_due_at: dueAt,
    links: title === null ? [] : [{
      ...linkBase, id: id * 10, record_type: "pre_spec", record_id: id, notice_id: id, source_type: "pre_spec",
      title, agency: "해솔시청", external_id: `PRE-${id}`, record_external_id: `PRE-${id}`,
    }],
  };
}
// 서버가 기한순으로 준 기한 지남 2건과 3일 이내 3건. 마이크로초와 한국 자정 경계를 함께 둔다.
export const holdReviewItems: OpportunityListItem[] = [
  holdItem(401, "공공데이터 통합관리체계 고도화", "2026-09-14T05:00:00Z", true, "예산 편성 결과를 확인한 뒤 다시 검토", "김보류"),
  holdItem(402, null, "2026-09-17T01:00:00.654321Z", true, null, null),
  holdItem(403, "시민 통합행정서비스 구축", "2026-09-17T15:30:00.123456Z", false, "발주처 사업 범위 확정 대기", "이담당"),
  holdItem(404, "지역산업 데이터 연계 플랫폼 구축", "2026-09-19T14:59:59Z", false, "  ", "박선택"),
  holdItem(405, "통합 인증·증명 서비스 운영", "2026-09-20T02:00:00+00:00", false, "공동수급 조건 확인 필요", "최담당"),
];
export function holdReviewList(items: OpportunityListItem[], total = items.length): OpportunityListResponse {
  return opportunityList(items, total);
}

export interface DashboardMockOptions {
  workload?: WorkloadResponse;
  deadlines?: OpportunityListResponse;
  decisions?: BidDeltaDecisionQueueResponse;
  overviewFailed?: PreSpecListResponse;
  overviewAttention?: PreSpecListResponse;
  blocking?: OpportunityListResponse;
  holdReviews?: OpportunityListResponse;
  newPlans?: OrderPlanListResponse;
  workloadError?: boolean;
  deadlineError?: boolean;
  decisionError?: boolean;
  overviewError?: boolean;
  blockingError?: boolean;
  holdReviewError?: boolean;
  newPlanError?: boolean;
  /** 고정 시계를 세우지 않는다(기본은 `DASH_NOW`). */
  skipClock?: boolean;
}

export interface DashboardMockTrace {
  /** 대시보드는 읽기 전용이다. 여기에 값이 생기면 화면이 무언가를 저장한 것이다. */
  writes: string[];
  requests: { path: string; params: Record<string, string> }[];
}

export async function mockDashboard(page: Page, options: DashboardMockOptions = {}): Promise<DashboardMockTrace> {
  await mockApi(page);
  if (!options.skipClock) await page.clock.setFixedTime(new Date(DASH_NOW));
  const trace: DashboardMockTrace = { writes: [], requests: [] };
  page.on("request", request => {
    if (request.url().includes("/api/") && !["GET", "HEAD"].includes(request.method())) trace.writes.push(`${request.method()} ${request.url()}`);
  });
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") return route.fallback();
    const params = Object.fromEntries(url.searchParams);
    let body: unknown;
    let failure = false;
    if (url.pathname === "/api/workload") { body = options.workload ?? dashboardWorkload; failure = !!options.workloadError; }
    else if (url.pathname === "/api/opportunities" && url.searchParams.has("deadline_within_days")) {
      body = options.deadlines ?? deadlineList; failure = !!options.deadlineError;
    }
    else if (url.pathname === "/api/opportunities" && url.searchParams.get("reason") === "blocking_item") {
      body = options.blocking ?? blockingList; failure = !!options.blockingError;
    }
    else if (url.pathname === "/api/opportunities" && url.searchParams.has("hold_review")) {
      // 기본은 재검토할 보류가 없는 상태다.
      body = options.holdReviews ?? holdReviewList([]); failure = !!options.holdReviewError;
    }
    else if (url.pathname === "/api/bid-delta/decision-queue") { body = options.decisions ?? decisionList; failure = !!options.decisionError; }
    else if (url.pathname === "/api/pre-specs" && url.searchParams.get("overview_view") === "failed") {
      body = options.overviewFailed ?? preSpecList(overviewFailedItems, 2); failure = !!options.overviewError;
    }
    else if (url.pathname === "/api/pre-specs" && url.searchParams.get("overview_view") === "attention") {
      body = options.overviewAttention ?? preSpecList(overviewAttentionItems, 2); failure = !!options.overviewError;
    }
    else if (url.pathname === "/api/order-plans" && url.searchParams.has("first_observed_from")) {
      body = options.newPlans ?? newPlanList; failure = !!options.newPlanError;
    }
    else return route.fallback();
    trace.requests.push({ path: url.pathname, params });
    await route.fulfill({
      status: failure ? 503 : 200, contentType: "application/json",
      body: JSON.stringify(failure ? { error: { code: "fixture_unavailable", message: "합성 조회 실패", details: null } } : body),
    });
  });
  return trace;
}
