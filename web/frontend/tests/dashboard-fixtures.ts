import type { Page } from "@playwright/test";
import type { DeadlineNotice, OpportunityListItem, OpportunityListResponse, RunStatsResponse, RunSummary, ValidationMetricsResponse, WorkloadResponse } from "../src/lib/types";
import { mockApi } from "./api-mock";

export const DASH_RUN = "dashboard-preview-20260907";
export const OTHER_RUN = "dashboard-preview-20260904";
export const reference = "2026-09-07T08:00:00Z";
export const dashboardNotices: DeadlineNotice[] = [
  ["공공데이터 통합관리체계 고도화", "해솔시청", "2026-09-08T07:00:00Z", "우선 검토", 2],
  ["시민 통합행정서비스 구축", "온빛광역시", "2026-09-09T05:00:00Z", "검토 권장", 1],
  ["지역산업 데이터 연계 플랫폼 구축", "새온산업진흥원", "2026-09-11T07:00:00Z", "우선 검토", 0],
  ["통합 인증·증명 서비스 운영", "하람공공서비스원", "2026-09-12T05:00:00Z", "관찰 대상", 1],
  ["행정정보 연계시스템 유지관리", "다온구청", "2026-09-14T06:00:00Z", "검토 권장", 0],
].map(([title, agency, deadline, grade, checks], index) => ({
  id: index + 1, notice_key: `bid:DEMO:${index}`, run_id: DASH_RUN, title: String(title), agency: String(agency),
  published_at: reference, deadline_at: String(deadline), estimated_price: null,
  sample_role: "analysis", sample_stratum: null, collection_bucket: null, grade: String(grade), readiness: null, focus: null,
  attachment_count: 0, attachment_status: "none", blocking_verification_items: Array.from({length:Number(checks)}, (_, i) => `확인 항목 ${i+1}`),
}));
export const dashboardStats: RunStatsResponse = {
  run_id: DASH_RUN, generated_at: reference, timezone: "Asia/Seoul", collected_count: 1240, candidate_count: 386,
  sample_count: 180, priority_review_count: 24, audit_missed_count: 2,
  funnel: [{key:"review_queue",label:"검토 대기",count:148}],
  grade_distribution: [
    {key:"우선 검토",label:"우선 검토",count:24}, {key:"검토 권장",label:"검토 권장",count:56},
    {key:"관찰 대상",label:"관찰 대상",count:62}, {key:"제외",label:"제외",count:38},
  ], readiness_distribution: [], focus_distribution: [], imminent_deadlines: dashboardNotices,
  verification_requests: [
    {item:"유사 사업 실적 인정 범위", count:4, notice_pks:[1,2,3,4], profile_sections:[]},
    {item:"직접생산확인증명서",count:2,notice_pks:[1,2],profile_sections:["5.2"]},
    {item:"공동수급 참여 조건",count:1,notice_pks:[2],profile_sections:[]},
  ],
};
export const dashboardMetrics: ValidationMetricsResponse = {
  run_id:DASH_RUN, metrics:[{key:"human_reference",label:"사람 정답 비교",value:null,percentage:null,threshold:null,
    meets_threshold:null,status:"not_measurable",basis:{numerator:0,denominator:0,detail:{}},reason:"평가 기준 미확인"}],
};
export const dashboardWorkload: WorkloadResponse = {
  generated_at: reference,
  items: [
    {key:"order_plan_pending",count:24,unavailable_reason:null},
    {key:"pre_spec_deep_review_ready",count:7,unavailable_reason:null},
    {key:"tracking_action_required",count:3,unavailable_reason:null},
    {key:"tracking_hold_review_due",count:1,unavailable_reason:null},
    {key:"bid_final_decision_pending",count:0,unavailable_reason:null},
  ],
};
export const dashboardRuns: RunSummary[] =[DASH_RUN,OTHER_RUN].map((run_id,index)=>({
  run_id,kind:"notices",window_from:index ? "2026-08-31" : "2026-09-03", window_to:index ? "2026-09-04" : "2026-09-07",
  timezone:"Asia/Seoul",generated_at:reference,screening_basis:null,status:"active",superseded_by:null,
  counts:{notices:1240,judgments:180,reviews:index ? 18 : 32,collection:{}},
}));

// 보류 재검토 패널 기준 시각. KST 2026-09-17 12:00이다.
export const HOLD_NOW = "2026-09-17T03:00:00Z";
function holdItem(id: number, title: string | null, dueAt: string, overdue: boolean, reason: string | null, selectedBy: string | null): OpportunityListItem {
  return {
    id, section: overdue ? "조치 필요" : "보류", pending_candidate_link_count: 0, open_blocking_item_count: 0,
    tracking_status: "보류", tracking_reason: reason, tracking_selected_by: selectedBy,
    tracking_selected_at: new Date(Date.parse(dueAt) - 14 * 86_400_000).toISOString(),
    recheck_signal: false, recheck_signal_at: null, recheck_signal_link_id: null, first_registered_stage: "pre_spec",
    action_reasons: overdue ? ["hold_overdue"] : [], hold_review_due_at: dueAt,
    links: title === null ? [] : [{
      id: id * 10, stage: "notice", link_type: "official", status: "확정", search_strategy: null, attempted_strategies: [],
      agency_match: null, last_searched_at: null, evidence_external_no: null, evidence_bid_no: null, human_decision: null,
      reviewer_name: null, reviewed_at: null, review_reason: null, record_type: "pre_spec", record_id: id, notice_id: id,
      order_plan_id: null, source_type: "pre_spec", title, agency: "해솔시청", external_id: `PRE-${id}`, record_external_id: `PRE-${id}`,
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
  return {
    items, total, limit: 5, offset: 0,
    section_counts: { "조치 필요": 0, "추적 중": 0, "보류": 0, "추적 종료": 0, "신규 입찰공고": 0, "미결정": 0 },
    action_reason_counts: { new_link: 0, candidate_pending: 0, merge_confirmation: 0, blocking_item: 0, hold_overdue: 0 },
  };
}

export async function mockDashboard(page: Page, options: {
  stats?: Partial<RunStatsResponse>; metrics?: ValidationMetricsResponse; runs?: RunSummary[]; workload?: WorkloadResponse;
  holdReviews?: OpportunityListResponse;
  statsError?: boolean; metricsError?: boolean; runsError?: boolean; workloadError?: boolean; holdReviewError?: boolean;
} = {}) {
  await mockApi(page);
  const writes: string[] = [];
  const holdRequests: URLSearchParams[] = [];
  page.on("request", request=> { if(request.url().includes("/api/") && !["GET","HEAD"].includes(request.method())) writes.push(request.method()+" "+request.url()); });
  await page.route("**/api/**", async route=> {
    const url=new URL(route.request().url());
    if(route.request().method()!=="GET") return route.fallback();
    let body: unknown;
    let failure=false;
    if(url.pathname==="/api/runs") {body={items:options.runs ?? dashboardRuns,total:(options.runs ?? dashboardRuns).length};failure=!!options.runsError;}
    else if(url.pathname.startsWith("/api/runs/") && url.pathname.endsWith("/stats")) {
      const id=decodeURIComponent(url.pathname.split("/")[3]);
      body={...structuredClone(dashboardStats),...options.stats,run_id:id,...(id===OTHER_RUN ? {collected_count:840,candidate_count:260} : {})};failure=!!options.statsError;
    }
    else if(url.pathname==="/api/metrics/validation") {body={...(options.metrics ?? dashboardMetrics),run_id:url.searchParams.get("run_id")};failure=!!options.metricsError;}
    else if(url.pathname==="/api/workload") {body=options.workload ?? dashboardWorkload;failure=!!options.workloadError;}
    // 기본은 재검토할 보류가 없는 상태다. 승인 시안 배치 검사는 빈 패널 위에서 잰다.
    else if(url.pathname==="/api/opportunities") {holdRequests.push(url.searchParams);body=options.holdReviews ?? holdReviewList([]);failure=!!options.holdReviewError;}
    else return route.fallback();
    await route.fulfill({status:failure?503:200,contentType:"application/json",body:JSON.stringify(failure?{error:{code:"fixture_unavailable",message:"합성 조회 실패",details:null}}:body)});
  });
  return {writes,holdRequests};
}
