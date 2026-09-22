import type { Page } from "@playwright/test";
import { searchKey, searchMatches } from "../src/lib/search";

/**
 * 사업 추적 화면 회귀.
 *
 * fixture는 승인된 시안(`bidops-opportunities-erp-20260907`)과 같은 길이·밀도의
 * 사업명·기관을 쓰되 값은 계약 형태로만 넣는다. 구역(`section`)과 구역 건수
 * (`section_counts`)는 **서버가 준 값**이며 화면이 다시 판정하지 않는다.
 */

export type Fixture = Record<string, unknown> & { id: number };

const baseLink = {
  search_strategy: null,
  attempted_strategies: [],
  agency_match: null,
  last_searched_at: null,
  evidence_external_no: null,
  evidence_bid_no: null,
  human_decision: null,
  reviewer_name: null,
  reviewed_at: null,
  review_reason: null,
  record_type: null,
  record_id: null,
  notice_id: null,
  order_plan_id: null,
  source_type: null,
  title: null,
  agency: null,
  external_id: null,
  // 추가형 투영(0921_practitioner-screens spec §5). 대상이 없거나 해당하지
  // 않으면 null — 개별 builder가 대상에 맞는 값만 채운다.
  budget: null,
  deadline_at: null,
  planned_order_year: null,
  planned_order_month: null,
  record_external_id: null,
};

function orderPlanLink(
  id: number,
  title: string,
  agency: string,
  externalId: string,
  timing: { budget?: number | null; planned_order_year?: string | null; planned_order_month?: string | null } = {},
) {
  return {
    ...baseLink,
    id,
    stage: "order_plan",
    link_type: "official",
    status: "확정",
    record_type: "order_plan",
    record_id: id,
    order_plan_id: id,
    title,
    agency,
    external_id: externalId,
    budget: timing.budget ?? null,
    planned_order_year: timing.planned_order_year ?? null,
    planned_order_month: timing.planned_order_month ?? null,
    record_external_id: externalId,
  };
}

function noticeLink(
  id: number,
  sourceType: "pre_spec" | "bid_notice",
  title: string,
  agency: string,
  externalId: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    ...baseLink,
    id,
    stage: "notice",
    link_type: "official",
    status: "확정",
    record_type: sourceType,
    record_id: id,
    notice_id: id,
    source_type: sourceType,
    title,
    agency,
    external_id: externalId,
    record_external_id: externalId,
    ...overrides,
  };
}

/** 연결 후보가 남아 있는 건. 서버가 `조치 필요`로 준다. */
const candidatePending: Fixture = {
  id: 101,
  section: "조치 필요",
  pending_candidate_link_count: 1,
  open_blocking_item_count: 0,
  action_reasons: ["candidate_pending"],
  hold_review_due_at: null,
  tracking_status: "계속 추적",
  tracking_reason: "사업 범위와 기존 검토 방향이 맞아 후속 공고 확인",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-09-04T05:20:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [
    orderPlanLink(1001, "공공데이터 통합관리체계 고도화", "해솔시청", "DEMO-OP-001", {
      budget: 950_000_000, planned_order_year: "2026", planned_order_month: "11",
    }),
    noticeLink(1002, "pre_spec", "공공데이터 통합관리체계 고도화", "해솔시청", "DEMO-PS-001", {
      link_type: "candidate",
      status: "후보 확인 대기",
      search_strategy: "normalized",
      attempted_strategies: ["full", "normalized"],
      agency_match: true,
      last_searched_at: "2026-09-06T01:20:00Z",
    }),
  ],
};

/** 새 입찰공고가 붙어 재검토 신호가 남은 건. */
const recheckSignal: Fixture = {
  id: 202,
  section: "조치 필요",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  action_reasons: ["new_link"],
  hold_review_due_at: null,
  tracking_status: "계속 추적",
  tracking_reason: "후속 공고를 계속 확인",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-09-04T05:20:00Z",
  recheck_signal: true,
  recheck_signal_at: "2026-09-06T01:30:00Z",
  recheck_signal_link_id: 2002,
  first_registered_stage: "order_plan",
  links: [
    orderPlanLink(2001, "시설관리 업무시스템 구축", "도담도시공사", "DEMO-OP-002"),
    noticeLink(2002, "bid_notice", "시설관리 업무시스템 구축", "도담도시공사", "DEMO-BN-002", {
      budget: 620_000_000, deadline_at: "2026-09-25T00:00:00Z",
    }),
  ],
};

/** 입찰공고로 처음 등록됐고 아직 아무도 추적을 고르지 않은 건. §7.2에 따라 서버는
 * `신규 입찰공고` 구역으로 준다. 이 mock server는 구역을 다시 판정하지 않고 각
 * 픽스처가 밝힌 `section`을 그대로 돌려준다. */
const unselected: Fixture = {
  id: 303,
  section: "신규 입찰공고",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  action_reasons: [],
  hold_review_due_at: null,
  tracking_status: "미선택",
  tracking_reason: null,
  tracking_selected_by: null,
  tracking_selected_at: null,
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "bid_notice",
  links: [noticeLink(3001, "bid_notice", "학교 통합정보서비스 운영 및 유지관리", "새온교육지원청", "DEMO-BN-003")],
};

/** blocking 확인 항목에 담당자 답이 없는 건. */
const blockingItem: Fixture = {
  id: 404,
  section: "조치 필요",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 1,
  action_reasons: ["blocking_item"],
  hold_review_due_at: null,
  tracking_status: "계속 추적",
  tracking_reason: "참여 조건 확인 후 재검토",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-09-03T01:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "pre_spec",
  links: [noticeLink(61, "pre_spec", "환경측정 데이터 품질관리 용역", "누리환경공단", "DEMO-PS-004")],
};

/** 이름 검색으로 사전규격을 찾지 못한 건. 서버 구역은 `추적 중`이다. */
const searchUnconfirmed: Fixture = {
  id: 505,
  section: "추적 중",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  action_reasons: [],
  hold_review_due_at: null,
  tracking_status: "계속 추적",
  tracking_reason: "후속 공고 확인",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-09-02T01:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [
    orderPlanLink(5001, "연구성과 통합검색 서비스 개편", "가온연구원", "DEMO-OP-005"),
    {
      ...baseLink,
      id: 5002,
      stage: "notice",
      link_type: "candidate",
      status: "검색 미확인",
      search_strategy: "normalized",
      attempted_strategies: ["full", "normalized"],
      last_searched_at: "2026-09-06T01:20:00Z",
    },
  ],
};

const held: Fixture = {
  id: 606,
  section: "보류",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  // `tracking_selected_at + 14일`. 아직 기한이 지나지 않아 사유가 없다.
  action_reasons: [],
  hold_review_due_at: "2026-09-18T05:20:00Z",
  tracking_status: "보류",
  tracking_reason: "참여 조건을 추가 확인한 뒤 다시 검토",
  tracking_selected_by: "시안 검토자",
  tracking_selected_at: "2026-09-04T05:20:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [orderPlanLink(6001, "학사행정시스템 통합 유지관리", "온빛대학교", "DEMO-OP-006")],
};

const ended: Fixture = {
  id: 707,
  section: "추적 종료",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  action_reasons: [],
  hold_review_due_at: null,
  tracking_status: "종료",
  tracking_reason: "현재 사업 방향과 맞지 않아 추적 종료",
  tracking_selected_by: "시안 검토자",
  tracking_selected_at: "2026-09-01T05:20:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [orderPlanLink(7001, "디지털 자료관리 시스템 재구축", "새롬도서관", "DEMO-OP-007")],
};

/** 서버가 구역을 정하지 못한 건. 전체에서만 보인다. */
const undecided: Fixture = {
  id: 808,
  section: null,
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  action_reasons: [],
  hold_review_due_at: null,
  tracking_status: "미선택",
  tracking_reason: null,
  tracking_selected_by: null,
  tracking_selected_at: null,
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [orderPlanLink(8001, "공공업무 시스템 개선 용역", "기관 미확인", "DEMO-OP-008")],
};

/** 공식 번호로 이어진 레코드가 사람 상태를 가진 다른 사업기회에 있어 병합 확인 후보가 된 건(§3.2 |H|≥2). */
const mergeConfirmation: Fixture = {
  id: 909,
  section: "조치 필요",
  pending_candidate_link_count: 1,
  open_blocking_item_count: 0,
  action_reasons: ["merge_confirmation"],
  hold_review_due_at: null,
  tracking_status: "계속 추적",
  tracking_reason: "민원 상담 범위를 계속 확인",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-09-05T01:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [
    orderPlanLink(9001, "스마트 민원 상담 플랫폼 구축", "한울시청", "DEMO-OP-009"),
    noticeLink(9002, "bid_notice", "스마트 민원 상담 플랫폼 구축", "한울시청", "DEMO-BN-009", {
      link_type: "candidate",
      status: "후보 확인 대기",
      search_strategy: "merge_confirmation",
      last_searched_at: "2026-09-10T01:00:00Z",
    }),
  ],
};

/** 보류 뒤 14일 재검토 기한이 지난 건(§7.3). 기한은 서버 값이다. */
const holdOverdue: Fixture = {
  id: 910,
  section: "조치 필요",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  action_reasons: ["hold_overdue"],
  hold_review_due_at: "2026-09-15T01:00:00Z",
  tracking_status: "보류",
  tracking_reason: "예산 편성 결과를 확인한 뒤 재검토",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-09-01T01:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [orderPlanLink(9101, "도시계획 정보체계 유지관리", "다온군청", "DEMO-OP-010")],
};

/**
 * T1 후속(F3 spec §6.3): 대표 링크가 사전규격이고 마감이 **미래**인 건. 기존 표본은
 * 대표 링크가 공고면 늘 지난 마감(501)이거나 값 자체가 없어서(3001) `describeDeadline`의
 * D-n(미래) 가지가 FIXTURES 안에서 재지 않았다. 발주계획 링크를 앞에 두지 않아야
 * "첫 확정 링크"가 사전규격이 된다 — 링크를 하나만 둔다. 기관·사업명은 새로 짓지 않고
 * `go-no-go-fixtures.ts`의 `BUSINESSES` 표본 중 이 FIXTURES 배열에 아직 없는 쌍을 쓴다.
 */
export const FUTURE_NOTICE_DEADLINE_DAYS = 5;
export const FUTURE_NOTICE_DEADLINE = new Date(Date.now() + FUTURE_NOTICE_DEADLINE_DAYS * 86_400_000).toISOString();

const futureDeadlineNotice: Fixture = {
  id: 911,
  section: "보류",
  pending_candidate_link_count: 0,
  open_blocking_item_count: 0,
  action_reasons: [],
  hold_review_due_at: "2026-10-15T01:00:00Z",
  tracking_status: "보류",
  tracking_reason: "예산 확정 시점까지 대기",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-10-01T01:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "pre_spec",
  links: [
    noticeLink(9112, "pre_spec", "교통정보 수집·제공 플랫폼 고도화", "한결교통공사", "DEMO-PS-011", {
      budget: 780_000_000,
      deadline_at: FUTURE_NOTICE_DEADLINE,
    }),
  ],
};

export const FIXTURES: Fixture[] = [
  candidatePending,
  recheckSignal,
  unselected,
  blockingItem,
  searchUnconfirmed,
  held,
  ended,
  undecided,
  mergeConfirmation,
  holdOverdue,
  futureDeadlineNotice,
];

/** 화면이 보류 기한 D±n을 계산하는 기준 시각. 한국 시간 2026-09-17 12:00이다. */
export const FIXED_NOW = new Date("2026-09-17T03:00:00Z");

/** blocking 확인 항목을 가진 공고. 답변이 없어 예외로 남는다. */
export const exceptionNotice = {
  id: 61,
  notice_key: "pre-spec:61",
  run_id: "20260817-20260823--20260824T090927.138116Z",
  title: "환경측정 데이터 품질관리 용역",
  agency: "누리환경공단",
  published_at: "2026-08-20T00:00:00Z",
  deadline_at: "2026-08-30T00:00:00Z",
  estimated_price: null,
  sample_role: null,
  sample_stratum: null,
  collection_bucket: null,
  grade: "우선 검토",
  readiness: null,
  focus: null,
  attachment_count: 0,
  attachment_status: "none",
  bid_no: null,
  bid_ord: null,
  source_type: "pre_spec",
  budget: null,
  method: null,
  url: null,
  timezone: "Asia/Seoul",
  procurement_class: null,
  region_limit: null,
  lifecycle: {},
  qualification_flags: {},
  focus_matches: [],
  performance_matches: [],
  performance_top_score: null,
  candidate_sources: [],
  judgment: {
    id: 9001,
    schema_version: "1",
    grade: "우선 검토",
    readiness: null,
    primary_focus: null,
    exclusion_category: null,
    summary: null,
    next_action: null,
    perspectives: [],
    counterarguments: [],
    verification_items: [
      { id: 1, item: "SW사업자 신고 여부", why: "참여 자격을 확인하지 못했습니다.", blocking: true, status: "unknown" },
      { id: 2, item: "참고용 유사 실적", why: "판정에 영향을 주지 않습니다.", blocking: false, status: "unknown" },
    ],
    matched_performances: [],
  },
  attachments: [],
  reviews: [],
};

export interface Trace {
  listQueries: URLSearchParams[];
  detailGets: number[];
  decisionGets: number[];
  deepReviewGets: number[];
  patches: Array<{ id: number; body: Record<string, unknown>; headers: Record<string, string> }>;
  linkDecisions: Array<{ linkId: number; body: Record<string, unknown>; headers: Record<string, string> }>;
  reviewPuts: Array<{ noticePk: number; body: Record<string, unknown> }>;
  acks: Array<{ id: number; body: Record<string, unknown>; headers: Record<string, string> }>;
  searches: Array<{ id: number; body: Record<string, unknown>; headers: Record<string, string> }>;
}

export interface MockOptions {
  listStatus?: number;
  trackingStatus?: number;
  linkDecisionStatus?: number;
  /** 후보 수락을 409 `candidate_merge_state_conflict`(양쪽 사람 상태)로 거절한다. */
  linkDecisionMergeConflict?: boolean;
  /** 확인 완료 직전에 신호 근거가 다른 연결로 바뀐 상태를 만든다(409 `recheck_signal_changed`). */
  recheckChanged?: boolean;
  /** 찾아보기 결과. 기본은 후보 2건이다. */
  searchScenario?: "candidates" | "empty" | "source_missing";
  decisionsStatus?: number;
  /** 추적 결정 기록을 비워 "기록 없음"을 만든다. */
  emptyDecisions?: boolean;
  /** 긴 한글 제목 상태를 만든다. 캡처·회귀 확인용이다. */
  longTitle?: boolean;
}

export async function mockOpportunities(page: Page, options: MockOptions = {}): Promise<Trace> {
  const trace: Trace = {
    listQueries: [], detailGets: [], decisionGets: [], deepReviewGets: [], patches: [], linkDecisions: [], reviewPuts: [], acks: [], searches: [],
  };
  const details = new Map<number, Fixture>(FIXTURES.map((item) => [item.id, structuredClone(item)]));
  if (options.longTitle) {
    const long = "공공데이터 통합관리체계 및 기관 간 정보연계 플랫폼 고도화와 데이터 품질관리 기반 구축 사업";
    for (const link of details.get(101)!.links as Array<Record<string, unknown>>) link.title = long;
  }
  const decisions = new Map<number, Array<Record<string, unknown>>>([
    [606, [{
      decided_at: "2026-09-04T05:20:00Z",
      tracking_status: "보류",
      previous_tracking_status: "계속 추적",
      reason: "참여 조건을 추가 확인한 뒤 다시 검토",
      claimed_name: "시안 검토자",
      audit_event_id: "f1000000-0000-4000-8000-000000000001",
      cleared_recheck_signal: false,
    }]],
    // 서버 순서(최신 먼저). 두 번째 결정은 재검토 신호를 함께 해제했다.
    [202, [{
      decided_at: "2026-09-04T05:20:00.000100Z",
      tracking_status: "계속 추적",
      previous_tracking_status: "보류",
      reason: "후속 공고를 계속 확인",
      claimed_name: "검토 담당자",
      audit_event_id: "f1000000-0000-4000-8000-000000000203",
      cleared_recheck_signal: true,
    }, {
      decided_at: "2026-09-02T00:00:00Z",
      tracking_status: "보류",
      previous_tracking_status: null,
      reason: "예산·일정 추가 확인 필요",
      claimed_name: "검토 담당자",
      audit_event_id: "f1000000-0000-4000-8000-000000000202",
      cleared_recheck_signal: false,
    }]],
  ]);

  let recheckChangeApplied = false;

  // 재검토 신호 이벤트(감사 투영, §6.3). 일부러 오래된 순으로 둬 화면이 정렬하는지 본다.
  // 결정 저장으로 해제한 이벤트는 그 결정과 같은 밀리초 안의 300마이크로초 뒤다.
  // 확인 완료 이벤트는 한국 시간 offset으로 온다(UTC 09-06 00:00). offset을 무시하면 마지막 생성 이벤트보다 뒤로 간다.
  const recheckEvents = new Map<number, Array<Record<string, unknown>>>([
    [202, [
      { kind: "created", link_id: 2002, actor_kind: "system", claimed_name: null, created_at: "2026-09-03T00:00:00Z", note_present: false },
      { kind: "cleared_by_decision", link_id: 2002, actor_kind: "human", claimed_name: "검토 담당자", created_at: "2026-09-04T05:20:00.000400Z", note_present: false },
      { kind: "created", link_id: 2002, actor_kind: "system", claimed_name: null, created_at: "2026-09-05T00:00:00Z", note_present: false },
      { kind: "acknowledged", link_id: 2002, actor_kind: "human", claimed_name: "홍길동", created_at: "2026-09-06T09:00:00+09:00", note_present: true },
      { kind: "created", link_id: 2002, actor_kind: "system", claimed_name: null, created_at: "2026-09-06T01:30:00Z", note_present: false },
    ]],
  ]);

  // 사업기회별 심층 검토 보고서 목록. 404는 완료 1건·진행 중 1건(공고명 미확인
  // 상태 포함)을 갖고, 606은 명시적으로 빈 목록이다(§11.1 빈 상태 회귀).
  const deepReviews = new Map<number, Array<Record<string, unknown>>>([
    [404, [
      {
        deep_review_id: "d1111111-1111-4111-8111-111111111111",
        notice_id: 61,
        notice_title: "환경측정 데이터 품질관리 용역",
        status: "completed",
        quality_status: "measured",
        created_at: "2026-09-10T01:00:00Z",
        current_attempt_status: "completed",
        latest_final_opinion: { value: "추진", decided_at: "2026-09-11T02:00:00Z" },
      },
      {
        deep_review_id: "d2222222-2222-4222-8222-222222222222",
        notice_id: 61,
        notice_title: null,
        status: "running",
        quality_status: null,
        created_at: "2026-09-12T03:00:00Z",
        current_attempt_status: "running",
        latest_final_opinion: null,
      },
    ]],
    [606, []],
  ]);

  // 연결된 공고는 모두 응답한다. 확인 항목이 있는 것은 61 하나뿐이다.
  await page.route("**/api/notices/*", async (route) => {
    const url = new URL(route.request().url());
    const match = url.pathname.match(/^\/api\/notices\/(\d+)$/);
    if (!match || route.request().method() !== "GET" || match[1] === "61") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...exceptionNotice, id: Number(match[1]), judgment: null, reviews: [] }),
    });
  });

  await page.route("**/api/notices/61", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(exceptionNotice) });
  });

  await page.route("**/api/notices/61/review", async (route) => {
    if (route.request().method() !== "PUT") {
      await route.fallback();
      return;
    }
    const body = JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>;
    trace.reviewPuts.push({ noticePk: 61, body });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        run_id: body.run_id,
        notice_pk: 61,
        disposition: body.disposition ?? null,
        system_judgment_review: body.system_judgment_review ?? null,
        corrected_grade: body.corrected_grade ?? null,
        corrected_readiness: body.corrected_readiness ?? null,
        weakest_perspective: body.weakest_perspective ?? null,
        reason: body.reason ?? null,
        reviewer: body.reviewer ?? null,
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
        answers: (body.verification_answers as Array<{ item: string; answer: string }>).map((entry, index) => ({ id: index + 1, ...entry })),
      }),
    });
  });

  await page.route("**/api/opportunities**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === "/api/opportunities" && request.method() === "GET") {
      trace.listQueries.push(new URLSearchParams(url.search));
      if (options.listStatus) {
        await route.fulfill({
          status: options.listStatus,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "service_unavailable", message: "합성 오류", details: null }, request_id: null }),
        });
        return;
      }
      const stage = url.searchParams.get("first_registered_stage");
      const query = url.searchParams.get("q");
      // 서버 facet 규칙(opportunity_queries.list_opportunities): 구역 건수는 `section`만,
      // 사유 건수는 `reason`만 빼고 센다. 검색은 확정 연결의 제목·기관만 본다.
      const scoped = [...details.values()].filter((item) => (!stage || item.first_registered_stage === stage)
        && (!query || !searchKey(query) || (item.links as Array<Record<string, unknown>>).some((link) => (
          (link.link_type === "official" && link.status === "확정") || link.status === "사람 확인 완료"
        ) && searchMatches(query, String(link.title ?? ""), String(link.agency ?? "")))));
      const requested = url.searchParams.get("section");
      const reason = url.searchParams.get("reason");
      const reasonsOf = (item: Fixture) => (item.action_reasons as string[] | undefined) ?? [];
      const section_counts: Record<string, number> = { "조치 필요": 0, "추적 중": 0, "보류": 0, "추적 종료": 0, "신규 입찰공고": 0, "미결정": 0 };
      const action_reason_counts: Record<string, number> = { new_link: 0, candidate_pending: 0, merge_confirmation: 0, blocking_item: 0, hold_overdue: 0 };
      for (const item of scoped) {
        const key = (item.section as string | null) ?? "미결정";
        if (!reason || reasonsOf(item).includes(reason)) section_counts[key] += 1;
        if (!requested || key === requested) for (const code of reasonsOf(item)) action_reason_counts[code] += 1;
      }
      const matched = scoped.filter((item) => (!requested || item.section === requested) && (!reason || reasonsOf(item).includes(reason)));
      const limit = Number(url.searchParams.get("limit") ?? 100);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: matched.slice(offset, offset + limit),
          section_counts,
          action_reason_counts,
          total: matched.length,
          limit,
          offset,
        }),
      });
      return;
    }

    const linkMatch = url.pathname.match(/^\/api\/opportunities\/links\/(\d+)\/decision$/);
    if (linkMatch && request.method() === "PATCH") {
      const linkId = Number(linkMatch[1]);
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.linkDecisions.push({ linkId, body, headers: request.headers() });
      if (options.linkDecisionMergeConflict && body.decision === "accepted") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "candidate_merge_state_conflict",
              message: "합성 병합 충돌",
              details: {
                opportunities: [
                  { id: 909, tracking_status: "계속 추적", tracking_selected_by: "검토 담당자", tracking_selected_at: "2026-09-05T01:00:00Z", recheck_signal: false },
                  { id: 912, tracking_status: "보류", tracking_selected_by: "다른 담당자", tracking_selected_at: "2026-09-08T02:30:00Z", recheck_signal: true },
                ],
              },
            },
            request_id: null,
          }),
        });
        return;
      }
      if (options.linkDecisionStatus) {
        await route.fulfill({
          status: options.linkDecisionStatus,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "candidate_state_conflict", message: "합성 충돌", details: null }, request_id: null }),
        });
        return;
      }
      const owner = [...details.values()].find((item) => (item.links as Array<{ id: number }>).some((link) => link.id === linkId));
      const link = (owner?.links as Array<Record<string, unknown>> | undefined)?.find((entry) => entry.id === linkId);
      if (link && owner) {
        link.status = "사람 확인 완료";
        link.human_decision = body.decision;
        link.reviewer_name = "홍길동";
        link.reviewed_at = "2026-09-07T06:00:00Z";
        link.review_reason = body.reason;
        owner.pending_candidate_link_count = 0;
        owner.section = "추적 중";
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(link ?? {}) });
      return;
    }

    const match = url.pathname.match(/^\/api\/opportunities\/(\d+)(?:\/(tracking-status|tracking-decisions|deep-reviews|recheck-acknowledgements|searches))?$/);
    if (!match) {
      await route.fallback();
      return;
    }
    const id = Number(match[1]);
    const detail = details.get(id);

    if (match[2] === "tracking-decisions" && request.method() === "GET") {
      trace.decisionGets.push(id);
      if (options.decisionsStatus) {
        await route.fulfill({
          status: options.decisionsStatus,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "opportunity_not_found", message: "합성 오류", details: null }, request_id: null }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          opportunity_id: id,
          items: options.emptyDecisions ? [] : decisions.get(id) ?? [],
          recheck_events: options.emptyDecisions ? [] : recheckEvents.get(id) ?? [],
        }),
      });
      return;
    }

    if (match[2] === "deep-reviews" && request.method() === "GET") {
      trace.deepReviewGets.push(id);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ opportunity_id: id, items: deepReviews.get(id) ?? [] }),
      });
      return;
    }

    if (!match[2] && request.method() === "GET") {
      trace.detailGets.push(id);
      await route.fulfill({
        status: detail ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(detail ?? { error: { code: "opportunity_not_found", message: "사업기회를 찾을 수 없습니다", details: null }, request_id: null }),
      });
      return;
    }

    if (match[2] === "recheck-acknowledgements" && request.method() === "POST" && detail) {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.acks.push({ id, body, headers: request.headers() });
      if (options.recheckChanged && !recheckChangeApplied) {
        // 사람이 보던 사이 정정공고가 새 근거로 붙었다.
        recheckChangeApplied = true;
        (detail.links as Array<Record<string, unknown>>).push(noticeLink(2003, "bid_notice", "시설관리 업무시스템 구축 정정공고", "도담도시공사", "DEMO-BN-002-1"));
        detail.recheck_signal_link_id = 2003;
        detail.recheck_signal_at = "2026-09-07T02:00:00Z";
      }
      if (!detail.recheck_signal) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "recheck_signal_absent", message: "합성 확인 오류", details: null }, request_id: null }),
        });
        return;
      }
      if (body.expected_link_id !== detail.recheck_signal_link_id) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "recheck_signal_changed", message: "합성 확인 오류", details: { current_link_id: detail.recheck_signal_link_id } },
            request_id: null,
          }),
        });
        return;
      }
      const events = recheckEvents.get(id) ?? [];
      events.push({
        kind: "acknowledged", link_id: detail.recheck_signal_link_id, actor_kind: "human", claimed_name: "홍길동",
        created_at: "2026-09-07T06:00:00Z", note_present: typeof body.note === "string" && body.note.trim().length > 0,
      });
      recheckEvents.set(id, events);
      detail.recheck_signal = false;
      detail.recheck_signal_at = null;
      detail.recheck_signal_link_id = null;
      detail.action_reasons = (detail.action_reasons as string[]).filter((code) => code !== "new_link");
      if ((detail.action_reasons as string[]).length === 0 && detail.section === "조치 필요") detail.section = "추적 중";
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detail) });
      return;
    }

    if (match[2] === "searches" && request.method() === "POST" && detail) {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.searches.push({ id, body, headers: request.headers() });
      const target = body.target === "bid_notice" ? "bid_notice" : "pre_spec";
      if (options.searchScenario === "source_missing") {
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "search_source_missing", message: "합성 찾아보기 오류", details: { target } }, request_id: null }),
        });
        return;
      }
      const searchedAt = "2026-09-17T02:00:00Z";
      const attempted = ["full", "breaking_split", "normalized", "longest_fragment"];
      if (options.searchScenario === "empty") {
        (detail.links as Array<Record<string, unknown>>).push({
          ...baseLink, id: 9901, stage: "notice", link_type: "candidate", status: "검색 미확인",
          attempted_strategies: attempted, last_searched_at: searchedAt,
        });
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ searched_at: searchedAt, target, attempted_strategies: attempted, candidates: [], search_unconfirmed: true }),
        });
        return;
      }
      const candidates = [
        noticeLink(9801, target, "학사행정시스템 통합 유지관리 사업", "온빛대학교", "DEMO-FOUND-1", {
          link_type: "candidate", status: "후보 확인 대기", search_strategy: "full", attempted_strategies: attempted,
          agency_match: true, last_searched_at: searchedAt,
        }),
        noticeLink(9802, target, "학사행정 통합 유지관리", "온빛교육재단", "DEMO-FOUND-2", {
          link_type: "candidate", status: "후보 확인 대기", search_strategy: "longest_fragment", attempted_strategies: attempted,
          agency_match: false, last_searched_at: searchedAt,
        }),
      ];
      (detail.links as Array<Record<string, unknown>>).push(...candidates);
      detail.pending_candidate_link_count = (detail.pending_candidate_link_count as number) + candidates.length;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ searched_at: searchedAt, target, attempted_strategies: attempted, candidates, search_unconfirmed: false }),
      });
      return;
    }

    if (match[2] === "tracking-status" && request.method() === "PATCH") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.patches.push({ id, body, headers: request.headers() });
      if (options.trackingStatus) {
        await route.fulfill({
          status: options.trackingStatus,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "tracking_reason_required", message: "합성 저장 오류", details: null }, request_id: null }),
        });
        return;
      }
      const current = details.get(id)!;
      const saved = {
        ...current,
        tracking_status: body.tracking_status,
        tracking_reason: body.reason,
        tracking_selected_by: "홍길동",
        tracking_selected_at: "2026-09-07T06:00:00Z",
        recheck_signal: false,
        section: body.tracking_status === "보류" ? "보류" : body.tracking_status === "종료" ? "추적 종료" : "추적 중",
      };
      details.set(id, saved as Fixture);
      const history = decisions.get(id) ?? [];
      history.unshift({
        decided_at: "2026-09-07T06:00:00Z",
        tracking_status: body.tracking_status,
        previous_tracking_status: current.tracking_status,
        reason: body.reason,
        claimed_name: "홍길동",
        audit_event_id: "f2000000-0000-4000-8000-000000000001",
        cleared_recheck_signal: Boolean(current.recheck_signal),
      });
      decisions.set(id, history);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(saved) });
      return;
    }

    await route.fallback();
  });

  return trace;
}
