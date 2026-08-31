import { expect, test } from "@playwright/test";
import { mockApi } from "./api-mock";

const RUN_ID = "20260817-20260823--20260824T090927.138116Z";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("legacy 첨부는 mutation control 없이 provenance와 안전한 문서 준비 안내만 제공한다", async ({ page }) => {
  const legacyMutationRequests: string[] = [];

  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      (request.method() === "POST" && pathname === "/api/notices/29/attachments")
      || (request.method() === "DELETE" && /^\/api\/attachments\/[^/]+$/.test(pathname))
    ) {
      legacyMutationRequests.push(`${request.method()} ${pathname}`);
    }
  });

  await page.route("**/api/notices/29/attachments", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        notice_pk: 29,
        agency: "대한체육회",
        bid_no: "R26BK01689347",
        title: "경기인 데이터 연계 시스템 구축",
        status: "completed",
        matched_portal: null,
        search_url: null,
        portal_message: "",
        steps: [],
        attachments: [{
          id: 9001,
          name: "기존-수동-등록.pdf",
          url: "/api/attachments/9001/download",
          origin: "manual",
          file_ext: ".pdf",
          size_bytes: 1024,
          stored_path: "/internal/legacy/9001.pdf",
          extract_status: "completed",
          created_at: "2026-08-24T10:58:11Z",
        }],
      }),
    });
  });
  await page.route("**/api/notices/29/document-bundles", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [] }),
    });
  });

  await page.goto(`/judgments/29?run=${encodeURIComponent(RUN_ID)}`);

  const panel = page.getByRole("heading", { name: "기존 첨부 출처 이력" }).locator("..").locator("..");
  await expect(panel).toContainText("기존 수동 등록 이력");
  await expect(panel).toContainText("읽기 전용 이력");
  await expect(panel).toContainText("ready bundle 판단에 사용하지 않음");
  await expect(panel).not.toContainText("/internal/legacy/9001.pdf");
  await expect(panel.getByText("안전한 문서 bundle 준비", { exact: false })).toBeVisible();
  await expect(panel.locator('input[type="file"]')).toHaveCount(0);
  await expect(panel.getByRole("button", { name: /삭제/ })).toHaveCount(0);
  await expect(panel.getByRole("link", { name: /내려받기|다운로드/ })).toHaveCount(0);

  const safePreparationLink = panel.getByRole("link", { name: "문서 준비 상태 확인" });
  await safePreparationLink.focus();
  await expect(safePreparationLink).toBeFocused();
  await safePreparationLink.click();
  await expect(page.locator("#document-preparation")).toBeVisible();
  await expect(page.locator("#document-preparation [role='status']")).toContainText("legacy 첨부 이력으로 대신할 수 없습니다.");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(legacyMutationRequests).toEqual([]);
});
