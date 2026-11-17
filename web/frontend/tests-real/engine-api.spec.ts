import { expect, test, type Page } from "@playwright/test";
import type { EngineRun } from "../src/lib/engineApi";

// Synchronize on the screen's required data, not an assumed lazy-chunk load time.
// HTTP failures and wrong notice identity fail explicitly; no timeout is extended.
async function loadNotice(page: Page, noticeId: number, navigate: () => Promise<unknown>) {
  const [response] = await Promise.all([
    page.waitForResponse((response) => response.request().method() === "GET"
      && new URL(response.url()).pathname === `/api/notices/${noticeId}`),
    navigate(),
  ]);
  expect(response.status()).toBe(200);
  expect((await response.json() as { id: number }).id).toBe(noticeId);
}

// No page.route: production UI, API, database and worker are all real; provider is mock_reference.
// The caller seeds an isolated real-company context, prespec notice and ready bundle and runs its worker.
test("actual engine receipt → shared worker → stored artifact → prespec result", async ({ page, request }) => {
  const noticeId = Number(process.env.BIDOPS_ENGINE_E2E_NOTICE_ID);
  expect((await request.get("/api/health")).ok()).toBe(true);
  const contextResponse = await request.get("/api/company");
  expect(contextResponse.ok()).toBe(true);
  const context = await contextResponse.json() as { company: { company_id: string } };
  const collection = `/api/companies/${context.company.company_id}/notices/${noticeId}/engine-runs`;
  expect((await request.get(collection)).ok()).toBe(true);
  await loadNotice(page, noticeId, () => page.goto(`/pre-specs/${noticeId}`));
  const panel = page.getByTestId("engine-analysis-panel");
  await expect(panel).toBeVisible();
  await panel.getByLabel("엔진 참조 실행 담당자 이름").fill("격리 E2E 검증");
  const accepted = page.waitForResponse((response) => response.url().endsWith(collection) && response.request().method() === "POST");
  await panel.getByRole("button", { name: "mock 참조 실행", exact: true }).click();
  const response = await accepted;
  expect(response.status()).toBe(202);
  const created = await response.json() as EngineRun;
  expect(created.quality_status).toBe("mock_reference");
  expect(created.notice_id).toBe(noticeId);
  expect(created.company_id).toBe(context.company.company_id);
  await expect(panel.getByTestId("engine-run-status")).toHaveAttribute("data-status", "partial", { timeout: 60_000 });
  const storedResponse = await request.get(`/api/engine-runs/${created.id}`);
  expect(storedResponse.ok()).toBe(true);
  const stored = await storedResponse.json() as EngineRun;
  expect(stored.analysis).not.toBeNull();
  expect(stored.input_sha256).toMatch(/^[0-9a-f]{64}$/);
  await expect(panel.getByTestId("engine-analysis-result")).toContainText(stored.analysis!.recommendation.summary);
  await expect(panel).toContainText("미확인 (UNKNOWN)");
  await expect(panel).toContainText("mock 참조");
  await expect(panel).not.toContainText("측정 통과");
  await panel.getByText("실행 식별 정보", { exact: true }).click();
  await expect(panel).toContainText(created.id);
  expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.getByTestId("engine-run-status").scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("real-engine-result.png") });
  await test.info().attach("engine-receipt", { body: JSON.stringify({ id: stored.id, status: stored.status, input_sha256: stored.input_sha256, quality_status: stored.quality_status }), contentType: "application/json" });
  await loadNotice(page, noticeId, () => page.reload());
  await expect(page.getByTestId("engine-run-status")).toHaveAttribute("data-status", "partial");
});
