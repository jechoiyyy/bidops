import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockCompanyWorkspace, mockPreSpecs, mockRealCompany } from "./api-mock";
import { COMPANY_BY_SLUG } from "./fixtures/company-demo";
import { RL_COMPANY_ID } from "./fixtures/company-rl";
import type { EngineRun } from "../src/lib/engineApi";

const company = COMPANY_BY_SLUG["demo-public-si"].company_id;
const path = `/companies/${company}/pre-specs/7102`;
const collection = `/api/companies/${company}/notices/7102/engine-runs`;
// Shape derived from analysis.schemas.Analysis and engine REST DTO; semantics only.
const result: EngineRun = {
  id: "1b5a81ca-fbb3-4d53-831a-ad7bcf944fcf", company_id: company, notice_id: 7102,
  bundle_id: "e8ef5a2c-c5f5-4d9a-8d7d-5fef74955b33", request_id: "d7badcfb-5627-42ac-899c-0f1f1f959a20",
  engine_sha256: "e".repeat(64), input_currentness: "current", profile_version_id: company,
  profile_sha256: "b".repeat(64), graph_version_id: company, graph_sha256: "c".repeat(64), documents: [],
  engine_version: "bid-deep-engine.v1", quality_status: "mock_reference", status: "partial",
  created_at: "2026-11-17T01:00:00Z", started_at: "2026-11-17T01:00:01Z", completed_at: "2026-11-17T01:00:02Z",
  input_sha256: "a".repeat(64), error_code: null, warnings: ["company_qualifications_unknown"],
  analysis: {
    schema_version: 1,
    recommendation: { decision: "CONDITIONAL_GO", fit_score: 0, summary: "회사 자격 확인이 필요한 mock 결과", preconditions: ["자격 확인 필요"], why_not: [] },
    assessment: { state: "abstain", decision: null, reason_codes: ["unknown_gate"], score_interval: null },
    gates: [{ code: "SW_BUSINESS_REPORT", rule_text: "소프트웨어 사업자 신고 확인", company_value: "unknown", verdict: "UNKNOWN", evidence: [{ quote: "소프트웨어 사업자 신고", page: 1, verified: true, location_status: "exact" }], action: "신고 확인서를 확인해 주세요.", unknown_fields: ["qualifications.sw_business_report"] }],
    fits: [], data_to_confirm: [{ field: "qualifications.sw_business_report", why: "확인된 회사 근거 없음" }],
  },
};
async function setup(page: Page, initial: EngineRun | null = null, reject = false) {
  await mockApi(page);
  await mockCompanyWorkspace(page);
  let current = initial;
  const posts: { request_id: string; mode: string; bundle_id: string }[] = [];
  await page.route(`**${collection}`, async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as typeof posts[number];
      posts.push(body);
      if (reject) { await route.fulfill({ status: 409, json: { error: { code: "bundle_not_ready", message: "private diagnostic must not appear" } } }); return; }
      current = { ...result, bundle_id: body.bundle_id, request_id: body.request_id, status: "queued", analysis: null };
      await route.fulfill({ status: 202, json: current }); return;
    }
    await route.fulfill({ json: { items: current ? [current] : [], total: current ? 1 : 0 } });
  });
  await page.route(`**/api/engine-runs/${result.id}`, async (route) => {
    current = current?.status === "queued" ? { ...result, bundle_id: current.bundle_id, request_id: current.request_id } : current;
    await route.fulfill({ json: current });
  });
  return posts;
}
for (const viewport of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
  test(`engine mock submit → poll → partial/unknown, ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const posts = await setup(page);
    await page.goto(path);
    const panel = page.getByTestId("engine-analysis-panel");
    await expect(panel).toContainText("엔진 실행 기록이 없어요.");
    expect(posts).toHaveLength(0);
    await panel.getByLabel("엔진 참조 실행 담당자 이름").fill("참조 검증 담당");
    await panel.getByRole("button", { name: "mock 참조 실행", exact: true }).click();
    await expect(panel.getByTestId("engine-run-status")).toHaveAttribute("data-status", "partial");
    expect(posts).toHaveLength(1);
    expect(posts[0].mode).toBe("mock_reference");
    expect(posts[0].request_id).toMatch(/^[0-9a-f-]{36}$/);
    await expect(panel).toContainText("미확인 (UNKNOWN)");
    await expect(panel).toContainText("판정 유보");
    await expect(panel).toContainText("계산 불가");
    await expect(panel).toContainText("company_qualifications_unknown");
    await expect(panel).not.toContainText("측정 통과");
    await panel.getByText("실행 식별 정보", { exact: true }).click();
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await panel.getByTestId("engine-run-status").scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`engine-partial-${viewport.width}.png`) });
    await page.reload();
    await expect(page.getByTestId("engine-run-status")).toHaveAttribute("data-status", "partial");
    expect(posts).toHaveLength(1);
  });
}

test("failed engine run keeps failure code and no invented analysis", async ({ page }) => {
  await setup(page, { ...result, status: "failed", analysis: null, error_code: "engine_artifact_invalid" });
  await page.goto(path);
  const panel = page.getByTestId("engine-analysis-panel");
  await expect(panel.getByTestId("engine-run-status")).toHaveAttribute("data-status", "failed");
  await expect(panel).toContainText("engine_artifact_invalid");
  await expect(panel).toContainText("저장된 분석 결과가 없어요.");
  await expect(panel.getByTestId("engine-analysis-result")).toHaveCount(0);
});

test("backend rejection is preserved without raw diagnostics or result", async ({ page }) => {
  await setup(page, null, true);
  await page.goto(path);
  const panel = page.getByTestId("engine-analysis-panel");
  await panel.getByLabel("엔진 참조 실행 담당자 이름").fill("참조 검증 담당");
  await panel.getByRole("button", { name: "mock 참조 실행", exact: true }).click();
  await expect(panel).toContainText("bundle_not_ready");
  await expect(panel).not.toContainText("private diagnostic");
  await expect(panel.getByTestId("engine-analysis-result")).toHaveCount(0);
});

test("lost POST response retries frozen request ID and actor", async ({ page }) => {
  const posts = await setup(page);
  const attempts: { id: string; actor: string | undefined }[] = [];
  await page.route(`**${collection}`, async (route) => {
    if (route.request().method() !== "POST") { await route.fallback(); return; }
    attempts.push({ id: (route.request().postDataJSON() as { request_id: string }).request_id, actor: route.request().headers()["x-bidops-actor-name"] });
    if (attempts.length === 1) { await route.abort("failed"); return; }
    await route.fallback();
  });
  await page.goto(path);
  const panel = page.getByTestId("engine-analysis-panel");
  const actor = panel.getByLabel("엔진 참조 실행 담당자 이름");
  await actor.fill("Receipt Reviewer");
  await panel.getByRole("button", { name: "mock 참조 실행", exact: true }).click();
  await expect(panel.getByRole("button", { name: "같은 요청 다시 확인" })).toBeEnabled();
  await expect(actor).toBeDisabled();
  await panel.getByRole("button", { name: "같은 요청 다시 확인" }).click();
  await expect(panel.getByTestId("engine-run-status")).toHaveAttribute("data-status", "partial");
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);
  expect(posts).toHaveLength(1);
});


test("stale engine input remains historical", async ({ page }) => {
  await setup(page, { ...result, input_currentness: "stale" });
  await page.goto(path);
  await expect(page.getByTestId("engine-currentness")).toHaveText("입력 현재성 · 입력이 변경된 과거 결과");
});


test("delayed engine detail shows loading until its result arrives", async ({ page }) => {
  const posts = await setup(page, result);
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let detailRequested = false;
  // Hold only the detail response: a completed collection must not conceal this loading state.
  await page.route(`**/api/engine-runs/${result.id}`, async (route) => {
    detailRequested = true;
    await gate;
    await route.fallback();
  });
  await page.goto(path);
  const panel = page.getByTestId("engine-analysis-panel");
  try {
    await expect.poll(() => detailRequested).toBe(true);
    await expect(panel.getByTestId("engine-detail-pending")).toHaveText("선택한 엔진 실행의 상세 결과를 불러오는 중이에요.");
    await expect(panel.getByTestId("engine-analysis-result")).toHaveCount(0);
    await expect(panel.getByTestId("engine-run-status")).toHaveCount(0);
  } finally {
    release();
  }
  await expect(panel.getByTestId("engine-detail-pending")).toHaveCount(0);
  await expect(panel.getByTestId("engine-run-status")).toHaveAttribute("data-status", "partial");
  await expect(panel.getByTestId("engine-analysis-result")).toContainText(result.analysis!.recommendation.summary);
  expect(posts).toHaveLength(0);
});


// 설계고도화안 C-9(2026-11-18): 사전규격 상세의 엔진 mock 패널은 개발·mock 서버(`BIDOPS_MOCK_API`)에서만
// 그린다. 화면 검사는 운영 번들(`vite build`)을 보므로 이 두 검사는 그 번들에서 대상이 없어 건너뛴다.
// 회사 데모 경로의 엔진 패널 검사(위)는 그대로 돈다.
test.skip("normal prespec preserves actor draft when its bundle arrives late with unavailable actor storage", async ({ page }) => {
  // Remembering is optional. A delayed server response must preserve the in-page draft
  // even when this browser cannot persist actor names (ActorField's supported fallback).
  await page.addInitScript(() => {
    const setItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key === "bidops.actorName") throw new DOMException("Storage unavailable", "SecurityError");
      return setItem.call(this, key, value);
    };
  });
  await mockApi(page);
  await mockPreSpecs(page);
  await mockRealCompany(page);
  const normalCollection = `/api/companies/${RL_COMPANY_ID}/notices/991/engine-runs`;
  const posts: { bundle_id: string; mode: string }[] = [];
  await page.route(`**${normalCollection}`, async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as typeof posts[number];
      posts.push(body);
      await route.fulfill({ status: 202, json: { ...result, company_id: RL_COMPANY_ID, notice_id: 991, bundle_id: body.bundle_id } });
      return;
    }
    await route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.route(`**/api/engine-runs/${result.id}`, (route) => route.fulfill({ json: { ...result, company_id: RL_COMPANY_ID, notice_id: 991 } }));
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/notices/991/document-bundles", async (route) => {
    await gate;
    await route.fulfill({ json: { items: [{ id: result.bundle_id, notice_id: 991, revision: 1, version: 1, status: "ready", documents: [], issues: [], confirmed_by: "fixture", confirmed_at: result.created_at, created_at: result.created_at }] } });
  });
  await page.goto("/pre-specs/991");
  const panel = page.getByTestId("engine-analysis-panel");
  const actor = panel.getByLabel("엔진 참조 실행 담당자 이름");
  try {
    await expect(panel).toContainText("확정된 준비 완료 문서 묶음이 필요해요.");
    await actor.fill("Bundle Arrival Reviewer");
    await expect(actor).toHaveValue("Bundle Arrival Reviewer");
    await expect(panel.getByRole("button", { name: "mock 참조 실행", exact: true })).toBeDisabled();
  } finally {
    release();
  }
  await expect(panel).not.toContainText("확정된 준비 완료 문서 묶음이 필요해요.");
  await expect(actor).toHaveValue("Bundle Arrival Reviewer");
  await panel.getByRole("button", { name: "mock 참조 실행", exact: true }).click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toMatchObject({ bundle_id: result.bundle_id, mode: "mock_reference" });
});

test.skip("normal prespec retries frozen receipt after ready bundle becomes a new draft", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await mockRealCompany(page);
  const normalCollection = `/api/companies/${RL_COMPANY_ID}/notices/991/engine-runs`;
  const initial = { ...result, company_id: RL_COMPANY_ID, notice_id: 991 };
  let draftCreated = false;
  let detailReads = 0;
  let listReads = 0;
  // A new unconfirmed draft does not replace the backend's latest ready bundle.
  // Currentness therefore stays current, but it must be re-read after this input change.
  const receiptId = "3b5a81ca-fbb3-4d53-831a-ad7bcf944fcf";
  let receipt: EngineRun | null = null;
  const posts: { body: { bundle_id: string; request_id: string }; actor: string | undefined }[] = [];
  await page.route(`**${normalCollection}`, async (route) => {
    if (route.request().method() === "POST") {
      const posted = { body: route.request().postDataJSON() as { bundle_id: string; request_id: string }, actor: route.request().headers()["x-bidops-actor-name"] };
      posts.push(posted);
      if (posts.length === 1) {
        // The server accepted a new run, then the response was lost. The worker
        // completes it before the next list read; the old historical run stays intact.
        receipt = { ...initial, id: receiptId, request_id: posted.body.request_id, bundle_id: posted.body.bundle_id, created_at: "2026-11-17T02:00:00Z", started_at: "2026-11-17T02:00:01Z", completed_at: "2026-11-17T02:00:02Z" };
        await route.abort("failed");
        return;
      }
      if (JSON.stringify(posted) !== JSON.stringify(posts[0])) {
        await route.fulfill({ status: 409, json: { error: { code: "idempotency_conflict", message: "Receipt input changed", details: null } } });
        return;
      }
      await route.fulfill({ status: 202, json: receipt });
      return;
    }
    listReads += 1;
    await route.fulfill({ json: { items: receipt ? [receipt, initial] : [initial], total: receipt ? 2 : 1 } });
  });
  await page.route(/\/api\/engine-runs\/[^/]+$/, async (route) => {
    detailReads += 1;
    const id = new URL(route.request().url()).pathname.split("/").at(-1);
    const row = id === initial.id ? initial : id === receiptId ? receipt : null;
    await route.fulfill({ status: row ? 200 : 404, json: row ?? { error: { code: "not_found", message: "Unknown fixture run", details: null } } });
  });
  const ready = { id: result.bundle_id, notice_id: 991, revision: 1, version: 1, status: "ready", documents: [], issues: [], confirmed_by: "fixture", confirmed_at: result.created_at, created_at: result.created_at };
  const draft = { ...ready, id: "2b5a81ca-fbb3-4d53-831a-ad7bcf944fcf", revision: 2, status: "draft", confirmed_at: null, confirmed_by: null };
  await page.route("**/api/notices/991/document-bundles", async (route) => {
    if (route.request().method() === "POST") {
      draftCreated = true;
      await route.fulfill({ status: 201, json: draft });
      return;
    }
    await route.fulfill({ json: { items: draftCreated ? [draft, ready] : [ready] } });
  });
  await page.goto("/pre-specs/991");
  const panel = page.getByTestId("engine-analysis-panel");
  await expect(panel.getByTestId("engine-currentness")).toHaveText("입력 현재성 · 현재 입력과 일치");
  await panel.getByLabel("엔진 참조 실행 담당자 이름").fill("Frozen Bundle Reviewer");
  await panel.getByRole("button", { name: "mock 참조 실행", exact: true }).click();
  await expect(panel.getByRole("button", { name: "같은 요청 다시 확인" })).toBeEnabled();
  const beforeChange = { listReads, detailReads };
  // Use the actual document preparation action to refresh the parent's bundle query.
  const openDocuments = page.getByRole("button", { name: "문서 준비 열기", exact: true });
  if (await openDocuments.isVisible()) await openDocuments.click();
  await page.getByLabel("문서 준비 담당자 이름").fill("New Draft Reviewer");
  await page.getByRole("button", { name: "새 문서 묶음 만들기", exact: true }).click();
  await expect(panel).toContainText("확정된 준비 완료 문서 묶음이 필요해요.");
  await expect.poll(() => listReads).toBeGreaterThan(beforeChange.listReads);
  await expect.poll(() => detailReads).toBeGreaterThan(beforeChange.detailReads);
  await expect(panel.getByTestId("engine-currentness")).toHaveText("입력 현재성 · 현재 입력과 일치");
  await expect(panel.getByLabel("엔진 참조 실행 담당자 이름")).toHaveValue("Frozen Bundle Reviewer");
  await panel.getByRole("button", { name: "같은 요청 다시 확인" }).click();
  await expect.poll(() => posts.length).toBe(2);
  expect(posts[1]).toEqual(posts[0]);
  expect(posts[1].body.bundle_id).toBe(ready.id);
  expect(posts[0].body.request_id).not.toBe(initial.request_id);
  await expect(panel.getByLabel("엔진 실행 이력")).toHaveValue(receiptId);
  await panel.getByText("실행 식별 정보", { exact: true }).click();
  await expect(panel).toContainText(receiptId);
});

// 설계고도화안 C-9: 운영 번들의 사전규격 상세에는 엔진 mock 패널이 없다(꺼진 기능을 실패 뒤에 드러내지 않는다).
test("운영 번들의 사전규격 상세에는 분석 엔진 mock 패널을 그리지 않는다", async ({ page }) => {
  await mockApi(page);
  await mockPreSpecs(page);
  await mockRealCompany(page, { notRegistered: true });
  await page.goto("/pre-specs/991");
  await expect(page.locator(".pre-spec-detail-header")).toBeVisible();
  await expect(page.getByText("분석 엔진 · mock 참조")).toHaveCount(0);
  await expect(page.getByTestId("engine-analysis-panel")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "mock 참조 실행" })).toHaveCount(0);
});
