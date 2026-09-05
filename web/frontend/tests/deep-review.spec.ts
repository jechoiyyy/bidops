import { test, expect } from "@playwright/test";
import { mockApi, mockDeepReviewLifecycle } from "./api-mock";

test.describe("심층 검토 보고서 접근성·반응형 계약", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("키보드 focus, 좁은 화면, 긴 matrix containment", async ({ page }) => {
    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "심층 검토 보고서", level: 1 })).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-review-primitive="sticky-decision-header"]')).toBeVisible();
    await page.getByRole("button", { name: /근거/ }).first().focus();
    await expect(page.getByRole("button", { name: /근거/ }).first()).toBeFocused();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(page.locator("table").first()).toBeVisible();
  });

  test("queued→running→complete 동안만 polling하고 완료 뒤 report를 요청한다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "polling");
    await page.goto("/deep-reviews/fixture-review");

    await expect(page.getByText("분석 진행 상태를 제한된 간격으로 자동 갱신하고 있습니다.")).toBeVisible();
    await expect(page.getByRole("button", { name: "새 attempt로 재시도" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "시스템 권고" })).toBeVisible({ timeout: 6_000 });

    expect(trace.reviewGets).toBeGreaterThanOrEqual(3);
    expect(trace.reportGets).toBe(1);
    expect(trace.events).toContain("review:queued");
    expect(trace.events).toContain("review:running");
    expect(trace.events).toContain("review:completed");
    expect(trace.events).toContain("report:completed");
    expect(trace.events).not.toContain("report:queued");
    expect(trace.events).not.toContain("report:running");

    const terminalReadCount = trace.reviewGets;
    await page.waitForTimeout(1_300);
    expect(trace.reviewGets).toBe(terminalReadCount);
    await expect(page.getByText("분석 진행 상태를 제한된 간격으로 자동 갱신하고 있습니다.")).toHaveCount(0);
  });

  test("completed 직후 report 409는 제한 재시도해 준비된 보고서로 복구한다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "completed");
    let reportRequests = 0;
    await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
      reportRequests += 1;
      if (reportRequests === 1) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "review_not_ready", message: "심층 검토가 아직 준비되지 않았습니다", details: null },
            request_id: null,
          }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "시스템 권고" })).toBeVisible({ timeout: 5_000 });
    expect(reportRequests).toBe(2);
    expect(trace.reportGets).toBe(1);
  });

  test("report 409가 제한 재시도 뒤에도 남으면 명시적 재조회로 복구한다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "completed");
    let reportRequests = 0;
    await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
      reportRequests += 1;
      if (reportRequests <= 3) {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "review_not_ready", message: "심층 검토가 아직 준비되지 않았습니다", details: null },
            request_id: null,
          }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto("/deep-reviews/fixture-review");
    const refetch = page.getByRole("button", { name: "보고서 다시 조회" });
    await expect(refetch).toBeVisible({ timeout: 5_000 });
    expect(reportRequests).toBe(3);
    await refetch.click();
    await expect(page.getByRole("heading", { name: "시스템 권고" })).toBeVisible();
    expect(reportRequests).toBe(4);
  });

  for (const fixture of [
    { status: 404, code: "not_found", message: "보고서를 찾을 수 없습니다" },
    { status: 500, code: "processing_failed", message: "심층 검토를 완료할 수 없습니다" },
  ]) {
    test(`report ${fixture.status}는 자동 재시도하거나 성공 처리하지 않는다`, async ({ page }) => {
      await mockDeepReviewLifecycle(page, "completed");
      let reportRequests = 0;
      await page.route("**/api/deep-reviews/fixture-review/report", async (route) => {
        reportRequests += 1;
        await route.fulfill({
          status: fixture.status,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: fixture.code, message: fixture.message, details: null },
            request_id: null,
          }),
        });
      });

      await page.goto("/deep-reviews/fixture-review");
      await expect(page.getByRole("alert")).toContainText(`${fixture.message} · 오류 코드 ${fixture.code}`);
      await page.waitForTimeout(1_200);
      expect(reportRequests).toBe(1);
      await expect(page.getByRole("heading", { name: "시스템 권고" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "보고서 다시 조회" })).toHaveCount(0);
    });
  }

  test("failed current attempt만 새 request ID로 한 번 재시도하고 이전 이력을 보존한다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "failed");
    await page.goto("/deep-reviews/fixture-review");

    await expect(page.getByRole("heading", { name: "새 attempt로 재시도" })).toBeVisible();
    await expect(page.getByText("Attempt 1회", { exact: true })).toBeVisible();
    await page.getByLabel("담당자 claimed name").fill("홍길동");
    await page.getByRole("button", { name: "새 attempt로 재시도" }).click();

    await expect(page.getByText("새 attempt 2회가 추가되었습니다. 기존 실패 이력은 보존됩니다.")).toBeVisible();
    await expect(page.getByText("Attempt 1회", { exact: true })).toBeVisible();
    await expect(page.getByText("Attempt 2회", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "새 attempt로 재시도" })).toHaveCount(0);
    expect(trace.attemptPosts).toHaveLength(1);
    expect(trace.attemptPosts[0].body.request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(trace.attemptPosts[0].headers["x-bidops-actor-name"]).toBe("UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99");
    expect(trace.attemptPosts[0].headers["x-bidops-actor-name-format"]).toBe("utf-8-percent-v1");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("retry typed 오류의 안전한 code와 message를 함께 표시한다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "failed");
    await page.route("**/api/deep-reviews/fixture-review/attempts", async (route) => {
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "active_attempt_exists", message: "이미 실행 중인 attempt가 있습니다", details: null },
          request_id: "fixture-conflict",
        }),
      });
    });
    await page.goto("/deep-reviews/fixture-review");
    await page.getByLabel("담당자 claimed name").fill("fixture actor");
    await page.getByRole("button", { name: "새 attempt로 재시도" }).click();
    await expect(page.getByRole("alert")).toContainText("이미 실행 중인 attempt가 있습니다 · 오류 코드 active_attempt_exists");
  });

  test("사전규격 심층검토 의견 초안을 이탈 보호하고 저장 결과를 live feedback으로 알린다", async ({ page }) => {
    const trace = await mockDeepReviewLifecycle(page, "completed");
    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "사전규격 심층검토 의견 추가" })).toBeVisible();

    await page.getByLabel("담당자 claimed name").fill("검토 담당자");
    await page.getByLabel("심층검토 의견 사유").fill("근거 확인 뒤 계속 검토합니다.");
    await expect(page.getByText(/저장되지 않은 심층검토 초안/)).toBeVisible();
    const blocked = await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    });
    expect(blocked).toBe(true);

    await page.getByRole("button", { name: "심층검토 의견 append" }).click();
    await expect(page.getByText("사전규격 심층검토 의견을 append-only로 저장했습니다.")).toBeVisible();
    await expect(page.getByText(/저장되지 않은 심층검토 초안/)).toHaveCount(0);
    expect(trace.opinionPosts).toHaveLength(1);
    expect(trace.opinionPosts[0].body.reason).toBe("근거 확인 뒤 계속 검토합니다.");
  });

  test("의견·보고서 수정본·근거 draft의 SPA 이탈을 취소하거나 명시적으로 허용한다", async ({ page }) => {
    await mockDeepReviewLifecycle(page, "completed");
    await page.goto("/deep-reviews/fixture-review");
    await expect(page.getByRole("heading", { name: "보고서 수정본 편집" })).toBeVisible();

    await page.getByLabel("절 내용").fill("저장되지 않은 보고서 수정본");
    await page.getByLabel("수정 사유").fill("수정본 이탈 보호 확인");
    await page.getByLabel("사실 변경 evidence ID (쉼표 구분)").fill("fixture-evidence-1");
    await page.getByLabel("심층검토 의견 사유").fill("저장되지 않은 의견");

    const messages: string[] = [];
    page.on("dialog", async (dialog) => {
      messages.push(dialog.message());
      if (messages.length === 1) await dialog.dismiss();
      else await dialog.accept();
    });

    const openDashboard = async () => {
      const dashboard = page.getByRole("link", { name: "대시보드", exact: true });
      const menuButton = page.getByRole("button", { name: "주 메뉴 열기" });
      if (await menuButton.isVisible()) {
        await menuButton.click();
        await expect(dashboard).toBeVisible();
      }
      await dashboard.click();
    };

    await openDashboard();
    await expect(page).toHaveURL(/\/deep-reviews\/fixture-review$/);
    await expect(page.getByLabel("절 내용")).toHaveValue("저장되지 않은 보고서 수정본");
    await expect(page.getByLabel("사실 변경 evidence ID (쉼표 구분)")).toHaveValue("fixture-evidence-1");
    await expect(page.getByLabel("심층검토 의견 사유")).toHaveValue("저장되지 않은 의견");

    await openDashboard();
    await expect.poll(() => new URL(page.url()).pathname).toBe("/");
    expect(messages).toEqual([
      "저장되지 않은 심층검토 초안이 있습니다. 이 페이지를 벗어나시겠습니까?",
      "저장되지 않은 심층검토 초안이 있습니다. 이 페이지를 벗어나시겠습니까?",
    ]);
  });
});

// ── PLAN 단계 F 작업 5 ─────────────────────────────────────────────────────

// 상단 카드는 넷이었고 명세 §6.5의 품질 표식이 다섯 번째로 붙었다. 표식은
// 실행이 참조 실행인지 측정 통과인지를 문자로 말하며, 값이 없는 옛 revision은
// `표식 없음`이다.
test("심층 검토 보고서는 상단 카드 5개와 결정 카드 요약 표를 갖는다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");

  const cards = page.locator(".deep-review-summary-card");
  await expect(cards).toHaveCount(5);
  await expect(cards.nth(0)).toContainText("종합 판단");
  await expect(cards.nth(1)).toContainText("검증 결과");
  await expect(cards.nth(2)).toContainText("미확인 사항");
  await expect(cards.nth(3)).toContainText("보고서 revision");
  await expect(cards.nth(3)).toContainText("append-only");
  await expect(cards.nth(4)).toContainText("품질 표식");
  await expect(cards.nth(4)).toContainText("참조 실행 · 품질 미측정");

  // 계약에 없는 축(참여 준비 상태)을 카드로 채우지 않고 그 사실을 밝힌다.
  await expect(page.locator(".deep-review-summary-note")).toContainText("참여 준비 상태");
  await expect(page.locator(".deep-review-summary-note")).toContainText("보고서 계약에 그 값이 없습니다");

  const table = page.getByRole("table", { name: "결정 카드 요약" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveText(["항목", "내용", "근거", "검증"]);
});

// 명세 §6.8이 문서 inventory와 사람 확인 필요 segment를 우측 열에 더한다.
// 문서 사실을 범위 다음에 두고, 편집·이력은 그 뒤로 밀린다.
test("우측 열은 보고서 범위·문서 inventory·수정본 저장·이력 순서로 배치된다", async ({ page }) => {
  await mockApi(page);
  await mockDeepReviewLifecycle(page, "completed");
  await page.goto("/deep-reviews/fixture-review");

  const side = page.locator(".deep-review-side");
  const sections = side.locator(":scope > section, :scope > [data-review-primitive='history-link-rail']");
  await expect(sections).toHaveCount(4);
  await expect(side.getByRole("heading", { name: "보고서 범위", exact: true })).toBeVisible();
  await expect(side.getByRole("heading", { name: "문서 요구사항 inventory와 사람 확인 구간", exact: true })).toBeVisible();
  await expect(side.getByRole("heading", { name: "보고서 수정본 편집", exact: true })).toBeVisible();
  await expect(side.getByRole("heading", { name: "보고서 이력과 연결", exact: true })).toBeVisible();

  // 수정본은 새 immutable revision이며 담당자 claimed name을 필수로 받는다.
  await expect(side).toContainText("새 immutable 수정본으로 추가합니다");
  const save = side.getByRole("button", { name: "새 보고서 수정본 저장", exact: true });
  await expect(save).toBeDisabled();
  await expect(page.locator("#deep-review-revision-disabled")).toContainText("claimed name을 입력하십시오");

  // 되돌릴 수 없는 결정(사전규격 심층검토 의견)은 본문 열에 남는다.
  await expect(side.getByRole("button", { name: "심층검토 의견 append", exact: true })).toHaveCount(0);
  await expect(page.locator(".deep-review-report-main").getByRole("button", { name: "심층검토 의견 append", exact: true })).toHaveCount(1);
});
