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
  await expect(panel).toContainText("확정 문서 묶음 판단에 쓰지 않음");
  await expect(panel).not.toContainText("/internal/legacy/9001.pdf");
  await expect(panel.getByText("안전한 문서 묶음 준비", { exact: false })).toBeVisible();
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

// 담당자 이름은 화면마다 되풀이해 묻지 않고 이 브라우저에 기억된다. 기억은
// 편의일 뿐이므로 **인증으로 표현되지 않고**, 이름이 채워졌다는 것만으로는
// 어떤 변경 요청도 나가지 않는다(docs/security.md · AGENTS.md).
test("기억된 담당자 이름은 인증으로 표현되지 않고 스스로 변경을 보내지 않는다", async ({ page }) => {
  const mutations: string[] = [];
  page.on("request", (request) => {
    const method = request.method();
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith("/api/") && method !== "GET" && method !== "HEAD") {
      mutations.push(`${method} ${pathname}`);
    }
  });

  await page.goto("/deep-reviews/fixture-review");
  const actor = page.getByLabel("담당자 이름");
  await actor.fill("기억되는 담당자");

  const describedBy = await actor.getAttribute("aria-describedby");
  const description = page.locator(`#${describedBy}`);
  await expect(description).toContainText("감사 귀속용");
  await expect(description).toContainText("로그인·신원 인증·권한 부여가 아닙니다");
  await expect(description).toContainText("이 브라우저에 기억됩니다");
  await expect(description).toContainText("로그인이나 신원 인증이 아닙니다");

  await page.reload();
  await expect(page.getByLabel("담당자 이름")).toHaveValue("기억되는 담당자");
  // 이름이 채워졌다고 해서 저장이 일어나지 않는다.
  expect(mutations).toEqual([]);
});
