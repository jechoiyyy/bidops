import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockDocumentStructurePage } from "./api-mock";

const FIXED_TIME = new Date("2026-08-31T09:00:00+09:00");

const trackingException = {
  notice_pk: 991,
  pre_spec_no: "PRE-991",
  title: "추적 예외 데이터 플랫폼 사전규격",
  agency: "테스트 조달기관",
  published_at: "2026-08-30T00:00:00Z",
  deadline_at: "2026-09-02T00:00:00Z",
  budget: 510_000_000,
  sw_business_status: "N",
  business_division: "기술용역",
  origin: "추적",
  opportunity_id: 77,
  tracking_status: "계속 추적",
  kept_by_tracking: true,
  document: { attachments: 6, "완료": 2, "대기": 1, "진행": 0, "차단": 2, "실패": 1 },
  overview_review_status: "needs_human_review",
};

const newPreSpec = {
  notice_pk: 992,
  pre_spec_no: "PRE-992",
  title: "신규 행정 서비스 사전규격",
  agency: "신규 발주기관",
  published_at: "2026-08-31T00:00:00Z",
  deadline_at: "2026-09-07T00:00:00Z",
  budget: null,
  sw_business_status: "Y",
  business_division: "일반용역",
  origin: "신규",
  opportunity_id: 78,
  tracking_status: "미선택",
  kept_by_tracking: false,
  document: { attachments: 1, "완료": 1, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  overview_review_status: "failed",
};

const allOnlyPreSpec = {
  notice_pk: 993,
  pre_spec_no: "PRE-993",
  title: "전체 보기 전용 사전규격",
  agency: "전체 발주기관",
  published_at: "2026-08-29T00:00:00Z",
  deadline_at: null,
  budget: null,
  sw_business_status: null,
  business_division: "기술용역",
  origin: null,
  opportunity_id: null,
  tracking_status: null,
  kept_by_tracking: false,
  document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  // notice에 prespec_overview_review 행이 아직 없다(개요 검토 미시작). 10값
  // 중 어느 것도 아니며, awaiting_document로 접어 넣지 않는다.
  overview_review_status: null,
};

const ALL_OVERVIEW_STATUSES: (string | null)[] = [
  "awaiting_document",
  "awaiting_structure",
  "preparing",
  "awaiting_model",
  "queued",
  "running",
  "needs_human_review",
  "completed",
  "failed",
  "cancelled",
  null,
];

function overviewStatusCounts(items: readonly { overview_review_status: string | null }[]) {
  return ALL_OVERVIEW_STATUSES.map((status) => ({
    status,
    count: items.filter((item) => item.overview_review_status === status).length,
  }));
}

const notice991 = {
  id: 991,
  notice_key: "pre-spec:991",
  run_id: "source-run-not-used-for-routing",
  title: trackingException.title,
  agency: trackingException.agency,
  published_at: trackingException.published_at,
  deadline_at: trackingException.deadline_at,
  estimated_price: null,
  sample_role: null,
  sample_stratum: null,
  collection_bucket: null,
  grade: null,
  readiness: null,
  focus: null,
  attachment_count: 6,
  attachment_status: "g2b",
  bid_no: null,
  bid_ord: null,
  source_type: "pre_spec",
  budget: trackingException.budget,
  method: null,
  url: "https://example.invalid/pre-specs/991",
  timezone: "Asia/Seoul",
  procurement_class: null,
  region_limit: null,
  lifecycle: { pre_spec_no: "PRE-991" },
  qualification_flags: { sw_business_status: "N" },
  focus_matches: [],
  performance_matches: [],
  performance_top_score: null,
  candidate_sources: [],
  judgment: null,
  attachments: [],
  reviews: [],
};

const unknownOverview = {
  schema_version: "bidops.prespec-overview-reviews.v2",
  notice_id: 991,
  reviews: [{
    id: "00000000-0000-0000-0000-000000000991",
    notice_id: 991,
    status: "needs_human_review",
    result: null,
    result_digest: null,
    binding_digest: null,
    validation_status: "pending",
    completed_at: null,
    current_snapshot: {
      id: "10000000-0000-0000-0000-000000000991",
      document_version_id: "20000000-0000-0000-0000-000000000991",
      structure_id: "30000000-0000-0000-0000-000000000991",
      source_sha256: "a".repeat(64),
      payload_sha256: "b".repeat(64),
      cut_status: "unknown",
      strategy: null,
      start_locator: null,
      end_locator: null,
      created_at: "2026-08-31T01:00:00Z",
    },
    attempts: [],
  }],
};

const completedOverview = {
  ...unknownOverview,
  reviews: [{
    ...unknownOverview.reviews[0],
    status: "completed",
    result: {
      schema_version: "bidops.prespec-overview-result.v1",
      recommendation: "조건부 추진 검토",
      summary: "민원·행정 데이터를 통합해 담당자가 업무 현황을 조회하는 행정 지원 플랫폼 구축 사업입니다.",
      conditions: ["기존 시스템 연계 범위와 기관별 데이터 제공 책임을 확인해야 합니다."],
      verification_due_at: "2026-09-02T00:00:00Z",
      unknowns: [
        {
          topic: "기존 시스템 연계 범위",
          reason: "개요 입력에는 연계 대상과 제공 API 목록이 없습니다.",
          verification_action: "심층 검토에서 연계 대상별 인터페이스 명세를 확인합니다.",
        },
        {
          topic: "개인정보 처리 책임",
          reason: "운영 주체와 개인정보 처리 역할이 확정되지 않았습니다.",
          verification_action: null,
        },
      ],
      evidence: [{
        claim: "사업은 행정 지원 플랫폼 구축과 기존 업무 데이터 연계를 포함합니다.",
        locator: { block_key: "overview-intro", page: 2, ordinal: 7 },
      }],
      input_limitations: ["제안요청서 앞부분의 개요 입력만 검토했습니다."],
    },
    result_digest: "c".repeat(64),
    binding_digest: "d".repeat(64),
    validation_status: "passed",
    completed_at: "2026-08-31T02:00:00Z",
    current_snapshot: { ...unknownOverview.reviews[0].current_snapshot, cut_status: "ready", strategy: "topic_heading" },
    attempts: [{
      id: "00000000-0000-0000-0000-000000000992",
      snapshot_id: "10000000-0000-0000-0000-000000000991",
      sequence: 1,
      status: "completed",
      reference_only: false,
      deployable: true,
      validation_status: "passed",
      result_digest: "c".repeat(64),
      binding_digest: "d".repeat(64),
      created_at: "2026-08-31T01:30:00Z",
      started_at: "2026-08-31T01:35:00Z",
      completed_at: "2026-08-31T02:00:00Z",
    }],
  }],
};

function completedOverviewWithEvidenceBlock(blockKey: string) {
  const review = completedOverview.reviews[0];
  return {
    ...completedOverview,
    reviews: [{
      ...review,
      result: {
        ...review.result,
        evidence: review.result.evidence.map((evidence) => ({
          ...evidence,
          locator: { ...evidence.locator, block_key: blockKey },
        })),
      },
    }],
  };
}

const awaitingModelOverview = {
  ...unknownOverview,
  reviews: [{
    ...unknownOverview.reviews[0],
    status: "awaiting_model",
  }],
};

interface PreSpecTrace {
  listQueries: URLSearchParams[];
  noticeGets: number[];
  overviewGets: number[];
  structurePageGets: Array<{ structureId: string; page: number }>;
  trackingPatches: Array<{ opportunityId: number; trackingStatus: string; reason: string }>;
}

interface PreSpecMockOptions {
  emptyDefault?: boolean;
  overviewNoticeId?: number;
  overviewReviewNoticeId?: number;
  overviewStatus?: number;
  overviewBody?: unknown;
}

async function mockPreSpecs(page: Page, options: PreSpecMockOptions = {}): Promise<PreSpecTrace> {
  const trace: PreSpecTrace = { listQueries: [], noticeGets: [], overviewGets: [], structurePageGets: [], trackingPatches: [] };
  const trackingByOpportunity = new Map<number, string>([
    [trackingException.opportunity_id, trackingException.tracking_status],
    [newPreSpec.opportunity_id, newPreSpec.tracking_status],
  ]);

  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const overviewMatch = url.pathname.match(/^\/api\/pre-specs\/(\d+)\/overview-reviews\/v2$/);

    if (overviewMatch && request.method() === "GET") {
      const id = Number(overviewMatch[1]);
      trace.overviewGets.push(id);
      const overviewBody = options.overviewBody ?? (id === 991 ? {
        ...unknownOverview,
        notice_id: options.overviewNoticeId ?? unknownOverview.notice_id,
        reviews: unknownOverview.reviews.map((review) => ({
          ...review,
          notice_id: options.overviewReviewNoticeId ?? review.notice_id,
        })),
      } : { detail: "사전규격 없음" });
      await route.fulfill({
        status: options.overviewStatus ?? (id === 991 ? 200 : 404),
        contentType: "application/json",
        body: JSON.stringify(overviewBody),
      });
      return;
    }

    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      trace.listQueries.push(new URLSearchParams(url.search));
      const noticePk = url.searchParams.has("notice_pk") ? Number(url.searchParams.get("notice_pk")) : null;
      const swOnly = url.searchParams.get("sw_only") !== "false";
      const allItems = [
        { ...trackingException, tracking_status: trackingByOpportunity.get(trackingException.opportunity_id) },
        { ...newPreSpec, tracking_status: trackingByOpportunity.get(newPreSpec.opportunity_id) },
        allOnlyPreSpec,
      ];
      const items = noticePk !== null
        ? allItems.filter((item) => item.notice_pk === noticePk)
        : swOnly
          ? options.emptyDefault ? [] : allItems.slice(0, 2)
          : allItems;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items,
          total: items.length,
          limit: 50,
          offset: 0,
          overview_status_counts: overviewStatusCounts(items),
        }),
      });
      return;
    }

    await route.fallback();
  });

  await page.route("**/api/opportunities/*/tracking-status", async (route) => {
    const request = route.request();
    const match = new URL(request.url()).pathname.match(/^\/api\/opportunities\/(\d+)\/tracking-status$/);
    if (request.method() !== "PATCH" || !match) {
      await route.fallback();
      return;
    }
    const body = request.postDataJSON() as { tracking_status?: string; reason?: string };
    const opportunityId = Number(match[1]);
    if (!trackingByOpportunity.has(opportunityId) || !body.tracking_status || !body.reason?.trim()) {
      await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "tracking_reason_required" }) });
      return;
    }
    trackingByOpportunity.set(opportunityId, body.tracking_status);
    trace.trackingPatches.push({
      opportunityId,
      trackingStatus: body.tracking_status,
      reason: body.reason,
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: opportunityId,
        tracking_status: body.tracking_status,
        tracking_reason: body.reason,
        tracking_selected_by: request.headers()["x-bidops-actor-name"] ?? "테스트 담당자",
        tracking_selected_at: "2026-09-01T00:00:00Z",
        recheck_signal: false,
        recheck_signal_at: null,
        recheck_signal_link_id: null,
        first_registered_stage: "order_plan",
        links: [],
      }),
    });
  });

  await page.route("**/api/notices/**", async (route) => {
    const request = route.request();
    const match = new URL(request.url()).pathname.match(/^\/api\/notices\/(\d+)$/);
    if (match && request.method() === "GET") {
      const id = Number(match[1]);
      trace.noticeGets.push(id);
      await route.fulfill({
        status: id === 991 || id === 992 || id === 993 ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(id === 991
          ? notice991
          // 992는 발주계획에 없던 신규 사전규격이다. 승계 건(991)과 달리 이 화면이
          // 추적 시작을 묻는 유일한 경우다.
          : id === 992
            ? { ...notice991, id: 992, notice_key: "pre-spec:992", title: newPreSpec.title, agency: newPreSpec.agency, attachment_count: 1, url: null, lifecycle: { pre_spec_no: newPreSpec.pre_spec_no }, qualification_flags: { sw_business_status: "Y" } }
            : id === 993
              ? { ...notice991, id: 993, notice_key: "pre-spec:993", title: allOnlyPreSpec.title, agency: allOnlyPreSpec.agency, attachment_count: 0, url: null, lifecycle: { pre_spec_no: allOnlyPreSpec.pre_spec_no }, qualification_flags: { sw_business_status: null } }
              : { detail: "공고 없음" }),
      });
      return;
    }
    await route.fallback();
  });

  const structurePageTrace = await mockDocumentStructurePage(page);
  trace.structurePageGets = structurePageTrace.pageGets;

  return trace;
}

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(FIXED_TIME);
  await mockApi(page);
});

test("URL 누락은 sw_only=true, 전체 보기와 기본값 복원은 서로 다른 query를 보낸다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const defaultView = page.getByRole("checkbox", { name: "SW 중심 · 추적 예외 포함" });
  await expect(defaultView).toBeChecked();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("true");
  expect(new URL(page.url()).searchParams.has("sw_only")).toBe(false);

  // React Router owns this controlled checkbox through the URL. A native
  // `uncheck()` assertion can run before the search-param render commits.
  await defaultView.click();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("false");
  await expect(defaultView).not.toBeChecked();
  expect(new URL(page.url()).searchParams.get("sw_only")).toBe("false");

  await page.getByRole("button", { name: "기본값으로" }).click();
  await expect(defaultView).toBeChecked();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("true");
  expect(new URL(page.url()).searchParams.has("sw_only")).toBe(false);
});

test("기본 보기 빈 상태의 전체 사전규격 보기는 sw_only=false를 명시한다", async ({ page }) => {
  const trace = await mockPreSpecs(page, { emptyDefault: true });
  await page.goto("/pre-specs");

  await expect(page.getByRole("button", { name: "전체 사전규격 보기" })).toBeVisible();
  await page.getByRole("button", { name: "전체 사전규격 보기" }).click();
  await expect.poll(() => trace.listQueries.at(-1)?.get("sw_only")).toBe("false");
  // allOnlyPreSpec은 개요 검토 미시작(null) 그룹에 있고 이 그룹은 기본
  // 접힘이므로, 펼치기 전에는 행이 접근성 트리에도 없다.
  await expect(page.getByRole("link", { name: allOnlyPreSpec.title })).toHaveCount(0);
  await page.getByRole("button", { name: /개요 검토 미시작/ }).click();
  await expect(page.getByRole("link", { name: allOnlyPreSpec.title })).toBeVisible();
});

test("추적 예외, 신규, D-day, 문서 차단과 실패를 별도 상태로 표시한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const trackedRow = page.locator("tbody tr").filter({ hasText: trackingException.title });
  await expect(trackedRow).toContainText("추적");
  await expect(trackedRow).toContainText("추적 예외");
  await expect(trackedRow).toContainText("N");
  await expect(trackedRow.getByLabel("D-day: D-2")).toBeVisible();
  await expect(trackedRow.getByText("차단 2", { exact: true })).toBeVisible();
  await expect(trackedRow.getByText("실패 1", { exact: true })).toBeVisible();

  const newRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: newPreSpec.title }) });
  await expect(newRow.getByText("신규", { exact: true })).toBeVisible();
});

test("개요 검토 상태 10값과 미시작(null)이 모두 그룹으로 표현된다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");

  const groupLabels: Record<string, string> = {
    awaiting_document: "문서 대기",
    awaiting_structure: "구조화 대기",
    preparing: "입력 준비 중",
    awaiting_model: "모델 실행 대기",
    queued: "실행 대기",
    running: "실행 중",
    needs_human_review: "사람 검토 필요",
    completed: "완료",
    failed: "실패",
    cancelled: "취소",
  };
  // 10값 전부가 화면에 존재한다 — 이 fixture에는 needs_human_review·failed
  // 만 실제 건수(1건씩)가 있고 나머지는 0건이지만, 0건 그룹도 숨기지 않는다.
  for (const [status, label] of Object.entries(groupLabels)) {
    // "실행 대기"(queued)가 "모델 실행 대기"(awaiting_model)의 부분 문자열이라
    // 앵커 없이 찾으면 strict mode violation이 난다 — 결정적 DOM 문제이지
    // flake가 아니다(docs/engineering-notes.md). 그룹 트리거 접근성 이름은
    // 라벨로 시작하므로 시작 앵커로 좁힌다.
    const trigger = page.getByRole("button", { name: new RegExp(`^${label}`) });
    await expect(trigger).toBeVisible();
    const expectedCount = status === "needs_human_review" || status === "failed" ? "1건" : "0건";
    await expect(trigger).toContainText(expectedCount);
  }
  // 개요 검토 미시작(null, prespec_overview_review 행 없음)은 10값과 다른
  // 별도의 열한 번째 그룹이며 awaiting_document로 접히지 않는다.
  const notStarted = page.getByRole("button", { name: /개요 검토 미시작/ });
  await expect(notStarted).toBeVisible();
  await expect(notStarted).toContainText("1건");
});

test("사람 검토 필요·실패는 기본 펼침, 그 외 그룹은 기본 접힘이다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");

  const needsHumanReview = page.getByRole("button", { name: /사람 검토 필요/ });
  const failed = page.getByRole("button", { name: /^실패/ });
  const notStarted = page.getByRole("button", { name: /개요 검토 미시작/ });
  const completed = page.getByRole("button", { name: /^완료/ });

  await expect(needsHumanReview).toHaveAttribute("aria-expanded", "true");
  await expect(failed).toHaveAttribute("aria-expanded", "true");
  await expect(notStarted).toHaveAttribute("aria-expanded", "false");
  await expect(completed).toHaveAttribute("aria-expanded", "false");

  // 기본 펼침 그룹의 행은 클릭 없이 바로 보인다.
  await expect(page.getByRole("link", { name: trackingException.title })).toBeVisible();
  await expect(page.getByRole("link", { name: newPreSpec.title })).toBeVisible();
  // 기본 접힘 그룹의 행은 펼치기 전에는 접근성 트리에 없다.
  await expect(page.getByRole("link", { name: allOnlyPreSpec.title })).toHaveCount(0);

  await notStarted.click();
  await expect(notStarted).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("link", { name: allOnlyPreSpec.title })).toBeVisible();

  // 키보드로도 접고 펼 수 있다 — Enter로 다시 접는다.
  await notStarted.focus();
  await page.keyboard.press("Enter");
  await expect(notStarted).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("link", { name: allOnlyPreSpec.title })).toHaveCount(0);
});

// ADR-0045 결정 6: 추적 상태를 묻는 자리는 하나다. 발주계획에서 승계한 건은 이 화면이
// 다시 묻지 않고 승계 사실만 밝힌다.
test("발주계획에서 승계한 건은 추적 상태를 다시 묻지 않고 승계 사실을 배지로 밝힌다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const trackedRow = page.locator("tbody tr").filter({ hasText: trackingException.title });
  await trackedRow.getByRole("button", { name: "추적 결정" }).click();

  const decisionPanel = page.locator("#pre-specs-tracking-target");
  await expect(decisionPanel.getByRole("heading", { name: "추적 상태 · 발주계획에서 승계" })).toBeVisible();
  await expect(decisionPanel.getByText("계속 추적 · 발주계획에서 승계", { exact: true })).toBeVisible();
  await expect(decisionPanel).toContainText("이 화면에서 다시 묻지 않으며 심층 검토가 정상 완료돼도 다시 묻지 않습니다.");

  // 결정 form 자체가 없다. 보류·추적 종료는 사업 추적에서만 고른다.
  await expect(decisionPanel.getByRole("button", { name: "추적 상태 저장", exact: true })).toHaveCount(0);
  await expect(decisionPanel.getByRole("button", { name: "추적 시작하고 심층 검토", exact: true })).toHaveCount(0);
  await expect(decisionPanel.getByRole("button", { name: "보류", exact: true })).toHaveCount(0);
  await expect(decisionPanel.getByRole("button", { name: "종료", exact: true })).toHaveCount(0);
  await expect(decisionPanel.getByRole("link", { name: "사업 추적" })).toBeVisible();
  expect(trace.trackingPatches).toEqual([]);
});

// PLAN 단계 D 작업 3: 이 화면의 결정은 심층 검토 실행 승인이다. 승계 건은 추적 상태를
// 다시 묻지 않으므로 그 진입점이 없으면 막다른 카드가 된다.
test("승계 건도 상세 pane에서 심층 검토 실행으로 이어질 수 있다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false&sort=deadline");

  const trackedRow = page.locator("tbody tr").filter({ hasText: trackingException.title });
  await trackedRow.getByRole("button", { name: "추적 결정" }).click();

  const detailPane = page.locator(".pre-specs-detail-pane");
  await detailPane.getByRole("link", { name: "심층 검토 실행 →" }).click();

  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/991");
  // 목록에서 들고 온 query를 잃지 않는다.
  expect(new URL(page.url()).search).toBe("?sw_only=false&sort=deadline");
});

// PLAN 단계 D 작업 4: 발주계획에 없던 신규 사전규격만 한 조작으로 받는다. 한 조작이지만
// 기록은 둘이다 — 추적 시작을 지금 남기고 심층 검토 실행 승인은 상세에서 이어서 남긴다.
test("신규 사전규격만 추적 시작하고 심층 검토를 한 조작으로 받고 두 기록을 따로 남긴다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const newRow = page.locator("tbody tr").filter({ hasText: newPreSpec.title });
  await newRow.getByRole("button", { name: "추적 결정" }).click();

  const decisionPanel = page.locator("#pre-specs-tracking-target");
  await expect(decisionPanel.getByRole("heading", { name: "심층 검토 추적 선택" })).toBeVisible();
  await expect(decisionPanel).toContainText("한 조작이지만 기록은 둘입니다.");
  // 이 화면에는 보류·추적 종료가 없다.
  await expect(decisionPanel.getByRole("button", { name: "보류", exact: true })).toHaveCount(0);
  await expect(decisionPanel.getByRole("button", { name: "종료", exact: true })).toHaveCount(0);
  await expect(decisionPanel).toContainText("사업 추적에서만 사람이 고릅니다.");

  await decisionPanel.getByRole("textbox", { name: "사유 (필수)" }).fill("발주계획에 없던 신규 건");
  await decisionPanel.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("홍길동");
  await decisionPanel.getByRole("button", { name: "추적 시작하고 심층 검토", exact: true }).click();

  // 기록 1: 추적 시작만 저장된다. 심층 검토 실행은 이 요청에 섞이지 않는다.
  await expect.poll(() => trace.trackingPatches).toEqual([{
    opportunityId: 78,
    trackingStatus: "계속 추적",
    reason: "발주계획에 없던 신규 건",
  }]);

  // 기록 2의 자리: 심층 검토 실행 승인은 문서 묶음이 준비된 상세에서 이어서 남긴다.
  await expect.poll(() => new URL(page.url()).pathname).toBe("/pre-specs/992");
});

test("사업기회가 없는 행은 목록에서도 추적 결정 비활성 사유를 보여준다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false");
  await page.getByRole("button", { name: /개요 검토 미시작/ }).click();

  const untrackedRow = page.locator("tbody tr").filter({ hasText: allOnlyPreSpec.title });
  const disabledButton = untrackedRow.getByRole("button", { name: "추적 결정" });
  await expect(disabledButton).toBeDisabled();
  await expect(page.getByText("아직 사업기회에 연결되지 않아 추적 결정을 기록할 수 없습니다.", { exact: true })).toBeVisible();
});

// ADR-0046 이 지원 폭을 1280~1920px 로 좁히면서 390px 의 목록·상세 전환은
// 없앴다(PLAN 단계 B). 행 선택은 목록을 덮지 않고 오른쪽 상세만 바꾼다.
test("사전규격 목록 행 선택은 목록을 유지한 채 오른쪽 상세만 바꾼다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const listPane = page.locator(".pre-specs-list-pane");
  const detailPane = page.locator(".pre-specs-detail-pane");
  await expect(listPane).toBeVisible();
  await expect(detailPane).toContainText("사전규격을 선택하십시오.");

  const row = page.getByRole("row").filter({ has: page.getByRole("link", { name: trackingException.title }) });
  await row.click();

  await expect(page.locator('[data-review-primitive="split-workspace"]')).not.toHaveAttribute("data-mobile-view", /.*/);
  await expect(page.locator('tbody tr[aria-selected="true"]')).toHaveCount(1);
  await expect(page.locator("#pre-specs-tracking-target")).toBeVisible();
  // 목록은 선택 뒤에도 그대로 남는다.
  await expect(listPane).toBeVisible();

  await page.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(page.locator("#pre-specs-tracking-target")).toHaveCount(0);
  await expect(listPane).toBeVisible();
  await expect(detailPane).toContainText("사전규격을 선택하십시오.");
});

test("notice 991 정본 상세는 29로 치환되지 않고 unknown을 사람 확인 상태로 보존한다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs?sw_only=false&sort=deadline");
  await page.getByRole("link", { name: trackingException.title }).click();

  expect(new URL(page.url()).pathname).toBe("/pre-specs/991");
  expect(new URL(page.url()).search).toBe("?sw_only=false&sort=deadline");
  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  await expect(page.getByText("notice 991", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("unknown · 사람 확인 필요", { exact: true })).toBeVisible();
  await expect(page.getByText("전체 문서 성공으로 자동 보정하지 않습니다.")).toBeVisible();
  expect(trace.noticeGets).toEqual([991]);
  expect(trace.overviewGets).toEqual([991]);
  expect(trace.noticeGets).not.toContain(29);

  await page.reload();
  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  expect(trace.noticeGets).toEqual([991, 991]);
  expect(trace.overviewGets).toEqual([991, 991]);
  expect(trace.noticeGets).not.toContain(29);
});

test("사전규격 상세는 notice_pk projection의 현재 추적 상태와 첨부 집계를 보여준다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs/991");

  await expect(page.getByText("현재 추적 상태", { exact: true })).toBeVisible();
  // 991은 발주계획에서 승계한 건이라 상세도 상태만 밝히고 다시 묻지 않는다.
  await expect(page.locator(".pre-spec-tracking-current").getByText("계속 추적 · 발주계획에서 승계", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "첨부 원문 취득 집계", exact: true })).toBeVisible();
  await expect(page.getByText("완료", { exact: true })).toBeVisible();
  await expect(page.getByText("차단", { exact: true })).toBeVisible();
  expect(trace.listQueries.at(-1)?.get("notice_pk")).toBe("991");
  expect(trace.listQueries.at(-1)?.has("sw_only")).toBe(false);
});

test("사유 없이 사전규격 추적 상태를 보낼 수 없다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  // 991은 승계 건이라 결정 form이 없다. 사유 규칙은 신규 건에서 확인한다.
  await page.goto("/pre-specs/992");

  // 저장 액션은 헤더가 소유하고 입력 form은 본문에 있다(PLAN 단계 F 작업 1).
  await expect(page.getByRole("button", { name: "추적 상태 저장", exact: true })).toBeDisabled();
  await expect(page.locator("#pre-spec-detail-tracking-disabled")).toContainText("추적 결정을 저장하려면 사유를 입력하십시오.");
  expect(trace.trackingPatches).toEqual([]);
});

test("사전규격 추적 선택에 성공하면 사람 결정 상태가 갱신된다", async ({ page }) => {
  const trace = await mockPreSpecs(page);
  await page.goto("/pre-specs/992");

  // 사전규격에서 고를 수 있는 값은 `계속 추적` 하나뿐이다(ADR-0045 결정 6).
  await expect(page.getByRole("button", { name: "보류", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "종료", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "계속 추적", exact: true }).click();
  await page.getByRole("textbox", { name: "사유 (필수)" }).fill("연계 범위를 확인한 뒤 계속 검토하기로 함");
  await page.getByRole("textbox", { name: "담당자 이름 (필수)" }).fill("홍길동");
  await page.getByRole("button", { name: "추적 상태 저장", exact: true }).click();

  await expect.poll(() => trace.trackingPatches).toEqual([{
    opportunityId: 78,
    trackingStatus: "계속 추적",
    reason: "연계 범위를 확인한 뒤 계속 검토하기로 함",
  }]);
  await expect(page.getByText("심층 검토 추적 상태를 저장했습니다.", { exact: true })).toBeVisible();
});

test("사업기회가 없으면 추적 결정을 기록할 수 없는 이유를 보여준다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs/993");

  await expect(page.getByText("사업기회 미연결", { exact: true })).toBeVisible();
  await expect(page.locator(".mutation-feedback-warning")).toContainText("아직 사업기회에 연결되지 않아 추적 상태를 결정할 수 없습니다.");
  await expect(page.getByRole("button", { name: "계속 추적", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "추적 상태 저장", exact: true })).toBeDisabled();
  await expect(page.locator("#pre-spec-detail-tracking-disabled")).toContainText("아직 사업기회에 연결되지 않아");
});

test("v2 개요 결과는 평가에 필요한 요약·미확인·근거 위치를 보여준다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: completedOverview });
  await page.goto("/pre-specs/991");

  await expect(page.getByRole("heading", { name: "요약", exact: true })).toBeVisible();
  await expect(page.getByText("민원·행정 데이터를 통합해 담당자가 업무 현황을 조회하는 행정 지원 플랫폼 구축 사업입니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("기존 시스템 연계 범위", { exact: true })).toBeVisible();
  await expect(page.getByText("개요 입력에는 연계 대상과 제공 API 목록이 없습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("심층 검토에서 연계 대상별 인터페이스 명세를 확인합니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("개인정보 처리 책임", { exact: true })).toBeVisible();
  await expect(page.getByText("운영 주체와 개인정보 처리 역할이 확정되지 않았습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("확인 방법 미지정", { exact: true })).toBeVisible();
  await expect(page.getByText("2쪽", { exact: true })).toBeVisible();
  await expect(page.getByText("overview-intro", { exact: true })).toBeVisible();
  await expect(page.getByText("ordinal 7", { exact: true })).toBeVisible();
  await expect(page.getByText("검증 통과 · passed", { exact: true })).toBeVisible();
  await expect(page.getByText(/판정으로 읽지 마세요/)).not.toBeVisible();
});

test("근거의 원문 열기는 locator 페이지의 블록을 불러온다", async ({ page }) => {
  const trace = await mockPreSpecs(page, { overviewBody: completedOverview });
  await page.goto("/pre-specs/991");

  await page.getByRole("button", { name: "원문 열기" }).click();

  await expect(page.getByRole("heading", { name: "페이지 2 · 원문 블록 확인", exact: true })).toBeVisible();
  await expect(page.getByText("페이지 2", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("1. 사업 개요와 추진 배경", { exact: true })).toBeVisible();
  await expect(page.getByText("공공기관의 민원·행정 데이터를 통합해 현황을 분석하고 담당자가 업무 현황을 조회하는 행정 지원 플랫폼 구축 사업입니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("주요 수행 범위는 기존 업무 데이터 연계와 운영 화면 구축입니다.", { exact: true })).toBeVisible();

  expect(trace.structurePageGets).toEqual([{
    structureId: "30000000-0000-0000-0000-000000000991",
    page: 2,
  }]);

  await page.getByRole("button", { name: "원문 닫기" }).click();
  await page.getByRole("button", { name: "원문 열기" }).click();
  expect(trace.structurePageGets).toHaveLength(1);
});

test("원문은 강조 블록과 앞뒤 맥락 블록을 함께 보여준다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: completedOverview });
  await page.goto("/pre-specs/991");
  await page.getByRole("button", { name: "원문 열기" }).click();

  const sourceBlocks = page.locator(".pre-spec-overview-source-block");
  await expect(sourceBlocks).toHaveCount(3);
  await expect(page.locator(".pre-spec-overview-source-block.is-target")).toHaveCount(1);
  await expect(page.locator(".pre-spec-overview-source-block.is-target")).toContainText("overview-intro");
  await expect(sourceBlocks.nth(0)).toContainText("overview-heading");
  await expect(sourceBlocks.nth(2)).toContainText("overview-scope");
});

test("원문 닫기는 열린 페이지와 블록을 화면에서 제거한다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: completedOverview });
  await page.goto("/pre-specs/991");
  await page.getByRole("button", { name: "원문 열기" }).click();
  await expect(page.locator("#pre-spec-overview-source")).toBeVisible();

  await page.getByRole("button", { name: "원문 닫기" }).click();
  await expect(page.locator("#pre-spec-overview-source")).not.toBeVisible();
  await expect(page.getByText("공공기관의 민원·행정 데이터를 통합해 현황을 분석하고 담당자가 업무 현황을 조회하는 행정 지원 플랫폼 구축 사업입니다.", { exact: true })).not.toBeVisible();
});

test("페이지에 locator 블록이 없으면 어긋남을 표시하고 강조하지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: completedOverviewWithEvidenceBlock("missing-block") });
  await page.goto("/pre-specs/991");
  await page.getByRole("button", { name: "원문 열기" }).click();

  await expect(page.getByText("근거 위치와 원문이 어긋났습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("1. 사업 개요와 추진 배경", { exact: true })).toBeVisible();
  await expect(page.locator(".pre-spec-overview-source-block.is-target")).toHaveCount(0);
});

test("원문은 내부 bbox·confidence·attributes와 객체 식별자를 화면에 내지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: completedOverview });
  await page.goto("/pre-specs/991");
  await page.getByRole("button", { name: "원문 열기" }).click();

  const body = page.locator("body");
  await expect(body).not.toContainText("910");
  await expect(body).not.toContainText("0.42");
  await expect(body).not.toContainText("do-not-render-attributes");
  await expect(body).not.toContainText("image-content-do-not-render");
});

test("v2 검증 실패는 결과를 판정으로 읽지 않도록 경고한다", async ({ page }) => {
  const failedOverview = {
    ...completedOverview,
    reviews: [{ ...completedOverview.reviews[0], validation_status: "failed" }],
  };
  await mockPreSpecs(page, { overviewBody: failedOverview });
  await page.goto("/pre-specs/991");

  await expect(page.getByText("검증 실패 · failed", { exact: true })).toBeVisible();
  await expect(page.getByText("검증에 실패한 결과입니다. 이 내용을 판정으로 읽지 마세요.", { exact: true })).toBeVisible();
});

test("result가 없고 awaiting_model이면 승인된 binding 대기 상태를 설명한다", async ({ page }) => {
  await mockPreSpecs(page, { overviewBody: awaitingModelOverview });
  await page.goto("/pre-specs/991");

  await expect(page.getByText("검토 결과 미확정", { exact: true })).toBeVisible();
  await expect(page.getByText("승인된 모델 binding이 없어 아직 실행되지 않은 상태입니다. 승인된 사설 모델 binding이 준비되기 전에는 모델을 호출하지 않습니다.", { exact: true })).toBeVisible();
});

test("overview envelope notice ID가 어긋나면 교차 정본을 렌더링하지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewNoticeId: 992 });
  await page.goto("/pre-specs/991");

  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  await expect(page.getByText("개요 검토 정본을 확인할 수 없습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("unknown · 사람 확인 필요", { exact: true })).not.toBeVisible();
  await expect(page.getByText("응답의 notice ID가 요청과 일치하지 않아 개요 검토를 표시하지 않습니다.", { exact: true })).toBeVisible();
});

test("overview nested review notice ID가 어긋나면 교차 정본을 렌더링하지 않는다", async ({ page }) => {
  await mockPreSpecs(page, { overviewReviewNoticeId: 992 });
  await page.goto("/pre-specs/991");

  await expect(page.getByRole("heading", { level: 2, name: trackingException.title })).toBeVisible();
  await expect(page.getByText("개요 검토 정본을 확인할 수 없습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText("unknown · 사람 확인 필요", { exact: true })).not.toBeVisible();
  await expect(page.getByText("응답의 notice ID가 요청과 일치하지 않아 개요 검토를 표시하지 않습니다.", { exact: true })).toBeVisible();
});

test("overview API 오류는 서버 detail이나 원문을 화면에 노출하지 않는다", async ({ page }) => {
  const secret = "raw-prompt-response-secret";
  await mockPreSpecs(page, { overviewStatus: 500, overviewBody: { detail: secret } });
  await page.goto("/pre-specs/991");

  await expect(page.getByText("개요 검토 상태를 불러오지 못했습니다.", { exact: true })).toBeVisible();
  await expect(page.getByText(secret, { exact: true })).not.toBeVisible();
  await expect(page.getByText("개요 검토 API 응답을 확인할 수 없습니다.", { exact: true })).toBeVisible();
});

test("사전규격 목록과 상세는 viewport 바깥으로 넘치지 않는다", async ({ page }) => {
  await mockPreSpecs(page);
  for (const path of ["/pre-specs", "/pre-specs/991"]) {
    await page.goto(path);
    await expect(page.locator("header.topbar h1")).toHaveText("사전규격");
    await expect.poll(() => page.evaluate(() => ({
      root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      canvas: (() => {
        const canvas = document.querySelector<HTMLElement>(".page-canvas");
        return canvas ? canvas.scrollWidth - canvas.clientWidth : 0;
      })(),
    }))).toEqual({ root: 0, canvas: 0 });
  }
});

// docs/design/PLAN.md 단계 F 작업 1·완료 게이트: 결정 **액션**은 요약 헤더에
// 고정되어 스크롤 위치와 무관하게 첫 화면에서 보이고, 되돌릴 수 없는 입력
// **form**은 헤더가 아니라 본문 열에 있다.
test("사전규격 상세는 결정 액션만 헤더에 고정하고 입력 form은 본문에 둔다", async ({ page }) => {
  await mockPreSpecs(page);
  // 결정 액션이 있는 건에서 확인한다. 991은 승계 건이라 결정 form이 없다.
  await page.goto("/pre-specs/992");
  const header = page.locator('[data-review-primitive="sticky-decision-header"]');
  await expect(header).toBeVisible();
  await expect(page.locator('[data-review-primitive="history-link-rail"]')).toHaveCount(1);

  const saveButton = header.getByRole("button", { name: "추적 상태 저장", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(header.getByRole("button", { name: "추적 결정 입력으로 이동", exact: true })).toBeInViewport();
  // 사유·담당자 입력은 헤더가 아니라 본문 열의 결정 패널 안에 있다.
  await expect(header.locator("textarea")).toHaveCount(0);
  await expect(page.locator(".detail-skeleton-main").getByRole("textbox", { name: "사유 (필수)" })).toHaveCount(1);

  await page.evaluate(() => document.querySelector(".page-canvas")?.scrollTo(0, 999_999));
  await expect(saveButton).toBeInViewport();
});

// 사업기회에 아직 연결되지 않은 사전규격도 비활성 결정 액션과 그 사유가
// 스크롤 없이 함께 보여야 한다 — 버튼만 헤더에 보이고 이유는 본문 깊숙이
// 남기지 않는다.
test("사업기회 미연결 사전규격은 비활성 추적 결정 액션과 사유가 스크롤 없이 함께 보인다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs/993");
  const saveButton = page.getByRole("button", { name: "추적 상태 저장", exact: true });
  await expect(saveButton).toBeInViewport();
  await expect(saveButton).toBeDisabled();
  await expect(page.locator("#pre-spec-detail-tracking-disabled")).toBeInViewport();
  await expect(page.locator("#pre-spec-detail-tracking-disabled")).toContainText("아직 사업기회에 연결되지 않아");
});
