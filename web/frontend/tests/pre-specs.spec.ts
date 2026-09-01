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
};

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
}

interface PreSpecMockOptions {
  emptyDefault?: boolean;
  overviewNoticeId?: number;
  overviewReviewNoticeId?: number;
  overviewStatus?: number;
  overviewBody?: unknown;
}

async function mockPreSpecs(page: Page, options: PreSpecMockOptions = {}): Promise<PreSpecTrace> {
  const trace: PreSpecTrace = { listQueries: [], noticeGets: [], overviewGets: [], structurePageGets: [] };

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
      const swOnly = url.searchParams.get("sw_only") !== "false";
      const items = swOnly
        ? options.emptyDefault ? [] : [trackingException, newPreSpec]
        : [trackingException, newPreSpec, allOnlyPreSpec];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0 }),
      });
      return;
    }

    await route.fallback();
  });

  await page.route("**/api/notices/**", async (route) => {
    const request = route.request();
    const match = new URL(request.url()).pathname.match(/^\/api\/notices\/(\d+)$/);
    if (match && request.method() === "GET") {
      const id = Number(match[1]);
      trace.noticeGets.push(id);
      await route.fulfill({
        status: id === 991 ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(id === 991 ? notice991 : { detail: "공고 없음" }),
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
  await expect(page.getByRole("link", { name: allOnlyPreSpec.title })).toBeVisible();
});

test("추적 예외, 신규, D-day, 문서 차단과 실패를 별도 상태로 표시한다", async ({ page }) => {
  await mockPreSpecs(page);
  await page.goto("/pre-specs");

  const trackedRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: trackingException.title }) });
  await expect(trackedRow).toContainText("추적");
  await expect(trackedRow).toContainText("추적 예외");
  await expect(trackedRow).toContainText("N");
  await expect(trackedRow.getByLabel("D-day: D-2")).toBeVisible();
  await expect(trackedRow.getByText("차단 2", { exact: true })).toBeVisible();
  await expect(trackedRow.getByText("실패 1", { exact: true })).toBeVisible();

  const newRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: newPreSpec.title }) });
  await expect(newRow.getByText("신규", { exact: true })).toBeVisible();
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
