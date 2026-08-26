import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./api-mock";

// 계획서 P0-2가 요구하는 다섯 경로에서 미저장 초안이 사라지지 않는지 확인한다.
const REASON = "검증용 미저장 메모";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  // 리뷰 저장은 고정 응답에 없으므로 이 검증에서만 따로 응답을 준다.
  await page.route("**/api/notices/*/review", async (route) => {
    if (route.request().method() !== "PUT") return route.fallback();
    const body = JSON.parse(route.request().postData() ?? "{}");
    const pk = Number(new URL(route.request().url()).pathname.split("/")[3]);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        notice_pk: pk, run_id: body.run_id, disposition: body.disposition,
        system_judgment_review: body.system_judgment_review, corrected_grade: body.corrected_grade,
        corrected_readiness: body.corrected_readiness, weakest_perspective: body.weakest_perspective,
        reason: body.reason, answers: body.verification_answers ?? [],
        reviewer: null, created_at: "2026-08-25T00:00:00Z", updated_at: "2026-08-25T00:00:00Z",
      }),
    });
  });
});

async function typeReason(page: Page): Promise<void> {
  const box = page.getByLabel("리뷰 사유");
  await box.fill(REASON);
  await expect(page.getByText("저장되지 않은 변경사항")).toBeVisible();
}

test.describe("넓은 화면의 검토 초안 흐름", () => {
  // 900px 이하에서는 목록과 상세가 분리되어 첫 공고가 자동 선택되지 않는다.
  // 분리 화면은 아래의 폭별 흐름 테스트에서 별도로 확인한다.
  test.skip(({ viewport }) => (viewport?.width ?? 0) <= 900, "분리 화면 흐름은 폭별 테스트에서 확인한다");

  test("목록 클릭으로 벗어났다 돌아와도 초안이 남는다", async ({ page }) => {
    await page.goto("/queue");
    await page.waitForURL(/\/queue\/\d+/);
    const first = page.url();
    await typeReason(page);
    await page.locator(".queue-list-item").nth(3).click();
    await expect(page.getByLabel("리뷰 사유")).toHaveValue("");
    await page.goBack();
    await expect(page.getByLabel("리뷰 사유")).toHaveValue(REASON);
    expect(page.url()).toBe(first);
  });

  test("J/K 이동 후 돌아와도 초안이 남는다", async ({ page }) => {
    await page.goto("/queue");
    await page.waitForURL(/\/queue\/\d+/);
    await typeReason(page);
    await page.locator("body").click();
    await page.keyboard.press("j");
    await expect(page.getByLabel("리뷰 사유")).toHaveValue("");
    await page.keyboard.press("k");
    await expect(page.getByLabel("리뷰 사유")).toHaveValue(REASON);
  });

  test("회차를 바꿨다 돌아와도 초안이 남는다", async ({ page }) => {
    await page.goto("/queue");
    await page.waitForURL(/\/queue\/\d+/);
    await typeReason(page);
    const url = new URL(page.url());
    const run = url.searchParams.get("run");
    url.searchParams.set("run", "다른-회차");
    await page.goto(url.pathname + url.search);
    url.searchParams.set("run", run!);
    await page.goto(url.pathname + url.search);
    await expect(page.getByLabel("리뷰 사유")).toHaveValue(REASON);
  });

  test("저장하면 다음 공고로 이동하고 알림과 되돌리기가 뜬다", async ({ page }) => {
    await page.goto("/queue");
    await page.waitForURL(/\/queue\/\d+/);
    const first = page.url();
    await typeReason(page);
    await page.getByRole("button", { name: "저장하고 다음" }).click();
    await expect(page.getByText("저장됨 · 다음 공고로 이동했습니다")).toBeVisible();
    expect(page.url()).not.toBe(first);
    await page.getByRole("button", { name: "되돌리기" }).click();
    expect(page.url()).toBe(first);
    // 저장이 끝났으므로 미저장 표시는 사라져 있어야 한다.
    await expect(page.getByText("저장되지 않은 변경사항")).toHaveCount(0);
  });

  test("미저장 상태에서 브라우저 이탈에 확인이 걸린다", async ({ page }) => {
    await page.goto("/queue");
    await page.waitForURL(/\/queue\/\d+/);
    await typeReason(page);
    const blocked = await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    });
    expect(blocked).toBe(true);
  });
});

test("검토 대기열에서 같은 공고로 돌아와도 미저장 초안이 남는다", async ({ page, viewport }) => {
  const splitLayout = (viewport?.width ?? 0) <= 900;
  await page.goto("/queue");

  if (splitLayout) {
    await expect(page.locator(".queue-list-item").first()).toBeVisible();
    await page.locator(".queue-list-item").first().click();
    await page.waitForURL(/\/queue\/\d+/);
    const first = page.url();
    const noticePk = new URL(first).pathname.split("/").pop();
    await typeReason(page);
    await page.getByRole("link", { name: "목록으로" }).click();
    await expect(page).toHaveURL(/\/queue(?:\?.*)?$/);
    await page.locator(".queue-list-item").first().click();
    await expect(page).toHaveURL(new RegExp(`/queue/${noticePk}(?:\\?.*)?$`));
    await expect(page.getByLabel("리뷰 사유")).toHaveValue(REASON);
    return;
  }

  // 1024/1440px에서는 기존 목록 내 선택·뒤로가기 흐름도 계속 의미가
  // 있으므로 같은 초안을 다른 공고를 거쳐 복원하는 경로를 확인한다.
  await page.waitForURL(/\/queue\/\d+/);
  const first = page.url();
  await typeReason(page);
  await page.locator(".queue-list-item").nth(3).click();
  await expect(page.getByLabel("리뷰 사유")).toHaveValue("");
  await page.goBack();
  await expect(page.getByLabel("리뷰 사유")).toHaveValue(REASON);
  expect(page.url()).toBe(first);
});
