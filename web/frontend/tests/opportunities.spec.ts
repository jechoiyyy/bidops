import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";

type OpportunityFixture = Record<string, unknown> & { id: number };

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
};

const unselected: OpportunityFixture = {
  id: 101,
  tracking_status: "미선택",
  tracking_reason: null,
  tracking_selected_by: null,
  tracking_selected_at: null,
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [{
    ...baseLink,
    id: 1001,
    stage: "order_plan",
    link_type: "official",
    status: "확정",
    record_type: "order_plan",
    record_id: 51,
    notice_id: null,
    order_plan_id: 51,
    source_type: null,
    title: "미선택 공공 데이터 플랫폼 구축",
    agency: "테스트 기관",
    external_id: "PLAN-101",
    record_external_id: "PLAN-101",
  }],
};

const endedWithRecheck: OpportunityFixture = {
  id: 202,
  tracking_status: "종료",
  tracking_reason: "현재 범위와 맞지 않아 능동 추적을 종료함",
  tracking_selected_by: "기존 담당자",
  tracking_selected_at: "2026-08-20T09:00:00Z",
  recheck_signal: true,
  recheck_signal_at: "2026-08-31T01:30:00Z",
  recheck_signal_link_id: 2002,
  first_registered_stage: "pre_spec",
  links: [{
    ...baseLink,
    id: 2001,
    stage: "notice",
    link_type: "official",
    status: "확정",
    record_type: "pre_spec",
    record_id: 61,
    notice_id: 61,
    order_plan_id: null,
    source_type: "pre_spec",
    title: "종료된 지능형 업무 시스템 사전규격",
    agency: "테스트 기관",
    external_id: "PRE-202",
    record_external_id: "PRE-202",
  }, {
    ...baseLink,
    id: 2002,
    stage: "notice",
    link_type: "official",
    status: "확정",
    record_type: "bid_notice",
    record_id: 62,
    notice_id: 62,
    order_plan_id: null,
    source_type: "bid_notice",
    title: "종료된 지능형 업무 시스템 본공고",
    agency: "테스트 기관",
    external_id: "BID-202",
    record_external_id: "BID-202",
  }],
};

const candidateRelation: OpportunityFixture = {
  id: 303,
  tracking_status: "계속 추적",
  tracking_reason: "후보 관계를 사람이 확인할 때까지 계속 추적",
  tracking_selected_by: "검토 담당자",
  tracking_selected_at: "2026-08-29T02:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [{
    ...baseLink,
    id: 3001,
    stage: "notice",
    link_type: "candidate",
    status: "후보 확인 대기",
    search_strategy: "normalized",
    attempted_strategies: ["full", "normalized"],
    agency_match: true,
    last_searched_at: "2026-08-30T03:00:00Z",
    record_type: "pre_spec",
    record_id: 71,
    notice_id: 71,
    order_plan_id: null,
    source_type: "pre_spec",
    title: "후보 관계 사전규격",
    agency: "후보 기관",
    external_id: "PRE-303",
    record_external_id: "PRE-303",
  }],
};

// 구역 네 개가 모두 내용을 갖도록 `추적 중`과 `보류`를 더한다. 둘 다 예외 작업도
// 재검토 신호도 없어야 `조치 필요`로 끌려가지 않는다.
const tracked: OpportunityFixture = {
  id: 404,
  tracking_status: "계속 추적",
  tracking_reason: "사전규격 공개를 계속 확인",
  tracking_selected_by: "추적 담당자",
  tracking_selected_at: "2026-08-28T01:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "order_plan",
  links: [{
    ...baseLink,
    id: 4001,
    stage: "order_plan",
    link_type: "official",
    status: "확정",
    record_type: "order_plan",
    record_id: 81,
    notice_id: null,
    order_plan_id: 81,
    source_type: null,
    title: "추적 중 국가물류 통합정보 고도화",
    agency: "국토교통부",
    external_id: "PLAN-404",
    record_external_id: "PLAN-404",
  }],
};

const held: OpportunityFixture = {
  id: 505,
  tracking_status: "보류",
  tracking_reason: "예산 확정 전까지 결정을 미룸",
  tracking_selected_by: "보류 담당자",
  tracking_selected_at: "2026-08-27T01:00:00Z",
  recheck_signal: false,
  recheck_signal_at: null,
  recheck_signal_link_id: null,
  first_registered_stage: "pre_spec",
  links: [{
    ...baseLink,
    id: 5001,
    stage: "notice",
    link_type: "official",
    status: "확정",
    record_type: "pre_spec",
    record_id: 91,
    notice_id: 91,
    order_plan_id: null,
    source_type: "pre_spec",
    title: "보류된 지방재정 표준화 사전규격",
    agency: "행정안전부",
    external_id: "PRE-505",
    record_external_id: "PRE-505",
  }],
};

interface OpportunityTrace {
  listQueries: URLSearchParams[];
  detailGets: number[];
  patches: Array<{ id: number; body: Record<string, unknown>; headers: Record<string, string> }>;
  linkDecisions: Array<{ linkId: number; body: Record<string, unknown>; headers: Record<string, string> }>;
  reviewPuts: Array<{ noticePk: number; body: Record<string, unknown> }>;
}

/** 검증 실패 예외를 만드는 공고. blocking 확인 항목에 담당자 답이 없다. */
const exceptionNotice = {
  id: 61,
  notice_key: "pre-spec:61",
  run_id: "20260817-20260823--20260824T090927.138116Z",
  title: "종료된 지능형 업무 시스템 사전규격",
  agency: "테스트 기관",
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

async function mockOpportunities(page: Page): Promise<OpportunityTrace> {
  const trace: OpportunityTrace = { listQueries: [], detailGets: [], patches: [], linkDecisions: [], reviewPuts: [] };
  const details = new Map<number, OpportunityFixture>([
    [unselected.id, structuredClone(unselected)],
    [endedWithRecheck.id, structuredClone(endedWithRecheck)],
    [candidateRelation.id, structuredClone(candidateRelation)],
    [tracked.id, structuredClone(tracked)],
    [held.id, structuredClone(held)],
  ]);

  await page.route("**/api/notices/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/notices/61" && route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(exceptionNotice) });
      return;
    }
    await route.fallback();
  });

  await page.route("**/api/notices/*/review", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/notices/61/review" && route.request().method() === "PUT") {
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
      return;
    }
    await route.fallback();
  });

  await page.route("**/api/opportunities**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const match = url.pathname.match(/^\/api\/opportunities\/(\d+)$/);

    if (url.pathname === "/api/opportunities" && request.method() === "GET") {
      trace.listQueries.push(new URLSearchParams(url.search));
      // 서버 필터를 흉내낸다. 구역 넷 중 셋은 저장된 추적 상태로 서버가 거르고
      // `조치 필요`만 화면이 나눈다.
      const status = url.searchParams.get("tracking_status");
      const items = [...details.values()].filter((item) => !status || item.tracking_status === status);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: status ? items.length : 53, limit: Number(url.searchParams.get("limit") ?? 100), offset: Number(url.searchParams.get("offset") ?? 0) }),
      });
      return;
    }

    const linkMatch = url.pathname.match(/^\/api\/opportunities\/links\/(\d+)\/decision$/);
    if (linkMatch && request.method() === "PATCH") {
      const linkId = Number(linkMatch[1]);
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.linkDecisions.push({ linkId, body, headers: request.headers() });
      const owner = [...details.values()].find((item) => (item.links as Array<{ id: number }>).some((link) => link.id === linkId));
      const link = (owner?.links as Array<Record<string, unknown>> | undefined)?.find((entry) => entry.id === linkId);
      if (link) {
        link.status = "사람 확인 완료";
        link.human_decision = body.decision;
        link.reviewer_name = "홍길동";
        link.reviewed_at = "2026-09-01T00:00:00Z";
        link.review_reason = body.reason;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(link ?? {}) });
      return;
    }

    if (match && request.method() === "GET") {
      const id = Number(match[1]);
      trace.detailGets.push(id);
      const detail = details.get(id);
      await route.fulfill({
        status: detail ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(detail ?? { error: { code: "opportunity_not_found", message: "사업기회를 찾을 수 없습니다", details: null }, request_id: null }),
      });
      return;
    }

    const trackingMatch = url.pathname.match(/^\/api\/opportunities\/(\d+)\/tracking-status$/);
    if (trackingMatch && request.method() === "PATCH") {
      const id = Number(trackingMatch[1]);
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, unknown>;
      trace.patches.push({ id, body, headers: request.headers() });
      const current = details.get(id)!;
      const saved = {
        ...current,
        tracking_status: body.tracking_status,
        tracking_reason: body.reason,
        tracking_selected_by: "홍길동",
        tracking_selected_at: "2026-08-31T04:00:00Z",
      };
      details.set(id, saved);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(saved) });
      return;
    }

    await route.fallback();
  });

  return trace;
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("구역·정렬·페이지 URL이 목록 선택과 뒤로 가기에서 복원된다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  // `보류`는 저장된 추적 상태 하나에 대응하므로 서버 필터로 나간다.
  const query = "section=%EB%B3%B4%EB%A5%98&first_registered_stage=pre_spec&sort=tracking_status";
  await page.goto(`/opportunities?${query}`);

  await expect.poll(() => trace.listQueries.some((params) => params.get("tracking_status") === "보류")).toBe(true);

  const row = page.locator(".review-dense-list-row", { hasText: "보류된 지방재정 표준화 사전규격" });
  await expect(row).toHaveCount(1);
  await row.click();
  await expect(page.locator(".opportunity-detail-title")).toHaveText("보류된 지방재정 표준화 사전규격");

  await page.getByRole("link", { name: "이 사업기회만 따로 열기 →" }).click();
  await expect(page.getByRole("heading", { name: "사업 추적 상세 #505" })).toBeVisible();
  const detailUrl = new URL(page.url());
  expect(detailUrl.pathname).toBe("/opportunities/505");
  expect(detailUrl.searchParams.get("section")).toBe("보류");
  expect(detailUrl.searchParams.get("first_registered_stage")).toBe("pre_spec");
  expect(detailUrl.searchParams.get("sort")).toBe("tracking_status");

  await page.reload();
  await expect(page.getByRole("heading", { name: "사업 추적 상세 #505" })).toBeVisible();

  await page.goBack();
  await expect(page.getByRole("heading", { level: 2, name: "사업 추적" })).toBeVisible();
  const listUrl = new URL(page.url());
  expect(listUrl.pathname).toBe("/opportunities");
  expect(listUrl.searchParams.get("section")).toBe("보류");
  expect(listUrl.searchParams.get("sort")).toBe("tracking_status");
});

// ADR-0046 결정 2 · PLAN 단계 E 완료 게이트: 한 사업기회는 한 행으로만 나타난다.
// 구역 판정이 한 곳에서만 이뤄지므로 구역 넷을 모두 돌아도 같은 id가 두 번
// 나오지 않는다.
test("한 사업기회는 구역 넷을 통틀어 한 행으로만 나타난다", async ({ page }) => {
  await mockOpportunities(page);
  const seen = new Map<string, string[]>();

  for (const section of ["조치 필요", "추적 중", "보류", "추적 종료"]) {
    await page.goto(`/opportunities?section=${encodeURIComponent(section)}`);
    await expect(page.locator(".opportunity-list-title")).toContainText(section);
    const ids = await page.locator(".review-dense-list-row .opportunity-card-id").allInnerTexts();
    seen.set(section, ids);
  }

  const all = [...seen.values()].flat();
  expect(new Set(all).size).toBe(all.length);
  // 미선택·재검토 신호·후보 확인 대기가 모두 조치 필요로 모인다. 저장된 상태가
  // `종료`여도 새 신호가 붙었으면 구역 밖으로 사라지지 않는다.
  expect(seen.get("조치 필요")).toEqual(expect.arrayContaining(["#101", "#202", "#303"]));
  expect(seen.get("추적 중")).toEqual(["#404"]);
  expect(seen.get("보류")).toEqual(["#505"]);
  expect(seen.get("추적 종료")).toEqual([]);
});

test("행은 다음 행동 하나와 저장된 추적 상태를 함께 보여준다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities?section=%EC%A1%B0%EC%B9%98%20%ED%95%84%EC%9A%94");

  const unselectedRow = page.locator(".review-dense-list-row", { hasText: "미선택 공공 데이터 플랫폼 구축" });
  await expect(unselectedRow).toContainText("추적 결정");
  await expect(unselectedRow).toContainText("미선택");

  const endedRow = page.locator(".review-dense-list-row", { hasText: "종료된 지능형 업무 시스템 사전규격" });
  await expect(endedRow).toContainText("재검토");
  await expect(endedRow).toContainText("종료");
  await expect(endedRow).toContainText("재검토 필요");

  const candidateRow = page.locator(".review-dense-list-row", { hasText: "후보 관계 사전규격" });
  await expect(candidateRow).toContainText("연결 확인");
  await expect(candidateRow).toContainText("계속 추적");
});

test("미선택 상세는 추적 이력과 시스템 신호를 다른 탭으로 나눠 보존한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101?sort=created_at");

  await page.getByRole("tab", { name: "추적 이력", exact: true }).click();
  const history = page.locator("#opportunity-panel-history");
  await expect(history).toContainText("미선택");
  await expect(history).toContainText("기록된 이유 없음");
  // 서버가 최근 한 건만 여는 사실을 감추지 않는다.
  await expect(history.locator(".opportunity-contract-gap")).toContainText("가장 최근 한 건");

  await page.getByRole("tab", { name: "시스템 신호", exact: true }).click();
  await expect(page.locator(".opportunity-signal")).toContainText("현재 재검토 신호가 없습니다.");
  expect(trace.detailGets).toEqual([101]);
  expect(trace.listQueries).toHaveLength(0);
});

test("종료 상태와 재검토 필요 신호를 서로 다른 자리에 보존한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/202");

  await page.getByRole("tab", { name: "시스템 신호", exact: true }).click();
  const signal = page.locator(".opportunity-signal");
  await expect(signal).toContainText("재검토 필요");
  await expect(signal).toContainText("BID-202");
  // 시스템 신호는 결정을 만들지 않는다.
  await expect(signal).toContainText("집계나 추적 결정을 자동으로 만들지 않습니다");

  await page.getByRole("tab", { name: "추적 이력", exact: true }).click();
  const history = page.locator("#opportunity-panel-history");
  await expect(history).toContainText("종료");
  await expect(history).toContainText("현재 범위와 맞지 않아 능동 추적을 종료함");
  await expect(history).not.toContainText("재검토 필요");
});

test("candidate relation fixture를 확정 관계로 바꾸지 않고 표시한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/303");

  const relation = page.locator(".opportunity-link");
  await expect(relation).toContainText("후보");
  await expect(relation).toContainText("후보 확인 대기");
  await expect(relation).toContainText("공식 번호가 아닌 후보 관계다. 사람 확인이 필요하다.");
  await expect(relation).not.toContainText("공식 통합번호로 확정된 관계다.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

// PLAN 단계 E 작업 3-2: 예외 작업(연결 불확실) 처리 경로가 사업 추적 상세에 있다.
// 서버는 이 계약을 갖고 있었지만 화면에 진입점이 없어 사람이 해소할 길이 없었다.
test("연결 불확실 예외를 사업 추적 상세에서 사람이 판정한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/303");
  await page.getByRole("tab", { name: "시스템 신호", exact: true }).click();

  const exception = page.locator(".opportunity-exception", { hasText: "연결 불확실" });
  await expect(exception).toContainText("후보 관계 사전규격");
  await expect(exception).toContainText("처리 경로");
  await expect(exception).toContainText("후보 연결 판정");

  const save = exception.getByRole("button", { name: "후보 연결 판정 저장" });
  await expect(save).toBeDisabled();
  await expect(page.locator("#candidate-decision-disabled-3001")).toContainText("이유를 입력하십시오");

  await exception.getByLabel("판정 이유").fill("공식 번호는 다르지만 같은 사업임을 원문에서 확인했습니다.");
  await exception.getByLabel("담당자 이름").fill("홍길동");
  await expect(save).toBeEnabled();
  await save.click();

  await expect(page.getByText("후보 연결을 수용으로 기록했습니다.")).toBeVisible();
  expect(trace.linkDecisions).toHaveLength(1);
  expect(trace.linkDecisions[0].linkId).toBe(3001);
  expect(trace.linkDecisions[0].body).toEqual({
    decision: "accepted",
    reason: "공식 번호는 다르지만 같은 사업임을 원문에서 확인했습니다.",
  });
  expect(trace.linkDecisions[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.linkDecisions[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  // 연결 판정은 추적 상태를 바꾸지 않는다.
  expect(trace.patches).toHaveLength(0);
});

// PLAN 단계 E 작업 3-2: 검증 실패의 사람 수정도 사업 추적에서 이뤄진다
// (ADR-0046 결정 3). 회차는 그 공고가 속한 회차를 그대로 쓰므로 누적 화면이
// 회차를 다시 묻지 않는다.
test("검증 실패 예외를 사업 추적 상세에서 담당자 답변으로 해소한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/202");
  await page.getByRole("tab", { name: "시스템 신호", exact: true }).click();

  const exception = page.locator(".opportunity-exception", { hasText: "검증 실패" });
  await expect(exception).toContainText("SW사업자 신고 여부");
  // blocking이 아닌 확인 항목은 예외로 올리지 않는다.
  await expect(page.locator(".opportunity-exception")).not.toContainText("참고용 유사 실적");

  const form = page.locator(".opportunity-exception-notice");
  await form.getByLabel("SW사업자 신고 여부").fill("공고 원문 3쪽에서 SW사업자 신고 대상임을 확인했습니다.");
  await form.getByLabel("수정 이유").fill("근거 위치를 확인해 blocking 항목을 해소함");
  await form.getByLabel("담당자 이름").fill("홍길동");
  await form.getByRole("button", { name: "확인 항목 답변 저장" }).click();

  await expect(page.getByText("확인 항목 답변을 저장했습니다.")).toBeVisible();
  expect(trace.reviewPuts).toHaveLength(1);
  const body = trace.reviewPuts[0].body;
  expect(body.run_id).toBe("20260817-20260823--20260824T090927.138116Z");
  expect(body.reviewer).toBe("홍길동");
  expect(body.verification_answers).toEqual([
    { item: "SW사업자 신고 여부", answer: "공고 원문 3쪽에서 SW사업자 신고 대상임을 확인했습니다." },
  ]);
  // 예외 수정이 등급·준비 상태·최종 처리를 덮지 않는다.
  expect(body.corrected_grade).toBeNull();
  expect(body.corrected_readiness).toBeNull();
  expect(body.disposition).toBeNull();
  // 추적 상태도 바뀌지 않는다.
  expect(trace.patches).toHaveLength(0);
});

test("근거 없음 예외는 화면이 해소할 수 없다는 사실을 그대로 말한다", async ({ page }) => {
  await mockOpportunities(page);
  await page.goto("/opportunities/303");
  await page.getByRole("tab", { name: "시스템 신호", exact: true }).click();

  // 후보 확인 대기는 화면이 처리하고, 검색 미확인은 처리하지 못한다. 둘을 같은
  // 문구로 덮지 않는다.
  await expect(page.locator(".opportunity-exception", { hasText: "연결 불확실" })).toHaveCount(1);
  await expect(page.locator(".opportunity-exception", { hasText: "근거 없음" })).toHaveCount(0);
});

test("추적 상태 변경은 접힌 채로 열리고 저장 계약을 유지한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101?sort=created_at");

  const secondary = page.locator('[data-review-primitive="secondary-input"]');
  await expect(secondary).toHaveAttribute("data-open", "false");
  // 접힌 상태에서도 현재 값과 "무엇을 바꾸지 않는지"가 보인다.
  await expect(secondary).toContainText("미선택");
  await expect(secondary).toContainText("최종 Go/No-Go를 바꾸지 않습니다");

  await page.getByRole("button", { name: "추적 상태 변경 열기" }).click();
  await expect(secondary).toHaveAttribute("data-open", "true");

  // `미선택`은 고를 수 없다. 결정을 되돌려 아무도 안 고른 상태로 만들지 않는다.
  const options = await page.locator(".opportunity-tracking-form select option").allInnerTexts();
  expect(options.some((label) => label.includes("미선택"))).toBe(false);

  await page.locator(".opportunity-tracking-form select").selectOption("계속 추적");
  await page.getByLabel("이유").fill("새 사전규격 공개 여부를 계속 확인");
  await page.getByLabel("담당자 이름").fill("홍길동");
  await expect(page.getByText("저장되지 않은 추적 상태 변경이 있습니다.")).toBeVisible();
  expect(await page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(true);

  // 이탈 확인은 브라우저 confirm이 아니라 화면의 확인 다이얼로그다. 취소하면 초안이 남는다.
  await page.locator('nav[aria-label="현재 위치"]').getByRole("link", { name: "사업 추적", exact: true }).click();
  const leaveDialog = page.getByRole("alertdialog");
  await expect(leaveDialog).toBeVisible();
  await expect(leaveDialog).toContainText("사업 추적 상세를 떠납니다");
  await leaveDialog.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page).toHaveURL(/\/opportunities\/101\?sort=created_at$/);
  await expect(page.getByLabel("이유")).toHaveValue("새 사전규격 공개 여부를 계속 확인");

  await page.getByRole("button", { name: "추적 상태 저장" }).click();
  await expect(page.getByText("추적 상태를 저장했습니다.")).toBeVisible();
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].body).toEqual({ tracking_status: "계속 추적", reason: "새 사전규격 공개 여부를 계속 확인" });
  expect(trace.patches[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
  expect(trace.patches[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
});

// 목록 조작(구역·정렬·페이지·행 선택)은 열려 있던 상세를 닫아 저장하지 않은 입력을
// 잃는다. 확인은 브라우저 confirm이 아니라 같은 화면 다이얼로그다.
test("목록을 바꾸기 전에 저장하지 않은 추적 상태 변경을 확인한다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities?section=%EC%A1%B0%EC%B9%98%20%ED%95%84%EC%9A%94");

  await page.getByRole("button", { name: "추적 상태 변경 열기" }).click();
  await page.getByLabel("이유").fill("목록 확인용 미저장 입력");

  await page.getByRole("radio", { name: "추적 중", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("목록을 바꿉니다");
  await dialog.getByRole("button", { name: "계속 편집", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByLabel("이유")).toHaveValue("목록 확인용 미저장 입력");

  await page.getByRole("radio", { name: "추적 중", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "저장하지 않고 목록 바꾸기", exact: true }).click();
  await expect(page).toHaveURL(/section=/);
  expect(trace.patches).toHaveLength(0);
});

// 추적 `종료`는 되돌릴 수 없는 결정이므로 확인 단계를 거쳐야 요청이 나간다.
// `계속 추적`·`보류`는 다시 고를 수 있으므로 확인 단계를 두지 않는다.
test("추적 종료는 확인 없이는 요청이 나가지 않고 취소하면 초안만 남는다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101?sort=created_at");

  await page.getByRole("button", { name: "추적 상태 변경 열기" }).click();
  await page.locator(".opportunity-tracking-form select").selectOption("종료");
  await page.getByLabel("이유").fill("현재 범위와 맞지 않아 능동 추적을 종료합니다.");
  await page.getByLabel("담당자 이름").fill("홍길동");

  await page.getByRole("button", { name: "추적 상태 저장" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("되돌릴 수 없습니다");
  await expect(dialog).toContainText("종료 · 추적 종료");
  await expect(dialog).toContainText("사업기회 #101");
  await expect(dialog).toContainText("현재 범위와 맞지 않아 능동 추적을 종료합니다.");
  expect(trace.patches).toHaveLength(0);

  await dialog.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.patches).toHaveLength(0);
  await expect(page.locator(".opportunity-tracking-form select")).toHaveValue("종료");
  await expect(page.getByLabel("이유")).toHaveValue("현재 범위와 맞지 않아 능동 추적을 종료합니다.");

  await page.getByRole("button", { name: "추적 상태 저장" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "종료 상태로 저장", exact: true }).click();
  await expect(page.getByText("추적 상태를 저장했습니다.")).toBeVisible();
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].body).toEqual({ tracking_status: "종료", reason: "현재 범위와 맞지 않아 능동 추적을 종료합니다." });
});

// `계속 추적`은 되돌릴 수 있는 결정이라 확인 단계 없이 그대로 저장된다.
test("계속 추적 저장은 확인 단계 없이 그대로 나간다", async ({ page }) => {
  const trace = await mockOpportunities(page);
  await page.goto("/opportunities/101?sort=created_at");

  await page.getByRole("button", { name: "추적 상태 변경 열기" }).click();
  await page.locator(".opportunity-tracking-form select").selectOption("계속 추적");
  await page.getByLabel("이유").fill("새 사전규격 공개 여부를 계속 확인");
  await page.getByLabel("담당자 이름").fill("홍길동");
  await page.getByRole("button", { name: "추적 상태 저장" }).click();

  await expect(page.getByText("추적 상태를 저장했습니다.")).toBeVisible();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  expect(trace.patches).toHaveLength(1);
});
