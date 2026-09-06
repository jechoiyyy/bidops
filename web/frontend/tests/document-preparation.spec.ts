import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";

const NOTICE_ID = 991;
const BUNDLE_ID = "10000000-0000-0000-0000-000000000991";
const SUPERSEDED_BUNDLE_ID = "10000000-0000-0000-0000-000000000990";
const DOCUMENT_ID = "20000000-0000-0000-0000-000000000991";
const ACTOR_HEADER = "UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99";

type Scenario = "flow" | "partial" | "forbidden" | "unavailable";

type RequestRecord = {
  body: Record<string, unknown>;
  headers: Record<string, string>;
};

interface PreparationTrace {
  creates: RequestRecord[];
  uploads: Array<{ body: string; headers: Record<string, string>; requestId: string | null }>;
  patches: RequestRecord[];
  confirms: RequestRecord[];
  deepReviews: RequestRecord[];
}

const notice = {
  id: NOTICE_ID,
  notice_key: "pre-spec:991",
  run_id: "source-run-not-used-for-routing",
  title: "안전한 문서 준비 사전규격",
  agency: "테스트 조달기관",
  published_at: "2026-08-30T00:00:00Z",
  deadline_at: "2026-09-02T00:00:00Z",
  estimated_price: null,
  sample_role: null,
  sample_stratum: null,
  collection_bucket: null,
  grade: "우선 검토",
  readiness: null,
  focus: null,
  attachment_count: 2,
  attachment_status: "g2b",
  bid_no: null,
  bid_ord: null,
  source_type: "pre_spec",
  budget: 510_000_000,
  method: null,
  url: "https://example.invalid/pre-specs/991",
  timezone: "Asia/Seoul",
  procurement_class: null,
  region_limit: null,
  lifecycle: { pre_spec_no: "PRE-991" },
  qualification_flags: { sw_business_status: "Y" },
  focus_matches: [],
  performance_matches: [],
  performance_top_score: null,
  candidate_sources: [],
  judgment: null,
  attachments: [],
  reviews: [],
};

const overview = {
  schema_version: "bidops.prespec-overview-reviews.v2",
  notice_id: NOTICE_ID,
  reviews: [],
};

function documentView(overrides: Record<string, unknown> = {}) {
  return {
    id: DOCUMENT_ID,
    bundle_id: BUNDLE_ID,
    version: 1,
    role: "기타",
    effective_date: null,
    replaces_document_version_id: null,
    is_current: true,
    safety_status: "safe",
    structure_status: "ready",
    original_filename: "제안요청서.pdf",
    ...overrides,
  };
}

function bundleView(overrides: Record<string, unknown> = {}) {
  return {
    id: BUNDLE_ID,
    notice_id: NOTICE_ID,
    revision: 1,
    version: 1,
    status: "draft",
    documents: [],
    issues: [],
    confirmed_by: null,
    confirmed_at: null,
    created_at: "2026-08-31T00:00:00Z",
    ...overrides,
  };
}

function parseJsonBody(pageBody: string | null): Record<string, unknown> {
  return JSON.parse(pageBody ?? "{}") as Record<string, unknown>;
}

function requestIdFromMultipart(body: string): string | null {
  return body.match(/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i)?.[0] ?? null;
}

// 문서 준비 화면이 추적 결정 구역을 그리는 데 필요한 최소 목록 항목이다.
// `opportunity_id`가 있어야 결정 동선이 오류가 아닌 정상 상태로 렌더링된다.
const preSpecItem = {
  notice_pk: NOTICE_ID,
  pre_spec_no: "PRE-991",
  title: notice.title,
  agency: notice.agency,
  published_at: notice.published_at,
  deadline_at: notice.deadline_at,
  budget: notice.budget,
  sw_business_status: "N",
  business_division: "일반용역",
  origin: "추적",
  opportunity_id: 202,
  tracking_status: "계속 추적",
  kept_by_tracking: true,
  document: { attachments: 2, "완료": 1, "대기": 1, "진행": 0, "차단": 0, "실패": 0 },
  overview_review_status: null,
  grade: "우선 검토",
  grade_source: "screening_judgment",
  auto_preparation_status: "not_applicable",
  auto_preparation_reason: null,
  latest_deep_review_id: null,
};

async function mockDocumentPreparation(page: Page, scenario: Scenario): Promise<PreparationTrace> {
  const trace: PreparationTrace = { creates: [], uploads: [], patches: [], confirms: [], deepReviews: [] };
  let bundle = scenario === "unavailable"
    ? bundleView({ revision: 2, version: 5, status: "ready", documents: [documentView({ original_filename: "ready.pdf", version: 2, role: "제안요청서" })], confirmed_by: "이전 담당자", confirmed_at: "2026-08-31T02:00:00Z" })
    : null;
  const superseded = bundleView({
    id: SUPERSEDED_BUNDLE_ID,
    revision: 1,
    version: 4,
    status: "superseded",
    documents: [documentView({ id: "20000000-0000-0000-0000-000000000990", bundle_id: SUPERSEDED_BUNDLE_ID, original_filename: "이전-확정본.pdf", version: 3 })],
    confirmed_by: "이전 담당자",
    confirmed_at: "2026-08-30T02:00:00Z",
  });
  let uploadCount = 0;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const method = request.method();

    if (pathname === `/api/notices/${NOTICE_ID}` && method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(notice) });
      return;
    }
    if (pathname === `/api/pre-specs/${NOTICE_ID}/overview-reviews/v2` && method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(overview) });
      return;
    }
    // 이 화면은 추적 결정 구역에서 사업기회 연결과 첨부 집계를 함께 조회한다.
    // 이 경로를 두지 않으면 갈무리 fixture가 404를 주고 구역 전체가 오류
    // 상태로 남는다. 문서 준비를 보려는 테스트가 관계 없는 오류 화면 위에서
    // 도는 셈이므로 여기서 정의된 상태를 준다.
    if (pathname === "/api/pre-specs" && method === "GET") {
      const requested = new URL(request.url()).searchParams.get("notice_pk");
      const items = requested === null || Number(requested) === NOTICE_ID ? [preSpecItem] : [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length, limit: 50, offset: 0 }),
      });
      return;
    }
    if (pathname === `/api/notices/${NOTICE_ID}/document-bundles` && method === "GET") {
      const items = bundle ? scenario === "unavailable" ? [bundle, superseded] : [bundle] : [];
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items }) });
      return;
    }
    if (pathname === `/api/notices/${NOTICE_ID}/document-bundles` && method === "POST") {
      const record = { body: parseJsonBody(request.postData()), headers: request.headers() };
      trace.creates.push(record);
      if (scenario === "forbidden") {
        await route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "effective_grade_ineligible", message: "현재 공고는 문서 검토 대상이 아닙니다", details: null }, request_id: null }),
        });
        return;
      }
      bundle = bundleView();
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(bundle) });
      return;
    }
    if (pathname === `/api/document-bundles/${BUNDLE_ID}/documents` && method === "POST") {
      uploadCount += 1;
      const body = request.postData() ?? "";
      trace.uploads.push({ body, headers: request.headers(), requestId: requestIdFromMultipart(body) });
      if (scenario === "partial" && uploadCount === 2) {
        bundle = bundleView({
          version: 4,
          status: "needs_review",
          documents: [
            documentView(),
            documentView({ id: "20000000-0000-0000-0000-000000000992", original_filename: "차단된-부록.pdf", safety_status: "blocked", structure_status: "failed" }),
            documentView({ id: "20000000-0000-0000-0000-000000000993", original_filename: "확인필요.hwpx", structure_status: "needs_review" }),
          ],
          issues: [{
            issue_id: "fixture-blocking-issue",
            code: "unsafe_document",
            severity: "차단",
            blocking: true,
            document_version_id: "20000000-0000-0000-0000-000000000992",
            message: "안전 검사에 실패한 문서가 있습니다.",
            locator_type: "none",
            locator: null,
          }],
        });
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "processing_failed", message: "문서 작업을 완료할 수 없습니다", details: null }, request_id: trace.uploads.at(-1)?.requestId }),
        });
        return;
      }
      const uploaded = documentView();
      bundle = bundleView({ version: 4, documents: [uploaded] });
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(uploaded) });
      return;
    }
    if (pathname === `/api/document-versions/${DOCUMENT_ID}` && method === "PATCH") {
      const record = { body: parseJsonBody(request.postData()), headers: request.headers() };
      trace.patches.push(record);
      const saved = documentView({ ...record.body, version: 2 });
      bundle = bundleView({ version: 4, documents: [saved] });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(saved) });
      return;
    }
    if (pathname === `/api/document-bundles/${BUNDLE_ID}/confirm` && method === "POST") {
      const record = { body: parseJsonBody(request.postData()), headers: request.headers() };
      trace.confirms.push(record);
      bundle = bundleView({
        version: 5,
        status: "ready",
        documents: bundle?.documents ?? [],
        confirmed_by: "홍길동",
        confirmed_at: "2026-08-31T03:00:00Z",
      });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(bundle) });
      return;
    }
    if (pathname === `/api/notices/${NOTICE_ID}/deep-reviews` && method === "POST") {
      const record = { body: parseJsonBody(request.postData()), headers: request.headers() };
      trace.deepReviews.push(record);
      if (scenario === "unavailable") {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "service_unavailable", message: "심층 검토 서비스를 사용할 수 없습니다", details: null }, request_id: record.body.request_id }),
        });
        return;
      }
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          id: "40000000-0000-0000-0000-000000000991",
          notice_id: NOTICE_ID,
          bundle_id: BUNDLE_ID,
          status: "queued",
          current_attempt: null,
          attempts: [],
          created_at: "2026-08-31T03:00:01Z",
          completed_at: null,
        }),
      });
      return;
    }

    await route.fallback();
  });

  return trace;
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("생성→upload→patch→confirm→deep review가 actor·request ID·version snapshot 계약을 지킨다", async ({ page }) => {
  const trace = await mockDocumentPreparation(page, "flow");
  await page.goto(`/pre-specs/${NOTICE_ID}`);

  await expect(page.getByRole("heading", { name: "문서 묶음 준비부터 심층 검토까지" })).toBeVisible();
  await page.getByLabel("문서 준비 담당자 이름").fill("홍길동");
  await page.getByRole("button", { name: "새 문서 묶음 만들기" }).click();
  await expect(page.getByText("문서 묶음 수정본 1 초안을 만들었습니다.")).toBeVisible();

  await page.getByLabel("안전한 문서 등록").locator("input[type=file]").setInputFiles({
    name: "제안요청서.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 fixture"),
  });
  await expect(page.getByText("문서 1건을 순차 등록했습니다.")).toBeVisible();
  await expect(page.getByText("안전 확인", { exact: true })).toBeVisible();
  await expect(page.getByText("구조화 완료", { exact: true })).toBeVisible();

  await page.getByLabel("문서 역할 · 제안요청서.pdf").selectOption("제안요청서");
  await page.getByLabel("시행일 · 제안요청서.pdf").fill("2026-09-01");
  await expect(page.getByLabel("현재 버전 · 제안요청서.pdf")).toBeChecked();
  await page.getByRole("button", { name: "문서 정보 저장", exact: true }).click();
  await expect(page.getByText("제안요청서.pdf 문서 정보를 버전 2으로 저장했습니다.")).toBeVisible();

  await expect(page.getByText(/문서 1건 이상 · 모든 문서 안전 확인 · 모든 문서 구조화 완료 · 차단 항목 0건/)).toBeVisible();
  await page.getByRole("button", { name: "문서 묶음 확정하기" }).click();
  await expect(page.getByText(/문서 묶음 수정본 1을 확정했습니다/)).toBeVisible();
  await expect(page.getByLabel("문서 역할 · 제안요청서.pdf")).toBeDisabled();
  await expect(page.getByText("이 문서 묶음과 그 안의 문서 버전은 확정돼 바뀌지 않습니다.")).toBeVisible();
  const preparationOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(preparationOverflow).toBeLessThanOrEqual(1);

  await page.getByRole("button", { name: "확정된 문서 묶음으로 심층 검토 시작" }).click();
  await expect(page).toHaveURL(/\/deep-reviews\/40000000-0000-0000-0000-000000000991$/);

  expect(trace.creates).toHaveLength(1);
  expect(trace.creates[0].body).toEqual({});
  expect(trace.uploads).toHaveLength(1);
  expect(trace.uploads[0].headers["content-type"]).toMatch(/^multipart\/form-data; boundary=/);
  expect(trace.uploads[0].requestId).toMatch(/^[0-9a-f-]{36}$/);
  expect(trace.patches).toHaveLength(1);
  expect(trace.patches[0].body).toEqual({
    role: "제안요청서",
    effective_date: "2026-09-01",
    replaces_document_version_id: null,
    is_current: true,
    version: 1,
  });
  expect(trace.confirms).toHaveLength(1);
  expect(trace.confirms[0].body.version).toBe(4);
  expect(trace.confirms[0].body.confirmed_documents).toEqual([{ document_version_id: DOCUMENT_ID, version: 2 }]);
  expect(trace.confirms[0].body.request_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(trace.deepReviews).toHaveLength(1);
  expect(trace.deepReviews[0].body.bundle_id).toBe(BUNDLE_ID);
  expect(trace.deepReviews[0].body.request_id).toMatch(/^[0-9a-f-]{36}$/);
  for (const request of [...trace.creates, ...trace.patches, ...trace.confirms, ...trace.deepReviews]) {
    expect(request.headers["x-bidops-actor-name"]).toBe(ACTOR_HEADER);
    expect(request.headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
  }
  expect(trace.uploads[0].headers["x-bidops-actor-name"]).toBe(ACTOR_HEADER);
  expect(trace.uploads[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
});

test("부분 upload 실패와 blocked·failed·needs_review를 ready로 표시하지 않는다", async ({ page }) => {
  const trace = await mockDocumentPreparation(page, "partial");
  await page.goto(`/pre-specs/${NOTICE_ID}`);
  await page.getByLabel("문서 준비 담당자 이름").fill("홍길동");
  await page.getByRole("button", { name: "새 문서 묶음 만들기" }).click();
  await page.getByLabel("안전한 문서 등록").locator("input[type=file]").setInputFiles([
    { name: "제안요청서.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 first") },
    { name: "부록.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 second") },
  ]);

  await expect(page.getByText("업로드 일부 실패 · 성공 1건 / 실패 1건. 전체 성공으로 처리하지 않았습니다.")).toBeVisible();
  await expect(page.getByText("안전 검사 차단", { exact: true })).toBeVisible();
  await expect(page.getByText("변환·구조화 실패", { exact: true })).toBeVisible();
  await expect(page.getByText("구조화 사람 확인 필요", { exact: true })).toBeVisible();
  await expect(page.getByText("차단 항목 1건을 먼저 해결해야 합니다.")).toBeVisible();
  await expect(page.getByRole("button", { name: "문서 묶음 확정하기" })).toBeDisabled();
  expect(trace.uploads).toHaveLength(2);
  expect(trace.uploads[0].requestId).toMatch(/^[0-9a-f-]{36}$/);
  expect(trace.uploads[1].requestId).toMatch(/^[0-9a-f-]{36}$/);
  expect(trace.uploads[0].requestId).not.toBe(trace.uploads[1].requestId);
});

test("403 effective grade gate를 우회하지 않고 안정 사유를 표시한다", async ({ page }) => {
  const trace = await mockDocumentPreparation(page, "forbidden");
  await page.goto(`/pre-specs/${NOTICE_ID}`);
  await page.getByLabel("문서 준비 담당자 이름").fill("홍길동");
  await page.getByRole("button", { name: "새 문서 묶음 만들기" }).click();

  const gateFeedback = page.locator(".mutation-feedback");
  await expect(gateFeedback).toContainText("현재 공고는 이 작업의 대상이 아닙니다");
  await expect(gateFeedback).toContainText("화면에 보이는 등급으로 서버 조건을 우회할 수 없습니다");
  expect(trace.creates).toHaveLength(1);
  expect(trace.creates[0].body).toEqual({});
});

test("ready·superseded 이력은 불변이고 503 profile/policy를 fail-closed로 표시한다", async ({ page }) => {
  const trace = await mockDocumentPreparation(page, "unavailable");
  await page.goto(`/pre-specs/${NOTICE_ID}`);
  await page.getByLabel("문서 준비 담당자 이름").fill("홍길동");

  await page.getByRole("button", { name: /수정본 1/ }).click();
  await expect(page.getByText("최신 수정본이 아니므로 과거 이력으로만 표시합니다.")).toBeVisible();
  await expect(page.getByLabel("문서 역할 · 이전-확정본.pdf")).toBeDisabled();
  await expect(page.getByRole("button", { name: "확정된 문서 묶음으로 심층 검토 시작" })).toHaveCount(0);

  await page.getByRole("button", { name: /수정본 2/ }).click();
  await expect(page.getByLabel("문서 역할 · ready.pdf")).toBeDisabled();
  await page.getByRole("button", { name: "확정된 문서 묶음으로 심층 검토 시작" }).click();
  // 이 화면의 alert는 하나가 아니다. 심층 검토 요청 결과만 본다.
  const deepReviewFeedback = page.locator(".mutation-feedback");
  await expect(deepReviewFeedback).toContainText("활성 회사 프로필 버전과 분석 정책 버전이 모두 있어야 심층 검토를 시작합니다");
  await expect(deepReviewFeedback).toContainText("hosted OpenAI로 자동 전환하지 않습니다");
  expect(trace.deepReviews).toHaveLength(1);
});
