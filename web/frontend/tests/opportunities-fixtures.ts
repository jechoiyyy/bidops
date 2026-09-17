import type { Page } from "@playwright/test";

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
  record_external_id: null,
};

function orderPlanLink(id: number, title: string, agency: string, externalId: string) {
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
    orderPlanLink(1001, "공공데이터 통합관리체계 고도화", "해솔시청", "DEMO-OP-001"),
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
    noticeLink(2002, "bid_notice", "시설관리 업무시스템 구축", "도담도시공사", "DEMO-BN-002"),
  ],
};

/** 아직 아무도 추적을 고르지 않은 건. 이 mock server는 §7.2의 새 구역 규칙을
 * 다시 판정하지 않고 각 픽스처가 스스로 밝힌 `section`을 그대로 돌려준다.
 * opportunities.spec.ts의 구역별 건수(§7.2를 반영한 화면은 F1-F4에서 나온다)가
 * 이 값에 매여 있어 여기서는 바꾸지 않는다. */
const unselected: Fixture = {
  id: 303,
  section: "조치 필요",
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

export const FIXTURES: Fixture[] = [
  candidatePending,
  recheckSignal,
  unselected,
  blockingItem,
  searchUnconfirmed,
  held,
  ended,
  undecided,
];

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
}

export interface MockOptions {
  listStatus?: number;
  trackingStatus?: number;
  linkDecisionStatus?: number;
  decisionsStatus?: number;
  /** 추적 결정 기록을 비워 "기록 없음"을 만든다. */
  emptyDecisions?: boolean;
  /** 긴 한글 제목 상태를 만든다. 캡처·회귀 확인용이다. */
  longTitle?: boolean;
}

export async function mockOpportunities(page: Page, options: MockOptions = {}): Promise<Trace> {
  const trace: Trace = { listQueries: [], detailGets: [], decisionGets: [], deepReviewGets: [], patches: [], linkDecisions: [], reviewPuts: [] };
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
      const scoped = [...details.values()].filter((item) => !stage || item.first_registered_stage === stage);
      const section_counts: Record<string, number> = { "조치 필요": 0, "추적 중": 0, "보류": 0, "추적 종료": 0, "신규 입찰공고": 0, "미결정": 0 };
      const action_reason_counts: Record<string, number> = { new_link: 0, candidate_pending: 0, merge_confirmation: 0, blocking_item: 0, hold_overdue: 0 };
      for (const item of scoped) {
        section_counts[(item.section as string | null) ?? "미결정"] += 1;
        for (const code of (item.action_reasons as string[] | undefined) ?? []) action_reason_counts[code] += 1;
      }
      const requested = url.searchParams.get("section");
      const items = requested ? scoped.filter((item) => item.section === requested) : scoped;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items,
          section_counts,
          action_reason_counts,
          total: requested ? section_counts[requested] : scoped.length,
          limit: Number(url.searchParams.get("limit") ?? 100),
          offset: Number(url.searchParams.get("offset") ?? 0),
        }),
      });
      return;
    }

    const linkMatch = url.pathname.match(/^\/api\/opportunities\/links\/(\d+)\/decision$/);
    if (linkMatch && request.method() === "PATCH") {
      const linkId = Number(linkMatch[1]);
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.linkDecisions.push({ linkId, body, headers: request.headers() });
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

    const match = url.pathname.match(/^\/api\/opportunities\/(\d+)(?:\/(tracking-status|tracking-decisions|deep-reviews))?$/);
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
        body: JSON.stringify({ opportunity_id: id, items: options.emptyDecisions ? [] : decisions.get(id) ?? [], recheck_events: [] }),
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
