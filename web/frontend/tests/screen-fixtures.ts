import { expect, test, type Page } from "@playwright/test";
import {
  mockApi,
  mockBidDelta,
  mockDeepReviewLifecycle,
  mockDocumentPreparationVisual,
  mockOpportunity,
  mockOrderPlans,
  mockPreSpecs,
  overviewEnvelopeFixture,
  overviewRunFixture,
} from "./api-mock";

// 화면 검사 세 층(의미·구조·픽셀)이 같은 고정 입력에서 출발하도록 여기 모은다.
// 층을 나눈 이유와 각 층의 게이트는 `docs/standards.md`에 있다.

// 마감까지 남은 날짜가 화면에 그려지므로, 시각을 고정하지 않으면 매일 스냅샷이 달라진다.
const FIXED_TIME = new Date("2026-08-25T09:00:00+09:00");

/** 고정 mock만으로 도달하는 화면. 세 층이 같은 목록을 순회한다. */
export const pages = [
  { name: "dashboard", path: "/" },
  { name: "queue", path: "/queue" },
  { name: "judgments", path: "/judgments" },
  { name: "reviews", path: "/reviews" },
  { name: "runs", path: "/runs" },
  { name: "attachments", path: "/attachments" },
  { name: "profile", path: "/profile" },
  { name: "metrics", path: "/metrics" },
  { name: "quality-gates", path: "/quality-gates" },
  // The default gate is operational approval (10/10); this second target
  // keeps the model-comparison "not eligible for activation" warning under
  // responsive visual coverage as well.
  { name: "quality-gates-comparison", path: "/quality-gates?gate=gate-model-comparison" },
  { name: "policies", path: "/policies" },
  { name: "operations", path: "/operations" },
  // docs/design/PLAN.md 2단계에서 새로 생긴 사이드바 항목과, 흡수한 탭 중
  // 이전에 리다이렉트라 기준선이 없던 산출물 감사 로그를 덮는다. 위 타깃들은
  // 이제 합친 화면의 각 탭을 찍는다(경로가 그대로 각 탭의 주소다).
  { name: "audit", path: "/audit" },
  { name: "criteria", path: "/criteria" },
  { name: "run-status", path: "/run-status" },
  { name: "go-no-go", path: "/go-no-go" },
];

/** 세 층이 공유하는 고정 입력. 각 spec의 `beforeEach`가 이것만 부른다. */
export function installScreenFixtures(): void {
  test.beforeEach(async ({ page }) => {
    // Keep visual tests on the local Pretendard contract. These defensive routes
    // also make an accidental future Google Fonts import fail closed without
    // allowing a remote font to affect a snapshot.
    await page.route("**://fonts.googleapis.com/**", async (route) => {
      await route.fulfill({ status: 200, contentType: "text/css", body: "" });
    });
    await page.route("**://fonts.gstatic.com/**", async (route) => {
      await route.fulfill({ status: 204, body: "" });
    });
    await page.clock.setFixedTime(FIXED_TIME);
    await mockApi(page);
  });
}

/** 로컬 Pretendard가 적용된 뒤에만 레이아웃을 안정화하고 스냅샷을 찍는다. */
export async function settleFonts(page: Page): Promise<void> {
  const fontState = await page.evaluate(async () => {
    const text = document.documentElement.textContent ?? "";
    await Promise.all([
      document.fonts.load('400 14px "Pretendard"', text),
      document.fonts.load('400 13px "Liberation Mono"', text),
    ]);
    await document.fonts.ready;
    await new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
    return {
      computedFontFamily: getComputedStyle(document.documentElement).fontFamily,
      pretendardLoaded: document.fonts.check('400 14px "Pretendard"'),
    };
  });
  expect(fontState.computedFontFamily).toContain("Pretendard");
  expect(fontState.pretendardLoaded).toBe(true);
}

/** Existing responsive regression contract, shared by legacy and lifecycle screens. */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const canvas = document.querySelector<HTMLElement>(".page-canvas");
    const widthOverflow = (element: HTMLElement): number => Math.max(0, element.scrollWidth - element.clientWidth);
    const actualLocalScrollers = new Set(
      [...document.querySelectorAll<HTMLElement>("body *")].filter((element) => {
        if (element === canvas) return false;
        const style = getComputedStyle(element);
        return (style.overflowX === "auto" || style.overflowX === "scroll")
          && element.scrollWidth > element.clientWidth;
      }),
    );
    const allowedScrollers = actualLocalScrollers;
    const isContainedByAllowedScroller = (element: Element): boolean => {
      let parent = element.parentElement;
      while (parent) {
        if (allowedScrollers.has(parent)) return true;
        parent = parent.parentElement;
      }
      return false;
    };
    const viewport = root.clientWidth;
    // Descendant exclusions require a real local horizontal scroller with
    // overflow-x auto/scroll and measurable scrollWidth excess; page-canvas
    // itself is never an exclusion.
    const overflowingDescendants = [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => !isContainedByAllowedScroller(element))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        if (rect.right <= 0 || rect.left >= viewport) return 0;
        return Math.max(rect.right - viewport, -rect.left);
      });
    const descendantOverflow = Math.max(0, ...overflowingDescendants);
    return {
      documentElement: widthOverflow(root),
      pageCanvas: canvas ? widthOverflow(canvas) : 0,
      descendants: descendantOverflow,
    };
  });
  expect(overflow.documentElement).toBeLessThanOrEqual(1);
  expect(overflow.pageCanvas, JSON.stringify(overflow)).toBeLessThanOrEqual(1);
  expect(overflow.descendants, JSON.stringify(overflow)).toBeLessThanOrEqual(1);
}

const VISUAL_COMPARISON_ID = "77777777-7777-4777-8777-777777777777";

export type LifecycleVisualTarget = {
  name: string;
  path: string;
  setup: (page: Page) => Promise<void>;
};

/** 화면마다 별도 setup이 필요한 생애주기 타깃. */
export const lifecycleVisualTargets: LifecycleVisualTarget[] = [
  { name: "opportunities-list", path: "/opportunities", setup: async (page) => { await mockOpportunity(page); } },
  { name: "opportunity-detail", path: "/opportunities/202", setup: async (page) => { await mockOpportunity(page); } },
  { name: "order-plans-list", path: "/order-plans", setup: async (page) => { await mockOrderPlans(page); } },
  { name: "pre-specs-list", path: "/pre-specs", setup: async (page) => { await mockPreSpecs(page); } },
  { name: "pre-spec-detail", path: "/pre-specs/991", setup: async (page) => { await mockPreSpecs(page); } },
  ...(["draft", "processing", "blocked", "ready"] as const).map((state) => ({
    name: `document-preparation-${state}`,
    path: "/pre-specs/991",
    setup: async (page: Page) => { await mockDocumentPreparationVisual(page, state); },
  })),
  ...(["queued", "running", "failed", "completed"] as const).map((state) => ({
    name: `deep-review-${state === "completed" ? "complete" : state}`,
    path: "/deep-reviews/fixture-review",
    setup: async (page: Page) => { await mockDeepReviewLifecycle(page, state); },
  })),
  ...(["unchanged", "changed", "unknown", "failed"] as const).map((state) => ({
    name: `bid-delta-${state}`,
    path: `/opportunities/501/bid-delta?comparison=${VISUAL_COMPARISON_ID}`,
    setup: async (page: Page) => { await mockBidDelta(page, { calculationStatus: "completed", resultStatus: state }); },
  })),
];


/** Shared v2 contract scenarios for the following screen tasks. */
export const contractFixtureScenarios = {
  orderPlansWithoutCompletedExecution: (page: Page) => mockOrderPlans(page, "no-completed-execution"),
  orderPlansWithoutOwner: (page: Page) => mockOrderPlans(page, "no-owning-opportunity"),
  preSpecClickReadyWithoutOrderPlan: {
    path: "/pre-specs?sw_only=false&auto_preparation_status=deep_review_ready_for_click",
    setup: (page: Page) => mockPreSpecs(page),
  },
} as const;


// ─ docs/0915_ui-redesign/spec.md §6 A3·A5 표본 ─────────────────────────────
// 목록 우측 정보 영역이 1280×800에서 스크롤 없이 보이는지(A3), 그리고 구역
// 순서와 값 없음 표기(A5)를 재려면 **개요 완료 · 주의 1건 · 미확인 2건 · 과업
// 4건**인 건과 **값이 거의 없는** 건이 한 응답에 함께 있어야 한다.
//
// 기존 표본(`api-mock.ts`의 `visualPreSpecItems`)은 다른 spec이 값까지 의존하므로
// 건드리지 않는다. `api-mock.ts`는 이 작업의 소유 밖이라 여기서 `page.route`로
// 덮어 새 표본만 추가한다.

export const PRE_SPEC_CAUTION_SAMPLE_PK = 7701;
export const PRE_SPEC_EMPTY_SAMPLE_PK = 7702;

// 이 표본을 쓰는 검사는 시계를 고정하지 않는다(A3는 실제 배치 높이를 잰다).
// D-day가 늘 같은 자리에 보이도록 마감은 지금으로부터 며칠 뒤로 잡는다.
const SAMPLE_DAY_MS = 86_400_000;
const sampleNow = Date.now();

const cautionSampleItem = {
  notice_pk: PRE_SPEC_CAUTION_SAMPLE_PK,
  pre_spec_no: "R26BD00273769",
  title: "예술인 공제사업 통합관리시스템 중장기 ISMP 수립",
  agency: "한국예술인복지재단",
  published_at: new Date(sampleNow - 3 * SAMPLE_DAY_MS).toISOString(),
  deadline_at: new Date(sampleNow + 2.5 * SAMPLE_DAY_MS).toISOString(),
  budget: 49_844_864,
  sw_business_status: "Y",
  business_division: "일반용역",
  origin: "신규",
  // 사업기회에 연결돼 있고 아직 사람이 고르지 않았다 — 바닥의 인라인 추적 폼이
  // 그려지는 가장 높은 상태이고, A3는 그 상태에서 재야 의미가 있다.
  opportunity_id: 7801,
  tracking_status: "미선택",
  kept_by_tracking: false,
  document: { attachments: 3, "완료": 3, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  overview_review_status: "completed",
  grade: "검토 권장",
  grade_source: "screening_judgment",
  auto_preparation_status: "bundle_ready",
  auto_preparation_reason: null,
  latest_deep_review_id: null,
  first_observed_at: new Date(sampleNow - 2 * SAMPLE_DAY_MS).toISOString(),
  last_observed_at: new Date(sampleNow - SAMPLE_DAY_MS).toISOString(),
  next_action: "decide_tracking",
};

/** 값이 거의 없는 건. A5의 `미확인` 계열 표기를 재는 자리다. */
const emptySampleItem = {
  notice_pk: PRE_SPEC_EMPTY_SAMPLE_PK,
  pre_spec_no: null,
  title: null,
  agency: null,
  published_at: null,
  deadline_at: null,
  budget: null,
  sw_business_status: null,
  business_division: null,
  origin: "신규",
  opportunity_id: null,
  tracking_status: null,
  kept_by_tracking: false,
  document: { attachments: 0, "완료": 0, "대기": 0, "진행": 0, "차단": 0, "실패": 0 },
  overview_review_status: null,
  grade: null,
  grade_source: null,
  auto_preparation_status: "not_applicable",
  auto_preparation_reason: null,
  latest_deep_review_id: null,
  first_observed_at: null,
  last_observed_at: null,
  next_action: null,
};

export const PRE_SPEC_CAUTION_SAMPLE_TASKS = [
  "현행 공제사업 3개 시스템 업무·데이터 현황 분석 및 이해관계자 요구 조사",
  "통합관리시스템 목표 모델과 정보화 전략 수립 (기능·데이터·연계 아키텍처)",
  "3개년 단계별 이행 계획과 소요 예산 산정, 사업 발주 방안 제시",
  "정보화 사업 발주를 위한 제안요청서 초안과 평가 기준 작성",
];

export const PRE_SPEC_CAUTION_SAMPLE_DESCRIPTION =
  "예술인 공제사업(창작준비금·산재보험 등)을 하나의 통합관리시스템으로 재구축하기 위한 중장기 정보화 전략(ISMP)을 수립하는 사업으로, 현행 3개 시스템의 업무·데이터를 분석해 목표 모델과 3개년 이행 계획을 도출한다.";

export const PRE_SPEC_CAUTION_SAMPLE_SCALE = "사업 예산은 49,844,864원(VAT 포함)이고 수행기간은 착수 후 6개월이다.";

export const PRE_SPEC_CAUTION_SAMPLE_UNKNOWNS = [
  "평가 배점표가 읽은 범위에 없어 확인하지 못했다.",
  "본공고 예정 시기가 읽은 범위에 없어 확인하지 못했다.",
];

/** 결정적 검사에 실패한 주장 하나 = spec §3.2의 주의 1건. */
export const PRE_SPEC_CAUTION_SAMPLE_HEADLINE = "수행 인력 상주 조건이 근거 위치와 연결되지 않았다.";

export const PRE_SPEC_CAUTION_SAMPLE_BID_NOTICE_NO = "R26BD00291144";

const cautionSampleRun = overviewRunFixture({
  id: "c1a7f0c2-7701-4a77-9c77-000000007701",
  status: "completed",
  result_id: "c1a7f0c2-7701-4a77-9c77-000000007701",
  verification_status: "needs_human_review",
  validation_status: "passed",
  evidence_check_status: "passed",
  warnings: [],
  failed_claims: [],
  result: {
    business_overview: [{
      claim_id: "s1",
      text: PRE_SPEC_CAUTION_SAMPLE_DESCRIPTION,
      evidence: [{ page: 3, quote: "중장기 정보화 전략(ISMP) 수립" }],
    }],
    main_tasks: PRE_SPEC_CAUTION_SAMPLE_TASKS.map((text, index) => ({
      claim_id: `s2-${index + 1}`,
      text,
      evidence: [{ page: 5 + index, quote: text.slice(0, 12) }],
    })),
    budget_and_period: [{
      claim_id: "s3",
      text: PRE_SPEC_CAUTION_SAMPLE_SCALE,
      evidence: [{ page: 4, quote: "사업예산 49,844,864원" }],
    }],
    // v7 이후 응답은 important_conditions·reviewer_analysis·unknowns 키 자체가
    // 없다(ADR-0057 결정 1). 참여 조건·위험/미확인은 심층 검토 결과가 갖는다.
    input_limitations: [],
  },
});

const cautionSampleVerification = {
  verification_id: cautionSampleRun.id,
  status: "needs_human_review" as const,
  reason_codes: ["required_fact_missing"],
  claims: [{
    claim_id: "s4",
    section: "important_conditions",
    text: PRE_SPEC_CAUTION_SAMPLE_HEADLINE,
    deterministic: { status: "failed" as const, reason_codes: ["quote_not_found"] },
    semantic: { status: "not_run" as const, reason_codes: [] },
    verified_evidence: [],
  }],
};

const cautionSampleNotice = {
  id: PRE_SPEC_CAUTION_SAMPLE_PK,
  notice_key: `pre-spec:${PRE_SPEC_CAUTION_SAMPLE_PK}`,
  run_id: "sample-run",
  title: cautionSampleItem.title,
  agency: cautionSampleItem.agency,
  published_at: cautionSampleItem.published_at,
  deadline_at: cautionSampleItem.deadline_at,
  estimated_price: null,
  sample_role: null,
  sample_stratum: null,
  collection_bucket: null,
  grade: null,
  readiness: null,
  focus: null,
  attachment_count: 3,
  attachment_status: "g2b",
  bid_no: null,
  bid_ord: null,
  source_type: "pre_spec",
  budget: cautionSampleItem.budget,
  method: null,
  url: null,
  timezone: "Asia/Seoul",
  procurement_class: null,
  region_limit: null,
  lifecycle: {
    pre_spec_no: cautionSampleItem.pre_spec_no,
    bid_ntice_no_list: PRE_SPEC_CAUTION_SAMPLE_BID_NOTICE_NO,
  },
  qualification_flags: { sw_business_status: "Y" },
  focus_matches: [],
  performance_matches: [],
  performance_top_score: null,
  candidate_sources: [],
  judgment: null,
  attachments: [],
  reviews: [],
};

const SAMPLE_OVERVIEW_STATUSES: (string | null)[] = ["completed", null];

/**
 * A3·A5 표본을 목록·개요·notice 세 응답에 함께 올린다. `mockApi` 뒤에 등록해야
 * 하며(뒤에 등록한 handler가 이긴다), 기존 표본은 그대로 둔 채 이 두 건만 쓴다.
 */
export async function mockPreSpecCautionSample(page: Page): Promise<void> {
  const items = [cautionSampleItem, emptySampleItem];
  await page.route("**/api/pre-specs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const overviewMatch = url.pathname.match(/^\/api\/pre-specs\/(\d+)\/overview$/);
    if (overviewMatch && request.method() === "GET") {
      const noticeId = Number(overviewMatch[1]);
      await route.fulfill({
        json: noticeId === PRE_SPEC_CAUTION_SAMPLE_PK
          ? overviewEnvelopeFixture(noticeId, cautionSampleRun, [cautionSampleRun], {
            verification: cautionSampleVerification,
          })
          : overviewEnvelopeFixture(noticeId, null),
      });
      return;
    }
    if (url.pathname === "/api/pre-specs" && request.method() === "GET") {
      const requested = url.searchParams.has("notice_pk") ? Number(url.searchParams.get("notice_pk")) : null;
      const shown = requested === null ? items : items.filter((item) => item.notice_pk === requested);
      await route.fulfill({
        json: {
          items: shown,
          total: shown.length,
          limit: 200,
          offset: 0,
          overview_status_counts: SAMPLE_OVERVIEW_STATUSES.map((status) => ({
            status,
            count: shown.filter((item) => item.overview_review_status === status).length,
          })),
          workspace_counts: { actionable: shown.filter((item) => item.next_action !== null).length, recent: shown.filter((item) => item.last_observed_at !== null).length, tracking: 0, all: shown.length },
          // 계약상 항상 있는 집계다. 이 표본의 마감은 `sampleNow + 2.5일`(미래)과
          // `null`(미확인) 둘뿐이라 구간 적용 전 actionable이 전부 `current`다.
          deadline_scope_counts: {
            current: shown.filter((item) => item.next_action !== null).length,
            passed: 0,
          },
        },
      });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/notices/**", async (route) => {
    const request = route.request();
    const match = new URL(request.url()).pathname.match(/^\/api\/notices\/(\d+)$/);
    if (!match || request.method() !== "GET") {
      await route.fallback();
      return;
    }
    const noticeId = Number(match[1]);
    await route.fulfill({
      status: noticeId === PRE_SPEC_CAUTION_SAMPLE_PK ? 200 : 404,
      json: noticeId === PRE_SPEC_CAUTION_SAMPLE_PK ? cautionSampleNotice : { detail: "공고 없음" },
    });
  });
}
